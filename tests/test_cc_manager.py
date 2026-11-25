"""Tests of the cache manager (system/cc_manager.py) without a server: decisions against the
simulator, and the slot and reference-count handling under delayed completions."""
import os
import random
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "simulator"))
sys.path.insert(0, os.path.join(ROOT, "system"))
from cachesim import Access  # noqa: E402
from cc_manager import POLICIES, CacheManager, OnlineLookahead  # noqa: E402
import cc_verify  # noqa: E402
import crossjob  # noqa: E402


def trace(jobs=3, objects=120, epochs=3, seed=1, overlap=1.0, rates=None):
    """Jobs read seeded permutations of (partly) shared objects; unit sizes; interleaved by time."""
    rng = random.Random(seed)
    out = []
    for j in range(jobs):
        own = int(objects * (1 - overlap))
        objs = list(range(objects - own)) + [objects + j * own + k for k in range(own)]
        dt, t = 1.0 / (rates[j] if rates else 1.0), rng.random()
        for e in range(epochs):
            order = objs[:]
            rng.shuffle(order)
            for o in order:
                out.append(Access(t, j, e, o, 1))
                t += dt * (0.5 + rng.random())
    out.sort()
    return cc_verify.dense(out)


class Decisions(unittest.TestCase):
    def same(self, accesses, cap, delay=0):
        for pol in POLICIES:
            ref, ref_res, _ = cc_verify.reference(accesses, pol, cap)
            got, got_res, mgr = cc_verify.through_manager(accesses, pol, cap, delay=delay)
            self.assertEqual(ref, got, f"{pol}: decisions differ")
            self.assertEqual(ref_res, got_res, f"{pol}: resident sets differ")
            self.assertEqual(mgr.stat["order_mismatches"] + mgr.stat["order_gaps"], 0)

    def test_shared_dataset(self):
        self.same(trace(), 24)

    def test_partial_overlap_and_unequal_rates(self):
        self.same(trace(jobs=4, objects=90, overlap=0.5, rates=[1, 2, 4, 1], seed=7), 30)

    def test_one_job(self):
        self.same(trace(jobs=1, objects=50, epochs=4, seed=3), 10)

    def test_tiny_and_full_capacity(self):
        t = trace(jobs=2, objects=40, seed=5)
        self.same(t, 1)
        self.same(t, 40)

    def test_delayed_completions_do_not_change_decisions(self):
        t = trace(jobs=5, objects=60, epochs=4, seed=11)
        for delay in (1, 7, 40):
            self.same(t, 6, delay=delay)


class ArrayRekeying(unittest.TestCase):
    """The manager's known-order policy re-keys its residents with arrays (KnownOrder(dense=...)); the simulator's
    reference does it object by object. With a short refresh interval the pass runs often in both."""

    def setUp(self):
        crossjob.KnownOrder.check_rekey = True          # also compares every array pass with the per-object keys

    def tearDown(self):
        crossjob.KnownOrder.check_rekey = False

    def test_decisions_equal_the_simulator_with_frequent_passes(self):
        acc = trace(jobs=5, objects=150, epochs=3, seed=21, rates=[1, 1, 2, 3, 1])
        for pol in ("known:epoch", "known:epoch2"):
            for delay in (0, 9):
                ref, ref_res, _ = cc_verify.reference(acc, pol, 31, refresh=29)
                got, got_res, mgr = cc_verify.through_manager(acc, pol, 31, delay=delay, refresh=29)
                self.assertTrue(mgr.policy.dense)
                first = next((i for i, (x, y) in enumerate(zip(ref, got)) if x != y), None)
                self.assertIsNone(first, f"{pol}: decisions differ from access {first}")
                self.assertTrue(ref_res == got_res, f"{pol}: resident sets differ")

    def test_with_prefetching_and_a_job_that_leaves_its_order(self):
        acc = trace(jobs=3, objects=120, epochs=3, seed=4)
        swapped = 0
        for i in range(len(acc) - 1):                    # job 1 sometimes reads another file than it announced
            a = acc[i]
            if a.job == 1 and i % 17 == 0:
                acc[i] = Access(a.t, a.job, a.epoch, (a.obj + 7) % 120, 1)
                swapped += 1
        announced = trace(jobs=3, objects=120, epochs=3, seed=4)
        _, _, mgr = through_manager_announcing(announced, acc, "known:epoch2", 30, refresh=31,
                                               prefetch=dict(par=4, lead=6.0, unused=12))
        self.assertEqual(mgr.stat["order_mismatches"], swapped)
        self.assertGreater(mgr.stat["prefetch_issued"], 0)


def through_manager_announcing(announced, accesses, policy, capacity, refresh, prefetch=None):
    """As cc_verify.through_manager, but the jobs announce the orders of `announced` and read `accesses`."""
    orig = cc_verify.runs_of
    calls = [0]

    def runs(_):
        calls[0] += 1
        return orig(announced)
    cc_verify.runs_of = runs
    try:
        return cc_verify.through_manager(accesses, policy, capacity, refresh=refresh, prefetch=prefetch)
    finally:
        cc_verify.runs_of = orig


class Slots(unittest.TestCase):
    class Backend:
        def __init__(self):
            self.calls = []

        def hit(self, req, slot, size, kind):
            self.calls.append(("hit", req, slot, kind))

        def miss(self, req, path, size, slot):
            self.calls.append(("miss", req, slot))

        def fail(self, req, code):
            self.calls.append(("fail", req, code))

    def manager(self, policy="lru", capacity=2, spare=2, objects=8):
        self.b = self.Backend()
        m = CacheManager(policy, capacity, capacity + spare, [(f"f{i}", 10 + i) for i in range(objects)], self.b)
        m.register(1, 0, objects, objects)
        m.announce(1, 0, 0, objects, list(range(objects)))
        return m

    def test_slot_not_reused_while_read(self):
        m = self.manager(capacity=1, spare=2)
        m.register(2, 0, 8, 8)
        m.announce(2, 0, 0, 8, list(range(8)))
        m.get(100, 1, 0, 0, 0)                       # miss, admitted
        a = self.b.calls[-1][2]
        m.admitted(0, a, True)
        m.get(200, 2, 0, 0, 0)                       # hit: a transfer now reads slot a
        self.assertEqual(self.b.calls[-1], ("hit", 200, a, 1))
        m.get(101, 1, 0, 1, 1)                       # capacity 1: object 1 evicts object 0
        b = self.b.calls[-1][2]
        self.assertNotEqual(a, b, "the slot that is being read was handed out")
        self.assertIn(a, m.draining)
        self.assertNotIn(a, m.free)
        m.check()
        m.hit_done(a)                                # the transfer ends: now the slot is free
        self.assertIn(a, m.free)
        m.admitted(1, b, True)
        m.check()

    def test_request_waits_for_running_admission(self):
        m = self.manager()
        m.register(2, 0, 8, 8)
        m.announce(2, 0, 0, 8, [0, 1, 2, 3, 4, 5, 6, 7])
        m.get(100, 1, 0, 0, 0)                       # miss; copy into the store not finished yet
        slot = self.b.calls[-1][2]
        n = len(self.b.calls)
        m.get(200, 2, 0, 0, 0)                       # same object: a hit for the policy, but the bytes are not there
        self.assertEqual(len(self.b.calls), n, "the second request must wait")
        self.assertEqual(m.stat["hit_waits"], 1)
        m.admitted(0, slot, True)
        self.assertEqual(self.b.calls[-1], ("hit", 200, slot, 4))
        self.assertEqual(m.pins[slot], 1)
        m.hit_done(slot)
        m.check()

    def test_evicted_during_copy_then_admitted_again(self):
        m = self.manager(capacity=1, spare=3)
        m.get(100, 1, 0, 0, 0)                       # object 0 -> slot a, copy running
        a = self.b.calls[-1][2]
        m.get(101, 1, 0, 1, 1)                       # object 1 evicts object 0 while its copy runs
        b = self.b.calls[-1][2]
        self.assertNotEqual(a, b)
        self.assertEqual(m.orphan, {a: 0})
        m.register(2, 0, 1, 1)
        m.announce(2, 0, 0, 1, [0])
        m.get(200, 2, 0, 0, 0)                       # object 0 again: a miss, admitted into a third slot
        c = self.b.calls[-1][2]
        self.assertNotIn(c, (a, b))
        m.admitted(0, a, True)                       # the first copy finishes: its slot is simply released
        self.assertIn(a, m.free)
        self.assertNotIn(0, m.slot_of)
        m.admitted(0, c, True)
        self.assertEqual(m.slot_of.get(0), c)
        m.admitted(1, b, True)
        m.check()

    def test_requests_are_processed_in_announced_order(self):
        m = self.manager(policy="known:epoch", capacity=4, objects=6)
        m.get(3, 1, 0, 2, 2)                         # position 2 arrives first
        m.get(2, 1, 0, 1, 1)
        self.assertEqual(self.b.calls, [], "held until position 0 has arrived")
        m.get(1, 1, 0, 0, 0)
        self.assertEqual([c[1] for c in self.b.calls], [1, 2, 3])
        self.assertEqual(m.stat["order_mismatches"], 0)

    def test_wrong_object_is_counted(self):
        m = self.manager()
        m.get(1, 1, 0, 0, 5)                         # announced object 0 at position 0, asked for 5
        self.assertEqual(m.stat["order_mismatches"], 1)

    def test_unknown_job_is_refused(self):
        m = self.manager()
        m.get(1, 99, 0, 0, 0)
        self.assertEqual(self.b.calls[-1][0], "fail")


class Prefetch(unittest.TestCase):
    """The prefetcher of the manager with a stub data plane: accounting and invariants."""

    def run_pf(self, policy, delay=0, **kw):
        acc = trace(jobs=3, objects=120, epochs=3, seed=4)
        pf = dict(par=4, lead=6.0, unused=12)
        pf.update(kw)
        got, _, mgr = cc_verify.through_manager(acc, policy, 30, delay=delay, prefetch=pf)
        st = mgr.stat
        self.assertEqual(st["prefetch_done"], st["prefetch_issued"])
        self.assertEqual(st["prefetch_issued"], st["prefetch_in_time"] + st["prefetch_late"] + st["prefetch_evicted_unused"] + len(mgr.pf))
        return acc, got, mgr

    def test_prefetched_files_are_hits_and_everything_is_accounted_for(self):
        acc, got, mgr = self.run_pf("known:epoch")
        plain, _, _ = cc_verify.through_manager(acc, "known:epoch", 30)
        self.assertGreater(mgr.stat["prefetch_in_time"], 0)
        self.assertGreater(sum(g[0] for g in got), sum(g[0] for g in plain))      # more requests find their file

    def test_delayed_reads_make_late_prefetches_not_errors(self):
        _, _, mgr = self.run_pf("known:epoch", delay=6)
        self.assertGreater(mgr.stat["prefetch_late"] + mgr.stat["prefetch_in_time"], 0)

    def test_limits_hold(self):
        acc = trace(jobs=3, objects=120, epochs=2, seed=5)
        seen = []

        class Probe(cc_verify.Stub):
            def prefetch(self, obj, path, size, slot):
                seen.append((self.mgr.pf_inflight, len(self.mgr.pf)))
                super().prefetch(obj, path, size, slot)
        orig = cc_verify.Stub
        cc_verify.Stub = Probe
        try:
            cc_verify.through_manager(acc, "known:epoch", 30, delay=5, prefetch=dict(par=2, lead=8.0, unused=5))
        finally:
            cc_verify.Stub = orig
        self.assertTrue(seen)
        self.assertLessEqual(max(a for a, _ in seen), 2)
        self.assertLessEqual(max(b for _, b in seen), 5)

    def test_window_follows_the_rate_after_a_burst_at_the_start(self):
        # A job with several read streams sends its first requests at once. The rate measured then is far too
        # high; the window must shrink to `lead` seconds of the job's real rate, not stay at what it was then.
        order = list(range(400))
        times = [1e-6 * i for i in range(8)] + [0.1 * i for i in range(1, 393)]       # 8 at once, then 10 per second
        acc = [cc_verify.Access(float(f"{t:.6f}"), 0, 0, o, 1) for t, o in zip(times, order)]
        seen = []

        class Probe(cc_verify.Stub):
            def prefetch(self, obj, path, size, slot):
                seen.append((self.mgr.clock(), len(self.mgr.pf)))
                super().prefetch(obj, path, size, slot)
        orig = cc_verify.Stub
        cc_verify.Stub = Probe
        try:
            _, _, mgr = cc_verify.through_manager(acc, "known:epoch", 300, prefetch=dict(par=4, lead=2.0, unused=200))
        finally:
            cc_verify.Stub = orig
        late = [n for t, n in seen if t > 10.0]
        self.assertTrue(late)
        self.assertLessEqual(max(late), 40)            # 2 s at 10 files per second is 20; the estimate is still a little high
        self.assertEqual(mgr.stat["prefetch_evicted_unused"], 0)

    def test_two_epoch_lookahead_removes_the_cut_at_the_epoch_end(self):
        _, _, one = self.run_pf("known:epoch")
        _, _, two = self.run_pf("known:epoch2")
        self.assertGreater(one.stat["prefetch_window_cut"], 0)
        self.assertLess(two.stat["prefetch_window_cut"], one.stat["prefetch_window_cut"])

    def test_no_prefetching_without_a_known_order_policy(self):
        acc = trace(jobs=2, objects=60, epochs=2, seed=6)
        _, _, mgr = cc_verify.through_manager(acc, "lru", 15, prefetch=dict(par=4, lead=6.0, unused=8))
        self.assertEqual(mgr.stat["prefetch_issued"], 0)


class Lookahead(unittest.TestCase):
    def test_two_epochs_are_visible_when_announced(self):
        look = OnlineLookahead("epoch2")
        look.add_job(0, 9)
        look.add_epoch(0, 0, [5, 6, 7])
        self.assertEqual(look.reveal(0, 0), [(1, 6), (2, 7)])           # the next epoch is not announced yet
        look.add_epoch(0, 1, [7, 5, 6])
        self.assertEqual(look.reveal(0, 1), [(3, 7), (4, 5), (5, 6)])   # now visible to the end of the next epoch
        self.assertFalse(look.complete(0))
        look.add_epoch(0, 2, [6, 7, 5])
        self.assertEqual(look.reveal(0, 3), [(6, 6), (7, 7), (8, 5)])
        self.assertTrue(look.complete(0))
        self.assertEqual(look.ahead(0, 3, 2), [(4, 5), (5, 6)])

    def test_reveals_the_rest_of_the_epoch(self):
        look = OnlineLookahead()
        look.add_job(7, 6)
        look.add_epoch(7, 0, [10, 11, 12])
        self.assertEqual(look.reveal(7, 0), [(1, 11), (2, 12)])
        self.assertEqual(look.reveal(7, 1), [])
        look.add_epoch(7, 1, [12, 10, 11])
        self.assertEqual(look.reveal(7, 3), [(4, 10), (5, 11)])
        self.assertFalse(look.is_last(7, 4))
        self.assertTrue(look.is_last(7, 5))


if __name__ == "__main__":
    unittest.main()
