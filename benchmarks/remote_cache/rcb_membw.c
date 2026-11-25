/* rcb_membw: local memory copy rates of the store, without network or storage.
 *
 * Gives the reference needed to tell what the memory itself can do from what the
 * remote data path delivers. Uses the same store set-up and the same memcpy as
 * rcb_server: each thread copies whole objects between slots of the store and a
 * private DRAM buffer.
 *
 * Usage:
 *   rcb_membw --backend dram|dax --store-bytes N [--dax-path DEV --dax-offset N]
 *             [--slot-bytes N] [--object-bytes N] --readers R --writers W
 *             [--seconds S] [--pin CPUS] [--label STR]
 *
 * Readers copy store -> private buffer, writers copy private buffer -> store.
 * Every thread works on its own range of slots. A devdax store is only written
 * when --writers is above zero; the range written is the range mapped.
 */
#include "rcb_common.h"

typedef struct {
    int id, writer;
    char *store, *buf;
    uint64_t slot_bytes, obj_bytes, first_slot, nslots;
    unsigned long long bytes;
    uint64_t ns;
    pthread_t tid;
} mthr_t;

static volatile int g_go, g_stop;
static pthread_barrier_t g_barrier;

static void *run(void *arg)
{
    mthr_t *t = (mthr_t *) arg;
    uint64_t x = 0x9e3779b97f4a7c15ULL * (uint64_t) (t->id + 1);
    pthread_barrier_wait(&g_barrier);
    while (!g_go)
        ;
    uint64_t t0 = rcb_now_ns();
    while (!g_stop) {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        char *slot = t->store + (t->first_slot + x % t->nslots) * t->slot_bytes;
        if (t->writer)
            memcpy(slot, t->buf, t->obj_bytes);
        else
            memcpy(t->buf, slot, t->obj_bytes);
        t->bytes += t->obj_bytes;
    }
    t->ns = rcb_now_ns() - t0;
    return NULL;
}

static const char *arg_val(int argc, char **argv, const char *name, const char *def)
{
    for (int i = 1; i + 1 < argc; i++)
        if (!strcmp(argv[i], name))
            return argv[i + 1];
    return def;
}

int main(int argc, char **argv)
{
    const char *backend = arg_val(argc, argv, "--backend", "");
    const char *dax_path = arg_val(argc, argv, "--dax-path", NULL);
    const char *label = arg_val(argc, argv, "--label", "");
    uint64_t dax_off = strtoull(arg_val(argc, argv, "--dax-offset", "0"), NULL, 0);
    uint64_t store_bytes = strtoull(arg_val(argc, argv, "--store-bytes", "0"), NULL, 0);
    uint64_t slot_bytes = strtoull(arg_val(argc, argv, "--slot-bytes", "4194304"), NULL, 0);
    uint64_t obj_bytes = strtoull(arg_val(argc, argv, "--object-bytes", "2898293"), NULL, 0);
    int readers = atoi(arg_val(argc, argv, "--readers", "0"));
    int writers = atoi(arg_val(argc, argv, "--writers", "0"));
    double seconds = atof(arg_val(argc, argv, "--seconds", "5"));
    int n = readers + writers;
    rcb_pin(arg_val(argc, argv, "--pin", NULL));

    int dax = !strcmp(backend, "dax");
    if (n < 1 || !store_bytes || store_bytes % RCB_HUGE || slot_bytes % RCB_HUGE || obj_bytes > slot_bytes ||
        (!dax && strcmp(backend, "dram")) || (dax && !dax_path) || store_bytes / slot_bytes < (uint64_t) n) {
        fprintf(stderr, "usage: rcb_membw --backend dram|dax --store-bytes N [--dax-path DEV --dax-offset N] "
                        "[--slot-bytes N] [--object-bytes N] --readers R --writers W [--seconds S] [--pin CPUS] [--label STR]\n");
        return 2;
    }
    char *store = dax ? (char *) rcb_map_dax(dax_path, dax_off, store_bytes, writers > 0) : (char *) rcb_alloc_dram(store_bytes);
    if (!store)
        return 1;
    if (dax)
        fprintf(stderr, "store: devdax %s bytes [%" PRIu64 ", %" PRIu64 ") mapped %s\n", dax_path, dax_off,
            dax_off + store_bytes, writers > 0 ? "read-write" : "read-only");

    uint64_t per = store_bytes / slot_bytes / (uint64_t) n;
    mthr_t *t = (mthr_t *) calloc((size_t) n, sizeof *t);
    pthread_barrier_init(&g_barrier, NULL, (unsigned) n + 1);
    for (int i = 0; i < n; i++) {
        t[i].id = i;
        t[i].writer = i >= readers;
        t[i].store = store;
        t[i].slot_bytes = slot_bytes;
        t[i].obj_bytes = obj_bytes;
        t[i].first_slot = (uint64_t) i * per;
        t[i].nslots = per;
        t[i].buf = (char *) rcb_alloc_dram(slot_bytes);
        if (!t[i].buf)
            return 1;
        memset(t[i].buf, 0x33 + i, slot_bytes);
        pthread_create(&t[i].tid, NULL, run, &t[i]);
    }
    pthread_barrier_wait(&g_barrier);
    g_go = 1;
    struct timespec ts = {(time_t) seconds, (long) ((seconds - (time_t) seconds) * 1e9)};
    nanosleep(&ts, NULL);
    g_stop = 1;
    double rd = 0, wr = 0;
    for (int i = 0; i < n; i++) {
        pthread_join(t[i].tid, NULL);
        double rate = t[i].bytes / 1e9 / (t[i].ns / 1e9);
        if (t[i].writer)
            wr += rate;
        else
            rd += rate;
    }
    printf("{\"label\":\"%s\",\"backend\":\"%s\",\"readers\":%d,\"writers\":%d,\"object_bytes\":%" PRIu64 ",\"seconds\":%.1f,"
           "\"read_gb_per_s\":%.3f,\"write_gb_per_s\":%.3f,\"total_gb_per_s\":%.3f}\n",
        label, backend, readers, writers, obj_bytes, seconds, rd, wr, rd + wr);
    return 0;
}
