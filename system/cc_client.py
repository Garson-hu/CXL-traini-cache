#!/usr/bin/env python3
"""Client of the minimal CXL training cache, and two test programs built on it.

As a module (used by the training input pipeline):

    c = CacheClient(open(addr_file).read().strip())
    c.register(job, seed, epoch_len, total_accesses)
    c.announce(job, epoch, order)            # object identifiers of this epoch, in order
    data, kind = c.get(job, epoch, pos, obj) # bytes of the file; may be called from many threads
    c.end(job)

As a program:

    cc_client.py replay --addr-file F --trace T.csv --catalog C [--verify] [--limit N]
        Send the accesses of a recorded trace one at a time, in trace order, each as the job that
        made it. Object identifier = position of the object's first appearance in the trace, so
        the catalog must list the files in that order (make_catalog does that).
    cc_client.py load --addr-file F --catalog C --job J --seed S --objects first:count --epochs E
                      --threads T [--verify] [--start-unix T0] [--out FILE]
        One job: every epoch a seeded permutation of its objects, T requests in flight.
        Prints one JSON line with throughput, latency percentiles, kinds, and mismatches.
    cc_client.py ctl --addr-file F shutdown | dump TAG | reset | stats

--verify reads every file directly once and compares a checksum of all bytes with what the
cache returned.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

KIND = {1: "hit", 2: "miss_admit", 3: "miss_bypass", 4: "hit_waited"}
CTL_REGISTER, CTL_ANNOUNCE, CTL_END, CTL_STATS, CTL_SHUTDOWN = 1, 2, 3, 4, 9


class Res(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int32), ("buf", ctypes.c_int32), ("ns_client", ctypes.c_uint64),
                ("ns_srv_total", ctypes.c_uint64), ("ns_srv_wait", ctypes.c_uint64), ("ns_srv_io", ctypes.c_uint64),
                ("ns_srv_bulk", ctypes.c_uint64)]


def ib_address(dev="ib0"):
    """IPv4 address of this node's InfiniBand interface (not stored anywhere)."""
    out = subprocess.run(["ip", "-4", "-o", "addr", "show", dev], capture_output=True, text=True).stdout.split()
    return out[out.index("inet") + 1].split("/")[0]


def ib_proto(dev="ib0"):
    """Mercury address of this node's InfiniBand interface, with the RDMA device of that interface named in it
    ('ofi+verbs;ofi_rxm://mlx5_0/<address>'). With the address alone Mercury cannot initialise on some nodes that
    have other RDMA devices too (RoCE adapters; seen on c51 and c52 on 2026-11-24, not on c58)."""
    try:
        rdma = sorted(os.listdir(f"/sys/class/net/{dev}/device/infiniband"))[0] + "/"
    except (OSError, IndexError):
        rdma = ""
    return f"ofi+verbs;ofi_rxm://{rdma}{ib_address(dev)}"


class CacheClient:
    def __init__(self, server_addr, proto=None, lib=None, nbuf=16, buf_bytes=3407872):
        lib = lib or os.path.join(os.environ.get("CXL_TRAINING_DATA_ROOT", ""), "tmp/build/cxlcache/libcc_client.so")
        self.lib = L = ctypes.CDLL(lib)
        L.ccc_init.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint64, ctypes.c_int]
        L.ccc_get.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int64, ctypes.c_int64,
                              ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(Res)]
        L.ccc_get.restype = ctypes.c_int64
        L.ccc_ctl.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64,
                              ctypes.POINTER(ctypes.c_int64), ctypes.c_int32]
        L.ccc_ctl.restype = ctypes.c_int64
        L.ccc_release.argtypes = [ctypes.c_int]
        L.ccc_release.restype = None
        L.ccc_sum.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        L.ccc_sum.restype = ctypes.c_uint64
        proto = proto or ib_proto()
        rc = L.ccc_init(proto.encode(), server_addr.encode(), nbuf, buf_bytes, 0)
        if rc != 0:
            raise RuntimeError(f"cc_client: cannot connect ({rc})")

    # -- control
    def ctl(self, op, job=0, a=0, b=0, c=0, ids=()):
        arr = (ctypes.c_int64 * max(1, len(ids)))(*ids)
        ret = self.lib.ccc_ctl(op, job, a, b, c, arr, len(ids))
        if ret < -1000:
            raise RuntimeError(f"cc_client: control message {op} failed in transport ({ret})")
        return ret

    def register(self, job, seed, epoch_len, total):
        ret = self.ctl(CTL_REGISTER, job, seed, epoch_len, total)
        if ret != 0:
            raise RuntimeError(f"cc_client: job {job} was not registered ({ret})")

    def announce(self, job, epoch, order):
        order = [int(o) for o in order]
        for off in range(0, len(order), 256):
            ret = self.ctl(CTL_ANNOUNCE, job, epoch, off, len(order), order[off:off + 256])
            if ret < 0:
                raise RuntimeError(f"cc_client: announcement of epoch {epoch} of job {job} refused ({ret})")

    def end(self, job):
        return self.ctl(CTL_END, job)

    def stats(self):
        names = ("accesses", "hits", "resident", "admissions", "evictions", "in_store", "order_violations")
        return {n: self.ctl(CTL_STATS, 0, i) for i, n in enumerate(names)}

    def dump(self, tag):
        return self.ctl(CTL_STATS, 0, 100, int(tag))

    def reset(self):
        return self.ctl(CTL_STATS, 0, 101)

    def shutdown(self):
        return self.ctl(CTL_SHUTDOWN)

    # -- data
    def get_raw(self, job, epoch, pos, obj):
        """Returns (pointer, size, Res). The caller must call release(res.buf)."""
        p, res = ctypes.c_void_p(), Res()
        n = self.lib.ccc_get(job, epoch, pos, obj, ctypes.byref(p), ctypes.byref(res))
        if n < 0:
            raise RuntimeError(f"cc_client: GET job {job} epoch {epoch} pos {pos} object {obj} failed ({n})")
        return p, n, res

    def release(self, buf):
        self.lib.ccc_release(buf)

    def get(self, job, epoch, pos, obj):
        """The bytes of the object, and how it was served (KIND)."""
        p, n, res = self.get_raw(job, epoch, pos, obj)
        try:
            return ctypes.string_at(p, n), res.kind
        finally:
            self.release(res.buf)

    def get_sum(self, job, epoch, pos, obj):
        """Size, checksum of the bytes, and the result record, without building a bytes object."""
        p, n, res = self.get_raw(job, epoch, pos, obj)
        try:
            return n, self.lib.ccc_sum(p, n), res
        finally:
            self.release(res.buf)

    def sum_bytes(self, data):
        return self.lib.ccc_sum(data, len(data))

    def close(self):
        self.lib.ccc_fini()


# ----------------------------------------------------------------------------- test programs

def load_catalog(path):
    return [(p.split()[0], int(p.split()[1])) for p in open(path) if p.strip()]


def file_sums(client, catalog, objs, threads=16):
    """Checksum of every listed file, read directly from the file system."""
    out, lock, it = {}, threading.Lock(), iter(objs)

    def work():
        while True:
            with lock:
                o = next(it, None)
            if o is None:
                return
            data = open(catalog[o][0], "rb").read()
            s = client.sum_bytes(data)
            with lock:
                out[o] = (len(data), s)
    ts = [threading.Thread(target=work) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def pct(v, p):
    v = sorted(v)
    return v[int(p * (len(v) - 1))] if v else 0


def cmd_replay(a, c):
    rows = []
    for line in open(a.trace):
        if line.startswith("#") or line.startswith("t,"):
            continue
        t, job, epoch, obj, size = line.strip().split(",")[:5]
        rows.append((int(job), int(epoch), int(obj)))
    if a.limit:
        rows = rows[:a.limit]
    ids = {}
    rows = [(j, e, ids.setdefault(o, len(ids))) for j, e, o in rows]
    catalog = load_catalog(a.catalog)
    assert len(catalog) >= len(ids), "the catalog has fewer objects than the trace"
    seq = {}
    for j, e, o in rows:
        runs = seq.setdefault(j, [])
        if not runs or runs[-1][0] != e:
            runs.append((e, []))
        runs[-1][1].append(o)
    expect = file_sums(c, catalog, sorted(ids.values())) if a.verify else {}
    for j, runs in seq.items():
        # epoch length as the simulator derives it from a trace: all accesses that carry the job's first epoch
        # label, also where a recorded trace interleaves the end of one epoch with the start of the next
        epoch_len = sum(len(o) for e, o in runs if e == runs[0][0])
        c.register(a.job_base + j, 0, epoch_len, sum(len(o) for _, o in runs))
    cursor = {j: [0, 0] for j in seq}
    kinds, bad, t0 = {}, 0, time.time()
    for j, e, o in rows:
        k, p = cursor[j]
        epoch, objs = seq[j][k]
        if p == 0:
            c.announce(a.job_base + j, epoch, objs)
        n, s, res = c.get_sum(a.job_base + j, epoch, p, o)
        kinds[res.kind] = kinds.get(res.kind, 0) + 1
        if a.verify and expect[o] != (n, s):
            bad += 1
        cursor[j] = [k + 1, 0] if p + 1 == len(objs) else [k, p + 1]
    for j in seq:
        c.end(a.job_base + j)
    print(json.dumps(dict(mode="replay", trace=a.trace, accesses=len(rows), objects=len(ids), jobs=len(seq),
                          verified=bool(a.verify), mismatches=bad, wall_s=round(time.time() - t0, 2),
                          kinds={KIND[k]: v for k, v in sorted(kinds.items())})))
    return 1 if bad else 0


def cmd_load(a, c):
    import numpy as np
    catalog = load_catalog(a.catalog)
    if a.objects_file:                     # object identifiers of the catalog, one per line
        objs = [int(x) for x in open(a.objects_file).read().split()]
        count = len(objs)
    else:
        first, count = (int(x) for x in a.objects.split(":"))
        objs = list(range(first, first + count))
    expect = file_sums(c, catalog, objs) if a.verify else {}
    c.register(a.job, a.seed, count, count * a.epochs)
    if a.start_unix:
        time.sleep(max(0.0, a.start_unix - time.time()))
    lat, kinds, bad, nbytes, lock = [], {}, [0], [0], threading.Lock()
    srv = dict(total=0, wait=0, io=0, bulk=0)
    t_begin = time.time()
    c0 = time.process_time()
    orders = [[objs[i] for i in np.random.default_rng(a.seed * 1000003 + e).permutation(count)] for e in range(a.epochs)]
    told = 0
    for e in range(a.epochs):
        order = orders[e]
        while told < min(a.epochs, e + a.lookahead):      # --lookahead 2: the next epoch is announced one epoch early
            c.announce(a.job, told, orders[told])
            told += 1
        nxt = [0]
        t_epoch = time.time()

        def work():
            while True:
                with lock:
                    p = nxt[0]
                    nxt[0] += 1
                if p >= count:
                    return
                if a.pace:                 # a consumer of --pace files per second: position p is not asked for earlier
                    d = t_epoch + p / a.pace - time.time()
                    if d > 0:
                        time.sleep(d)
                o = order[p]
                if a.verify:
                    n, s, res = c.get_sum(a.job, e, p, o)
                else:                      # throughput runs: do not touch the bytes
                    _, n, res = c.get_raw(a.job, e, p, o)
                    c.release(res.buf)
                    s = 0
                with lock:
                    lat.append((res.ns_client, res.kind))
                    kinds[res.kind] = kinds.get(res.kind, 0) + 1
                    nbytes[0] += n
                    srv["total"] += res.ns_srv_total
                    srv["wait"] += res.ns_srv_wait
                    srv["io"] += res.ns_srv_io
                    srv["bulk"] += res.ns_srv_bulk
                    if a.verify and expect[o] != (n, s):
                        bad[0] += 1
        ts = [threading.Thread(target=work) for _ in range(a.threads)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    wall, cpu = time.time() - t_begin, time.process_time() - c0
    c.end(a.job)
    n = len(lat)
    hits = [x / 1e6 for x, k in lat if k in (1, 4)]
    miss = [x / 1e6 for x, k in lat if k in (2, 3)]
    rec = dict(mode="load", job=a.job, seed=a.seed, host=os.uname().nodename, objects=count, epochs=a.epochs,
               threads=a.threads, requests=n, bytes=nbytes[0], wall_s=round(wall, 3), t_begin=t_begin,
               objects_per_s=round(n / wall, 1), gb_per_s=round(nbytes[0] / 1e9 / wall, 4), client_cpu_s=round(cpu, 2),
               verified=bool(a.verify), mismatches=bad[0], kinds={KIND[k]: v for k, v in sorted(kinds.items())},
               lookahead=a.lookahead, pace=a.pace, request_s_total=round(sum(x for x, _ in lat) / 1e9, 3),
               request_ms=dict(p50=round(pct([x / 1e6 for x, _ in lat], .5), 3), p90=round(pct([x / 1e6 for x, _ in lat], .9), 3),
                               p99=round(pct([x / 1e6 for x, _ in lat], .99), 3)),
               hit_ms=dict(n=len(hits), p50=round(pct(hits, .5), 3), p99=round(pct(hits, .99), 3), max=round(max(hits, default=0), 3)),
               miss_ms=dict(n=len(miss), p50=round(pct(miss, .5), 3), p99=round(pct(miss, .99), 3), max=round(max(miss, default=0), 3)),
               server_ms_mean={k: round(v / 1e6 / max(1, n), 3) for k, v in srv.items()},
               t_end=round(t_begin + wall, 3))
    line = json.dumps(rec)
    print(line)
    if a.out:
        open(a.out, "a").write(line + "\n")
    return 1 if bad[0] else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("replay", "load", "ctl"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--addr-file", required=True)
    ap.add_argument("--proto")
    ap.add_argument("--lib")
    ap.add_argument("--catalog")
    ap.add_argument("--trace")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--job-base", type=int, default=0)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--job", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--objects", default="0:0")
    ap.add_argument("--objects-file", help="load: file with the job's object identifiers, instead of --objects first:count")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--start-unix", type=float, default=0.0)
    ap.add_argument("--lookahead", type=int, choices=(1, 2), default=1, help="load: epochs of the order announced ahead")
    ap.add_argument("--pace", type=float, default=0.0, help="load: requests per second of the job (0: as fast as possible)")
    ap.add_argument("--out")
    a = ap.parse_intermixed_args()
    c = CacheClient(open(a.addr_file).read().strip(), proto=a.proto, lib=a.lib, nbuf=max(16, a.threads))
    rc = 0
    if a.mode == "replay":
        rc = cmd_replay(a, c)
    elif a.mode == "load":
        rc = cmd_load(a, c)
    else:
        what = a.args[0]
        if what == "shutdown":
            c.shutdown()
        elif what == "dump":
            c.dump(a.args[1])
        elif what == "reset":
            c.reset()
        elif what == "stats":
            print(json.dumps(c.stats()))
    c.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
