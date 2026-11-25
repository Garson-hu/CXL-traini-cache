/* Shared definitions of the minimal CXL training cache (cc).
 *
 * Wire protocol between training clients and the cache server (Mercury):
 *   cc_get  GET(job, epoch, position, object): the client registers a buffer and sends its bulk
 *           handle; the server pushes the object's bytes into it and then responds.
 *   cc_ctl  small control messages: register a job, announce the order of an epoch, end a job,
 *           read counters, shut the server down.
 *
 * The helpers for memory, timing and pinning are copied from the data-path benchmark
 * (benchmarks/remote_cache/rcb_common.h), which stays unchanged. */
#ifndef CC_COMMON_H
#define CC_COMMON_H

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define CC_RPC_GET "cc_get"
#define CC_RPC_CTL "cc_ctl"
#define CC_HUGE (2UL << 20)
#define CC_CTL_MAX_IDS 256 /* object identifiers per control message; an epoch order is sent in pieces */

/* control operations */
enum {
    CC_CTL_NULL = 0,     /* respond immediately */
    CC_CTL_REGISTER = 1, /* a = seed, b = epoch length (files per epoch), c = number of epochs */
    CC_CTL_ANNOUNCE = 2, /* a = epoch, b = offset of this piece in the epoch's order, ids[n] = objects */
    CC_CTL_END = 3,      /* the job has finished */
    CC_CTL_STATS = 4,    /* a = which counter; answered by the manager */
    CC_CTL_SHUTDOWN = 9
};

/* how a GET was served (cc_get_out_t.kind) */
enum {
    CC_KIND_HIT = 1,       /* from the store, zero-copy */
    CC_KIND_MISS_ADMIT = 2, /* from storage through a DRAM buffer; the object was admitted */
    CC_KIND_MISS_BYPASS = 3, /* from storage through a DRAM buffer; not admitted */
    CC_KIND_HIT_WAITED = 4  /* from the store, after waiting for another request's admission of the same object */
};

static inline uint64_t cc_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t) ts.tv_sec * 1000000000ULL + (uint64_t) ts.tv_nsec;
}

/* 64-bit checksum over the buffer; only used to compare two copies of the same bytes. */
static inline uint64_t cc_sum(const void *p, size_t n)
{
    const unsigned char *b = (const unsigned char *) p;
    uint64_t h = 1469598103934665603ULL, w;
    size_t i = 0;
    for (; i + 8 <= n; i += 8) {
        memcpy(&w, b + i, 8);
        h = (h ^ w) * 1099511628211ULL;
        h ^= h >> 29;
    }
    for (; i < n; i++)
        h = (h ^ b[i]) * 1099511628211ULL;
    return h;
}

/* Anonymous DRAM, 2 MiB aligned, transparent huge pages requested, touched before use. */
static inline void *cc_alloc_dram(size_t bytes)
{
    size_t len = (bytes + CC_HUGE - 1) / CC_HUGE * CC_HUGE;
    void *p = mmap(NULL, len + CC_HUGE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED)
        return NULL;
    uintptr_t a = ((uintptr_t) p + CC_HUGE - 1) / CC_HUGE * CC_HUGE;
    madvise((void *) a, len, MADV_HUGEPAGE);
    memset((void *) a, 0, len);
    return (void *) a;
}

/* Map [offset, offset+bytes) of a devdax device read-write. Both must be multiples of 2 MiB.
 * Nothing outside that range is mapped. */
static inline void *cc_map_dax(const char *path, uint64_t offset, size_t bytes)
{
    if (offset % CC_HUGE || bytes % CC_HUGE) {
        fprintf(stderr, "cc: dax offset and length must be multiples of 2 MiB\n");
        return NULL;
    }
    int fd = open(path, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "cc: open %s: %s\n", path, strerror(errno));
        return NULL;
    }
    void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, (off_t) offset);
    close(fd);
    if (p == MAP_FAILED) {
        fprintf(stderr, "cc: mmap %s [%" PRIu64 ", +%zu): %s\n", path, offset, bytes, strerror(errno));
        return NULL;
    }
    return p;
}

/* Restrict the calling thread to a CPU list: "8-15", "3", "0,2,4". NULL or "": leave unpinned. */
static inline void cc_pin(const char *cpus)
{
    if (!cpus || !*cpus)
        return;
    cpu_set_t set;
    CPU_ZERO(&set);
    char *dup = strdup(cpus), *save = NULL;
    for (char *tok = strtok_r(dup, ",", &save); tok; tok = strtok_r(NULL, ",", &save)) {
        int a, b;
        if (sscanf(tok, "%d-%d", &a, &b) == 2) {
            for (int c = a; c <= b; c++)
                CPU_SET(c, &set);
        } else if (sscanf(tok, "%d", &a) == 1)
            CPU_SET(a, &set);
    }
    free(dup);
    if (sched_setaffinity(0, sizeof set, &set) != 0)
        fprintf(stderr, "cc: sched_setaffinity(%s): %s\n", cpus, strerror(errno));
}

#ifdef CC_WITH_MERCURY
#include <mercury.h>
#include <mercury_bulk.h>
#include <mercury_proc.h>
#include <mercury_proc_bulk.h>

typedef struct {
    int32_t job;
    int32_t epoch;
    int64_t pos;    /* position of this access in the epoch's announced order */
    int64_t obj;    /* object identifier: line number in the catalog */
    hg_bulk_t bulk; /* the client's buffer */
} cc_get_in_t;

typedef struct {
    int64_t ret;       /* bytes sent, or a negative errno-style code */
    int32_t kind;      /* CC_KIND_* */
    int32_t pad;
    uint64_t ns_total; /* handler entry to respond */
    uint64_t ns_wait;  /* handler entry to the manager's decision (ordering, lookup, waiting for an admission) */
    uint64_t ns_io;    /* reading the file (misses) */
    uint64_t ns_bulk;  /* HG_Bulk_transfer call to its completion */
} cc_get_out_t;

typedef struct {
    int32_t op;
    int32_t job;
    int64_t a, b, c;
    int32_t n;
    int64_t ids[CC_CTL_MAX_IDS];
} cc_ctl_in_t;

typedef struct {
    int64_t ret;
} cc_ctl_out_t;

static inline hg_return_t hg_proc_cc_get_in_t(hg_proc_t proc, void *data)
{
    cc_get_in_t *in = (cc_get_in_t *) data;
    hg_return_t r;
    if ((r = hg_proc_int32_t(proc, &in->job)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int32_t(proc, &in->epoch)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->pos)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->obj)) != HG_SUCCESS) return r;
    return hg_proc_hg_bulk_t(proc, &in->bulk);
}

static inline hg_return_t hg_proc_cc_get_out_t(hg_proc_t proc, void *data)
{
    cc_get_out_t *out = (cc_get_out_t *) data;
    hg_return_t r;
    if ((r = hg_proc_int64_t(proc, &out->ret)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int32_t(proc, &out->kind)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int32_t(proc, &out->pad)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_total)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_wait)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_io)) != HG_SUCCESS) return r;
    return hg_proc_uint64_t(proc, &out->ns_bulk);
}

static inline hg_return_t hg_proc_cc_ctl_in_t(hg_proc_t proc, void *data)
{
    cc_ctl_in_t *in = (cc_ctl_in_t *) data;
    hg_return_t r;
    if ((r = hg_proc_int32_t(proc, &in->op)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int32_t(proc, &in->job)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->a)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->b)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->c)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int32_t(proc, &in->n)) != HG_SUCCESS) return r;
    if (in->n < 0 || in->n > CC_CTL_MAX_IDS)
        return HG_PROTOCOL_ERROR;
    for (int32_t i = 0; i < in->n; i++)
        if ((r = hg_proc_int64_t(proc, &in->ids[i])) != HG_SUCCESS) return r;
    return HG_SUCCESS;
}

static inline hg_return_t hg_proc_cc_ctl_out_t(hg_proc_t proc, void *data)
{
    return hg_proc_int64_t(proc, &((cc_ctl_out_t *) data)->ret);
}
#endif /* CC_WITH_MERCURY */

#endif /* CC_COMMON_H */
