# simulator/

Trace-driven cache policy simulation.

**Status:** a minimal simulator exists and was used for experiments
`2026-11-12-cache-policy-replay` and `2026-11-12-cross-job-known-order`. All
of its output is simulation: hit rates and byte volumes. It has no notion of
time, bandwidth, memory type, or network, and it says nothing about training
speed or about CXL.

The cache prototype ([system/](../system/README.md)) imports the policy
classes `Static`, `LRU`, `ReuseEpoch`, and `KnownOrder` from here and calls
them for every request. A change to one of these classes changes the server.
[system/cc_verify.py](../system/cc_verify.py) checks the server against this
simulator.

## Contents

| File | Purpose |
|---|---|
| [cachesim.py](cachesim.py) | Single-cache policies, replay engine, and command line. Standard library only. |
| [crossjob.py](crossjob.py) | Cross-job policies and references: the known-order policy, per-job caches, a Quiver-inspired replay, and an upper bound. Used through `cachesim.py` by policy name. |

Tests are in [tests/test_cachesim.py](../tests/test_cachesim.py) and
[tests/test_crossjob.py](../tests/test_crossjob.py). Trace
preparation scripts are in [scripts/](../scripts/README.md).

## Model

- Objects are whole files. Capacity is in bytes.
- A miss means the bytes are read from storage. A policy may then admit the
  object or let it bypass the cache.
- Trace format: CSV `t,job,epoch,obj,size`. Comment lines start with `#`; one
  of them states `kind=real` or `kind=synthetic`, and that label is copied
  into every result row.

## Policies

| Name | Summary | Information used |
|---|---|---|
| `none` | no cache | — |
| `lru` | admit all, evict least recently used | past accesses |
| `lfu` | admit all, evict lowest count | past accesses |
| `slru` | probation and protected segments | past accesses |
| `tinylfu` | LRU with frequency-based admission (simplified: exact counters) | past accesses |
| `static` | fill once, never evict, bypass afterwards | none |
| `reuse-gap` | online candidate: next use estimated from each file's last gap | per-file history |
| `reuse-epoch` | online candidate: next use estimated from which jobs have read the file in their current epoch | per-job epoch progress and epoch length |
| `oracle` | Belady's rule with admission bypass | exact future (offline) |

Cross-job names (in `crossjob.py`):

| Name | Summary | Information used |
|---|---|---|
| `known:epoch`, `known:all`, `known:<w>` | ranks cached files by the earliest estimated next use across jobs | the part of its own upcoming order that each job has announced (rest of the epoch, whole run, or the next w accesses), each job's position and measured rate. No future timestamps. |
| `known:...:rate=<f>@<job>`, `:stale=<n>`, `:alpha=<a>` | the same with a wrong rate for one job, delayed progress, or a different averaging window for the rate | as stated |
| `perjob-static`, `perjob-lru` | one cache per job, capacity split equally, no sharing | history |
| `quiver`, `quiver-full` | Quiver-inspired replay: jobs consume the dataset chunk by chunk and take cached files first. **It changes the order in which jobs read**, so it is not a policy on a fixed trace. `quiver-full` keeps as many chunks as fit. An approximation, not a reproduction of Quiver. | which jobs have consumed what |
| `bound` | upper bound on the object hit rate of any policy that keeps the jobs' orders | exact future (offline) |

Online policies are constructed from `online_view()` of the trace facts, which
contains no future accesses. The known-order policy sees announced order only
through `crossjob.Lookahead`.

Since 2026-11-24: `known:epoch2`, two-epoch lookahead (the rest of the
current epoch and the whole next one), and `KnownOrder.offer`, which puts a
file that is not resident through the ranked admission of a miss without
moving any job's position; the cache server's prefetcher uses it. The
existing modes and methods are unchanged.

Since 2026-11-24 (evening): `KnownOrder(dense=N)`, for callers whose
objects are the integers 0 to N-1 (the cache server's catalog). The pass
that gives every resident a new key is then computed for all residents at
once from arrays kept beside the policy's dictionaries (needs numpy). The
keys are equal to the last bit and no decision changes; a pass over 80,659
residents with 40 jobs takes 0.07 to 0.09 s instead of 4.6 to 4.8 s. The
simulator's own replays do not use it (`build()` leaves `dense` at 0), so
the per-object pass stays the reference that the cache manager is checked
against. `KnownOrder.check_rekey = True` (tests) compares every array pass
with the per-object keys.

Still not in the simulator: prefetching as part of a replay, and time. The
replay counts hits and bytes and has no model of how long a storage read
takes. A scheduling model with both exists as a script of experiment
`2026-11-24-two-epoch-lookahead-prefetch`; it is an estimate built on a
fitted storage model and is not part of this directory.

`oracle` gives the minimum number of misses for equal-sized objects. For
objects of different sizes it is a reference, not a bound; `bound` brackets it
from above for object hits. Exact definitions:
the plan of experiment `2026-11-12-cache-policy-replay` (kept locally under `experimental_results/`).

## Usage

```bash
python3 simulator/cachesim.py --trace TRACE.csv --out RESULT.csv \
    [--capacities 0.05,0.1,0.2,0.4,0.8] [--policies lru,static,oracle] [--check]
python3 -m unittest discover -s tests -v
```

Capacities are fractions of the working set (total size of the distinct files
in the trace). The program refuses to overwrite an existing result file.
`--check` asserts the capacity and accounting invariants during the replay.

## Conventions

- Large traces live under `$CXL_TRAINING_DATA_ROOT/traces/`, each with a
  provenance note. Only tiny test inputs live in the repository.
- Results go to `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/`; a small
  summary goes to `experimental_results/<experiment_id>/`.
- A new policy needs a hand-computed test, and a comparison against the
  strongest existing baseline on real traces, not only against LRU.
- Known gaps: no timing model, so no statement about training speed; the
  Quiver-inspired replay does not model cache allocation between datasets.
