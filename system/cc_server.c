/* cc_server: data plane of the minimal CXL training cache, built as a shared library.
 *
 * Derived from the data-path benchmark server (benchmarks/remote_cache/rcb_server.c). It holds
 * objects in fixed slots of one memory region (anonymous DRAM, or a byte range of a devdax
 * device) and moves bytes; it takes no decision. Every request is handed to the manager
 * (system/cc_manager.py, which loads this library) as an event, and the manager answers with
 * one of:
 *   ccs_hit(req, slot, size)         the NIC reads the slot and writes into the client's buffer
 *                                    (HG_Bulk_transfer on the registered store, no CPU copy)
 *   ccs_miss(req, path, size, slot)  a worker reads the file into a pooled DRAM buffer, sends it
 *                                    to the client from that buffer, responds, and then copies
 *                                    it into the slot (slot < 0: do not store)
 *   ccs_fail(req, code)
 * Completions come back as events, so the manager knows when a slot is no longer being read
 * and when an admitted object is in the store.
 *
 * Threads: one Mercury progress thread, `workers` threads for file reads and copies, and the
 * manager's thread, which calls ccs_poll and the functions above. The library keeps no cache
 * metadata. A devdax store maps exactly [dax_offset, dax_offset + store_bytes) and writes only
 * into slots the manager names. */
#define CC_WITH_MERCURY
#include "cc_common.h"
#include <stdatomic.h>

/* ---- what the manager sees (mirrored in cc_manager.py) ---- */
enum { CCS_EV_GET = 1, CCS_EV_CTL = 2, CCS_EV_HIT_DONE = 3, CCS_EV_MISS_SENT = 4, CCS_EV_ADMITTED = 5, CCS_EV_PREFETCHED = 6 };

typedef struct {
    int32_t type;
    int32_t job;
    int32_t epoch;
    int32_t op;     /* CTL: operation */
    int32_t n;      /* CTL: number of ids (read them with ccs_ctl_ids) */
    int32_t status; /* completions: 0, or a negative code */
    uint64_t req;   /* opaque request handle */
    int64_t pos, obj, a, b, c;
    int64_t slot;   /* completions */
    uint64_t t_ns;  /* monotonic time at which the request arrived (GET, CTL) or the step finished */
    uint64_t ns_io, ns_bulk, ns_copy;
} ccs_event_t;

typedef struct bounce {
    void *buf;
    hg_bulk_t bulk;
    struct bounce *next;
} bounce_t;

typedef struct req {
    hg_handle_t h;
    int is_ctl;
    cc_get_in_t in;
    cc_ctl_in_t ctl;
    cc_get_out_t out;
    uint64_t t0, t_bulk;
    int64_t slot, size;
    char *path;
    bounce_t *b;
    int stage; /* miss: 0 read and send, 1 copy into the store */
    int prefetch; /* 1: no client; read the file and copy it into the slot */
    struct req *next;
} req_t;

typedef struct evnode {
    ccs_event_t ev;
    struct evnode *next;
} evnode_t;

static hg_class_t *g_class;
static hg_context_t *g_ctx;
static char *g_store;
static uint64_t g_store_bytes, g_slot_bytes, g_nslots;
static hg_bulk_t g_store_bulk = HG_BULK_NULL;
static int g_workers, g_nbounce, g_busy;
static volatile int g_stop;
static pthread_t g_progress_tid, *g_worker_tids;
static bounce_t *g_bounces;
static char g_pin[256];

static pthread_mutex_t g_qm = PTHREAD_MUTEX_INITIALIZER; /* work queue */
static pthread_cond_t g_qcv = PTHREAD_COND_INITIALIZER;
static req_t *g_qhead, *g_qtail;
static req_t *g_pqhead, *g_pqtail; /* prefetch reads: behind all demand work */
static int g_pf_running, g_pf_max;

static pthread_mutex_t g_bm = PTHREAD_MUTEX_INITIALIZER; /* bounce buffers */
static pthread_cond_t g_bcv = PTHREAD_COND_INITIALIZER;
static bounce_t *g_bfree;

static pthread_mutex_t g_em = PTHREAD_MUTEX_INITIALIZER; /* events for the manager */
static pthread_cond_t g_ecv = PTHREAD_COND_INITIALIZER;
static evnode_t *g_ehead, *g_etail;

/* counters: 0 gets, 1 hits, 2 misses, 3 bytes sent from the store, 4 bytes sent from DRAM buffers,
 * 5 bytes read from files, 6 bytes copied into the store, 7 control messages, 8 errors,
 * 9 prefetches done, 10 bytes read from files by prefetches (not in 5; their copies are in 6) */
#define CCS_NCOUNTERS 11
static atomic_ullong g_cnt[CCS_NCOUNTERS];

static void post(const ccs_event_t *ev)
{
    evnode_t *n = (evnode_t *) malloc(sizeof *n);
    n->ev = *ev;
    n->next = NULL;
    pthread_mutex_lock(&g_em);
    if (g_etail)
        g_etail->next = n;
    else
        g_ehead = n;
    g_etail = n;
    pthread_cond_signal(&g_ecv);
    pthread_mutex_unlock(&g_em);
}

static bounce_t *bounce_get(void)
{
    pthread_mutex_lock(&g_bm);
    while (!g_bfree)
        pthread_cond_wait(&g_bcv, &g_bm);
    bounce_t *b = g_bfree;
    g_bfree = b->next;
    pthread_mutex_unlock(&g_bm);
    return b;
}

static void bounce_put(bounce_t *b)
{
    pthread_mutex_lock(&g_bm);
    b->next = g_bfree;
    g_bfree = b;
    pthread_cond_signal(&g_bcv);
    pthread_mutex_unlock(&g_bm);
}

static void submit(req_t *r)
{
    r->next = NULL;
    pthread_mutex_lock(&g_qm);
    if (g_qtail)
        g_qtail->next = r;
    else
        g_qhead = r;
    g_qtail = r;
    pthread_cond_signal(&g_qcv);
    pthread_mutex_unlock(&g_qm);
}

static void destroy(req_t *r)
{
    if (r->prefetch) {
        free(r->path);
        free(r);
        return;
    }
    if (r->is_ctl)
        HG_Free_input(r->h, &r->ctl);
    else
        HG_Free_input(r->h, &r->in);
    HG_Destroy(r->h);
    free(r->path);
    free(r);
}

/* ---- completion of a GET ---- */

static void completion_event(req_t *r, int type, int status)
{
    ccs_event_t ev;
    memset(&ev, 0, sizeof ev);
    ev.type = type;
    ev.job = r->in.job;
    ev.epoch = r->in.epoch;
    ev.pos = r->in.pos;
    ev.obj = r->in.obj;
    ev.req = (uint64_t) (uintptr_t) r;
    ev.slot = r->slot;
    ev.status = status;
    ev.t_ns = cc_now_ns();
    ev.ns_io = r->out.ns_io;
    ev.ns_bulk = r->out.ns_bulk;
    post(&ev);
}

/* After the response of a hit, or of a miss that is not stored, has left: nothing else to do. */
static hg_return_t on_respond_final(const struct hg_cb_info *info)
{
    destroy((req_t *) info->arg);
    return HG_SUCCESS;
}

/* After the response of a miss that is to be stored has left: copy into the slot on a worker. */
static hg_return_t on_respond_then_admit(const struct hg_cb_info *info)
{
    req_t *r = (req_t *) info->arg;
    r->stage = 1;
    submit(r);
    return HG_SUCCESS;
}

static void respond(req_t *r, int64_t ret, hg_cb_t cb)
{
    r->out.ret = ret;
    r->out.ns_total = cc_now_ns() - r->t0;
    if (HG_Respond(r->h, cb, r, &r->out) != HG_SUCCESS) {
        fprintf(stderr, "cc_server: HG_Respond failed\n");
        atomic_fetch_add(&g_cnt[8], 1);
        if (cb == on_respond_then_admit) { /* the client is gone; the manager still has to learn the outcome */
            completion_event(r, CCS_EV_ADMITTED, -EIO);
            if (r->b)
                bounce_put(r->b);
        }
        destroy(r);
    }
}

static hg_return_t on_bulk(const struct hg_cb_info *info)
{
    req_t *r = (req_t *) info->arg;
    int ok = info->ret == HG_SUCCESS;
    r->out.ns_bulk = cc_now_ns() - r->t_bulk;
    if (!ok) {
        fprintf(stderr, "cc_server: bulk transfer failed (%d)\n", (int) info->ret);
        atomic_fetch_add(&g_cnt[8], 1);
    }
    if (!r->b) { /* hit: the slot is no longer being read */
        if (ok)
            atomic_fetch_add(&g_cnt[3], (unsigned long long) r->size);
        completion_event(r, CCS_EV_HIT_DONE, ok ? 0 : -EIO);
        respond(r, ok ? r->size : -EIO, on_respond_final);
        return HG_SUCCESS;
    }
    if (ok)
        atomic_fetch_add(&g_cnt[4], (unsigned long long) r->size);
    completion_event(r, CCS_EV_MISS_SENT, ok ? 0 : -EIO);
    if (r->slot >= 0 && ok) { /* respond first, then store */
        respond(r, r->size, on_respond_then_admit);
        return HG_SUCCESS;
    }
    if (r->slot >= 0) /* the transfer failed: the admission does not happen */
        completion_event(r, CCS_EV_ADMITTED, -EIO);
    bounce_put(r->b);
    r->b = NULL;
    respond(r, ok ? r->size : -EIO, on_respond_final);
    return HG_SUCCESS;
}

static void start_bulk(req_t *r, hg_bulk_t local, hg_size_t local_off)
{
    const struct hg_info *hgi = HG_Get_info(r->h);
    r->t_bulk = cc_now_ns();
    hg_return_t hr = HG_Bulk_transfer(g_ctx, on_bulk, r, HG_BULK_PUSH, hgi->addr, r->in.bulk, 0, local, local_off,
        (hg_size_t) r->size, HG_OP_ID_IGNORE);
    if (hr != HG_SUCCESS) {
        struct hg_cb_info fake;
        memset(&fake, 0, sizeof fake);
        fake.arg = r;
        fake.ret = hr;
        fprintf(stderr, "cc_server: HG_Bulk_transfer failed to start (%d)\n", (int) hr);
        on_bulk(&fake);
    }
}

/* ---- worker threads: file reads and copies into the store ---- */

/* A prefetch: file -> DRAM buffer -> slot, the path of an admission, without a client. */
static void work_prefetch(req_t *r)
{
    ccs_event_t ev;
    memset(&ev, 0, sizeof ev);
    ev.type = CCS_EV_PREFETCHED;
    ev.job = -1;
    ev.obj = r->in.obj;
    ev.slot = r->slot;
    bounce_t *b = bounce_get();
    uint64_t t = cc_now_ns();
    size_t size = (size_t) r->size, got = 0;
    int fd = open(r->path, O_RDONLY);
    if (fd >= 0) {
        while (got < size) {
            ssize_t n = pread(fd, (char *) b->buf + got, size - got, (off_t) got);
            if (n < 0 && errno == EINTR)
                continue;
            if (n <= 0)
                break;
            got += (size_t) n;
        }
        close(fd);
    }
    ev.ns_io = cc_now_ns() - t;
    if (got == size) {
        t = cc_now_ns();
        memcpy(g_store + (uint64_t) r->slot * g_slot_bytes, b->buf, size);
        ev.ns_copy = cc_now_ns() - t;
        atomic_fetch_add(&g_cnt[6], (unsigned long long) size);
        atomic_fetch_add(&g_cnt[9], 1);
        atomic_fetch_add(&g_cnt[10], (unsigned long long) size);
    } else {
        fprintf(stderr, "cc_server: prefetch of %s gave %zu of %zu bytes\n", r->path, got, size);
        atomic_fetch_add(&g_cnt[8], 1);
        ev.status = -EIO;
    }
    bounce_put(b);
    ev.t_ns = cc_now_ns();
    post(&ev);
    destroy(r);
    pthread_mutex_lock(&g_qm);
    g_pf_running--;
    pthread_cond_signal(&g_qcv);
    pthread_mutex_unlock(&g_qm);
}

static void work(req_t *r)
{
    if (r->prefetch) {
        work_prefetch(r);
        return;
    }
    if (r->stage == 1) { /* the client has its data; store the object */
        uint64_t t = cc_now_ns();
        memcpy(g_store + (uint64_t) r->slot * g_slot_bytes, r->b->buf, (size_t) r->size);
        ccs_event_t ev;
        memset(&ev, 0, sizeof ev);
        ev.type = CCS_EV_ADMITTED;
        ev.job = r->in.job;
        ev.epoch = r->in.epoch;
        ev.pos = r->in.pos;
        ev.obj = r->in.obj;
        ev.req = (uint64_t) (uintptr_t) r;
        ev.slot = r->slot;
        ev.t_ns = cc_now_ns();
        ev.ns_copy = ev.t_ns - t;
        atomic_fetch_add(&g_cnt[6], (unsigned long long) r->size);
        bounce_put(r->b);
        r->b = NULL;
        post(&ev);
        destroy(r);
        return;
    }
    r->b = bounce_get();
    uint64_t t = cc_now_ns();
    size_t size = (size_t) r->size, got = 0;
    int fd = open(r->path, O_RDONLY);
    if (fd >= 0) {
        while (got < size) {
            ssize_t n = pread(fd, (char *) r->b->buf + got, size - got, (off_t) got);
            if (n < 0 && errno == EINTR)
                continue;
            if (n <= 0)
                break;
            got += (size_t) n;
        }
        close(fd);
    }
    r->out.ns_io = cc_now_ns() - t;
    if (got != size) {
        fprintf(stderr, "cc_server: reading %s gave %zu of %zu bytes\n", r->path, got, size);
        atomic_fetch_add(&g_cnt[8], 1);
        completion_event(r, CCS_EV_MISS_SENT, -EIO);
        if (r->slot >= 0)
            completion_event(r, CCS_EV_ADMITTED, -EIO);
        bounce_put(r->b);
        r->b = NULL;
        respond(r, -EIO, on_respond_final);
        return;
    }
    atomic_fetch_add(&g_cnt[5], (unsigned long long) size);
    start_bulk(r, r->b->bulk, 0);
}

static void *worker(void *arg)
{
    (void) arg;
    cc_pin(g_pin);
    for (;;) {
        pthread_mutex_lock(&g_qm);
        while (!g_qhead && !(g_pqhead && g_pf_running < g_pf_max) && !g_stop)
            pthread_cond_wait(&g_qcv, &g_qm);
        req_t *r = g_qhead;
        if (r) { /* demand work first */
            g_qhead = r->next;
            if (!g_qhead)
                g_qtail = NULL;
        } else if (g_pqhead && g_pf_running < g_pf_max && !g_stop) {
            r = g_pqhead;
            g_pqhead = r->next;
            if (!g_pqhead)
                g_pqtail = NULL;
            g_pf_running++;
        }
        pthread_mutex_unlock(&g_qm);
        if (!r)
            return NULL;
        work(r);
    }
}

/* ---- RPC handlers (progress thread): hand the request to the manager ---- */

static hg_return_t get_handler(hg_handle_t h)
{
    req_t *r = (req_t *) calloc(1, sizeof *r);
    r->h = h;
    r->t0 = cc_now_ns();
    r->slot = -1;
    if (HG_Get_input(h, &r->in) != HG_SUCCESS) {
        fprintf(stderr, "cc_server: HG_Get_input failed\n");
        HG_Destroy(h);
        free(r);
        return HG_SUCCESS;
    }
    atomic_fetch_add(&g_cnt[0], 1);
    ccs_event_t ev;
    memset(&ev, 0, sizeof ev);
    ev.type = CCS_EV_GET;
    ev.job = r->in.job;
    ev.epoch = r->in.epoch;
    ev.pos = r->in.pos;
    ev.obj = r->in.obj;
    ev.req = (uint64_t) (uintptr_t) r;
    ev.t_ns = r->t0;
    post(&ev);
    return HG_SUCCESS;
}

static hg_return_t ctl_handler(hg_handle_t h)
{
    req_t *r = (req_t *) calloc(1, sizeof *r);
    r->h = h;
    r->is_ctl = 1;
    r->t0 = cc_now_ns();
    if (HG_Get_input(h, &r->ctl) != HG_SUCCESS) {
        fprintf(stderr, "cc_server: HG_Get_input (ctl) failed\n");
        HG_Destroy(h);
        free(r);
        return HG_SUCCESS;
    }
    atomic_fetch_add(&g_cnt[7], 1);
    ccs_event_t ev;
    memset(&ev, 0, sizeof ev);
    ev.type = CCS_EV_CTL;
    ev.job = r->ctl.job;
    ev.op = r->ctl.op;
    ev.n = r->ctl.n;
    ev.a = r->ctl.a;
    ev.b = r->ctl.b;
    ev.c = r->ctl.c;
    ev.req = (uint64_t) (uintptr_t) r;
    ev.t_ns = r->t0;
    post(&ev);
    return HG_SUCCESS;
}

static hg_return_t on_ctl_respond(const struct hg_cb_info *info)
{
    destroy((req_t *) info->arg);
    return HG_SUCCESS;
}

static void *progress_fn(void *arg)
{
    (void) arg;
    cc_pin(g_pin);
    while (!g_stop) {
        unsigned int n = 0;
        hg_return_t hr;
        do {
            hr = HG_Trigger(g_ctx, 0, 1, &n);
        } while (hr == HG_SUCCESS && n && !g_stop);
        HG_Progress(g_ctx, g_busy ? 0 : 100);
    }
    for (uint64_t end = cc_now_ns() + 300000000ULL; cc_now_ns() < end;) { /* let the last responses leave */
        unsigned int n = 0;
        HG_Trigger(g_ctx, 0, 16, &n);
        HG_Progress(g_ctx, 10);
    }
    return NULL;
}

/* ---- interface for the manager ---- */

/* Set up the store, Mercury, and the threads. backend: "dram" or "dax". Returns 0, or a negative
 * code. addr_out receives the server's Mercury address. */
int ccs_start(const char *backend, const char *dax_path, uint64_t dax_offset, uint64_t store_bytes, uint64_t slot_bytes,
    const char *proto, int workers, int nbounce, const char *pin, int busy, char *addr_out, int addr_len)
{
    if (!store_bytes || store_bytes % CC_HUGE || !slot_bytes || slot_bytes % 4096 || workers < 1 || nbounce < 1)
        return -EINVAL;
    g_store_bytes = store_bytes;
    g_slot_bytes = slot_bytes;
    g_nslots = store_bytes / slot_bytes;
    g_workers = workers;
    g_nbounce = nbounce;
    g_busy = busy;
    snprintf(g_pin, sizeof g_pin, "%s", pin ? pin : "");

    uint64_t t = cc_now_ns();
    if (!strcmp(backend, "dax")) {
        if (!dax_path)
            return -EINVAL;
        g_store = (char *) cc_map_dax(dax_path, dax_offset, store_bytes);
        if (g_store)
            printf("store: devdax %s bytes [%" PRIu64 ", %" PRIu64 ") mapped read-write\n", dax_path, dax_offset,
                dax_offset + store_bytes);
    } else if (!strcmp(backend, "dram")) {
        g_store = (char *) cc_alloc_dram(store_bytes);
        if (g_store)
            printf("store: anonymous DRAM, %" PRIu64 " bytes, zeroed\n", store_bytes);
    } else
        return -EINVAL;
    if (!g_store)
        return -ENOMEM;
    printf("store: %" PRIu64 " slots of %" PRIu64 " bytes, set up in %.1f ms\n", g_nslots, g_slot_bytes,
        (cc_now_ns() - t) / 1e6);

    struct hg_init_info info = HG_INIT_INFO_INITIALIZER;
    if (busy)
        info.na_init_info.progress_mode = NA_NO_BLOCK;
    g_class = HG_Init_opt(proto, HG_TRUE, &info);
    if (!g_class) {
        fprintf(stderr, "cc_server: HG_Init(%s) failed\n", proto);
        return -EIO;
    }
    g_ctx = HG_Context_create(g_class);
    if (!g_ctx)
        return -EIO;
    HG_Register_name(g_class, CC_RPC_GET, hg_proc_cc_get_in_t, hg_proc_cc_get_out_t, get_handler);
    HG_Register_name(g_class, CC_RPC_CTL, hg_proc_cc_ctl_in_t, hg_proc_cc_ctl_out_t, ctl_handler);

    char self[256] = "";
    hg_size_t self_len = sizeof self;
    hg_addr_t self_addr = HG_ADDR_NULL;
    HG_Addr_self(g_class, &self_addr);
    HG_Addr_to_string(g_class, self, &self_len, self_addr);
    HG_Addr_free(g_class, self_addr);
    snprintf(addr_out, (size_t) addr_len, "%s", self);

    void *p = g_store;
    hg_size_t sz = (hg_size_t) store_bytes;
    t = cc_now_ns();
    if (HG_Bulk_create(g_class, 1, &p, &sz, HG_BULK_READ_ONLY, &g_store_bulk) != HG_SUCCESS) {
        fprintf(stderr, "cc_server: registering the store failed\n");
        return -EIO;
    }
    printf("store registered for bulk transfers in %.1f ms (read-only for the NIC)\n", (cc_now_ns() - t) / 1e6);

    g_bounces = (bounce_t *) calloc((size_t) nbounce, sizeof *g_bounces);
    char *region = (char *) cc_alloc_dram((size_t) nbounce * slot_bytes);
    if (!region)
        return -ENOMEM;
    for (int i = 0; i < nbounce; i++) {
        g_bounces[i].buf = region + (uint64_t) i * slot_bytes;
        hg_size_t bsz = (hg_size_t) slot_bytes;
        if (HG_Bulk_create(g_class, 1, &g_bounces[i].buf, &bsz, HG_BULK_READ_ONLY, &g_bounces[i].bulk) != HG_SUCCESS) {
            fprintf(stderr, "cc_server: registering a DRAM buffer failed\n");
            return -EIO;
        }
        g_bounces[i].next = g_bfree;
        g_bfree = &g_bounces[i];
    }

    g_stop = 0;
    g_worker_tids = (pthread_t *) calloc((size_t) workers, sizeof *g_worker_tids);
    for (int i = 0; i < workers; i++)
        pthread_create(&g_worker_tids[i], NULL, worker, NULL);
    pthread_create(&g_progress_tid, NULL, progress_fn, NULL);
    fflush(stdout);
    return 0;
}

/* Wait up to timeout_ms for events; copy at most max of them. Returns their number. */
int ccs_poll(ccs_event_t *out, int max, int timeout_ms)
{
    int n = 0;
    pthread_mutex_lock(&g_em);
    if (!g_ehead && timeout_ms > 0) {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_sec += timeout_ms / 1000;
        ts.tv_nsec += (long) (timeout_ms % 1000) * 1000000L;
        if (ts.tv_nsec >= 1000000000L) {
            ts.tv_sec++;
            ts.tv_nsec -= 1000000000L;
        }
        pthread_cond_timedwait(&g_ecv, &g_em, &ts);
    }
    while (g_ehead && n < max) {
        evnode_t *e = g_ehead;
        g_ehead = e->next;
        if (!g_ehead)
            g_etail = NULL;
        out[n++] = e->ev;
        free(e);
    }
    pthread_mutex_unlock(&g_em);
    return n;
}

/* The identifiers that came with a control request. */
int ccs_ctl_ids(uint64_t req, int64_t *out, int max)
{
    req_t *r = (req_t *) (uintptr_t) req;
    int n = r->ctl.n < max ? r->ctl.n : max;
    memcpy(out, r->ctl.ids, (size_t) n * sizeof(int64_t));
    return n;
}

void ccs_reply_ctl(uint64_t req, int64_t ret)
{
    req_t *r = (req_t *) (uintptr_t) req;
    cc_ctl_out_t out = {ret};
    if (HG_Respond(r->h, on_ctl_respond, r, &out) != HG_SUCCESS) {
        fprintf(stderr, "cc_server: HG_Respond (ctl) failed\n");
        destroy(r);
    }
}

/* Serve the request from the store. kind: CC_KIND_HIT or CC_KIND_HIT_WAITED. */
void ccs_hit(uint64_t req, int64_t slot, int64_t size, int kind)
{
    req_t *r = (req_t *) (uintptr_t) req;
    r->slot = slot;
    r->size = size;
    r->out.kind = kind;
    r->out.ns_wait = cc_now_ns() - r->t0;
    atomic_fetch_add(&g_cnt[1], 1);
    if (slot < 0 || (uint64_t) slot >= g_nslots || size <= 0 || (uint64_t) size > g_slot_bytes) {
        ccs_event_t ev;
        memset(&ev, 0, sizeof ev);
        ev.type = CCS_EV_HIT_DONE;
        ev.req = req;
        ev.slot = slot;
        ev.obj = r->in.obj;
        ev.job = r->in.job;
        ev.status = -EINVAL;
        ev.t_ns = cc_now_ns();
        post(&ev);
        respond(r, -EINVAL, on_respond_final);
        return;
    }
    start_bulk(r, g_store_bulk, (hg_size_t) ((uint64_t) slot * g_slot_bytes));
}

/* Serve the request from the file; slot >= 0: store the object there afterwards. */
void ccs_miss(uint64_t req, const char *path, int64_t size, int64_t slot)
{
    req_t *r = (req_t *) (uintptr_t) req;
    r->slot = slot;
    r->size = size;
    r->path = strdup(path);
    r->out.kind = slot >= 0 ? CC_KIND_MISS_ADMIT : CC_KIND_MISS_BYPASS;
    r->out.ns_wait = cc_now_ns() - r->t0;
    atomic_fetch_add(&g_cnt[2], 1);
    if (size <= 0 || (uint64_t) size > g_slot_bytes || (slot >= 0 && (uint64_t) slot >= g_nslots)) {
        completion_event(r, CCS_EV_MISS_SENT, -EINVAL);
        if (slot >= 0)
            completion_event(r, CCS_EV_ADMITTED, -EINVAL);
        respond(r, -EINVAL, on_respond_final);
        return;
    }
    submit(r);
}

/* At most `max_running` prefetch reads at once (0: none are started). */
void ccs_set_prefetch(int max_running)
{
    pthread_mutex_lock(&g_qm);
    g_pf_max = max_running;
    pthread_cond_broadcast(&g_qcv);
    pthread_mutex_unlock(&g_qm);
}

/* Read the file into the slot in the background. Answered by an event CCS_EV_PREFETCHED (obj, slot, status). */
void ccs_prefetch(int64_t obj, const char *path, int64_t size, int64_t slot)
{
    req_t *r = (req_t *) calloc(1, sizeof *r);
    r->prefetch = 1;
    r->in.obj = obj;
    r->slot = slot;
    r->size = size;
    r->path = strdup(path);
    r->next = NULL;
    if (size <= 0 || (uint64_t) size > g_slot_bytes || slot < 0 || (uint64_t) slot >= g_nslots) {
        ccs_event_t ev;
        memset(&ev, 0, sizeof ev);
        ev.type = CCS_EV_PREFETCHED;
        ev.job = -1;
        ev.obj = obj;
        ev.slot = slot;
        ev.status = -EINVAL;
        ev.t_ns = cc_now_ns();
        post(&ev);
        destroy(r);
        return;
    }
    pthread_mutex_lock(&g_qm);
    if (g_pqtail)
        g_pqtail->next = r;
    else
        g_pqhead = r;
    g_pqtail = r;
    pthread_cond_signal(&g_qcv);
    pthread_mutex_unlock(&g_qm);
}

void ccs_fail(uint64_t req, int64_t code)
{
    req_t *r = (req_t *) (uintptr_t) req;
    r->out.ns_wait = cc_now_ns() - r->t0;
    atomic_fetch_add(&g_cnt[8], 1);
    respond(r, code, on_respond_final);
}

void ccs_counters(uint64_t *out)
{
    for (int i = 0; i < CCS_NCOUNTERS; i++)
        out[i] = (uint64_t) atomic_load(&g_cnt[i]);
}

/* Checksum of what a slot holds: used by tests to compare the store with the files. */
uint64_t ccs_slot_sum(int64_t slot, int64_t size)
{
    return cc_sum(g_store + (uint64_t) slot * g_slot_bytes, (size_t) size);
}

uint64_t ccs_nslots(void)
{
    return g_nslots;
}

void ccs_stop(void)
{
    g_stop = 1;
    pthread_join(g_progress_tid, NULL);
    pthread_mutex_lock(&g_qm);
    pthread_cond_broadcast(&g_qcv);
    pthread_mutex_unlock(&g_qm);
    for (int i = 0; i < g_workers; i++)
        pthread_join(g_worker_tids[i], NULL);
    for (int i = 0; i < g_nbounce; i++)
        HG_Bulk_free(g_bounces[i].bulk);
    if (g_store_bulk != HG_BULK_NULL)
        HG_Bulk_free(g_store_bulk);
    HG_Context_destroy(g_ctx);
    HG_Finalize(g_class);
}
