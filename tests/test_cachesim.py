"""Tests for simulator/cachesim.py. Standard library only.

Run from the repository root:  python3 -m unittest discover -s tests -v
All traces here are tiny synthetic inputs made for testing. They are not evidence about workloads.
"""
import functools
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "simulator"))
import cachesim  # noqa: E402
from cachesim import Access, POLICIES, simulate, trace_info  # noqa: E402


def make(objs, size=1, job=0, epoch=0):
    """Trace of unit-size (or fixed-size) objects named by small integers or letters."""
    ids = {}
    return [Access(float(i), job, epoch, ids.setdefault(o, len(ids)), size) for i, o in enumerate(objs)]


def replay(policy, accesses, capacity):
    info = trace_info(accesses)
    return simulate(accesses, POLICIES[policy](capacity, info), info, check=True)


def epoch_trace(n_objects, epochs, jobs=1, seed=0, sizes=None):
    """Each job reads every object once per epoch in its own random order; jobs alternate."""
    rng = random.Random(seed)
    per_job = []
    for j in range(jobs):
        seq = []
        for e in range(epochs):
            order = list(range(n_objects))
            rng.shuffle(order)
            seq += [(j, e, o) for o in order]
        per_job.append(seq)
    out = []
    for step in range(n_objects * epochs):
        for j in range(jobs):
            job, e, o = per_job[j][step]
            out.append(Access(float(len(out)), job, e, o, sizes[o] if sizes else 1))
    return out


def best_possible_hits(accesses, capacity):
    """Exhaustive search over all admission and eviction choices. Unit-size objects only."""
    objs = [a.obj for a in accesses]

    @functools.lru_cache(maxsize=None)
    def go(i, resident):
        if i == len(objs):
            return 0
        o = objs[i]
        if o in resident:
            return 1 + go(i + 1, resident)
        best = go(i + 1, resident)                              # bypass
        if len(resident) < capacity:
            best = max(best, go(i + 1, resident | {o}))
        else:
            for v in resident:
                best = max(best, go(i + 1, (resident - {v}) | {o}))
        return best

    return go(0, frozenset())


class HandComputed(unittest.TestCase):
    def test_none(self):
        r = replay("none", make("abab"), 2)
        self.assertEqual((r["hits"], r["storage_read_bytes"], r["admissions"]), (0, 4, 0))

    def test_lru(self):
        r = replay("lru", make("abacb"), 2)       # a b a(hit) c(evicts b) b(evicts a)
        self.assertEqual((r["hits"], r["evictions"], r["admissions"]), (1, 2, 4))

    def test_lfu(self):
        r = replay("lfu", make("aabca"), 2)       # c evicts b (count 1), not a (count 2)
        self.assertEqual((r["hits"], r["evictions"]), (2, 1))

    def test_static(self):
        r = replay("static", make("abcabc"), 2)   # a and b pinned, c always bypassed
        self.assertEqual((r["hits"], r["evictions"], r["admissions"]), (2, 0, 2))

    def test_slru_protects_reused_object(self):
        t = make("abacdefgha")
        self.assertEqual(replay("lru", t, 5)["hits"], 1)    # LRU loses 'a' before its last use
        self.assertEqual(replay("slru", t, 5)["hits"], 2)   # SLRU keeps 'a' in the protected segment

    def test_tinylfu_admission(self):
        r = replay("tinylfu", make("aabccc"), 2)  # c is admitted only once it is more popular than a
        self.assertEqual((r["hits"], r["admissions"], r["evictions"]), (1, 3, 1))

    def test_oracle_bypasses_objects_never_used_again(self):
        r = replay("oracle", make("abcab"), 2)    # c is never reused: not admitted
        self.assertEqual((r["hits"], r["admissions"], r["evictions"]), (2, 2, 0))


class OracleIsOptimalForEqualSizes(unittest.TestCase):
    def test_against_exhaustive_search(self):
        rng = random.Random(7)
        for case in range(60):
            n_obj, cap = rng.randint(3, 5), rng.randint(1, 3)
            t = make([rng.randrange(n_obj) for _ in range(11)])
            self.assertEqual(replay("oracle", t, cap)["hits"], best_possible_hits(t, cap), f"case {case}")


class OncePerEpochSingleJob(unittest.TestCase):
    """Analytical note A1: with one job and one read per file per epoch, hits per epoch <= capacity,
    and static pinning reaches that."""

    def test_static_equals_oracle_equals_bound(self):
        n, epochs = 300, 4
        t = epoch_trace(n, epochs, seed=1)
        for cap in (15, 60, 150, 240):
            static, oracle = replay("static", t, cap), replay("oracle", t, cap)
            self.assertEqual(static["hits"], (epochs - 1) * cap)
            self.assertEqual(oracle["hits"], (epochs - 1) * cap)
            self.assertEqual(replay("reuse-epoch", t, cap)["hits"], static["hits"])
            for p in ("lru", "lfu", "slru", "tinylfu", "reuse-gap"):
                self.assertLessEqual(replay(p, t, cap)["hits"], oracle["hits"], p)

    def test_lru_matches_closed_form(self):
        n = 4000
        t = epoch_trace(n, 2, seed=3)
        for c in (0.2, 0.5, 0.8):
            predicted = c + (1 - c) * math.log(1 - c)
            self.assertAlmostEqual(replay("lru", t, int(c * n))["warm_obj_hit_rate"], predicted, delta=0.02)


class SharedDataset(unittest.TestCase):
    def test_epoch_aware_candidate_between_static_and_oracle(self):
        t = epoch_trace(400, 3, jobs=2, seed=5)
        cap = 80
        static, cand, oracle = (replay(p, t, cap)["hits"] for p in ("static", "reuse-epoch", "oracle"))
        self.assertGreater(oracle, static)
        self.assertGreaterEqual(cand, static)
        self.assertLessEqual(cand, oracle)


class Accounting(unittest.TestCase):
    def test_every_policy_respects_capacity_and_byte_accounting(self):
        rng = random.Random(11)
        sizes = [rng.randint(1, 9) for _ in range(200)]
        weights = [1.0 / (k + 1) for k in range(200)]
        t = [Access(float(i), 0, i // 1500, o, sizes[o])
             for i, o in enumerate(rng.choices(range(200), weights=weights, k=3000))]
        total = sum(a.size for a in t)
        for cap in (25, 200, 600):
            for name in POLICIES:
                r = replay(name, t, cap)                       # check=True asserts used <= capacity
                self.assertEqual(r["bytes"], total, name)
                self.assertEqual(r["admission_bytes"] - r["evicted_bytes"], r["final_resident_bytes"], name)
                self.assertLessEqual(r["final_resident_bytes"], cap, name)
                self.assertTrue(0 <= r["storage_read_bytes"] <= total, name)
            self.assertEqual(replay("none", t, cap)["storage_read_bytes"], total)

    def test_object_larger_than_cache_is_never_admitted(self):
        t = [Access(0.0, 0, 0, 0, 10), Access(1.0, 0, 0, 0, 10)]
        for name in POLICIES:
            self.assertEqual(replay(name, t, 5)["admissions"], 0, name)


class TraceFilesAndCli(unittest.TestCase):
    def test_kind_label_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            trace, out = os.path.join(d, "t.csv"), os.path.join(d, "r.csv")
            with open(trace, "w") as f:
                f.write("# kind=synthetic; test input\nt,job,epoch,obj,size\n0,0,0,1,5\n1,0,0,2,5\n2,0,1,1,5\n")
            accesses, kind = cachesim.load_trace(trace)
            self.assertEqual((len(accesses), kind), (3, "synthetic"))
            with open(os.devnull, "w") as null:
                stdout, sys.stdout = sys.stdout, null
                try:
                    cachesim.main(["--trace", trace, "--out", out, "--capacities", "0.5"])
                finally:
                    sys.stdout = stdout
            with open(out) as f:
                rows = f.read().splitlines()
            self.assertEqual(len(rows), 1 + len(POLICIES))
            self.assertIn("synthetic", rows[1])
            with self.assertRaises(SystemExit):
                cachesim.main(["--trace", trace, "--out", out])


if __name__ == "__main__":
    unittest.main()
