# Experiment Plan

Status: roadmap only, 2026-11-11. **No experiment in this plan has been run.**
The plan is provisional and each phase can be changed or dropped based on what
the previous phase shows.

Conventions:

- Experiment IDs: `E<NNN>-<short-name>`, for example
  `E001-training-io-characterization`. IDs are never reused.
- Report: `docs/experiments/<experiment_id>.md`, from
  [experiments/TEMPLATE.md](experiments/TEMPLATE.md).
- Metadata and small summaries: `experimental_results/<experiment_id>/`.
- Raw results: `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/`.
- Every result is labeled as real hardware, simulation, or analytical.

## Phase overview

| Phase | Topic | Answers | Status |
|---|---|---|---|
| 0 | Repository and storage setup | — | Done (2026-11-11) |
| 1 | Workload characterization | Is there an I/O problem to solve, and when? | Audit done 2026-11-11; first experiment planned, not run |
| 2 | Cache policy baselines | Does policy matter under limited capacity? (RQ2) | Not started |
| 3 | Storage and CXL measurements | How fast are the real storage and CXL paths? | Not started |
| 4 | Minimal CXL cache prototype | Can a basic cache work in the data-loading path? | Not started |
| 5 | End-to-end evaluation | Does CXL caching speed up training? (RQ1, RQ3) | Not started |
| 6 | Extended evaluation | Larger datasets, multi-GPU, concurrent jobs (RQ4) | Not started, conditional |

## Phase 1: Workload Characterization

Goal: analyze CosmoFlow access patterns, data reuse, storage bandwidth, and GPU
data stalls.

Work items:

- Record which CosmoFlow implementation, commit, and dataset version are used.
  Locate the scripts and raw data behind the historical c33 numbers and record
  their provenance.
- Capture a file-level access trace over at least three epochs (file, bytes,
  time, epoch). Recompute the reuse-distance distribution from it.
- Measure the data consumption rate of training and the time the training loop
  waits for data.
- Measure BeeGFS read bandwidth on c28 as a function of read parallelism, for
  files of the dataset's size.
- Measure the upper bound of any cache: the same input pipeline reading from
  memory (for example a tmpfs copy of a dataset subset) versus from BeeGFS.

Decision gate: if data loading keeps up with training from BeeGFS in every
configuration of interest, caching cannot speed up that configuration. Either
identify configurations where storage is the bottleneck (see note A2 in
[research_questions.md](research_questions.md)) or revise the research
questions.

## Phase 2: Cache Policy Baselines

Goal: compare LRU, static pinned, and future-aware policies using trace replay
and realistic capacity constraints.

Work items:

- Trace-driven simulator (see [simulator/README.md](../simulator/README.md)).
- Policies: no cache, LRU, static pinned caching with bypass, future-aware
  replacement, offline oracle bound.
- Sweep cache capacity as a fraction of dataset size.
- Metrics: storage reads and bytes per epoch, hit ratio per epoch.
- Check analytical note A1: static pinning and the offline bound should match
  for single-job once-per-epoch traces.

Decision gate: if static pinning matches the offline bound for the workloads of
interest, do not build replacement machinery for them. Look for settings where
the bound does not hold (shared datasets, concurrent jobs) before investing in
policy design.

All Phase 2 output is simulation and must be labeled as such.

## Phase 3: Storage and CXL Measurements

Goal: measure actual BeeGFS and CXL cache-path behavior.

Work items:

- BeeGFS and local NVMe read behavior under the access pattern of the workload.
- CXL read and write bandwidth and latency compared with DRAM on c28.
- Cost of moving data between CXL memory and DRAM, single and concurrent.
- Cache lookup overhead once a prototype design exists.

Prerequisite: an agreed way to use CXL memory on c28. Since 2026-11-11 the
devdax devices `dax0.0` and `dax1.0` can be opened by this user, and per the
user nobody else uses them. They have no file system. `dax2.0` is root-only and
in use by a famfs mount ([hardware/c28.md](../hardware/c28.md)). Writing to a
DAX device happens only within an agreed experiment plan; any configuration
change needs explicit approval.

## Phase 4: Minimal CXL Cache Prototype

Goal: integrate a basic cache with the training data-loading path.

Work items:

- Start with the simplest design that Phase 2 and Phase 3 support.
- Verify correctness first: data served from the cache is byte-identical to
  data read from storage.
- Collect cache statistics (hits, misses, bytes, population time).

No architecture is chosen yet. Record the choice in [decisions.md](decisions.md)
when it is made.

## Phase 5: End-to-End Evaluation

Goal: compare BeeGFS-only, prefetching, DRAM caching, and CXL caching under
controlled resource budgets.

Work items:

- Configurations: BeeGFS only, BeeGFS with prefetching, DRAM cache, CXL cache.
- Controlled budgets: DRAM available to the job, cache capacity, I/O threads.
- Metrics: epoch time, training throughput, data-wait time, storage bytes read.
- Repeated runs with reported variance, fixed and recorded seeds.

Open issue: the A100 (c33) and the CXL memory (c28) are in different machines.
An integrated end-to-end measurement has to run on one machine. How to obtain
one (training on the c28 GPU, a data-loading-only harness with emulated GPU
consumption, or different hardware) is undecided and must be stated clearly in
any result.

## Phase 6: Extended Evaluation

Goal: study larger datasets, multiple GPU ranks, and concurrent workloads, if
justified by prior results.

Only started when Phases 1-5 show a benefit worth extending, or show that the
interesting regime is the shared or larger-than-cache one.

## First experiment (planned, not started)

`E001-training-io-characterization`:
[experiments/001-training-io-characterization-plan.md](experiments/001-training-io-characterization-plan.md).
It measures raw storage read rate, the supply rate of the real input pipeline
from BeeGFS and from host memory, the GPU's compute-only rate, and data-wait
time in instrumented training, all on c28.

Why first: it bounds what any cache can gain and shows whether training is
limited by storage, by CPU work in the input pipeline, or by the GPU, before
any cache code is written. It needs no CXL access and no hardware changes.

It replaces the candidate named `E001-cosmoflow-io-headroom` in the first
version of this plan.
