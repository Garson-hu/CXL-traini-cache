# Experiment Plan

Status: roadmap, last updated 2026-11-24. Phases 1 to 4 have been carried
out and phase 5 in part (see the table). On 2026-11-24 the user extended the
mechanism with two-epoch lookahead and asynchronous prefetching; phases 7 to
9 are the work that follows from it. The plan is provisional and each phase
can be changed or dropped based on what the previous phase shows.

Conventions:

- An experiment is named `YYYY-MM-DD-<short-name>`, after the day it starts.
  Names are never reused.
- Everything about one experiment lives in `experimental_results/<name>/`:
  `plan.md`, `summary.md` (from [experiments/TEMPLATE.md](experiments/TEMPLATE.md)),
  metadata, small tables and figures. These directories are local and not
  tracked by Git.
- The tracked record is one row per experiment in
  [experiments/INDEX.md](experiments/INDEX.md).
- Large raw results: `$CXL_TRAINING_DATA_ROOT/results/<name>/`.
- Every result is labeled as real hardware, simulation, or analytical.

## Phase overview

| Phase | Topic | Answers | Status |
|---|---|---|---|
| 0 | Repository and storage setup | — | Done (2026-11-11) |
| 1 | Workload characterization | Is there an I/O problem to solve, and when? | Done 2026-11-16 as `2026-11-16-workload-io-validation` and `2026-11-16-loader-gpu-scaling`: not for jobs with two or more read streams on the available GPUs, alone or as eight concurrent jobs; yes for jobs with exactly one read stream; analytically from about 15 concurrent jobs otherwise. Measured on 2026-11-17 (`2026-11-17-multi-gpu-io-saturation`): yes from about 12 jobs with two read streams per job and from about 16 to 17 jobs with eight; 20 jobs wait 20% to 26% of the time and memory-resident input removes it. The decision gate below applies. |
| 2 | Cache policy baselines | Does policy matter under limited capacity? (RQ1, RQ2) | Done in simulation on 2026-11-12: `2026-11-12-cache-policy-replay` (first pass) and `2026-11-12-cross-job-known-order` (known-order policy against per-job caches, a Quiver-inspired replay, and an offline reference) |
| 3 | Storage and CXL measurements | How fast are the real storage and CXL paths? | Done 2026-11-15 as `2026-11-12-remote-cxl-data-path`: direct BeeGFS, remote DRAM, and remote CXL paths, admission, concurrent reads and writes, I/O replay |
| 4 | Minimal CXL cache prototype | Can a basic cache work in the data-loading path? | Done 2026-11-17 as `2026-11-17-cxl-cache-integration`: one server with a store in CXL memory or DRAM, the simulator's four policies, CosmoFlow's input pipeline reading through it; correct on 877,280 verified objects, decisions equal to the simulator, 12.3 GB/s of hits. Architecture: D007 |
| 5 | End-to-end evaluation | Does CXL caching speed up training? (RQ1, RQ3) | Started 2026-11-17 in reduced form inside `2026-11-17-cxl-cache-integration`: 20 jobs run at the full rate with half of their bytes from the cache where direct BeeGFS on never-read data loses 17%; direct BeeGFS does as well on data read 10 to 95 minutes before. The comparison under a limited cache, a policy, and storage that is slow for the reused data is not run, nor are the 256 and 512 GiB capacities. 2026-11-18 (`2026-11-18-large-working-set-reuse`): the gate for that comparison was tested and not passed at 20 jobs: on the full shared dataset direct BeeGFS does not stall (0.8% waiting, emulated jobs); it begins to at 26 jobs |
| 6 | Extended evaluation | Larger datasets, multi-GPU, concurrent jobs (RQ4) | Not started, conditional |
| 7 | Lookahead and prefetching: characterization and simulation | What does two-epoch lookahead add, when does a prefetch meet its deadline, and what do replacement and prefetching contribute in simulation? (RQ1, RQ2) | First pass done 2026-11-24 in `2026-11-24-two-epoch-lookahead-prefetch`: two-epoch mode in the simulator; a scheduling model with a fitted storage model as a script of that experiment. Open: next-use distances across epoch boundaries as distributions |
| 8 | Lookahead and prefetching in the prototype | Does the joint mechanism work correctly in the running cache? (RQ2) | Done in minimal form 2026-11-24: prefetch path, prefetcher, two-epoch announcement; correct on every check made |
| 9 | Evaluation of the combined mechanism | Does it reduce GPU data stalls and raise training throughput, separately and together? (RQ3) | Small scale done 2026-11-24 (four training jobs): prefetching removes latency-bound waiting, as eight read streams do; no effect of the longer lookahead on waiting. The bandwidth-bound regime: preliminary validation and a three-minute pilot with 40 emulated jobs done 2026-11-24 in `2026-11-24-large-scale-cache-evaluation`; the comparison of the configurations is not run and waits for approval |

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

Done on 2026-11-17 ([system/](../system/README.md), decision D007 in
[decisions.md](decisions.md), experiment `2026-11-17-cxl-cache-integration`):
a C data plane derived from the data-path benchmark, a Python control plane
that calls the simulator's policy classes, a Mercury client, and an input
pipeline `cache` in the training harness. Byte-identical data, decisions
equal to the simulator, statistics per run. Open in the prototype:
variable-size allocation, persistence, more than one reader of BeeGFS for
misses.

## Phase 5: End-to-End Evaluation

Goal: compare BeeGFS-only, prefetching, DRAM caching, and CXL caching under
controlled resource budgets.

Work items:

- Configurations: BeeGFS only, BeeGFS with prefetching, DRAM cache, CXL cache.
- Controlled budgets: DRAM available to the job, cache capacity, I/O threads.
- Metrics: epoch time, training throughput, data-wait time, storage bytes read.
- Repeated runs with reported variance, fixed and recorded seeds.

First results (2026-11-17, `2026-11-17-cxl-cache-integration`, reduced scale,
single runs): direct BeeGFS, the cache with its store in CXL memory, and the
cache with a DRAM store were compared with 20 jobs; prefetching beyond the
jobs' own read streams was not a separate configuration. What is still to
do, in this order:

1. Done 2026-11-18 (`2026-11-18-large-working-set-reuse`): the storage
   supplies its cold ceiling (0.66 to 0.86 GB/s) divided by the share of
   bytes that comes from disk; 20 jobs stall only above a cold share of 0.7
   to 0.85; on the full shared dataset the share settles at 0.6 and the
   jobs do not wait. The run of item 2 would show no difference at 20 jobs.
2. The comparison this phase is about therefore needs demand above the
   storage limit, which starts at about 26 jobs of this GPU class, the
   number of suitable nodes that exist. Next step, not yet agreed: the read
   side of 32 to 40 jobs emulated with the paced loader (no GPU), direct
   BeeGFS against static pinning and known order through the cache with 256
   GiB of CXL memory, with the storage servers' disk counters; 9 to 10 TB of
   BeeGFS reads and 2.5 hours of 14 to 20 nodes. In the prototype all
   misses pass through one BeeGFS client (the server machine); whether
   that carries 1 to 1.7 GB/s has to be checked first. The question is no longer
   only whether a cache removes the stall but whether known order leaves
   the disks less to do than static pinning when the servers' own memory is
   in the path (simulated: no, unless that memory is small).
3. Real training at the largest job count the cluster allows, if item 2
   shows a difference worth confirming. Repeated runs with variance.

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

## Extension: two-epoch lookahead and asynchronous prefetching

Added on 2026-11-24 with the refined research idea
([research_idea.md](research_idea.md), sections 4 and 9; decision D009).
Nothing below has been run or implemented. Experiments get their dated
names when they start.

What the measurements so far fix for these phases:

- Prefetching can only be judged where jobs wait. Jobs waited in two kinds
  of configuration: with one or two read streams per job while the storage
  was below its limit (latency), and from about 26 jobs of the available GPU
  class on (bandwidth). With 20 jobs and eight streams on reused data they
  do not wait.
- The storage's supply follows a measured rule (cold limit of 0.66 to 0.86
  GB/s divided by the share of bytes from disk), and its servers keep the
  last minutes of what they read. A simulation of prefetching has to
  contain both.
- The strong baselines are static pinning, a loader with enough read
  streams of its own, and prefetching without reuse-aware replacement.

State after `2026-11-24-two-epoch-lookahead-prefetch` (same day): phases 7
and 8 were carried out in a first form and phase 9 at small scale. What is
left of the lists below: the distributions of item 1 of phase 7; in phase
9 the bandwidth-bound regime on hardware, the configuration "prefetching
with static pinning", jobs with eight streams behind the prefetching cache,
a DRAM store, repetitions, and disk counters on the storage servers. The
results do not make a larger run of prefetching by itself worthwhile: its
benefit is the one a loader with more read streams also gets, and under a
bandwidth deficit the model shows none. Next, in this order: (a) decide
which case prefetching is for (a job that cannot raise its own read
parallelism) and measure that case with a consumer faster than these GPUs;
(b) take decompression out of the read stream of the cache pipeline and
repeat the one-stream run without prefetching; (c) limit the share of the
capacity that prefetched files hold and measure the storage reads again;
(d) with the user's approval, the bandwidth-bound comparison of 2026-11-18
with prefetching as one more configuration.

State after the preliminary validation and pilot of
`2026-11-24-large-scale-cache-evaluation` (evening of the same day): item
(d) is prepared and not run. Done: the cache is correct with the full
catalog and a 256 GiB store; the miss path through the server machine
carries the load; 40 emulated jobs stall on cold storage (53% waiting); a
three-minute pilot of the cache at that demand; three corrections to the
server and the prefetcher. Found on the way and to be respected by the
comparison: (1) consecutive configurations must not replay the same
request sequences, because the storage servers still hold the earlier
run's files; a new seed base per configuration is proposed; (2) disk
counters on the storage servers are needed to say what the disks read, and
need a free CPU there; (3) the known-order policy stalls the manager for
4.6 to 4.8 s every 131,072 requests at this scale, and 40 jobs need 40 s to
start; (4) the server, as one BeeGFS client, gets a smaller share of a
saturated storage than direct clients while other users read. Proposed
comparison: 40 emulated jobs, direct BeeGFS, static pinning, known order,
known order with two-epoch prefetching, and direct BeeGFS again, 20 minutes
each; at most 9.8 TB of BeeGFS reads, 6 to 7 expected. It needs the user's
approval.

State after the second part of the same experiment (2026-11-24, 20:42 to
21:47; the user's second task sheet): the comparison is specified by the
user (the five runs above, 20 minutes each, two windows of 10 minutes,
other seeds of the same kind per configuration, storage state and
background load recorded per configuration, stop if the first direct run
waits less than 10% in its second window) and **still not run**. Done
before it: item (3) is fixed for the periodic pass (0.07 to 0.09 s, same
decisions; the start-up is unchanged); the cache client works on nodes
with several RDMA devices; 40 jobs start and run through the comparison's
scripts; the other users' reads are measured per user; scripts for the
series, the storage monitors, the probe of the storage state, and the
analysis exist and were rehearsed with four jobs. Open: disk counters need
a Slurm job on each storage server, and Slurm allocates whole nodes, so
the servers must be free of other users' jobs (none was until 22:02 on
2026-11-24; the others are expected on 2026-11-25). Expected and to be respected when the result is
read: in 20 minutes known order is still building up its reuse (simulated
hit share 1 − exp(−n/N)), so the second window is not a steady state;
getting past the first peak would take 35 to 45 minutes per run at the
rates seen. Budget: at most 9.8 TB, 5 to 6.5 expected. Approved by the
user on 2026-11-24 with runs of 20 minutes; queued to start by itself
when the storage servers' monitors run.

### Phase 7: characterization and simulation (RQ1, RQ2)

1. **What two-epoch lookahead adds** (trace analysis, no hardware). On the
   four real traces and on generated full-dataset workloads: next-use
   distance in accesses and in time, within an epoch and across its end;
   the share of next uses that only two-epoch lookahead makes visible; for
   every access the time between becoming visible and happening, under
   current-epoch and under two-epoch announcement, against the measured
   time of a fetch (tens of milliseconds for one reader on idle storage, up
   to seconds per file when 160 streams read cold data).
2. **The combined mechanism in simulation.** Needs additions to the
   simulator that do not exist: a two-epoch lookahead mode, time in the
   replay, a storage model with the measured supply rule, and a prefetcher
   with a limited number of concurrent fetches. Configurations: static
   pinning and known-order replacement (current epoch, two epochs), each
   without and with prefetching, and an offline reference that knows the
   true times. Per configuration: estimated waiting, prefetches complete in
   time, late, and unused, bytes read from storage for misses and for
   prefetching, bytes admitted. Workloads: the real traces; jobs with few
   read streams; more jobs than the storage can serve; several epochs over a
   working set larger than the cache; staggered jobs. A simulation with a
   storage model is an estimate of time, not a measurement, and is labelled
   so.

### Phase 8: the mechanism in the prototype (RQ2)

- Announcement of two epochs in the client and the harness; a prefetch
  queue in the control plane; fetches through the existing path (storage
  read into DRAM, CPU copy into CXL memory); one ranking for admission,
  eviction, and prefetching; counters for prefetches in time, late, and
  unused.
- Checks as for the prototype in `2026-11-17-cxl-cache-integration`: data
  equal to the files, decisions equal to the simulator given the same
  announcements, no file evicted while a transfer or a pending use depends
  on it, small scale first.
- The existing known-order rule is kept; changes to it need a measured
  reason.
- A DAX device and byte range have to be agreed for the experiment that
  runs it.

### Phase 9: evaluation, separately and together (RQ3)

| Regime | Configuration that shows it (measured without a cache) | Expectation, to be written as a hypothesis before the run |
|---|---|---|
| Latency-bound | 20 jobs with two read streams each (25% waiting); 8 jobs with one stream (41.5%) | Prefetching can remove the wait; so can more streams in the job |
| Bandwidth-bound | 26 jobs (3% waiting) is the onset; beyond it only emulated jobs (32 to 40) | Prefetching does not help beyond what reuse from the cache saves |
| Epoch boundaries and uneven demand | Several epochs over a working set larger than the cache; staggered jobs | Two-epoch lookahead lets the cache fetch a job's first files of the next epoch in time |

Configurations in each regime: direct BeeGFS with the job's own streams;
direct BeeGFS with eight streams; through the cache with static pinning;
known-order replacement alone; prefetching alone (with static pinning);
both together; a DRAM store of the same size where practical. Measures: GPU
data waiting and training throughput first; then prefetches in time, late,
and unused; bytes read from BeeGFS for misses and for prefetching; disk
reads on the storage servers; Mercury traffic; bytes admitted into CXL
memory; CPU. Repetitions with variance for the central comparisons.

This phase contains the comparison left open on 2026-11-18 (static pinning
against known order at 32 to 40 emulated jobs, with the storage servers'
memory in the path). It reads terabytes from shared storage and needs the
user's approval, as before. In the prototype every miss and every prefetch
is read by the server machine, one BeeGFS client; what that path carries
has to be measured first.

### The non-evictable famfs mode (separate, conditional)

The CXL tier of the earlier FitCache code never frees what it stores. For
such a store the comparison is between filling it at first open, as that
code does, and filling it in announced order ahead of first use. It is
planned and reported apart from the evictable cache. This project has no
famfs mount it may use (`/mnt/famfs/dax2.0` is off limits), so whether and
where this is run is the user's decision.

## Outcome of Phase 1 and the next step

`2026-11-11-training-io-characterization` was planned and never run. Its
parts were carried out on 2026-11-16 within
`2026-11-16-workload-io-validation` ([experiments/INDEX.md](experiments/INDEX.md)):
the supply rate of the real input pipeline from first-read BeeGFS, re-read
BeeGFS, and host memory, the compute-only rate, and data-wait time in
instrumented training on c28.

Result at the decision gate: data loading keeps up with training from cold
BeeGFS for one job with a parallel reader on the available GPUs. The gate asks
to identify configurations where storage is the bottleneck. They are
identified analytically: summed demand above the shared first-read supply
(about 255 samples/s), which is about 15 concurrent jobs on RTX 4060 Ti cards
or four A100-class GPUs, on a dataset the storage servers cannot hold. How
the evaluation should reach that regime is proposed in
[decisions.md](decisions.md), D006, and waits for the user's decision.

`2026-11-16-loader-gpu-scaling` then measured the space between the
sequential reader and the parallel one, and up to eight real concurrent
jobs: only single-stream jobs wait for storage, and eight jobs use half of
the shared first-read supply. It names three candidate configurations for
Phase 4 and Phase 5 (one read stream per job; eight such jobs; the baseline
reader as comparison).

Small follow-ups that need no cache: the residency probes on a quiet day
(about 2 GB of reads) and an instrumented run on the A100 node when it is
free (after 2026-11-21).

`2026-11-17-multi-gpu-io-saturation` ran the test of the estimated storage
limit, on the user's request: 7 to 20 real concurrent jobs. Jobs with two
read streams wait from about 12 jobs on; jobs with eight streams do not wait
at 15 jobs and wait 20% of the time at 20, where the shared first-read
supply (0.76 GB/s to the jobs) is below the demand (0.95 GB/s). Memory
restores the full rate everywhere. Phase 4 and Phase 5 therefore have a
real-training configuration in which a cache can matter against a
well-configured loader: 20 jobs, with a headroom of 1.24 times. Open
follow-ups: a repetition of the 15-job and 20-job runs with two streams (78
GB of first reads), and 20 jobs on one shared dataset over a longer time,
to see how much of the demand the storage servers' memory absorbs by itself.

