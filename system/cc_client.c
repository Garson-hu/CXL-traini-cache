/* cc_client: client side of the minimal CXL training cache, built as a shared library and used
 * from Python through ctypes (system/cc_client.py).
 *
 * One Mercury context and one progress thread per process. ccc_get may be called from any
 * number of threads at once: each call takes a registered buffer from a pool, sends
 * GET(job, epoch, position, object) with the buffer's bulk handle, and blocks until the server
 * has pushed the object's bytes into the buffer and responded. The caller copies the bytes out
 * and returns the buffer with ccc_release.
 *
 * The RPC pattern follows the data-path benchmark client (benchmarks/remote_cache/rcb_client.c). */
#define CC_WITH_MERCURY
#include "cc_common.h"

typedef struct {
    int32_t kind;
    int32_t buf;          /* index of the buffer that holds the data; give it back with ccc_release */
    uint64_t ns_client;   /* this call, start to finish */
    uint64_t ns_srv_total, ns_srv_wait, ns_srv_io, ns_srv_bulk;
} ccc_res_t;

typedef struct {
    void *buf;
    hg_bulk_t bulk;
    int next;
} cbuf_t;

typedef struct {
    pthread_mutex_t m;
    pthread_cond_t cv;
    int done;
    hg_return_t hret;
    cc_get_out_t out;
    cc_ctl_out_t cout;
    int is_ctl;
} call_t;

static hg_class_t *g_class;
static hg_context_t *g_ctx;
static hg_id_t g_rpc_get, g_rpc_ctl;
static hg_addr_t g_svr = HG_ADDR_NULL;
static pthread_t g_ptid;
static volatile int g_stop;
static int g_busy, g_ready;
static cbuf_t *g_bufs;
static int g_nbuf, g_free = -1;
static uint64_t g_buf_bytes;
static pthread_mutex_t g_bm = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_bcv = PTHREAD_COND_INITIALIZER;

static void *progress_fn(void *arg)
{
    (void) arg;
    while (!g_stop) {
        unsigned int n = 0;
        hg_return_t hr;
        do {
            hr = HG_Trigger(g_ctx, 0, 1, &n);
        } while (hr == HG_SUCCESS && n && !g_stop);
        HG_Progress(g_ctx, g_busy ? 0 : 100);
    }
    return NULL;
}

static hg_return_t on_reply(const struct hg_cb_info *info)
{
    call_t *c = (call_t *) info->arg;
    hg_return_t hr = info->ret;
    if (hr == HG_SUCCESS) {
        if (c->is_ctl) {
            hr = HG_Get_output(info->info.forward.handle, &c->cout);
            if (hr == HG_SUCCESS)
                HG_Free_output(info->info.forward.handle, &c->cout);
        } else {
            hr = HG_Get_output(info->info.forward.handle, &c->out);
            if (hr == HG_SUCCESS)
                HG_Free_output(info->info.forward.handle, &c->out);
        }
    }
    pthread_mutex_lock(&c->m);
    c->hret = hr;
    c->done = 1;
    pthread_cond_signal(&c->cv);
    pthread_mutex_unlock(&c->m);
    return HG_SUCCESS;
}

/* Forward and wait. Returns the Mercury status. */
static hg_return_t call(hg_id_t rpc, void *in, call_t *c)
{
    hg_handle_t h;
    pthread_mutex_init(&c->m, NULL);
    pthread_cond_init(&c->cv, NULL);
    c->done = 0;
    hg_return_t hr = HG_Create(g_ctx, g_svr, rpc, &h);
    if (hr != HG_SUCCESS)
        return hr;
    hr = HG_Forward(h, on_reply, c, in);
    if (hr != HG_SUCCESS) {
        HG_Destroy(h);
        return hr;
    }
    pthread_mutex_lock(&c->m);
    while (!c->done)
        pthread_cond_wait(&c->cv, &c->m);
    pthread_mutex_unlock(&c->m);
    HG_Destroy(h);
    pthread_mutex_destroy(&c->m);
    pthread_cond_destroy(&c->cv);
    return c->hret;
}

/* proto: e.g. "ofi+verbs;ofi_rxm://<this node's InfiniBand address>"; server_addr: the address the
 * server printed. nbuf registered buffers of buf_bytes each: the number of GETs that can be in
 * flight at once. Returns 0 or a negative code. */
int ccc_init(const char *proto, const char *server_addr, int nbuf, uint64_t buf_bytes, int busy)
{
    if (g_ready)
        return 0;
    struct hg_init_info info = HG_INIT_INFO_INITIALIZER;
    g_busy = busy;
    if (busy)
        info.na_init_info.progress_mode = NA_NO_BLOCK;
    g_class = HG_Init_opt(proto, HG_FALSE, &info);
    if (!g_class) {
        fprintf(stderr, "cc_client: HG_Init(%s) failed\n", proto);
        return -EIO;
    }
    g_ctx = HG_Context_create(g_class);
    if (!g_ctx)
        return -EIO;
    g_rpc_get = HG_Register_name(g_class, CC_RPC_GET, hg_proc_cc_get_in_t, hg_proc_cc_get_out_t, NULL);
    g_rpc_ctl = HG_Register_name(g_class, CC_RPC_CTL, hg_proc_cc_ctl_in_t, hg_proc_cc_ctl_out_t, NULL);
    if (HG_Addr_lookup2(g_class, server_addr, &g_svr) != HG_SUCCESS) {
        fprintf(stderr, "cc_client: cannot look up %s\n", server_addr);
        return -EHOSTUNREACH;
    }
    g_nbuf = nbuf;
    g_buf_bytes = buf_bytes;
    g_bufs = (cbuf_t *) calloc((size_t) nbuf, sizeof *g_bufs);
    char *region = (char *) cc_alloc_dram((size_t) nbuf * buf_bytes);
    if (!region)
        return -ENOMEM;
    for (int i = 0; i < nbuf; i++) {
        g_bufs[i].buf = region + (uint64_t) i * buf_bytes;
        hg_size_t sz = (hg_size_t) buf_bytes;
        if (HG_Bulk_create(g_class, 1, &g_bufs[i].buf, &sz, HG_BULK_WRITE_ONLY, &g_bufs[i].bulk) != HG_SUCCESS) {
            fprintf(stderr, "cc_client: registering a buffer failed\n");
            return -EIO;
        }
        g_bufs[i].next = g_free;
        g_free = i;
    }
    g_stop = 0;
    pthread_create(&g_ptid, NULL, progress_fn, NULL);
    g_ready = 1;
    return 0;
}

static int buf_get(void)
{
    pthread_mutex_lock(&g_bm);
    while (g_free < 0)
        pthread_cond_wait(&g_bcv, &g_bm);
    int i = g_free;
    g_free = g_bufs[i].next;
    pthread_mutex_unlock(&g_bm);
    return i;
}

void ccc_release(int i)
{
    if (i < 0 || i >= g_nbuf)
        return;
    pthread_mutex_lock(&g_bm);
    g_bufs[i].next = g_free;
    g_free = i;
    pthread_cond_signal(&g_bcv);
    pthread_mutex_unlock(&g_bm);
}

/* Fetch one object. On success returns its size, sets *data to the bytes (valid until
 * ccc_release(res->buf)) and fills res. On failure returns a negative code and holds no buffer. */
int64_t ccc_get(int32_t job, int32_t epoch, int64_t pos, int64_t obj, void **data, ccc_res_t *res)
{
    uint64_t t0 = cc_now_ns();
    int i = buf_get();
    cc_get_in_t in = {job, epoch, pos, obj, g_bufs[i].bulk};
    call_t c;
    memset(&c, 0, sizeof c);
    hg_return_t hr = call(g_rpc_get, &in, &c);
    int64_t ret = hr == HG_SUCCESS ? c.out.ret : -1100 - (int64_t) hr;
    memset(res, 0, sizeof *res);
    res->buf = -1;
    res->ns_client = cc_now_ns() - t0;
    if (ret < 0) {
        ccc_release(i);
        return ret;
    }
    res->kind = c.out.kind;
    res->buf = i;
    res->ns_srv_total = c.out.ns_total;
    res->ns_srv_wait = c.out.ns_wait;
    res->ns_srv_io = c.out.ns_io;
    res->ns_srv_bulk = c.out.ns_bulk;
    *data = g_bufs[i].buf;
    return ret;
}

/* Control message. ids may be NULL with n = 0; n is at most CC_CTL_MAX_IDS. Returns the server's
 * answer, or a negative code below -1000 for a transport error. */
int64_t ccc_ctl(int32_t op, int32_t job, int64_t a, int64_t b, int64_t c_, const int64_t *ids, int32_t n)
{
    if (n < 0 || n > CC_CTL_MAX_IDS)
        return -EINVAL;
    cc_ctl_in_t in;
    memset(&in, 0, sizeof in);
    in.op = op;
    in.job = job;
    in.a = a;
    in.b = b;
    in.c = c_;
    in.n = n;
    if (n)
        memcpy(in.ids, ids, (size_t) n * sizeof(int64_t));
    call_t c;
    memset(&c, 0, sizeof c);
    c.is_ctl = 1;
    hg_return_t hr = call(g_rpc_ctl, &in, &c);
    return hr == HG_SUCCESS ? c.cout.ret : -1100 - (int64_t) hr;
}

uint64_t ccc_sum(const void *p, uint64_t n)
{
    return cc_sum(p, (size_t) n);
}

void ccc_fini(void)
{
    if (!g_ready)
        return;
    g_stop = 1;
    pthread_join(g_ptid, NULL);
    for (int i = 0; i < g_nbuf; i++)
        HG_Bulk_free(g_bufs[i].bulk);
    HG_Addr_free(g_class, g_svr);
    HG_Context_destroy(g_ctx);
    HG_Finalize(g_class);
    g_ready = 0;
}
