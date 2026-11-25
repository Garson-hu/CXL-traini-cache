#!/usr/bin/env python3
"""Cache server of the minimal CXL training cache: one process on the machine with the memory.

It loads the data plane (libcc_server.so, from cc_server.c), which owns the store and talks
Mercury, and runs the manager (cc_manager.py), which owns the metadata and takes every decision
with a policy of the simulator. The two meet in one loop: the data plane hands over events
(a GET arrived, a transfer finished, an admission copy finished), the manager answers.

  cc_server.py --catalog FILE --policy static|lru|reuse-epoch|known:epoch --capacity-slots N
               --backend dram | --backend dax --dax-path DEV --dax-offset BYTES --dax-agreed DEV:START:END
               --proto 'ofi+verbs;ofi_rxm://<this machine's InfiniBand address>' --addr-file FILE
               --out DIR [--lib PATH] [--slot-bytes N] [--spare N] [--workers N] [--bounce N]
               [--pin CPUS] [--check]

The store has capacity + spare slots; the policy may fill `capacity` of them. With --backend dax
the server maps exactly [dax-offset, dax-offset + store bytes) of the device and writes only
there. It refuses to start unless that range lies inside --dax-agreed (the range the user has
agreed to for this experiment) and no other process of this user maps the device.

It stops on the SHUTDOWN control message or on SIGTERM/SIGINT and then writes, into --out,
accesses.csv (every access with the decision taken) and summary.json. The control message
STATS with a = 100 writes the same files with a tag and a = 101 clears the statistics while
keeping the cache content; see cc_client.py.
"""
import argparse
import ctypes
import glob
import json
import os
import resource
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cc_manager import CacheManager, load_catalog  # noqa: E402

EV_GET, EV_CTL, EV_HIT_DONE, EV_MISS_SENT, EV_ADMITTED, EV_PREFETCHED = 1, 2, 3, 4, 5, 6
CTL_NULL, CTL_REGISTER, CTL_ANNOUNCE, CTL_END, CTL_STATS, CTL_SHUTDOWN = 0, 1, 2, 3, 4, 9
COUNTERS = ("gets", "hits_served", "misses_served", "bytes_from_store", "bytes_from_dram_buffers",
            "bytes_read_from_files", "bytes_copied_into_store", "control_messages", "errors",
            "prefetches_done", "bytes_read_from_files_by_prefetch")


class Event(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int32), ("job", ctypes.c_int32), ("epoch", ctypes.c_int32), ("op", ctypes.c_int32),
                ("n", ctypes.c_int32), ("status", ctypes.c_int32), ("req", ctypes.c_uint64),
                ("pos", ctypes.c_int64), ("obj", ctypes.c_int64), ("a", ctypes.c_int64), ("b", ctypes.c_int64),
                ("c", ctypes.c_int64), ("slot", ctypes.c_int64), ("t_ns", ctypes.c_uint64),
                ("ns_io", ctypes.c_uint64), ("ns_bulk", ctypes.c_uint64), ("ns_copy", ctypes.c_uint64)]


class DataPlane:
    """What the manager calls to have bytes moved."""

    def __init__(self, lib):
        self.lib = lib

    def hit(self, req, slot, size, kind):
        self.lib.ccs_hit(req, slot, size, kind)

    def miss(self, req, path, size, slot):
        self.lib.ccs_miss(req, path.encode(), size, slot)

    def fail(self, req, code):
        self.lib.ccs_fail(req, code)

    def prefetch(self, obj, path, size, slot):
        self.lib.ccs_prefetch(obj, path.encode(), size, slot)


def dax_users(path):
    """PIDs of this user's other processes that map the device (their maps are readable)."""
    me, out = os.getpid(), []
    for maps in glob.glob("/proc/[0-9]*/maps"):
        pid = int(maps.split("/")[2])
        if pid == me:
            continue
        try:
            if os.path.basename(path) in open(maps).read():
                out.append(pid)
        except OSError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--capacity-slots", type=int, required=True)
    ap.add_argument("--spare", type=int, default=256)
    ap.add_argument("--slot-bytes", type=int, default=3407872)
    ap.add_argument("--backend", choices=("dram", "dax"), required=True)
    ap.add_argument("--dax-path")
    ap.add_argument("--dax-offset", type=int, default=0)
    ap.add_argument("--dax-agreed", help="DEV:START:END, the byte range of the device this experiment may use")
    ap.add_argument("--dax-other-servers", default="", help="PID:START:END,... of cache servers of the same experiment that map "
                    "other parts of the device; any other process that maps the device stops the start")
    ap.add_argument("--proto", required=True)
    ap.add_argument("--addr-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lib", default=os.path.join(os.environ.get("CXL_TRAINING_DATA_ROOT", ""), "tmp/build/cxlcache/libcc_server.so"))
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--bounce", type=int, default=128)
    ap.add_argument("--pin", default="")
    ap.add_argument("--check", action="store_true", help="verify the metadata invariants after every batch of events")
    ap.add_argument("--no-gc", action="store_true", help="switch off Python's cyclic garbage collector: the manager and the policies "
                    "build no reference cycles, and with millions of announced positions its passes stall the manager for seconds")
    ap.add_argument("--timeline", type=float, default=0.0, help="write a line of counters to timeline.csv every N seconds (0: off)")
    ap.add_argument("--slots-high-first", action="store_true", help="test: fill the store from its last slot downwards "
                    "(the choice of slot takes no part in any decision)")
    ap.add_argument("--prefetch-par", type=int, default=0, help="prefetch reads in flight (0: no prefetching); known-order policies only")
    ap.add_argument("--prefetch-lead", type=float, default=5.0, help="prefetch window: seconds of a job's announced accesses")
    ap.add_argument("--prefetch-unused", type=int, default=0, help="prefetched files waiting for their first use (0: a quarter of the capacity)")
    a = ap.parse_args()

    if a.no_gc:
        import gc
        gc.disable()
    catalog = load_catalog(a.catalog)
    nslots = a.capacity_slots + a.spare
    huge = 2 << 20
    store_bytes = (nslots * a.slot_bytes + huge - 1) // huge * huge
    if max(s for _, s in catalog) > a.slot_bytes:
        sys.exit("cc_server: the catalog has a file larger than a slot")
    if a.backend == "dax":
        if not a.dax_path or not a.dax_agreed:
            sys.exit("cc_server: --backend dax needs --dax-path and --dax-agreed")
        dev, start, end = a.dax_agreed.rsplit(":", 2)
        if dev != a.dax_path or a.dax_offset < int(start) or a.dax_offset + store_bytes > int(end):
            sys.exit(f"cc_server: [{a.dax_offset}, {a.dax_offset + store_bytes}) of {a.dax_path} is not inside the agreed range {a.dax_agreed}")
        known = {}
        for item in filter(None, a.dax_other_servers.split(",")):
            pid, s0, s1 = (int(x) for x in item.split(":"))
            known[pid] = (s0, s1)
            if a.dax_offset < s1 and s0 < a.dax_offset + store_bytes:
                sys.exit(f"cc_server: the requested range overlaps the store of server {pid} [{s0}, {s1})")
        users = [p for p in dax_users(a.dax_path) if p not in known]
        if users:
            sys.exit(f"cc_server: {a.dax_path} is mapped by other processes of this user ({users}); not started")
    os.makedirs(a.out, exist_ok=True)
    if a.pin:
        cpus = set()
        for tok in a.pin.split(","):
            lo, _, hi = tok.partition("-")
            cpus.update(range(int(lo), int(hi or lo) + 1))
        os.sched_setaffinity(0, cpus)

    lib = ctypes.CDLL(a.lib)
    lib.ccs_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
                              ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_int]
    lib.ccs_poll.argtypes = [ctypes.POINTER(Event), ctypes.c_int, ctypes.c_int]
    lib.ccs_ctl_ids.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_int64), ctypes.c_int]
    lib.ccs_reply_ctl.argtypes = [ctypes.c_uint64, ctypes.c_int64]
    lib.ccs_hit.argtypes = [ctypes.c_uint64, ctypes.c_int64, ctypes.c_int64, ctypes.c_int]
    lib.ccs_miss.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.c_int64, ctypes.c_int64]
    lib.ccs_fail.argtypes = [ctypes.c_uint64, ctypes.c_int64]
    lib.ccs_prefetch.argtypes = [ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64, ctypes.c_int64]
    lib.ccs_set_prefetch.argtypes = [ctypes.c_int]
    lib.ccs_counters.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    lib.ccs_slot_sum.argtypes = [ctypes.c_int64, ctypes.c_int64]
    lib.ccs_slot_sum.restype = ctypes.c_uint64
    for f in (lib.ccs_reply_ctl, lib.ccs_hit, lib.ccs_miss, lib.ccs_fail, lib.ccs_counters, lib.ccs_stop, lib.ccs_prefetch,
              lib.ccs_set_prefetch):
        f.restype = None

    addr = ctypes.create_string_buffer(256)
    rc = lib.ccs_start(a.backend.encode(), (a.dax_path or "").encode(), a.dax_offset, store_bytes, a.slot_bytes,
                       a.proto.encode(), a.workers, a.bounce, a.pin.encode(), 0, addr, 256)
    if rc != 0:
        sys.exit(f"cc_server: the data plane did not start ({rc})")

    now = [time.monotonic()]
    pf = None
    if a.prefetch_par > 0:
        if not a.policy.startswith("known"):
            sys.exit("cc_server: prefetching needs a known-order policy")
        if a.prefetch_par > max(1, a.workers // 2) or a.prefetch_par > max(1, a.bounce // 2):
            sys.exit("cc_server: --prefetch-par must leave at least half of the workers and of the DRAM buffers to requests")
        pf = dict(par=a.prefetch_par, lead=a.prefetch_lead, unused=a.prefetch_unused or max(a.prefetch_par, a.capacity_slots // 4))
        lib.ccs_set_prefetch(a.prefetch_par)
    mgr = CacheManager(a.policy, a.capacity_slots, nslots, catalog, DataPlane(lib), clock=lambda: now[0], prefetch=pf)
    if a.slots_high_first:
        mgr.free.reverse()
    timing = dict(io_n=0, io_ns=0, io_max=0, hit_n=0, hit_bulk_ns=0, miss_bulk_ns=0, copy_n=0, copy_ns=0, pf_n=0, pf_io_ns=0, pf_io_max=0)
    # time a file read took: bucket k counts reads of [2^(k-1), 2^k) ms, bucket 0 those under 1 ms
    hist = dict(miss=[0] * 24, prefetch=[0] * 24)
    bucket = lambda ns: min(23, int(ns // 1000000).bit_length())
    t_start, cpu0 = time.time(), resource.getrusage(resource.RUSAGE_SELF)
    mgr_cpu = [0.0]
    loop_max = [0.0, 0.0]                 # longest single pass over a batch of events: since the last timeline line, overall

    def counters():
        arr = (ctypes.c_uint64 * len(COUNTERS))()
        lib.ccs_counters(arr)
        return dict(zip(COUNTERS, arr))

    base = dict(counters=dict.fromkeys(COUNTERS, 0), cpu=cpu0, t=t_start)

    def write(tag=""):
        ru, c = resource.getrusage(resource.RUSAGE_SELF), counters()
        s = mgr.summary()
        s.update(backend=a.backend, slot_bytes=a.slot_bytes, store_bytes=store_bytes, workers=a.workers,
                 dax_range=[a.dax_offset, a.dax_offset + store_bytes] if a.backend == "dax" else None,
                 wall_s=time.time() - base["t"], user_s=ru.ru_utime - base["cpu"].ru_utime,
                 sys_s=ru.ru_stime - base["cpu"].ru_stime, manager_cpu_s=mgr_cpu[0], timing=dict(timing),
                 data_plane={k: c[k] - base["counters"][k] for k in COUNTERS}, host=os.uname().nodename,
                 read_ms_histogram=dict(note="bucket k: file reads that took [2^(k-1), 2^k) ms; bucket 0: under 1 ms",
                                        miss=list(hist["miss"]), prefetch=list(hist["prefetch"])),
                 manager_longest_pass_s=round(loop_max[1], 4), written=time.strftime("%Y-%m-%dT%H:%M:%S"))
        json.dump(s, open(os.path.join(a.out, f"summary{tag}.json"), "w"), indent=1)
        mgr.write_log(os.path.join(a.out, f"accesses{tag}.csv"))
        return s

    def reset():
        mgr.stat.clear()
        mgr.log.clear()                   # the time base stays: the policy's state carries over
        for k in timing:
            timing[k] = 0
        for h in hist.values():
            h[:] = [0] * 24
        loop_max[1] = 0.0
        base.update(counters=counters(), cpu=resource.getrusage(resource.RUSAGE_SELF), t=time.time())
        mgr_cpu[0] = 0.0

    stop = [False]
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    open(a.addr_file, "w").write(addr.value.decode() + "\n")
    print(f"address: {addr.value.decode()}\nconfig: policy={a.policy} capacity_slots={a.capacity_slots} store_slots={nslots} "
          f"slot_bytes={a.slot_bytes} backend={a.backend} objects={len(catalog)} workers={a.workers} pid={os.getpid()}\nready", flush=True)

    TL_STATS = ("accesses", "hits", "hit_bytes", "bytes", "admissions", "bypasses", "evictions", "hit_waits", "prefetch_issued",
                "prefetch_done", "prefetch_in_time", "prefetch_late", "prefetch_evicted_unused", "prefetch_declined", "prefetch_passed",
                "order_gaps", "admissions_without_slot")
    TL_TIMING = ("io_n", "io_ns", "miss_bulk_ns", "hit_n", "hit_bulk_ns", "copy_n", "copy_ns", "pf_n", "pf_io_ns")
    tl, last_tl = None, time.monotonic()
    if a.timeline > 0:                    # cumulative values; differences between lines give rates
        tl = open(os.path.join(a.out, "timeline.csv"), "w")
        tl.write("t_unix," + ",".join(TL_STATS) + "," + ",".join(TL_TIMING) + "," + ",".join(COUNTERS) +
                 ",resident,in_store,free_slots,prefetch_unused,prefetch_in_flight,held_requests,user_s,sys_s,manager_cpu_s,longest_pass_s\n")

    def timeline_line():
        ru, c = resource.getrusage(resource.RUSAGE_SELF), counters()
        held = sum(len(st.held) for st in mgr.jobs.values())
        tl.write(f"{time.time():.3f}," + ",".join(str(mgr.stat.get(k, 0)) for k in TL_STATS) + "," + ",".join(str(timing[k]) for k in TL_TIMING) +
                 "," + ",".join(str(c[k]) for k in COUNTERS) +
                 f",{len(mgr.policy.resident)},{len(mgr.slot_of)},{len(mgr.free)},{len(mgr.pf)},{mgr.pf_inflight},{held},"
                 f"{ru.ru_utime:.2f},{ru.ru_stime:.2f},{mgr_cpu[0]:.3f},{loop_max[0]:.4f}\n")
        tl.flush()
        loop_max[0] = 0.0

    evs = (Event * 256)()
    ids = (ctypes.c_int64 * 256)()
    last_tick = time.monotonic()
    tags = 0
    while not stop[0]:
        n = lib.ccs_poll(evs, 256, 20)
        c0, w0 = time.thread_time(), time.monotonic()
        for k in range(n):
            ev = evs[k]
            now[0] = ev.t_ns / 1e9
            if ev.type == EV_GET:
                mgr.get(ev.req, ev.job, ev.epoch, ev.pos, ev.obj)
            elif ev.type == EV_HIT_DONE:
                timing["hit_n"] += 1
                timing["hit_bulk_ns"] += ev.ns_bulk
                mgr.hit_done(ev.slot)
            elif ev.type == EV_MISS_SENT:
                timing["io_n"] += 1
                timing["io_ns"] += ev.ns_io
                timing["io_max"] = max(timing["io_max"], ev.ns_io)
                timing["miss_bulk_ns"] += ev.ns_bulk
                hist["miss"][bucket(ev.ns_io)] += 1
            elif ev.type == EV_ADMITTED:
                timing["copy_n"] += 1
                timing["copy_ns"] += ev.ns_copy
                mgr.admitted(ev.obj, ev.slot, ev.status == 0)
            elif ev.type == EV_PREFETCHED:
                timing["pf_n"] += 1
                timing["pf_io_ns"] += ev.ns_io
                timing["pf_io_max"] = max(timing["pf_io_max"], ev.ns_io)
                hist["prefetch"][bucket(ev.ns_io)] += 1
                timing["copy_n"] += 1
                timing["copy_ns"] += ev.ns_copy
                mgr.prefetched(ev.obj, ev.slot, ev.status == 0, ev.ns_io / 1e9)
            elif ev.type == EV_CTL:
                ret = 0
                if ev.op == CTL_REGISTER:
                    ret = mgr.register(ev.job, ev.a, ev.b, ev.c)
                elif ev.op == CTL_ANNOUNCE:
                    m = lib.ccs_ctl_ids(ev.req, ids, 256)
                    ret = mgr.announce(ev.job, ev.a, ev.b, ev.c, list(ids[:m]))
                elif ev.op == CTL_END:
                    ret = mgr.end(ev.job)
                elif ev.op == CTL_STATS:
                    if ev.a == 100:
                        tags += 1
                        write(f"-{ev.b}")
                    elif ev.a == 101:
                        reset()
                    else:
                        s = mgr.stat
                        ret = [s["accesses"], s["hits"], len(mgr.policy.resident), s["admissions"], s["evictions"],
                               len(mgr.slot_of), s["order_mismatches"] + s["order_gaps"]][ev.a] if 0 <= ev.a < 7 else -22
                elif ev.op == CTL_SHUTDOWN:
                    stop[0] = True
                lib.ccs_reply_ctl(ev.req, ret)
        if n and a.check:
            mgr.check()
        t = time.monotonic()
        if t - last_tick > 0.1:
            last_tick = t
            if n < 256:                   # no backlog: everything that has arrived has been seen
                now[0] = t
            # With a backlog (after a long pass of the manager) the hold timeout is judged on the arrival time of
            # the last event processed, so that the manager's own delay is not taken for a missing predecessor.
            mgr.tick()
        mgr_cpu[0] += time.thread_time() - c0
        if n:
            d = time.monotonic() - w0
            loop_max[0], loop_max[1] = max(loop_max[0], d), max(loop_max[1], d)
        if tl and t - last_tl >= a.timeline:
            last_tl = t
            timeline_line()
    if tl:
        timeline_line()
        tl.close()
    time.sleep(0.3)                       # let the answer to SHUTDOWN leave
    s = write()
    lib.ccs_stop()
    print(f"stopped: accesses={s.get('accesses', 0)} hits={s.get('hits', 0)} byte_hit_rate={s['byte_hit_rate']:.4f} "
          f"admissions={s.get('admissions', 0)} evictions={s.get('evictions', 0)} user_s={s['user_s']:.1f} sys_s={s['sys_s']:.1f}", flush=True)


if __name__ == "__main__":
    main()
