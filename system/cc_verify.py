#!/usr/bin/env python3
"""Check the cache manager against the trace simulator.

  cc_verify.py offline <trace.csv> [--capacities 0.05,0.2] [--policies ...] [--delay N]
      Feed a recorded trace to the manager, access by access, the way running jobs would: every
      job registers, announces the order of each epoch just before its first access of that
      epoch, and sends one request per access. No server, no network, no file is read. The
      manager's decision for every access (hit or miss, admitted or not, number of evictions) and
      its resident set are compared with the simulator's on the same trace with every object
      counted as one unit (the manager's capacity is a number of slots).
      --delay N: transfers and admission copies finish only N requests later, in random order,
      as they do in the running server. The policy decisions must not change; this exercises
      the slot and reference-count handling.

  cc_verify.py log <accesses.csv written by the server>
      Run the simulator on the trace the server recorded (the accesses in the order and at the
      times the manager processed them) and compare it with the decisions in the same file.

Exit status 0 if every decision agrees. SIMULATION is the reference here, not a result.
"""
import argparse
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "simulator"))
sys.path.insert(0, HERE)
import cachesim  # noqa: E402
import crossjob  # noqa: E402
from cachesim import Access  # noqa: E402
from cc_manager import POLICIES, CacheManager  # noqa: E402


def reference(accesses, policy, capacity, objects=None, refresh=None):
    """The simulator's decisions on a unit-size trace: [(hit, admitted, evictions)], resident set.
    The policy object is built exactly as cachesim.replay builds it, and driven as simulate() does.
    objects: the number of objects the server was told its catalog has, if that differs from the
    number of objects in the trace (the known-order policy derives its refresh interval from it).
    refresh: tests only, the known-order policy's refresh interval in accesses."""
    info = cachesim.trace_info(accesses)
    if objects:
        info["objects"] = objects
    if policy in cachesim.POLICIES:
        pol = cachesim.POLICIES[policy](capacity, cachesim.online_view(info))
    else:
        pol = crossjob.build(policy, capacity, info)
    if refresh and hasattr(pol, "refresh"):
        pol.refresh = refresh
    out = []
    for i, a in enumerate(accesses):
        hit = pol.contains(a)
        admitted = False
        if hit:
            pol.on_hit(i, a)
        else:
            admitted = bool(pol.on_miss(i, a))
        out.append((int(hit), int(admitted), len(pol.evicted)))
        pol.evicted.clear()
    return out, set(pol.resident), info


class Stub:
    """Stands in for the data plane. Completions are delivered `delay` requests later."""

    def __init__(self, delay, seed=0):
        self.delay, self.rng, self.queue, self.mgr = delay, random.Random(seed), [], None
        self.req_obj = {}

    def hit(self, req, slot, size, kind):
        self.queue.append(("hit", slot, None))

    def miss(self, req, path, size, slot):
        if slot >= 0:
            self.queue.append(("adm", slot, self.req_obj[req]))

    def fail(self, req, code):
        raise AssertionError(f"request {req} failed with {code}")

    def prefetch(self, obj, path, size, slot):
        self.queue.append(("pf", slot, obj))

    def deliver(self, everything=False):
        while self.queue and (everything or len(self.queue) > self.delay):
            k = self.rng.randrange(len(self.queue)) if self.delay else 0
            what, slot, obj = self.queue.pop(k)
            if what == "hit":
                self.mgr.hit_done(slot)
            elif what == "pf":
                self.mgr.prefetched(obj, slot, True)
            else:
                self.mgr.admitted(obj, slot, True)


def runs_of(accesses):
    """Per job: its accesses split into epochs (maximal runs of one epoch label)."""
    seq = {}
    for a in accesses:
        runs = seq.setdefault(a.job, [])
        if not runs or runs[-1][0] != a.epoch:
            runs.append((a.epoch, []))
        runs[-1][1].append(a.obj)
    return seq


def through_manager(accesses, policy, capacity, delay=0, check_every=1, prefetch=None, refresh=None):
    """Replay through the manager. Returns its decisions and resident set. With 'known:epoch2' a job
    announces the next epoch together with the current one, as a job with two-epoch lookahead does.
    refresh: tests only, the known-order policy's refresh interval in accesses."""
    info = cachesim.trace_info(accesses)
    nobj = max(a.obj for a in accesses) + 1
    catalog = [(f"object-{o}", 1) for o in range(nobj)]
    now = [0.0]
    stub = Stub(delay)
    spare = 64 + 2 * delay
    mgr = CacheManager(policy, capacity, capacity + spare + (prefetch or {}).get("par", 0), catalog, stub, objects=info["objects"],
                       clock=lambda: now[0], prefetch=prefetch)
    stub.mgr = mgr
    if refresh and hasattr(mgr.policy, "refresh"):
        mgr.policy.refresh = refresh
    seq = runs_of(accesses)
    for job, runs in seq.items():
        assert mgr.register(job, 0, info["epoch_len"][job], sum(len(o) for _, o in runs)) == 0
    cursor = {job: [0, 0] for job in seq}     # run index, position in the run
    told = {job: 0 for job in seq}            # runs announced so far
    ahead = 2 if policy == "known:epoch2" else 1
    for n, a in enumerate(accesses):
        k, p = cursor[a.job]
        epoch, objs = seq[a.job][k]
        now[0] = a.t
        if p == 0:                            # the job announces this epoch's order (and the next one's), in pieces
            while told[a.job] < min(len(seq[a.job]), k + ahead):
                e2, o2 = seq[a.job][told[a.job]]
                for off in range(0, len(o2), 256):
                    mgr.announce(a.job, e2, off, len(o2), o2[off:off + 256])
                told[a.job] += 1
        stub.req_obj[n] = a.obj
        mgr.get(n, a.job, epoch, p, a.obj)
        cursor[a.job] = [k + 1, 0] if p + 1 == len(objs) else [k, p + 1]
        stub.deliver()
        if check_every and n % check_every == 0:
            mgr.check()
    stub.deliver(everything=True)
    mgr.check()
    assert not mgr.loading and not mgr.orphan and not mgr.draining and not any(mgr.pins), "transfers left over"
    assert len(mgr.log) == len(accesses), "requests were held back"
    return [(r[6], r[7], r[8]) for r in mgr.log], set(mgr.policy.resident), mgr


def compare(ref, got, ref_res, got_res):
    diff = [i for i, (x, y) in enumerate(zip(ref, got)) if x != y]
    return dict(accesses=len(ref), hits_sim=sum(r[0] for r in ref), hits_mgr=sum(g[0] for g in got),
                admissions_sim=sum(r[1] for r in ref), admissions_mgr=sum(g[1] for g in got),
                evictions_sim=sum(r[2] for r in ref), evictions_mgr=sum(g[2] for g in got),
                differing=len(diff), first_difference=diff[0] if diff else None, resident_equal=ref_res == got_res)


def dense(accesses):
    """Object identifiers 0..n-1 in order of first appearance; sizes set to one unit; times to the
    microsecond, the resolution at which the manager passes time to the policy and records it."""
    ids = {}
    return [Access(float(f"{a.t:.6f}"), a.job, a.epoch, ids.setdefault(a.obj, len(ids)), 1) for a in accesses]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("offline", "log"))
    ap.add_argument("trace")
    ap.add_argument("--capacities", default="0.05,0.2,0.4")
    ap.add_argument("--policies", default=",".join(POLICIES))
    ap.add_argument("--delay", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="use only the first N accesses")
    ap.add_argument("--prefetch", default="", help="offline: PAR:LEAD_SECONDS:UNUSED; the known-order policies are also run with "
                    "prefetching (no reference exists for that: invariants and the prefetch accounting are checked)")
    args = ap.parse_args()
    bad = 0
    if args.mode == "offline":
        accesses, _ = cachesim.load_trace(args.trace)
        if args.limit:
            accesses = accesses[:args.limit]
        unit = dense(accesses)
        nobj = len({a.obj for a in unit})
        print(f"trace {args.trace}: {len(unit)} accesses, {nobj} objects, {len({a.job for a in unit})} jobs; delay {args.delay}")
        print("policy,capacity_frac,capacity_slots,accesses,hits_sim,hits_mgr,admissions_sim,admissions_mgr,"
              "evictions_sim,evictions_mgr,differing,resident_equal")
        for frac in [float(x) for x in args.capacities.split(",")]:
            cap = max(1, int(frac * nobj))
            for pol in args.policies.split(","):
                ref, ref_res, _ = reference(unit, pol, cap)
                got, got_res, _ = through_manager(unit, pol, cap, delay=args.delay, check_every=97)
                c = compare(ref, got, ref_res, got_res)
                bad += c["differing"] + (not c["resident_equal"])
                print(f"{pol},{frac},{cap},{c['accesses']},{c['hits_sim']},{c['hits_mgr']},{c['admissions_sim']},"
                      f"{c['admissions_mgr']},{c['evictions_sim']},{c['evictions_mgr']},{c['differing']},{int(c['resident_equal'])}")
                if args.prefetch and pol.startswith("known"):
                    par, lead, unused = args.prefetch.split(":")
                    pf = dict(par=int(par), lead=float(lead), unused=int(unused) or max(int(par), cap // 4))
                    got, _, mgr = through_manager(unit, pol, cap, delay=args.delay, check_every=97, prefetch=pf)
                    st = mgr.stat
                    ends = st["prefetch_in_time"] + st["prefetch_late"] + st["prefetch_evicted_unused"] + len(mgr.pf)
                    ok = ends == st["prefetch_issued"] and st["prefetch_done"] == st["prefetch_issued"]
                    bad += not ok
                    print(f"  {pol}+prefetch({args.prefetch}): hits {sum(g[0] for g in got)} of {len(got)}, prefetches issued {st['prefetch_issued']}, "
                          f"in time {st['prefetch_in_time']}, late {st['prefetch_late']}, evicted unused {st['prefetch_evicted_unused']}, "
                          f"unused at the end {len(mgr.pf)}, declined {st['prefetch_declined']}, window cut {st['prefetch_window_cut']}; accounting {'ok' if ok else 'WRONG'}")
    else:
        rows, head = [], None
        for line in open(args.trace):
            if line.startswith("#"):
                head = line
                continue
            if line.startswith("t,"):
                continue
            p = line.strip().split(",")
            rows.append((Access(float(p[0]), int(p[1]), int(p[2]), int(p[3]), 1), (int(p[6]), int(p[7]), int(p[8]))))
        import re
        m = re.search(r"policy (\S+), capacity (\d+) slots, catalog (\d+) objects", head or "")
        pol, cap, nobj = m.group(1), int(m.group(2)), int(m.group(3))
        # The server's own object identifiers are kept: the ranked policies break ties between equal
        # next-use estimates by identifier, so renumbering would change decisions.
        unit = [r[0] for r in rows]
        ref, _, _ = reference(unit, pol, cap, objects=nobj)
        got = [r[1] for r in rows]
        c = compare(ref, got, set(), set())
        bad += c["differing"]
        print(f"log {args.trace}: policy {pol}, capacity {cap} slots, {c['accesses']} accesses; simulator on the recorded trace: "
              f"hits {c['hits_sim']} (server {c['hits_mgr']}), admissions {c['admissions_sim']} (server {c['admissions_mgr']}), "
              f"evictions {c['evictions_sim']} (server {c['evictions_mgr']}); differing decisions: {c['differing']}"
              + (f", first at access {c['first_difference']}" if c["differing"] else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
