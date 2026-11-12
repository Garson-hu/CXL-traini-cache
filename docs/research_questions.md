# Research Questions

Status: **tentative**, 2026-11-11. These questions are provisional and are
expected to change as measurements come in. Record every change in the revision
log at the end of this file and, when it changes the direction of the project,
in [decisions.md](decisions.md).

Evidence labels are defined in [project_overview.md](project_overview.md).

## RQ1: CXL Cache Effectiveness

**How much can CXL caching reduce storage I/O and accelerate multi-epoch training?**

- What would answer it: storage bytes read per epoch and end-to-end training
  time with and without a CXL cache, on the same machine, under stated resource
  budgets.
- Current evidence: none from this project.
- Note: reducing storage I/O and accelerating training are two separate claims.
  The first can hold without the second.

## RQ2: Cache Management

**How should training data be admitted, retained, and evicted when CXL cache capacity is limited?**

- What would answer it: a trace-driven comparison of no cache, LRU, static
  pinned caching with bypass, future-aware replacement, and an offline bound
  across cache capacities, followed by confirmation on real hardware.
- Current evidence: analytical note A1 below. No simulation, no measurement.
- Caution: a new policy only matters if it beats static pinning with admission
  bypass under a realistic capacity constraint.

## RQ3: End-to-End Performance

**Under what conditions do reduced storage accesses translate into improved training throughput?**

- What would answer it: measurements that vary the ratio between storage read
  rate and training consumption rate (read parallelism, storage contention,
  GPU speed, number of jobs) and record data-wait time and throughput.
- Current evidence: **[Historical]** observation that prefetching hides I/O
  latency when storage bandwidth exceeds consumption. See note A2.

## RQ4: Shared Caching

**Can a shared CXL cache improve training efficiency across multiple GPU workers or concurrent training jobs?**

- What would answer it: experiments or trace replay with several ranks or jobs
  reading the same dataset through one cache.
- Current evidence: none.
- This question is only pursued if earlier phases justify it.

## Hypotheses

These are claims to test, not findings.

| ID | RQ | Hypothesis |
|---|---|---|
| H1 | RQ1 | When the whole dataset is retained in the cache, storage reads in every epoch after the first drop to near zero. The open part is how much training time this saves. |
| H2 | RQ3 | Caching improves training throughput only when the storage path cannot sustain the consumption rate. When it can, prefetching performs about as well as caching. |
| H3 | RQ2 | For a single job that reads each file once per epoch, future-aware replacement does not avoid more storage reads than static pinning (follows from A1). |
| H4 | RQ4 | When several jobs or ranks share a dataset and a cache, a read by one can serve a later access by another within the same epoch, so the single-job bound in A1 no longer applies and policy choice may matter. |

## Analytical notes

Both notes are **[Analytical]**: derived by reasoning, not measured and not yet
checked by simulation. They are recorded here because they affect which
experiments are worth running. Treat them as claims to verify.

### A1. Capacity bound for once-per-epoch access

Setting: one training job; each of N files is read exactly once per epoch, in a
new shuffled order each epoch; the cache holds at most C bytes; the dataset has
D bytes; the run has E epochs.

Argument:

1. An access in epoch e+1 avoids a storage read only if the file's data has
   stayed in the cache since it was last read from storage. That last read
   happened at or before the file's access in epoch e.
2. The file's residency in the cache therefore spans the boundary between
   epoch e and epoch e+1.
3. All such residencies overlap at that boundary, and the cache holds at most
   C bytes at any instant.
4. So the bytes served from the cache during epoch e+1 are at most C, for any
   admission and replacement policy, including one with full knowledge of the
   future.
5. Static pinning (admit files until the cache is full, never evict, bypass the
   cache for everything else) serves the pinned set, about C bytes, in every
   epoch after the first. It meets the bound, up to how well whole files pack
   into C.

Consequences, if the argument holds:

- For this access pattern, no replacement policy avoids more storage reads per
  epoch than static pinning. The fraction of all bytes that can avoid storage
  over a run is at most `(E-1)/E * min(1, C/D)`.
- The mean reuse distance of N-1 is a property of any once-per-epoch pattern.
  The short reuse distances at epoch boundaries do not create extra hits,
  because holding those files displaces others one for one.
- Policies can still differ in which accesses hit, in population cost, and in
  metadata and copy overhead. Whether any of that affects training time is an
  empirical question.
- The bound does not apply when its assumptions break: several jobs or ranks
  sharing one dataset and cache, sampling with replacement, epochs that cover
  only part of the dataset, files that differ greatly in size or cost, or
  workloads that mix datasets. If cache management is a research contribution
  of this project, it most likely lives in those settings.

How to check: replay a once-per-epoch trace through static pinning and an
offline optimal policy across capacities (Phase 2 of the
[experiment plan](experiment_plan.md)). The two should produce the same number
of storage reads.

### A2. Bandwidth-deficit model

A first-order model for when caching can matter. Let R be the rate at which
training consumes data and B the storage read rate the job can sustain.

- If `B >= R`, storage can keep up given enough read parallelism and lookahead.
  Expect little benefit from caching.
- If `B < R`, and a fraction `f = min(1, C/D)` of the bytes is served from the
  cache with hits spread evenly over the epoch, storage has to supply
  `(1 - f) * R`. Data loading keeps up when `f >= 1 - B/R`.

Illustration with **[Historical]** c33 numbers, not a prediction for any
system: with R of about 0.21 GB/s and one BeeGFS stream at about 0.064 GB/s,
the model gives f of at least about 0.70. With eight streams (about 0.52 GB/s)
there is no deficit.

The model ignores burstiness, decoding cost, the bandwidth of the cache path
itself, and the first epoch. Its purpose is to choose experiment conditions,
not to predict results.

## Revision log

| Date | Change | Reason |
|---|---|---|
| 2026-11-11 | Initial RQ1-RQ4, H1-H4, notes A1-A2 recorded | Repository setup |
