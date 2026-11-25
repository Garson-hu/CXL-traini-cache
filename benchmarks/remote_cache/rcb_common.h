/* Shared definitions of the remote cache data-path benchmark (rcb).
 *
 * The benchmark is a measurement tool, not a cache: the server holds objects in
 * fixed slots of one memory region (DRAM or a devdax mapping) and executes the
 * operations a client tells it to. There is no lookup, policy, or eviction logic.
 *
 * RPC pattern as in FitCache: the client registers a buffer and sends its bulk
 * handle, the server moves the data with HG_Bulk_transfer and then responds. */
#ifndef RCB_COMMON_H
#define RCB_COMMON_H

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
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define RCB_RPC_NAME "rcb_io"
#define RCB_HUGE (2UL << 20)

/* operations */
enum {
    RCB_OP_NULL = 0,     /* respond immediately: RPC cost without data */
    RCB_OP_GET = 1,      /* server pushes `size` bytes of slot to the client */
    RCB_OP_PUT = 2,      /* server pulls `size` bytes from the client into slot */
    RCB_OP_FETCH = 3,    /* server reads file `path` into slot (or a bounce buffer if slot < 0) and pushes it */
    RCB_OP_SHUTDOWN = 9
};

/* flags */
#define RCB_F_COPY 1    /* move the data through a DRAM bounce buffer on the server (one memcpy) */
#define RCB_F_ALLOC 2   /* with COPY: allocate, zero and register that buffer per request, as FitCache does */
#define RCB_F_NOPUSH 4  /* FETCH: admit only, send nothing back */
#define RCB_F_INLINE 8  /* do the copy or the file read on the server's progress thread, not on a worker */

static inline uint64_t rcb_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t) ts.tv_sec * 1000000000ULL + (uint64_t) ts.tv_nsec;
}

static inline double rcb_cpu_s(int who, double *sys_s)
{
    struct rusage ru;
    getrusage(who, &ru);
    if (sys_s)
        *sys_s = ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6;
    return ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6;
}

/* 64-bit checksum over the buffer; only used to compare two copies of the same bytes. */
static inline uint64_t rcb_sum(const void *p, size_t n)
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

/* Anonymous DRAM, 2 MiB aligned, with transparent huge pages requested: the same
 * page size a devdax mapping uses. Touched before use. */
static inline void *rcb_alloc_dram(size_t bytes)
{
    size_t len = (bytes + RCB_HUGE - 1) / RCB_HUGE * RCB_HUGE;
    void *p = mmap(NULL, len + RCB_HUGE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED)
        return NULL;
    uintptr_t a = ((uintptr_t) p + RCB_HUGE - 1) / RCB_HUGE * RCB_HUGE;
    madvise((void *) a, len, MADV_HUGEPAGE);
    memset((void *) a, 0, len);
    return (void *) a;
}

/* Map [offset, offset+bytes) of a devdax device. Both must be multiples of 2 MiB. */
static inline void *rcb_map_dax(const char *path, uint64_t offset, size_t bytes, int writable)
{
    if (offset % RCB_HUGE || bytes % RCB_HUGE) {
        fprintf(stderr, "rcb: dax offset and length must be multiples of 2 MiB\n");
        return NULL;
    }
    int fd = open(path, writable ? O_RDWR : O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "rcb: open %s: %s\n", path, strerror(errno));
        return NULL;
    }
    void *p = mmap(NULL, bytes, PROT_READ | (writable ? PROT_WRITE : 0), MAP_SHARED, fd, (off_t) offset);
    close(fd);
    if (p == MAP_FAILED) {
        fprintf(stderr, "rcb: mmap %s [%" PRIu64 ", +%zu): %s\n", path, offset, bytes, strerror(errno));
        return NULL;
    }
    return p;
}

static inline void rcb_pin(const char *cpus) /* "8-15" or "3" or "0,2,4"; NULL: leave unpinned */
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
        fprintf(stderr, "rcb: sched_setaffinity(%s): %s\n", cpus, strerror(errno));
}

#ifdef RCB_WITH_MERCURY
#include <mercury.h>
#include <mercury_bulk.h>
#include <mercury_proc.h>
#include <mercury_proc_bulk.h>
#include <mercury_proc_string.h>

typedef struct {
    int32_t op;
    int32_t flags;
    int64_t slot;
    int64_t size;
    hg_bulk_t bulk;         /* the client's buffer */
    hg_const_string_t path; /* FETCH only */
} rcb_in_t;

typedef struct {
    int64_t ret;       /* bytes moved, or a negative errno-style code */
    uint64_t ns_total; /* handler entry to respond */
    uint64_t ns_queue; /* waiting for a worker thread */
    uint64_t ns_io;    /* reading the file (FETCH) */
    uint64_t ns_copy;  /* memcpy between the store and a bounce buffer */
    uint64_t ns_bulk;  /* HG_Bulk_transfer call to its completion callback */
    uint64_t sum;      /* checksum of the object as stored (only when the server runs with --sum) */
} rcb_out_t;

static inline hg_return_t hg_proc_rcb_in_t(hg_proc_t proc, void *data)
{
    rcb_in_t *in = (rcb_in_t *) data;
    hg_return_t r;
    if ((r = hg_proc_int32_t(proc, &in->op)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int32_t(proc, &in->flags)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->slot)) != HG_SUCCESS) return r;
    if ((r = hg_proc_int64_t(proc, &in->size)) != HG_SUCCESS) return r;
    if ((r = hg_proc_hg_bulk_t(proc, &in->bulk)) != HG_SUCCESS) return r;
    return hg_proc_hg_const_string_t(proc, &in->path);
}

static inline hg_return_t hg_proc_rcb_out_t(hg_proc_t proc, void *data)
{
    rcb_out_t *out = (rcb_out_t *) data;
    hg_return_t r;
    if ((r = hg_proc_int64_t(proc, &out->ret)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_total)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_queue)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_io)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_copy)) != HG_SUCCESS) return r;
    if ((r = hg_proc_uint64_t(proc, &out->ns_bulk)) != HG_SUCCESS) return r;
    return hg_proc_uint64_t(proc, &out->sum);
}
#endif /* RCB_WITH_MERCURY */

#endif /* RCB_COMMON_H */
