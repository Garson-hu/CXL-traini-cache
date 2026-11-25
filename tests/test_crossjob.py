"""Tests for simulator/crossjob.py. Standard library only, except the class ArrayRekeying (numpy; skipped without it).

Run from the repository root:  python3 -m unittest discover -s tests -v
All traces here are tiny synthetic inputs made for testing. They are not evidence about workloads.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "simulator"))
import cachesim  # noqa: E402
import crossjob  # noqa: E402
from cachesim import Access, INF, online_view, trace_info  # noqa: E402

ONLINE = ("lru", "lfu", "slru", "tinylfu", "static", "reuse-gap", "reuse-epoch",
          "perjob-static", "perjob-lru", "known:epoch", "known:0.1", "known:16", "quiver", "quiver-full")
TIMING = ("policy_us_per_access",)


def jobs_trace(n_objects, epochs, rates=(1.0, 1.0), starts=None, seed=0, sizes=None, datasets=None, orders=None):
    """Each job reads its dataset once per epoch in its own random order, at its own rate.
    Returns accesses merged by time. datasets: per-job list of object ids (default: all jobs 0..n-1).
    orders: optional {(job, epoch): order} to override single epochs."""
    rng = random.Random(seed)
    starts = starts or [0.0] * len(rates)
    events = []
    for j, rate in enumerate(rates):
        objs = list(datasets[j]) if datasets else list(range(n_objects))
        pos = 0
        for e in range(epochs):
            order = list(objs)
            rng.shuffle(order)
            if orders and (j, e) in orders:
                order = list(orders[(j, e)])
            for o in order:
                events.append((starts[j] + pos / rate, j, e, o))
                pos += 1
    events.sort()
    return [Access(t, j, e, o, sizes[o] if sizes else 1) for t, j, e, o in events]


def replay(name, accesses, capacity, hits_out=None):
    return cachesim.replay(name, accesses, trace_info(accesses), capacity, check=True, hits_out=hits_out)


def stable(row):
    return {k: v for k, v in row.items() if k not in TIMING}


class LookaheadReveals(unittest.TestCase):
    def setUp(self):
        self.seq = {0: [(o, e) for e in range(2) for o in (10, 11, 12, 13)]}

    def test_count_window(self):
        look = crossjob.Lookahead(self.seq, 2.0, {0: 4})
        self.assertEqual(look.reveal(0, 0), [(1, 11), (2, 12)])
        self.assertEqual(look.reveal(0, 1), [(3, 13)])          # only what became visible
        self.assertEqual(look.reveal(0, 1), [])

    def test_epoch_window_stops_at_the_epoch_boundary(self):
        look = crossjob.Lookahead(self.seq, "epoch", {0: 4})
        self.assertEqual([q for q, _ in look.reveal(0, 0)], [1, 2, 3])
        self.assertEqual(look.reveal(0, 3), [])                  # next epoch not announced yet
        self.assertEqual([q for q, _ in look.reveal(0, 4)], [5, 6, 7])

    def test_all_and_last(self):
        look = crossjob.Lookahead(self.seq, "all", {0: 4})
        self.assertEqual(len(look.reveal(0, 0)), 7)
        self.assertTrue(look.is_last(0, 7))
        self.assertFalse(look.is_last(0, 6))


class KnownOrderMechanics(unittest.TestCase):
    def test_progress_tracking_and_cross_job_next_use(self):
        # job 0 reads one file per time unit, job 1 two per time unit; both read files 0..5 in order
        t = jobs_trace(6, 1, rates=(1.0, 2.0), orders={(0, 0): range(6), (1, 0): range(6)})
        info = trace_info(t)
        p = crossjob.build("known:all", 100, info)
        for i, a in enumerate(t[:5]):                            # replay a prefix by hand
            (p.on_hit if p.contains(a) else p.on_miss)(i, a)
        done = {j: sum(1 for a in t[:5] if a.job == j) for j in (0, 1)}
        self.assertEqual({j: p.jobs[j].pos for j in (0, 1)}, {0: done[0] - 1, 1: done[1] - 1})
        self.assertEqual({j: p.jobs[j].done for j in (0, 1)}, done)
        now = t[4].t
        # file 5: job 0 is (5 - pos0) accesses away at rate 1, job 1 is (5 - pos1) away at rate 2
        expect = min(now + (5 - p.jobs[0].pos) / 1.0, now + (5 - p.jobs[1].pos) / 2.0)
        self.assertAlmostEqual(p._key(now, 5), expect, places=6)
        self.assertAlmostEqual(p._eta(now, 0, 5), now + (5 - p.jobs[0].pos) / 1.0, places=6)

    def test_admission_and_bypass(self):
        # capacity one file. job 0 reads a then b, job 1 reads b then a, alternating.
        t = [Access(0.0, 0, 0, 0, 1), Access(0.5, 1, 0, 1, 1), Access(1.0, 0, 0, 1, 1), Access(1.5, 1, 0, 0, 1)]
        r = replay("known:all", t, 1)
        # a is bypassed (job 1 is not known yet, so no reuse is visible); b is admitted and hit by job 0
        self.assertEqual((r["hits"], r["admissions"], r["evictions"]), (1, 1, 0))

    def test_evicts_the_file_needed_last(self):
        # one job, two epochs: a b c | c a b, capacity two files, full knowledge of its own order
        order = {(0, 0): [0, 1, 2], (0, 1): [2, 0, 1]}
        t = jobs_trace(3, 2, rates=(1.0,), orders=order)
        r = replay("known:all", t, 2)
        o = replay("oracle", t, 2)
        self.assertEqual(r["hits"], o["hits"])
        self.assertEqual(r["hits"], 2)

    def test_equals_static_for_one_job(self):
        t = jobs_trace(200, 3, rates=(1.0,), seed=2)
        for cap in (20, 100):
            self.assertEqual(replay("known:epoch", t, cap)["hits"], replay("static", t, cap)["hits"])

    def test_two_jobs_between_static_and_oracle(self):
        t = jobs_trace(400, 3, rates=(1.0, 1.0), seed=3)
        cap = 80
        static, known, oracle = (replay(p, t, cap)["hits"] for p in ("static", "known:epoch", "oracle"))
        self.assertGreater(known, static)
        self.assertLessEqual(known, oracle)


class NoOracleLeak(unittest.TestCase):
    def test_online_view_has_no_future(self):
        t = jobs_trace(50, 2, seed=1)
        view = online_view(trace_info(t))
        for key in cachesim.OFFLINE_KEYS:
            self.assertNotIn(key, view)

    def test_decisions_do_not_depend_on_what_was_not_announced(self):
        # two traces that are identical in every job's first epoch and differ afterwards
        n = 120
        t1 = jobs_trace(n, 3, rates=(1.0, 1.0), seed=4)
        t2_orders = {}
        rng = random.Random(99)
        for j in (0, 1):
            first = [a.obj for a in t1 if a.job == j and a.epoch == 0]
            t2_orders[(j, 0)] = first
            for e in (1, 2):
                later = list(range(n))
                rng.shuffle(later)
                t2_orders[(j, e)] = later
        t2 = jobs_trace(n, 3, rates=(1.0, 1.0), seed=4, orders=t2_orders)
        prefix = next(i for i, a in enumerate(t1) if a.epoch == 1)   # everything before any second epoch
        self.assertEqual(t1[:prefix], t2[:prefix])
        self.assertNotEqual(t1, t2)
        for name in ONLINE:
            h1, h2 = [], []
            replay(name, t1, 30, hits_out=h1)
            replay(name, t2, 30, hits_out=h2)
            self.assertEqual(h1[:prefix], h2[:prefix], name)
        # the two traces really differ later, so the equality above is not trivial
        self.assertNotEqual(replay("oracle", t1, 30)["hits"], replay("oracle", t2, 30)["hits"])

    def test_bounded_lookahead_ignores_the_far_future(self):
        # same first 40 accesses of each job; the rest of the FIRST epoch differs
        n = 100
        base = jobs_trace(n, 1, rates=(1.0, 1.0), seed=5)
        orders = {}
        rng = random.Random(7)
        for j in (0, 1):
            mine = [a.obj for a in base if a.job == j]
            tail = mine[40:]
            rng.shuffle(tail)
            orders[(j, 0)] = mine[:40] + tail
        other = jobs_trace(n, 1, rates=(1.0, 1.0), seed=5, orders=orders)
        h1, h2 = [], []
        replay("known:8", base, 20, hits_out=h1)
        replay("known:8", other, 20, hits_out=h2)
        horizon = 2 * (40 - 8) - 2                                # both jobs are before position 40 - 8
        self.assertEqual(h1[:horizon], h2[:horizon])


try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


@unittest.skipUnless(HAVE_NUMPY, "numpy is needed for the array pass")
class ArrayRekeying(unittest.TestCase):
    """KnownOrder(dense=N) computes the re-keying pass with arrays. It must give the same keys, bit for bit,
    and so the same decisions as the per-object pass, which stays the reference."""

    def setUp(self):
        crossjob.KnownOrder.check_rekey = True          # every array pass is compared with the per-object keys

    def tearDown(self):
        crossjob.KnownOrder.check_rekey = False

    def both(self, accesses, mode, capacity, refresh, **kw):
        info, out = trace_info(accesses), []
        nobj = max(a.obj for a in accesses) + 1
        for dense in (0, nobj):
            look = crossjob.Lookahead(info["_job_seq"], mode, info["epoch_len"])
            pol = crossjob.KnownOrder(capacity, online_view(info), look, refresh=refresh, dense=dense, **kw)
            passes, plain = [0], pol._rekey_all

            def counted(now, plain=plain, passes=passes):
                passes[0] += 1
                plain(now)
            pol._rekey_all = counted
            dec = []
            for i, a in enumerate(accesses):
                if pol.contains(a):
                    pol.on_hit(i, a)
                    dec.append((True, False, ()))
                else:
                    dec.append((False, bool(pol.on_miss(i, a)), tuple(pol.evicted)))
                    pol.evicted.clear()
            out.append((dec, pol, passes[0]))
        (d0, p0, n0), (d1, p1, n1) = out
        first = next((i for i, (x, y) in enumerate(zip(d0, d1)) if x != y), None)      # no diff of long lists
        self.assertIsNone(first, f"{mode}: decisions differ from access {first}")
        self.assertTrue(p0.key == p1.key, f"{mode}: keys differ")
        self.assertTrue(list(p0.key) == list(p1.key), f"{mode}: order of the residents differs")
        self.assertEqual(n0, n1)
        self.assertGreater(n1, len(accesses) // (2 * refresh), "the periodic pass did not run")
        self.assertGreater(sum(d[1] for d in d1), 0)
        for j in p1.jobs:                                # the arrays mirror the dictionaries
            head, flag = p1._head[j], p1._flag[j]
            for o in range(nobj):
                dq = p1.future[j].get(o)
                self.assertEqual(head[o], dq[0] if dq else -1)
                self.assertEqual(flag[o], (1 if o in p1.member[j] else 0) + (2 if o in p1.consumed[j] else 0))
        return d1, p1

    def test_every_lookahead_mode(self):
        acc = jobs_trace(60, 4, rates=(1.0, 2.5, 0.7), starts=[0.0, 3.0, 11.0], seed=2)
        for mode in ("epoch", "epoch2", "all", 0.1, 16.0):
            self.both(acc, mode, 12, 23)

    def test_jobs_with_different_datasets(self):
        sets = [range(0, 40), range(20, 70), range(60, 90)]      # a file outside a job's dataset has no use by it
        acc = jobs_trace(90, 3, rates=(1.0, 1.3, 2.0), seed=5, datasets=sets)
        for mode in ("epoch", "epoch2", 8.0):
            self.both(acc, mode, 15, 17)

    def test_stale_positions_and_wrong_rates(self):
        acc = jobs_trace(50, 3, rates=(1.0, 1.0, 3.0), seed=8)
        self.both(acc, "epoch", 10, 19, stale=8, rate_bias={0: 2.0, 2: 0.25})
        self.both(acc, "epoch2", 10, 19, stale=5)

    def test_a_file_read_twice_in_an_epoch(self):
        twice = {(0, e): [o % 30 for o in range(45)] for e in range(3)}     # job 0 reads 15 files twice per epoch
        acc = jobs_trace(30, 3, rates=(1.5, 1.0), seed=3, orders=twice)
        for mode in ("epoch", "epoch2", "all"):
            self.both(acc, mode, 8, 13)

    def test_full_and_tiny_cache(self):
        acc = jobs_trace(40, 3, rates=(1.0, 1.7), seed=9)
        self.both(acc, "epoch", 1, 11)
        self.both(acc, "epoch2", 40, 11)


class PerJobCaches(unittest.TestCase):
    def test_no_sharing_between_jobs(self):
        t = jobs_trace(100, 3, rates=(1.0, 1.0), seed=6)
        r = replay("perjob-static", t, 40)                        # 20 files per job
        self.assertEqual(r["hits"], 2 * (3 - 1) * 20)
        self.assertGreater(replay("static", t, 40)["hits"], r["hits"])


class QuiverInspired(unittest.TestCase):
    def test_every_file_once_per_epoch_and_capacity_respected(self):
        rng = random.Random(8)
        sizes = [rng.randint(1, 9) for _ in range(300)]
        t = jobs_trace(300, 2, rates=(1.0, 1.0, 1.0), seed=8, sizes=sizes)
        for name in ("quiver", "quiver-full"):
            for cap in (60, 300, 900):
                r = replay(name, t, cap)                          # asserts used <= capacity inside
                self.assertEqual(r["bytes"], sum(a.size for a in t), name)
                self.assertEqual(r["accesses"], len(t))

    def test_aligned_jobs_share_each_chunk(self):
        k = 4
        t = jobs_trace(400, 2, rates=(1.0,) * k, seed=9)
        r = replay("quiver", t, 80)
        self.assertGreater(r["obj_hit_rate"], (k - 1) / k - 0.05)   # one job loads, the others hit
        self.assertGreater(r["obj_hit_rate"], replay("oracle", t, 80)["obj_hit_rate"])  # it changes the order

    def test_single_job_gains_nothing_beyond_static(self):
        t = jobs_trace(400, 3, rates=(1.0,), seed=10)
        self.assertLessEqual(replay("quiver", t, 80)["hits"], replay("static", t, 80)["hits"])


class BoundAndAccounting(unittest.TestCase):
    def setUp(self):
        rng = random.Random(11)
        self.sizes = [rng.randint(2, 9) for _ in range(150)]
        self.t = jobs_trace(150, 3, rates=(1.0, 2.0, 0.7), starts=[0.0, 20.0, 5.0], seed=11, sizes=self.sizes)

    def test_bound_dominates_every_fixed_order_policy(self):
        for cap in (40, 200, 500):
            bound = replay("bound", self.t, cap)["hits"]
            for name in ("oracle",) + tuple(p for p in ONLINE if not p.startswith("quiver")):
                self.assertLessEqual(replay(name, self.t, cap)["hits"], bound, name)

    def test_accounting_and_capacity(self):
        total = sum(a.size for a in self.t)
        for cap in (40, 200, 500):
            for name in ONLINE + ("known:all", "known:epoch:stale=16", "known:epoch:rate=2@0"):
                r = replay(name, self.t, cap)
                self.assertEqual(r["bytes"], total, name)
                self.assertEqual(r["admission_bytes"] - r["evicted_bytes"], r["final_resident_bytes"], name)
                self.assertLessEqual(r["final_resident_bytes"], cap, name)
                self.assertTrue(0.0 <= r["mean_occupancy"] <= 1.0, name)

    def test_replay_is_deterministic(self):
        for name in ONLINE + ("known:all", "oracle", "bound"):
            self.assertEqual(stable(replay(name, self.t, 200)), stable(replay(name, self.t, 200)), name)


if __name__ == "__main__":
    unittest.main()
