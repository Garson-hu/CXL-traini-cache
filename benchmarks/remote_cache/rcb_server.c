/* rcb_server: server side of the remote cache data-path benchmark.
 *
 * Holds objects in fixed slots of one memory region and executes GET, PUT and
 * FETCH requests from rcb_client over Mercury. The region is either anonymous
 * DRAM (2 MiB pages requested) or a byte range of a devdax device (CXL memory).
 * Everything else is identical between the two, which is the point.
 *
 * Data paths (the client selects one per request with flags):
 *   zero-copy   the NIC reads from / writes to the store directly
 *               (HG_Bulk_transfer on the registered store)
 *   COPY        store <-> DRAM bounce buffer by memcpy, then the transfer from that buffer
 *   COPY|ALLOC  like COPY, but the buffer is calloc'ed and registered per request
 *   COPY|ALLOC|INLINE  the same on the progress thread: FitCache's read handler
 *
 * Usage:
 *   rcb_server --backend dram|dax --store-bytes N [--dax-path DEV --dax-offset N]
 *              [--slot-bytes N] [--proto STR] [--addr-file FILE] [--workers N] [--bounce N]
 *              [--reg whole|slot] [--pin CPUS] [--busy] [--sum]
 *
 * A devdax store maps exactly [dax-offset, dax-offset + store-bytes) and never
 * touches anything outside it. The server writes into the store only when a
 * client sends PUT or FETCH. It does not initialise the store.
 */
#define RCB_WITH_MERCURY
#include "rcb_common.h"
#include <signal.h>
#include <stdatomic.h>

typedef struct bounce {
    void *buf;
    hg_bulk_t bulk;
    struct bounce *next;
} bounce_t;

typedef struct req {
    hg_handle_t h;
    rcb_in_t in;
    rcb_out_t out;
    uint64_t t0, t_q, t_bulk;
    bounce_t *b;     /* pooled bounce buffer */
    void *abuf;      /* per-request buffer (ALLOC) */
    hg_bulk_t abulk; /* bulk handle of abuf, or a per-request handle over the slot (--reg slot) */
    int stage;       /* PUT with COPY: 1 once the data is in the bounce buffer */
    struct req *next;
} req_t;

static hg_class_t *g_class;
static hg_context_t *g_ctx;
static char *g_store;
static uint64_t g_store_bytes, g_slot_bytes = 4UL << 20, g_nslots;
static hg_bulk_t g_store_bulk = HG_BULK_NULL;
static int g_reg_whole = 1, g_workers = 0, g_nbounce = 64, g_sum = 0, g_busy = 0;
static volatile sig_atomic_t g_stop = 0;

static pthread_mutex_t g_qm = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_qcv = PTHREAD_COND_INITIALIZER;
static req_t *g_qhead, *g_qtail;

static pthread_mutex_t g_bm = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_bcv = PTHREAD_COND_INITIALIZER;
static bounce_t *g_bfree;

static atomic_ullong g_nreq, g_bytes_out, g_bytes_in, g_bytes_file;

static void on_signal(int sig)
{
    (void) sig;
    g_stop = 1;
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

static void cleanup(req_t *r)
{
    int shutdown = r->in.op == RCB_OP_SHUTDOWN;
    if (r->abulk != HG_BULK_NULL)
        HG_Bulk_free(r->abulk);
    free(r->abuf);
    if (r->b)
        bounce_put(r->b);
    HG_Free_input(r->h, &r->in);
    HG_Destroy(r->h);
    free(r);
    if (shutdown)
        g_stop = 1;
}

static hg_return_t on_respond(const struct hg_cb_info *info)
{
    cleanup((req_t *) info->arg);
    return HG_SUCCESS;
}

static void respond(req_t *r, int64_t ret)
{
    r->out.ret = ret;
    if (g_sum && ret > 0 && r->in.slot >= 0)
        r->out.sum = rcb_sum(g_store + (uint64_t) r->in.slot * g_slot_bytes, (size_t) ret);
    r->out.ns_total = rcb_now_ns() - r->t0;
    atomic_fetch_add(&g_nreq, 1);
    if (HG_Respond(r->h, on_respond, r, &r->out) != HG_SUCCESS) {
        fprintf(stderr, "rcb_server: HG_Respond failed\n");
        cleanup(r);
    }
}

static void submit(req_t *r)
{
    r->t_q = rcb_now_ns();
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

static void work(req_t *r);

static hg_return_t on_bulk(const struct hg_cb_info *info)
{
    req_t *r = (req_t *) info->arg;
    r->out.ns_bulk = rcb_now_ns() - r->t_bulk;
    if (info->ret != HG_SUCCESS) {
        fprintf(stderr, "rcb_server: bulk transfer failed (%d)\n", (int) info->ret);
        respond(r, -EIO);
    } else if (r->in.op == RCB_OP_PUT && r->stage == 1) {
        if (g_workers > 0 && !(r->in.flags & RCB_F_INLINE))
            submit(r);
        else
            work(r);
    } else {
        if (r->in.op == RCB_OP_PUT)
            atomic_fetch_add(&g_bytes_in, (unsigned long long) r->in.size);
        else
            atomic_fetch_add(&g_bytes_out, (unsigned long long) r->in.size);
        respond(r, r->in.size);
    }
    return HG_SUCCESS;
}

static void start_bulk(req_t *r, hg_bulk_op_t op, hg_bulk_t local, hg_size_t local_off)
{
    const struct hg_info *hgi = HG_Get_info(r->h);
    r->t_bulk = rcb_now_ns();
    hg_return_t hr = HG_Bulk_transfer(g_ctx, on_bulk, r, op, hgi->addr, r->in.bulk, 0, local, local_off,
        (hg_size_t) r->in.size, HG_OP_ID_IGNORE);
    if (hr != HG_SUCCESS) {
        fprintf(stderr, "rcb_server: HG_Bulk_transfer failed to start (%d)\n", (int) hr);
        respond(r, -EIO);
    }
}

/* Transfer between the client and the store itself. */
static void start_bulk_store(req_t *r, hg_bulk_op_t op)
{
    uint64_t off = (uint64_t) r->in.slot * g_slot_bytes;
    if (g_reg_whole) {
        start_bulk(r, op, g_store_bulk, off);
        return;
    }
    void *p = g_store + off;
    hg_size_t sz = (hg_size_t) r->in.size;
    if (HG_Bulk_create(g_class, 1, &p, &sz, HG_BULK_READWRITE, &r->abulk) != HG_SUCCESS) {
        r->abulk = HG_BULK_NULL;
        respond(r, -ENOMEM);
        return;
    }
    start_bulk(r, op, r->abulk, 0);
}

/* A DRAM buffer for this request: pooled and registered once, or allocated here. */
static void *acquire(req_t *r)
{
    if ((r->in.flags & (RCB_F_ALLOC | RCB_F_INLINE)) || g_workers == 0) { /* the progress thread must not wait for the pool */
        r->abuf = calloc(1, (size_t) r->in.size);
        return r->abuf;
    }
    r->b = bounce_get();
    return r->b->buf;
}

static void start_bulk_buf(req_t *r, hg_bulk_op_t op)
{
    if (r->b) {
        start_bulk(r, op, r->b->bulk, 0);
        return;
    }
    hg_size_t sz = (hg_size_t) r->in.size;
    if (HG_Bulk_create(g_class, 1, &r->abuf, &sz, HG_BULK_READWRITE, &r->abulk) != HG_SUCCESS) {
        r->abulk = HG_BULK_NULL;
        respond(r, -ENOMEM);
        return;
    }
    start_bulk(r, op, r->abulk, 0);
}

/* Steps that copy memory or read a file. Runs on a worker thread, or on the
 * progress thread when the server has no workers (as in FitCache). */
static void work(req_t *r)
{
    size_t size = (size_t) r->in.size;
    char *sp = r->in.slot >= 0 ? g_store + (uint64_t) r->in.slot * g_slot_bytes : NULL;
    int copy = r->in.flags & RCB_F_COPY;
    uint64_t t;
    void *buf;

    if (r->t_q) {
        r->out.ns_queue += rcb_now_ns() - r->t_q;
        r->t_q = 0;
    }
    switch (r->in.op) {
    case RCB_OP_GET: /* COPY: store -> buffer -> client */
        if (!(buf = acquire(r))) {
            respond(r, -ENOMEM);
            return;
        }
        t = rcb_now_ns();
        memcpy(buf, sp, size);
        r->out.ns_copy = rcb_now_ns() - t;
        start_bulk_buf(r, HG_BULK_PUSH);
        return;
    case RCB_OP_PUT: /* COPY: client -> buffer -> store */
        if (r->stage == 0) {
            if (!acquire(r)) {
                respond(r, -ENOMEM);
                return;
            }
            r->stage = 1;
            start_bulk_buf(r, HG_BULK_PULL);
            return;
        }
        buf = r->b ? r->b->buf : r->abuf;
        t = rcb_now_ns();
        memcpy(sp, buf, size);
        r->out.ns_copy = rcb_now_ns() - t;
        r->stage = 2;
        atomic_fetch_add(&g_bytes_in, (unsigned long long) size);
        respond(r, (int64_t) size);
        return;
    case RCB_OP_FETCH: { /* file -> slot (directly, or through a buffer with COPY) -> client */
        int direct = sp && !copy;
        buf = direct ? (void *) sp : acquire(r);
        if (!buf) {
            respond(r, -ENOMEM);
            return;
        }
        t = rcb_now_ns();
        int fd = open(r->in.path, O_RDONLY);
        if (fd < 0) {
            respond(r, -errno);
            return;
        }
        size_t got = 0;
        while (got < size) {
            ssize_t n = pread(fd, (char *) buf + got, size - got, (off_t) got);
            if (n < 0 && errno == EINTR)
                continue;
            if (n <= 0)
                break;
            got += (size_t) n;
        }
        close(fd);
        r->out.ns_io = rcb_now_ns() - t;
        if (got != size) {
            respond(r, -EIO);
            return;
        }
        atomic_fetch_add(&g_bytes_file, (unsigned long long) size);
        if (sp && copy) {
            t = rcb_now_ns();
            memcpy(sp, buf, size);
            r->out.ns_copy = rcb_now_ns() - t;
        }
        if (sp)
            atomic_fetch_add(&g_bytes_in, (unsigned long long) size);
        if (r->in.flags & RCB_F_NOPUSH)
            respond(r, (int64_t) size);
        else if (direct)
            start_bulk_store(r, HG_BULK_PUSH);
        else
            start_bulk_buf(r, HG_BULK_PUSH);
        return;
    }
    default:
        respond(r, -EINVAL);
    }
}

static void *worker(void *arg)
{
    (void) arg;
    for (;;) {
        pthread_mutex_lock(&g_qm);
        while (!g_qhead && !g_stop)
            pthread_cond_wait(&g_qcv, &g_qm);
        req_t *r = g_qhead;
        if (r) {
            g_qhead = r->next;
            if (!g_qhead)
                g_qtail = NULL;
        }
        pthread_mutex_unlock(&g_qm);
        if (!r)
            return NULL;
        work(r);
    }
}

static hg_return_t rcb_handler(hg_handle_t h)
{
    req_t *r = (req_t *) calloc(1, sizeof *r);
    r->h = h;
    r->t0 = rcb_now_ns();
    r->abulk = HG_BULK_NULL;
    if (HG_Get_input(h, &r->in) != HG_SUCCESS) {
        fprintf(stderr, "rcb_server: HG_Get_input failed\n");
        HG_Destroy(h);
        free(r);
        return HG_SUCCESS;
    }
    int op = r->in.op;
    if (op == RCB_OP_NULL || op == RCB_OP_SHUTDOWN) {
        respond(r, 0);
        return HG_SUCCESS;
    }
    if (r->in.size <= 0 || (uint64_t) r->in.size > g_slot_bytes || r->in.slot >= (int64_t) g_nslots ||
        (r->in.slot < 0 && op != RCB_OP_FETCH) || (op != RCB_OP_GET && op != RCB_OP_PUT && op != RCB_OP_FETCH)) {
        respond(r, -EINVAL);
        return HG_SUCCESS;
    }
    if ((op == RCB_OP_GET || op == RCB_OP_PUT) && !(r->in.flags & RCB_F_COPY)) {
        start_bulk_store(r, op == RCB_OP_GET ? HG_BULK_PUSH : HG_BULK_PULL);
        return HG_SUCCESS;
    }
    if (g_workers > 0 && !(r->in.flags & RCB_F_INLINE))
        submit(r);
    else
        work(r);
    return HG_SUCCESS;
}

static const char *arg_val(int argc, char **argv, const char *name, const char *def)
{
    for (int i = 1; i + 1 < argc; i++)
        if (!strcmp(argv[i], name))
            return argv[i + 1];
    return def;
}

static int arg_flag(int argc, char **argv, const char *name)
{
    for (int i = 1; i < argc; i++)
        if (!strcmp(argv[i], name))
            return 1;
    return 0;
}

int main(int argc, char **argv)
{
    const char *backend = arg_val(argc, argv, "--backend", "");
    const char *dax_path = arg_val(argc, argv, "--dax-path", NULL);
    uint64_t dax_off = strtoull(arg_val(argc, argv, "--dax-offset", "0"), NULL, 0);
    const char *proto = arg_val(argc, argv, "--proto", "ofi+verbs;ofi_rxm://");
    const char *addr_file = arg_val(argc, argv, "--addr-file", NULL);
    g_store_bytes = strtoull(arg_val(argc, argv, "--store-bytes", "0"), NULL, 0);
    g_slot_bytes = strtoull(arg_val(argc, argv, "--slot-bytes", "4194304"), NULL, 0);
    g_workers = atoi(arg_val(argc, argv, "--workers", "0"));
    g_nbounce = atoi(arg_val(argc, argv, "--bounce", "64"));
    g_reg_whole = strcmp(arg_val(argc, argv, "--reg", "whole"), "slot") != 0;
    g_sum = arg_flag(argc, argv, "--sum");
    g_busy = arg_flag(argc, argv, "--busy");
    rcb_pin(arg_val(argc, argv, "--pin", NULL));

    if (!g_store_bytes || g_store_bytes % RCB_HUGE || g_slot_bytes % RCB_HUGE ||
        (strcmp(backend, "dram") && strcmp(backend, "dax")) || (!strcmp(backend, "dax") && !dax_path)) {
        fprintf(stderr, "usage: rcb_server --backend dram|dax --store-bytes N [--dax-path DEV --dax-offset N] "
                        "[--slot-bytes N] [--proto STR] [--addr-file FILE] [--workers N] [--bounce N] "
                        "[--reg whole|slot] [--pin CPUS] [--busy] [--sum]\n"
                        "       store-bytes, slot-bytes and dax-offset must be multiples of 2 MiB\n");
        return 2;
    }
    g_nslots = g_store_bytes / g_slot_bytes;

    uint64_t t = rcb_now_ns();
    if (!strcmp(backend, "dax")) {
        g_store = (char *) rcb_map_dax(dax_path, dax_off, g_store_bytes, 1);
        if (g_store)
            printf("store: devdax %s bytes [%" PRIu64 ", %" PRIu64 ") mapped read-write\n", dax_path, dax_off,
                dax_off + g_store_bytes);
    } else {
        g_store = (char *) rcb_alloc_dram(g_store_bytes);
        if (g_store)
            printf("store: anonymous DRAM, %" PRIu64 " bytes, zeroed\n", g_store_bytes);
    }
    if (!g_store) {
        fprintf(stderr, "rcb_server: cannot set up the store\n");
        return 1;
    }
    printf("store: %" PRIu64 " slots of %" PRIu64 " bytes, set up in %.1f ms\n", g_nslots, g_slot_bytes,
        (rcb_now_ns() - t) / 1e6);

    struct hg_init_info info = HG_INIT_INFO_INITIALIZER;
    if (g_busy)
        info.na_init_info.progress_mode = NA_NO_BLOCK;
    g_class = HG_Init_opt(proto, HG_TRUE, &info);
    if (!g_class) {
        fprintf(stderr, "rcb_server: HG_Init(%s) failed\n", proto);
        return 1;
    }
    g_ctx = HG_Context_create(g_class);
    if (!g_ctx) {
        fprintf(stderr, "rcb_server: HG_Context_create failed\n");
        return 1;
    }
    HG_Register_name(g_class, RCB_RPC_NAME, hg_proc_rcb_in_t, hg_proc_rcb_out_t, rcb_handler);

    char self[256] = "";
    hg_size_t self_len = sizeof self;
    hg_addr_t self_addr = HG_ADDR_NULL;
    HG_Addr_self(g_class, &self_addr);
    HG_Addr_to_string(g_class, self, &self_len, self_addr);
    HG_Addr_free(g_class, self_addr);
    printf("address: %s\n", self);

    if (g_reg_whole) {
        void *p = g_store;
        hg_size_t sz = (hg_size_t) g_store_bytes;
        t = rcb_now_ns();
        if (HG_Bulk_create(g_class, 1, &p, &sz, HG_BULK_READWRITE, &g_store_bulk) != HG_SUCCESS) {
            fprintf(stderr, "rcb_server: registering the whole store failed; try --reg slot\n");
            return 1;
        }
        printf("store registered for bulk transfers in %.1f ms\n", (rcb_now_ns() - t) / 1e6);
    }

    bounce_t *bounces = (bounce_t *) calloc((size_t) (g_nbounce > 0 ? g_nbounce : 1), sizeof *bounces);
    if (g_workers > 0 && g_nbounce > 0) {
        char *region = (char *) rcb_alloc_dram((size_t) g_nbounce * g_slot_bytes);
        if (!region) {
            fprintf(stderr, "rcb_server: cannot allocate bounce buffers\n");
            return 1;
        }
        for (int i = 0; i < g_nbounce; i++) {
            bounces[i].buf = region + (uint64_t) i * g_slot_bytes;
            hg_size_t sz = (hg_size_t) g_slot_bytes;
            if (HG_Bulk_create(g_class, 1, &bounces[i].buf, &sz, HG_BULK_READWRITE, &bounces[i].bulk) != HG_SUCCESS) {
                fprintf(stderr, "rcb_server: registering a bounce buffer failed\n");
                return 1;
            }
            bounces[i].next = g_bfree;
            g_bfree = &bounces[i];
        }
    }

    pthread_t *tids = (pthread_t *) calloc((size_t) (g_workers > 0 ? g_workers : 1), sizeof *tids);
    for (int i = 0; i < g_workers; i++)
        pthread_create(&tids[i], NULL, worker, NULL);

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    printf("config: backend=%s workers=%d bounce=%d reg=%s busy=%d sum=%d pid=%d\n", backend, g_workers,
        g_workers > 0 ? g_nbounce : 0, g_reg_whole ? "whole" : "slot", g_busy, g_sum, (int) getpid());
    if (addr_file) {
        FILE *f = fopen(addr_file, "w");
        if (f) {
            fprintf(f, "%s\n", self);
            fclose(f);
        }
    }
    printf("ready\n");
    fflush(stdout);

    uint64_t t_start = rcb_now_ns();
    while (!g_stop) {
        unsigned int n = 0;
        hg_return_t hr;
        do {
            hr = HG_Trigger(g_ctx, 0, 1, &n);
        } while (hr == HG_SUCCESS && n && !g_stop);
        HG_Progress(g_ctx, g_busy ? 0 : 100);
    }
    /* let the response to SHUTDOWN leave */
    for (uint64_t end = rcb_now_ns() + 300000000ULL; rcb_now_ns() < end;) {
        unsigned int n = 0;
        HG_Trigger(g_ctx, 0, 16, &n);
        HG_Progress(g_ctx, 10);
    }

    pthread_mutex_lock(&g_qm);
    pthread_cond_broadcast(&g_qcv);
    pthread_mutex_unlock(&g_qm);
    for (int i = 0; i < g_workers; i++)
        pthread_join(tids[i], NULL);

    double sys_s, user_s = rcb_cpu_s(RUSAGE_SELF, &sys_s);
    printf("served: requests=%llu bytes_out=%llu bytes_in=%llu bytes_file=%llu wall_s=%.1f user_s=%.2f sys_s=%.2f\n",
        (unsigned long long) g_nreq, (unsigned long long) g_bytes_out, (unsigned long long) g_bytes_in,
        (unsigned long long) g_bytes_file, (rcb_now_ns() - t_start) / 1e9, user_s, sys_s);

    if (g_workers > 0)
        for (int i = 0; i < g_nbounce; i++)
            HG_Bulk_free(bounces[i].bulk);
    if (g_store_bulk != HG_BULK_NULL)
        HG_Bulk_free(g_store_bulk);
    HG_Context_destroy(g_ctx);
    HG_Finalize(g_class);
    return 0;
}
