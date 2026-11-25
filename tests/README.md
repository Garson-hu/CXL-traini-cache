# tests/

Correctness and regression tests.

**Status:** tests exist for the cache policy simulator and for the manager of
the cache prototype. The framework is the standard library's `unittest`,
chosen so that no dependency is needed. One exception since 2026-11-24:
the known-order policy's array re-keying (`KnownOrder(dense=N)`), which
the cache manager uses, needs numpy; the tests of the manager with a
known-order policy therefore need it, and the class `ArrayRekeying` of
`test_crossjob.py` is skipped without it. The simulator itself still runs
without numpy.

## Contents

| File | Covers |
|---|---|
| [test_cachesim.py](test_cachesim.py) | Every policy on hand-computed traces; `oracle` against an exhaustive search; the single-job bound (note A1); LRU against its closed form; capacity and byte accounting for all policies; trace labels; the no-overwrite rule |
| [test_cc_manager.py](test_cc_manager.py) | The cache manager ([system/cc_manager.py](../system/cc_manager.py)) without a server: the prefetcher's accounting and limits, its window after a burst of first requests, and the two-epoch lookahead (added 2026-11-24); its decisions against the simulator for all five policies on synthetic multi-job traces, also with transfers and admission copies finishing late and in random order; a slot is not reused while a transfer reads it; a request waits for a running admission of the same object; an object evicted during its copy and admitted again; requests processed in announced order; a request that does not match the announcement is counted; an unknown job is refused; the array re-keying against the simulator's per-object pass with a pass every 29 requests, with prefetching and with a job that leaves its announced order (added 2026-11-24, evening) |
| [test_crossjob.py](test_crossjob.py) | What a job's lookahead reveals; per-job progress tracking and the cross-job next-use estimate; admission, bypass, and eviction of the known-order policy; that no online policy's decisions change when the unannounced future changes; per-job caches; the Quiver-inspired replay (every file once per epoch, capacity respected); the upper bound; determinism; `ArrayRekeying` (added 2026-11-24, evening): the known-order policy with arrays against the same policy without, on every lookahead mode, jobs with different datasets, stale positions and wrong rates, a file read twice in an epoch, a full and a one-slot cache: equal decisions, equal keys after every pass, and arrays that mirror the dictionaries |

## Running

```bash
python3 -m unittest discover -s tests -v
```

The tests take about three seconds. All inputs are tiny synthetic traces
generated inside the tests. They are test fixtures, not evidence about
workloads. The new tests report the first differing access instead of
comparing long lists with `assertEqual`: `unittest` takes minutes to
print the difference of two lists of thousands of tuples.

## Conventions

- Tests are small and fast. They must not need a real dataset, a GPU, or CXL
  hardware.
- Tests that need large data or special hardware are experiments, not tests.
- Cache policies are checked against hand-computed results on small traces.
- A cache implementation must be tested for data correctness: bytes served
  from the cache equal bytes read from storage.
- Record in [WORKLOG.md](../WORKLOG.md) which tests were actually run after a
  change. "Tests pass" is only written when they were run.
