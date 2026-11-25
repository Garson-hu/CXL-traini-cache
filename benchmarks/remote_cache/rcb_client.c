/* rcb_client: load generator of the remote cache data-path benchmark.
 *
 * Executes a workload file with a fixed number of threads. Each thread takes the
 * next operation, executes it, and blocks until it is complete (closed loop), as
 * a data-loader thread blocks in read(). Operations are handed out in file order.
 *
 * Workload file, one operation per line:   OP FLAGS SLOT SIZE [PATH]
 *   G  get SIZE bytes of SLOT from the server                 (Mercury)
 *   P  put SIZE bytes into SLOT (content: PATH if given, else the thread's buffer)
 *   F  the server reads PATH into SLOT (-1: no slot) and sends it back
 *   N  null RPC
 *   B  read PATH directly from the file system, no server      (direct BeeGFS path)
 * FLAGS is the sum of 1 (COPY), 2 (ALLOC), 4 (NOPUSH), 8 (INLINE); see rcb_common.h.
 *
 * An operation that writes a slot waits until earlier operations on that slot
 * are complete, and a get waits for an earlier write of its slot, so replaying a
 * recorded admission and eviction sequence keeps its order.
 *
 * Usage:
 *   rcb_client --workload FILE --threads N --out FILE.csv [--server ADDR | --server-file FILE]
 *              [--proto STR] [--repeat R] [--count N] [--seconds S] [--verify] [--pin CPUS] [--busy]
 *              [--label STR] [--shutdown]
 * With --seconds the run ends after S seconds even if operations are left.
 */
#define RCB_WITH_MERCURY
#include "rcb_common.h"

typedef struct {
    char op;
    int flags;
    long slot;
    long size;
    char *path;
} wop_t;

typedef struct {
    int64_t ret;
    uint64_t t_start, lat, ns_prep;
    rcb_out_t out;
    uint16_t thr;
} rec_t;

typedef struct {
    int id;
    pthread_t tid;
    void *buf, *vbuf;
    hg_bulk_t bulk;
    pthread_mutex_t m;
    pthread_cond_t cv;
    int done;
    hg_return_t hret;
    rcb_out_t out;
} thr_t;

static hg_class_t *g_class;
static hg_context_t *g_ctx;
static hg_id_t g_rpc;
static hg_addr_t g_svr = HG_ADDR_NULL;
static volatile int g_stop_progress;
static int g_busy, g_verify;

static wop_t *g_ops;
static size_t g_nops, g_total, g_cursor;
static uint64_t g_deadline; /* monotonic ns; 0: none */
static rec_t *g_recs;
static pthread_mutex_t g_m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cv = PTHREAD_COND_INITIALIZER;
static unsigned char *g_writer;
static unsigned short *g_readers;
static uint64_t g_t_begin;
static size_t g_buf_bytes = 4UL << 20;
static unsigned long g_mismatch, g_errors;

static void *progress_fn(void *arg)
{
    (void) arg;
    while (!g_stop_progress) {
        unsigned int n = 0;
        hg_return_t hr;
        do {
            hr = HG_Trigger(g_ctx, 0, 1, &n);
        } while (hr == HG_SUCCESS && n && !g_stop_progress);
        HG_Progress(g_ctx, g_busy ? 0 : 100);
    }
    return NULL;
}

static hg_return_t on_reply(const struct hg_cb_info *info)
{
    thr_t *t = (thr_t *) info->arg;
    rcb_out_t out;
    memset(&out, 0, sizeof out);
    hg_return_t hr = info->ret;
    if (hr == HG_SUCCESS) {
        hr = HG_Get_output(info->info.forward.handle, &out);
        if (hr == HG_SUCCESS)
            HG_Free_output(info->info.forward.handle, &out);
    }
    pthread_mutex_lock(&t->m);
    t->out = out;
    t->hret = hr;
    t->done = 1;
    pthread_cond_signal(&t->cv);
    pthread_mutex_unlock(&t->m);
    return HG_SUCCESS;
}

static int64_t rpc(thr_t *t, int op, int flags, long slot, long size, const char *path, rcb_out_t *out)
{
    hg_handle_t h;
    rcb_in_t in;
    in.op = op;
    in.flags = flags;
    in.slot = slot;
    in.size = size;
    in.bulk = t->bulk;
    in.path = path ? path : "";
    if (HG_Create(g_ctx, g_svr, g_rpc, &h) != HG_SUCCESS)
        return -1001;
    t->done = 0;
    if (HG_Forward(h, on_reply, t, &in) != HG_SUCCESS) {
        HG_Destroy(h);
        return -1002;
    }
    pthread_mutex_lock(&t->m);
    while (!t->done)
        pthread_cond_wait(&t->cv, &t->m);
    pthread_mutex_unlock(&t->m);
    HG_Destroy(h);
    if (out)
        *out = t->out;
    return t->hret == HG_SUCCESS ? t->out.ret : -1100 - (int64_t) t->hret;
}

static int64_t read_file(const char *path, void *buf, size_t size)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return -errno;
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
    return (int64_t) got;
}

static int is_write(const wop_t *o)
{
    return o->slot >= 0 && (o->op == 'P' || o->op == 'F');
}

static void *run(void *arg)
{
    thr_t *t = (thr_t *) arg;
    for (;;) {
        pthread_mutex_lock(&g_m);
        wop_t *o;
        size_t i;
        for (;;) {
            if (g_cursor >= g_total || (g_deadline && rcb_now_ns() >= g_deadline)) {
                pthread_cond_broadcast(&g_cv);
                pthread_mutex_unlock(&g_m);
                return NULL;
            }
            i = g_cursor;
            o = &g_ops[i % g_nops];
            if (o->slot < 0 || !(g_writer[o->slot] || (is_write(o) && g_readers[o->slot])))
                break;
            pthread_cond_wait(&g_cv, &g_m);
        }
        if (o->slot >= 0) {
            if (is_write(o))
                g_writer[o->slot] = 1;
            else
                g_readers[o->slot]++;
        }
        g_cursor++;
        pthread_mutex_unlock(&g_m);

        rec_t *rc = &g_recs[i];
        rc->thr = (uint16_t) t->id;
        int64_t ret;
        uint64_t t0 = rcb_now_ns();
        if (o->op == 'P' && o->path) { /* content of the put: not part of its latency */
            ret = read_file(o->path, t->buf, (size_t) o->size);
            rc->ns_prep = rcb_now_ns() - t0;
            t0 = rcb_now_ns();
        }
        switch (o->op) {
        case 'B': ret = read_file(o->path, t->buf, (size_t) o->size); break;
        case 'G': ret = rpc(t, RCB_OP_GET, o->flags, o->slot, o->size, NULL, &rc->out); break;
        case 'P': ret = rpc(t, RCB_OP_PUT, o->flags, o->slot, o->size, NULL, &rc->out); break;
        case 'F': ret = rpc(t, RCB_OP_FETCH, o->flags, o->slot, o->size, o->path, &rc->out); break;
        case 'N': ret = rpc(t, RCB_OP_NULL, 0, -1, 0, NULL, &rc->out); break;
        default: ret = -EINVAL;
        }
        uint64_t t1 = rcb_now_ns();
        rc->ret = ret;
        rc->t_start = t0 - g_t_begin;
        rc->lat = t1 - t0;

        int bad = 0, err = ret < 0 || (o->op != 'N' && ret != o->size);
        int has_data = !err && (o->op == 'G' || (o->op == 'F' && !(o->flags & RCB_F_NOPUSH)));
        if (has_data && rc->out.sum && rc->out.sum != rcb_sum(t->buf, (size_t) ret))
            bad = 1; /* what arrived differs from what the server holds */
        if (g_verify && has_data && o->path) {
            int64_t n = read_file(o->path, t->vbuf, (size_t) o->size);
            if (n != ret || memcmp(t->buf, t->vbuf, (size_t) ret) != 0)
                bad = 1; /* what arrived differs from the file */
        }
        pthread_mutex_lock(&g_m);
        g_mismatch += (unsigned long) bad;
        g_errors += (unsigned long) err;
        if (o->slot >= 0) {
            if (is_write(o))
                g_writer[o->slot] = 0;
            else
                g_readers[o->slot]--;
            pthread_cond_broadcast(&g_cv);
        }
        pthread_mutex_unlock(&g_m);
    }
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

static int load_workload(const char *file, long *max_slot, int *needs_rpc)
{
    FILE *f = fopen(file, "r");
    if (!f)
        return -1;
    size_t cap = 0;
    char *line = NULL;
    size_t len = 0;
    *max_slot = -1;
    *needs_rpc = 0;
    while (getline(&line, &len, f) > 0) {
        if (line[0] == '#' || line[0] == '\n')
            continue;
        char op, path[4096] = "";
        int flags;
        long slot, size;
        int k = sscanf(line, " %c %d %ld %ld %4095s", &op, &flags, &slot, &size, path);
        if (k < 4 || !strchr("GPFNB", op) || ((op == 'B' || op == 'F') && !path[0]) || (size_t) size > g_buf_bytes) {
            fprintf(stderr, "rcb_client: bad workload line: %s", line);
            fclose(f);
            return -1;
        }
        if (g_nops == cap) {
            cap = cap ? cap * 2 : 4096;
            g_ops = (wop_t *) realloc(g_ops, cap * sizeof *g_ops);
        }
        wop_t *o = &g_ops[g_nops++];
        o->op = op;
        o->flags = flags;
        o->slot = (op == 'B' || op == 'N') ? -1 : slot;
        o->size = size;
        o->path = path[0] ? strdup(path) : NULL;
        if (o->slot > *max_slot)
            *max_slot = o->slot;
        if (op != 'B')
            *needs_rpc = 1;
    }
    free(line);
    fclose(f);
    return g_nops ? 0 : -1;
}

int main(int argc, char **argv)
{
    const char *workload = arg_val(argc, argv, "--workload", NULL);
    const char *out_path = arg_val(argc, argv, "--out", NULL);
    const char *server = arg_val(argc, argv, "--server", NULL);
    const char *server_file = arg_val(argc, argv, "--server-file", NULL);
    const char *proto = arg_val(argc, argv, "--proto", "ofi+verbs;ofi_rxm://");
    const char *label = arg_val(argc, argv, "--label", "");
    int nthr = atoi(arg_val(argc, argv, "--threads", "1"));
    long repeat = atol(arg_val(argc, argv, "--repeat", "1"));
    long count = atol(arg_val(argc, argv, "--count", "0"));
    double seconds = atof(arg_val(argc, argv, "--seconds", "0"));
    int shutdown = arg_flag(argc, argv, "--shutdown");
    g_verify = arg_flag(argc, argv, "--verify");
    g_busy = arg_flag(argc, argv, "--busy");
    rcb_pin(arg_val(argc, argv, "--pin", NULL));

    long max_slot;
    int needs_rpc;
    if (!workload || nthr < 1 || load_workload(workload, &max_slot, &needs_rpc) != 0) {
        fprintf(stderr, "usage: rcb_client --workload FILE --threads N --out FILE.csv [--server ADDR | --server-file FILE] "
                        "[--proto STR] [--repeat R] [--count N] [--seconds S] [--verify] [--pin CPUS] [--busy] [--label STR] [--shutdown]\n");
        return 2;
    }
    if (out_path && access(out_path, F_OK) == 0) {
        fprintf(stderr, "rcb_client: %s exists; refusing to overwrite\n", out_path);
        return 2;
    }
    g_total = g_nops * (size_t) (repeat > 0 ? repeat : 1);
    if (count > 0 && (size_t) count < g_total)
        g_total = (size_t) count;
    g_recs = (rec_t *) calloc(g_total, sizeof *g_recs);
    g_writer = (unsigned char *) calloc((size_t) max_slot + 2, 1);
    g_readers = (unsigned short *) calloc((size_t) max_slot + 2, sizeof *g_readers);

    char addr[512] = "";
    pthread_t ptid;
    if (needs_rpc || shutdown) {
        if (server)
            snprintf(addr, sizeof addr, "%s", server);
        else if (server_file) {
            FILE *f = fopen(server_file, "r");
            if (!f || !fgets(addr, sizeof addr, f)) {
                fprintf(stderr, "rcb_client: cannot read %s\n", server_file);
                return 1;
            }
            fclose(f);
            addr[strcspn(addr, "\r\n")] = 0;
        }
        if (!addr[0]) {
            fprintf(stderr, "rcb_client: the workload needs a server (--server or --server-file)\n");
            return 2;
        }
        struct hg_init_info info = HG_INIT_INFO_INITIALIZER;
        if (g_busy)
            info.na_init_info.progress_mode = NA_NO_BLOCK;
        g_class = HG_Init_opt(proto, HG_FALSE, &info);
        if (!g_class) {
            fprintf(stderr, "rcb_client: HG_Init(%s) failed\n", proto);
            return 1;
        }
        g_ctx = HG_Context_create(g_class);
        g_rpc = HG_Register_name(g_class, RCB_RPC_NAME, hg_proc_rcb_in_t, hg_proc_rcb_out_t, NULL);
        if (HG_Addr_lookup2(g_class, addr, &g_svr) != HG_SUCCESS) {
            fprintf(stderr, "rcb_client: cannot resolve %s\n", addr);
            return 1;
        }
        pthread_create(&ptid, NULL, progress_fn, NULL);
    }

    thr_t *thr = (thr_t *) calloc((size_t) nthr, sizeof *thr);
    for (int i = 0; i < nthr; i++) {
        thr[i].id = i;
        thr[i].buf = rcb_alloc_dram(g_buf_bytes);
        thr[i].vbuf = g_verify ? rcb_alloc_dram(g_buf_bytes) : NULL;
        pthread_mutex_init(&thr[i].m, NULL);
        pthread_cond_init(&thr[i].cv, NULL);
        if (!thr[i].buf) {
            fprintf(stderr, "rcb_client: cannot allocate buffers\n");
            return 1;
        }
        memset(thr[i].buf, 0x5a + i, g_buf_bytes); /* content of puts that name no file */
        if (g_class) {
            hg_size_t sz = (hg_size_t) g_buf_bytes;
            if (HG_Bulk_create(g_class, 1, &thr[i].buf, &sz, HG_BULK_READWRITE, &thr[i].bulk) != HG_SUCCESS) {
                fprintf(stderr, "rcb_client: registering a buffer failed\n");
                return 1;
            }
        }
    }
    if (g_class) { /* open the connection before timing starts */
        uint64_t t = rcb_now_ns();
        int64_t r = rpc(&thr[0], RCB_OP_NULL, 0, -1, 0, NULL, NULL);
        if (r != 0) {
            fprintf(stderr, "rcb_client: first RPC to %s failed (%" PRId64 ")\n", addr, r);
            return 1;
        }
        fprintf(stderr, "rcb_client: connected to %s in %.1f ms\n", addr, (rcb_now_ns() - t) / 1e6);
    }

    double sys0, user0 = rcb_cpu_s(RUSAGE_SELF, &sys0);
    struct timespec rt;
    clock_gettime(CLOCK_REALTIME, &rt);
    g_t_begin = rcb_now_ns();
    if (seconds > 0)
        g_deadline = g_t_begin + (uint64_t) (seconds * 1e9);
    for (int i = 0; i < nthr; i++)
        pthread_create(&thr[i].tid, NULL, run, &thr[i]);
    for (int i = 0; i < nthr; i++)
        pthread_join(thr[i].tid, NULL);
    double wall = (rcb_now_ns() - g_t_begin) / 1e9;
    double sys1, user1 = rcb_cpu_s(RUSAGE_SELF, &sys1);

    g_total = g_cursor; /* operations actually executed */
    unsigned long long bytes = 0;
    for (size_t i = 0; i < g_total; i++)
        if (g_recs[i].ret > 0)
            bytes += (unsigned long long) g_recs[i].ret;
    if (out_path) {
        FILE *f = fopen(out_path, "w");
        if (!f) {
            fprintf(stderr, "rcb_client: cannot write %s\n", out_path);
            return 1;
        }
        fprintf(f, "idx,thread,op,flags,slot,size,ret,t_start_ns,lat_ns,prep_ns,srv_total_ns,srv_queue_ns,srv_io_ns,srv_copy_ns,srv_bulk_ns\n");
        for (size_t i = 0; i < g_total; i++) {
            const wop_t *o = &g_ops[i % g_nops];
            const rec_t *r = &g_recs[i];
            fprintf(f, "%zu,%u,%c,%d,%ld,%ld,%" PRId64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
                i, r->thr, o->op, o->flags, o->slot, o->size, r->ret, r->t_start, r->lat, r->ns_prep, r->out.ns_total,
                r->out.ns_queue, r->out.ns_io, r->out.ns_copy, r->out.ns_bulk);
        }
        fclose(f);
    }
    printf("{\"label\":\"%s\",\"threads\":%d,\"ops\":%zu,\"bytes\":%llu,\"wall_s\":%.6f,\"gb_per_s\":%.4f,\"ops_per_s\":%.2f,"
           "\"client_user_s\":%.3f,\"client_sys_s\":%.3f,\"errors\":%lu,\"mismatches\":%lu,\"verify\":%d,"
           "\"begin_unix_ns\":%lld}\n",
        label, nthr, g_total, bytes, wall, bytes / 1e9 / wall, g_total / wall, user1 - user0, sys1 - sys0, g_errors,
        g_mismatch, g_verify, (long long) rt.tv_sec * 1000000000LL + rt.tv_nsec);

    if (g_class) {
        if (shutdown)
            rpc(&thr[0], RCB_OP_SHUTDOWN, 0, -1, 0, NULL, NULL);
        g_stop_progress = 1;
        pthread_join(ptid, NULL);
        for (int i = 0; i < nthr; i++)
            HG_Bulk_free(thr[i].bulk);
        HG_Addr_free(g_class, g_svr);
        HG_Context_destroy(g_ctx);
        HG_Finalize(g_class);
    }
    return g_errors || g_mismatch ? 3 : 0;
}
