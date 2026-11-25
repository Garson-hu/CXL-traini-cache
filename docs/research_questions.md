# Research Questions

Status: the three questions were fixed by the user on 2026-11-12 and refined
by the user on 2026-11-24 (wording below; the direction is unchanged, the
mechanism is extended, decision D009). Evidence last updated 2026-11-24
(`2026-11-24-two-epoch-lookahead-prefetch`); the refinement itself added no
evidence and changed none.
Record every change in the revision log at the end of this file and, when it
changes the direction of the project, in [decisions.md](decisions.md).

Fixed direction: **Online Reuse-Aware CXL Caching for Distributed Training.**
A shared CXL-based training data cache that exploits cross-job reuse and
future access sequences provided by the applications, to reduce storage
stalls and accelerate distributed training. The mechanism under study since
2026-11-24: known-order replacement, two-epoch lookahead, and asynchronous
prefetching, managed together ([research_idea.md](research_idea.md),
sections 4 and 9).

Evidence labels are defined in [project_overview.md](project_overview.md).
The idea behind these questions, and its refined form after the first
evidence, is in [research_idea.md](research_idea.md).

## RQ1: Cross-Job Reuse Characterization

**Characterize reuse across training jobs and epochs, including reuse
distance, next-use distance, and the availability of future access
information. How much useful information can be obtained from two-epoch
lookahead?**

Wording until 2026-11-24 ("Reuse Opportunity"): do realistic training
workloads exhibit sufficient variation and predictability in data reuse to
benefit from reuse-aware caching?

To investigate: reuse frequency; reuse distance and LRU stack distance;
next-use distance; changes across epochs; reuse across concurrent training
jobs; cache capacity versus working-set size. Pay particular attention to
cases where simple static retention is already optimal or near-optimal.
Added on 2026-11-24: which future access information a running job can
give, and when; how many next uses fall beyond the end of the current epoch
and become visible only with two-epoch lookahead; how much time lies
between the moment an access becomes known and the access itself, compared
with the time a fetch from storage takes.

State of the added part after `2026-11-24-two-epoch-lookahead-prefetch`:

- **[Observed]** A seeded job can announce its next epoch one epoch early
  without any change to what it reads: identical request sets with
  one-epoch and two-epoch announcement, no request that differs from the
  announced order (test clients; four training jobs, three epochs).
- **[Simulated]** For replacement, two-epoch lookahead gives the byte hit
  rate of whole-run knowledge on the three CosmoFlow traces: 0.1 to 2.9
  points above one-epoch lookahead at 5%, 20%, and 80% capacity. On the
  FitCache trace, whose epoch labels interleave at the boundaries, it gives
  0.1 points where whole-run knowledge gives 2.5.
- **[Simulated]** and **[Observed]** For prefetching, the extra epoch
  matters only for the first requests after an epoch boundary: the
  prefetcher catches up as soon as an epoch is announced. On hardware the
  prefetch window was cut by the end of the announced order at 661 of
  24,576 accesses with one-epoch lookahead and at none with two-epoch
  lookahead, with no difference in waiting.
- Not characterized: next-use distances across the epoch boundary as a
  distribution; loaders whose order is not a function of a seed.

- Current evidence, **[Simulated]** on real traces
  (`2026-11-12-cache-policy-replay` ([experiments/INDEX.md](experiments/INDEX.md))): for one job that reads each file
  once per epoch, static retention is optimal and there is no opportunity. For
  two jobs sharing a dataset, a future-aware reference avoids far more storage
  reads than any simple policy, so an opportunity exists there.
- **[Simulated]** (`2026-11-12-cross-job-known-order`): the opportunity
  persists in synthetic compositions with 2, 4, and 8 jobs, speed ratios up to
  1:4, staggered starts, and partial overlap. A replay that reorders the jobs'
  reads (Quiver-inspired) exploits the same reuse more strongly at small
  capacity when jobs have equal speed.
- **[Simulated]** on a new real trace (`2026-11-16-workload-io-validation`):
  two jobs on two GPU nodes with logged job identity, speeds 16.2 and 10.6
  samples/s, the second started three minutes later. The opportunity is
  there and smaller: at 20% capacity the offline reference serves 34.3% of
  the bytes against 18.0% for static pinning (46.2% and 17.9% on the earlier
  trace). 23% of the accesses come after the faster job has ended. The
  Quiver-inspired replay, far ahead on the earlier trace, reaches 28.4%.
- **[Simulated]** on a real eight-job trace (`2026-11-16-loader-gpu-scaling`,
  eight identical nodes, same start, three epochs, job identity logged): at
  20% capacity the offline reference serves 58.6% of the bytes against 19.1%
  for static pinning and 1.7% for per-job caches of the same total size. The
  Quiver-inspired replay reaches 88.3%; these jobs travel together.
- **[Simulated]** on a real twenty-job trace (`2026-11-17-multi-gpu-io-saturation`,
  twenty GPU nodes, same start, three epochs over the same files, job
  identity logged): at 20% capacity the offline reference serves 60.0% of
  the bytes against 19.6% for static pinning and 0.7% for per-job caches of
  the same total size. 98% of the accesses follow a read of the same file
  by another job.
- **[Observed]** in the running cache with real training
  (`2026-11-17-cxl-cache-integration`): the reuse is there in a live system
  (20 jobs on a shared pool; a cache of 18% of the pool served 50.6% of the
  bytes with the known-order policy). What it is worth depends on what the
  storage does with the same reuse: every time data was reused in that
  experiment (read twice 10 and 50 minutes before, or once 95 minutes
  before), BeeGFS served it to 20 direct jobs at the full rate. Reuse and slow storage were
  not observed for the same bytes.
- **[Observed]** (`2026-11-18-large-working-set-reuse`, 20 emulated jobs on
  the full 1.52 TB set, each in its own order, direct BeeGFS, one hour):
  every file is reused by every job, and the jobs do not wait for storage
  (0.8% waiting, as from memory). The storage servers' memory serves 40% of
  the bytes; a stall needs more than 70% to 85% of the bytes from disk. At
  26 jobs a stall begins (3% waiting). Reuse and a storage stall do not
  coexist on this cluster at the job counts its GPUs allow.
  **[Simulated]** They would from about 32 jobs.
- Open: real traces with partial dataset overlap or with many jobs of
  different speeds, other workloads, how common shared datasets are, and
  clusters or job counts in which demand exceeds the storage's cold
  supply.

## RQ2: Reuse-Aware Cache Management

**Extend the existing known-order cache management with two-epoch lookahead
and asynchronous prefetching, and manage prefetching, admission, and
eviction together under limited CXL capacity.**

Wording until 2026-11-24 ("Online Reuse-Aware Cache Management"): can an
online policy use observed training access behavior to improve cache
admission, retention, and eviction?

The four parts:

| Part | Content | State on 2026-11-24 |
|---|---|---|
| Two-epoch lookahead | Training jobs announce their upcoming file access sequences two epochs ahead. | Implemented on 2026-11-24, read as "the rest of the current epoch and the whole next one": lookahead mode `epoch2` in the simulator, policy `known:epoch2` in the cache, announcement of the next epoch in the client and the harness. The manager's decisions equal the simulator's. |
| Admission and replacement | The existing next-use-aware rule is kept: files needed sooner are preferred. | Implemented in the simulator and in the cache prototype; evidence below. Not to be redesigned without need. |
| Asynchronous prefetching | Upcoming files that are not cached are fetched from BeeGFS into CXL memory before the application requests them. | A minimal version exists since 2026-11-24: background reads behind all demand work, a cap on reads in flight, a window of announced accesses per job. Measured at small scale. |
| Joint management | Prefetching is coordinated with admission and eviction under limited CXL capacity. | Minimal form: a prefetch candidate is offered to the unchanged ranked admission (`KnownOrder.offer`), and a cap limits prefetched files not yet used. Not tuned; not stressed. |

Future information that a job has at run time (its own announced order, no
timestamps) is kept apart from offline oracle information (the recorded
trace with the true time of every access); the oracle is a reference only.
Where a store cannot evict (the famfs mode of the earlier FitCache code),
replacement does not apply; that mode is treated and reported separately
([research_idea.md](research_idea.md), section 4).

Candidate inputs: historical reuse observations; estimated next-reuse distance
or probability; file size; estimated storage retrieval cost; available CXL
cache capacity; since 2026-11-24 also the time until an announced access and
what the storage can deliver until then. No complex learned predictor
unless simpler ones are shown to be insufficient.

Considerations fixed with the refinement:

- A prefetch must finish before its file is requested to hide the read.
- Two-epoch lookahead gives more time for that, most of all near epoch
  boundaries; it does not guarantee that a transfer meets its deadline.
- Prefetching cannot remove a sustained deficit of storage bandwidth.

- Current evidence, **[Simulated]**: an estimator based on per-file history
  does not help. An estimator based on each job's progress through its epoch
  beats static pinning but recovers only part of the gap to the future-aware
  reference, and on the real two-job trace it loses to LRU at the smallest
  capacity.
- Correction, **[Simulated]** (`2026-11-12-cross-job-known-order`): the loss
  to LRU came from job labels guessed by time windows. With reconstructed job
  identity the progress-based estimator is ahead of LRU at every capacity and
  recovers 32% to 82% of the gap.
- **[Simulated]** (`2026-11-12-cross-job-known-order`): in training, part of
  the "future" is observable online, because a seeded data loader knows its
  order in advance (NoPFS). A policy that is told each job's order for the
  rest of its epoch recovers 83% to 96% of the gap on the real two-job trace,
  and 99% to 100% with the order of the whole run. A quarter-epoch lookahead
  gives most of this, and a rate estimate wrong by a factor of two costs about
  one point. It does not reach the hit rate of order-changing coordination at
  small capacity.
- **[Simulated]** on the new real trace with unequal speeds
  (`2026-11-16-workload-io-validation`): the order of the policies is
  unchanged. Known order for the rest of the epoch serves 30.9% at 20%
  capacity (progress-aware 25.1%, LRU 6.3%) and recovers 75% to 88% of the
  gap between static pinning and the offline reference; with the whole run's
  order, 95% to 100%. Against the Quiver-inspired replay it is level at 5%
  capacity, 5 points behind at 10%, and ahead from 20% upward.
- **[Simulated]** on the real eight-job trace (`2026-11-16-loader-gpu-scaling`):
  known order for the rest of the epoch serves 57.3% at 20% capacity and
  recovers 93% to 99% of the gap between static pinning and the offline
  reference; the progress-aware policy 30.6% (16% to 64% of the gap), LRU
  27.3%. The Quiver-inspired replay is 15 to 43 points ahead up to 40%
  capacity and behind at 80%.
- **[Simulated]** on the real twenty-job trace (`2026-11-17-multi-gpu-io-saturation`):
  known order for the rest of the epoch serves 59.5% at 20% capacity and
  recovers 98% to 99% of the gap between static pinning and the offline
  reference at every capacity; the progress-aware policy 29.5% (10% to 54%
  of the gap), LRU 27.5%. The Quiver-inspired replay is ahead at 5% and 10%
  capacity (62.5%, 84.4%) and behind above that (41.6%), which was not
  examined.
- **[Observed]** in the running cache (`2026-11-17-cxl-cache-integration`):
  the policies are the simulator's classes inside a real server, and the
  server's decisions equal the simulator's on recorded traces (10.7 million
  accesses) and on the server's own logs. With 20 real training jobs, 8 read
  streams each, three epochs over a shared pool of 1,024 files, the cache
  served, at 18% and 36% of the pool: known order 50.6% and 68.9% of the
  bytes, progress-aware 26.0% and 46.4%, LRU 17.2% and 34.7%, static pinning
  17.7% and 35.5%. Known order halved the bytes read from BeeGFS at 18%.
  A job announces its seed, epoch length, and each epoch's order; requests
  carry the position; that is all the server uses.

- **[Simulated]** on generated full-dataset workloads
  (`2026-11-18-large-working-set-reuse`: 20 to 40 jobs, 524,288 files, 256
  GiB cache): known order serves 49% of the bytes from the cache, static
  pinning and LRU 15%, progress-aware 17%. With the storage servers' memory
  modelled behind the cache as a recency cache of 600 GiB (the size that
  reproduces the measured cold share), that lead does not reach the disks:
  0.46 GB/s from disk with known order against 0.43 with static pinning at
  20 jobs, 0.73 against 0.68 at 32. Known order keeps what will be re-read
  soon, the servers keep what was read recently, and with independent
  random orders these are largely the same reads. Known order is ahead only
  if the servers keep less (0.50 against 0.63 at 300 GiB). On a storage
  system with a large server-side cache, a policy has to be judged by the
  disks' load of cache and servers together, not by the cache's hit rate.
  Not measured.

- **[Observed]** and **[Simulated]**, the extended mechanism at small scale
  (`2026-11-24-two-epoch-lookahead-prefetch`):
  - Without prefetching the manager still decides as the simulator, for
    one-epoch and two-epoch lookahead (4.56 million trace accesses and the
    logs of three training runs, no differing decision).
  - Four training jobs on a shared pool of 2,048 files, cache of 20%:
    static pinning served 18.4% of the bytes, known order 47.2%, known
    order with prefetching 99.9% (one-epoch lookahead) and 100.0%
    (two-epoch); every prefetch but one was complete before its request,
    none was evicted unused.
  - Prefetching read 8% to 11% more from BeeGFS than known order alone and
    copied 42% to 45% more into CXL memory: a prefetched file holds a slot
    until it is used.

- **[Observed]**, the mechanism at full scale, before the comparison
  (`2026-11-24-large-scale-cache-evaluation`, preliminary validation):
  - With the full catalog (524,288 files), 40 jobs, and 256 GiB of slots
    the manager decides as the simulator: no differing decision in 403,200
    accesses without a server, none on the logs of two pilot runs; 40,960
    requests through the server compared byte for byte, none differs.
  - On this workload two-epoch lookahead takes exactly the decisions of
    one-epoch lookahead: an epoch lasts 8.7 hours, and the second one never
    ranks among the files the cache holds.
  - Cost of the policy at that scale: 70 µs per request (131 with
    prefetching), and one pass of 4.6 to 4.8 s every 131,072 requests in
    which every resident file is re-keyed and no request is answered.
    Since the evening of 2026-11-24 the pass is computed with arrays in
    0.07 to 0.09 s; decisions and keys are unchanged (806,400 accesses per
    configuration against the simulator's per-object pass). The start is
    unchanged: a job's first request takes 0.26 s (one announced epoch) or
    0.6 s (two), and 40 jobs deliver their first batches 3 to 33 s after a
    common start.
  - **[Simulated]** and **[Analytical]**, found while checking that pass:
    after a common cold start the hit share of known order is
    1 − exp(−n/N) until the jobs have made about N requests in all (N
    files; every re-read of a file is then a hit), falls by about 20
    points, and swings towards 50% (40 jobs, 256 GiB). The fall is not
    caused by the re-keying. A 20-minute run at the storage limit ends
    inside that first rise.
  - The prefetcher did not keep its window with jobs of several read
    streams (5,897 prefetches for 1,352 requests); corrected.
  - With 40 jobs at the storage limit and an empty cache, 35% of the
    prefetches were complete when the job asked; the rest were still being
    read or had been passed by the job.

## RQ3: CXL-Based Training Acceleration

**Does the combined mechanism, reuse-aware replacement with asynchronous
prefetching, reduce GPU data stalls and improve end-to-end distributed
training throughput? What do replacement and prefetching contribute
separately, and what together?**

Wording until 2026-11-24 ("Distributed CXL Training Acceleration"): can the
resulting policy improve real training performance through a remote CXL
cache?

To measure: GPU data waiting time; end-to-end training throughput; BeeGFS
read reduction; cache hit rate and byte hit rate; CXL cache traffic; Mercury
communication overhead. Added on 2026-11-24: the same for replacement
alone, prefetching alone, and both; for prefetching the share of requests
whose file was complete in time, late, or fetched and not used; the bytes
read from BeeGFS for prefetching; what the storage servers' own memory
serves (their disk counters); the cost of admission into CXL memory. Remote
DRAM and direct BeeGFS are required baselines, the latter with a loader
that has enough read streams of its own. Cache hits alone do not show an
acceleration.

State of the added part after `2026-11-24-two-epoch-lookahead-prefetch`
(four training jobs, store in CXL memory, single runs):

- **[Observed]** Latency-bound case, every job on its own cold files with
  one read stream: 39.5% waiting directly from BeeGFS (10.2 samples/s per
  job), 18.7% through the cache with known order and no prefetching, 0.5%
  with prefetching (16.9 samples/s). A direct job with eight read streams:
  0.5%. Prefetching removes the wait that too little read parallelism
  causes, and so does more parallelism in the job.
- **[Observed]** Shared pool of 2,048 files, three epochs, one stream:
  waiting differs only in the first epoch (4.0% direct, 1.1% static, 1.2%
  known order, 0.5% with prefetching); from the second epoch on every
  configuration waits 0.4% to 0.5%, because the pool is in the storage
  servers' memory. Total throughput within 1.4% across all five.
- **[Observed]** One-epoch against two-epoch lookahead with prefetching: no
  difference in waiting or throughput.
- **[Simulated]** (scheduling model fitted to this project's measurements):
  with 40 jobs on the full dataset, where the storage's bandwidth is
  exceeded, prefetching changes nothing (24.4% waiting with and without;
  static pinning 21.6%, direct 34.8%).
- Not measured: prefetching where the storage is the limit; more than four
  jobs; jobs with eight streams behind the prefetching cache; the overlap
  with the storage servers' memory by disk counters (no server had a free
  CPU).

State after the preliminary validation and pilot of
`2026-11-24-large-scale-cache-evaluation` (emulated jobs: real input
pipeline with eight read streams, paced consumer, no GPU; single runs; no
disk counters; **the comparison of the four configurations has not been
run**):

- **[Observed]** 40 emulated jobs on the full dataset from cold storage,
  direct BeeGFS: 47% of their rate, 53% waiting, 200 requests queued at the
  storage servers, which sent 0.94 GB/s. The storage limit the comparison
  needs is reached with 40 jobs.
- **[Observed]** The same demand through the cache (known order,
  two-epoch lookahead, prefetching, 256 GiB in CXL memory, empty at the
  start), three minutes: 42% of the rate once it ran, 58% waiting; 11%
  fewer samples than direct, and 40 s before the jobs ran at all. An empty
  cache has nothing to give in three minutes; this is the cost of the tier,
  not its value.
- **[Observed]** The miss path through one machine: 12.1 GB/s on data in
  the storage servers' memory (the link), equal to direct reads on cold and
  mixed data with 320 streams (0.81 against 0.78, 1.58 against 1.56 GB/s).
  But as one BeeGFS client it received a smaller share of a saturated
  storage than 20 nodes reading directly while other users read too (0.78
  against 0.92 GB/s in the pilot); the storage's total output was the same.
- **[Observed]** 8 jobs (0.39 GB/s): 0.3% to 0.5% waiting in all four
  configurations; the cache tier costs 0.2 points.
- **[Observed]**, on method: consecutive configurations with the same
  request sequences are not independent. The later ones asked for files the
  storage servers still held from the earlier one (82% to 95% of the misses
  read in 1 to 2 ms).
- **[Observed]**, 40-job check of the second part (two runs of 90 s,
  cache empty at the start): known order 45% of the rate and 54% waiting,
  with two-epoch lookahead and prefetching 47% and 53%; 37% of the
  prefetches finished before their request. Same as direct BeeGFS in the
  pilot; 90 s hold no reuse.
- Not measured: static pinning against known order at the storage limit;
  the steady state; what the disks read; prefetching against no
  prefetching at 40 jobs beyond 90 s.

- Current evidence on CXL and training time: none. Trace replay cannot say
  anything about CXL, the network, or training time.
- **[Observed]** (`2026-11-12-remote-cxl-data-path`, direct BeeGFS path only,
  client c39, 2.9 MB files): first reads reach 0.11 GB/s with 1 thread and
  0.77 GB/s with 32. Files read shortly before reach 2.0 GB/s with 1 thread
  and 12.3 GB/s with 16 or more, the limit of the client's 100 Gb/s link;
  they come from the memory of the storage servers. A remote cache behind the
  same kind of link can therefore help only with data the storage servers do
  not hold in memory. Files read three days earlier were cold again.
- **[Observed]** (the same experiment, 2026-11-15, client c44, server c28):
  remote CXL through Mercury equals remote DRAM, 10.2 GB/s with one client
  thread and 12.3 GB/s from 8, limited by the link; the NIC reads CXL memory
  directly. Admission into CXL costs the same as into DRAM; its cost is the
  storage read. Admissions do not disturb reads (under 1%), unless the NIC
  writes into CXL memory itself: that path is capped at 4.24 GB/s and cuts
  concurrent reads by 94%.
- **[Observed]**, I/O replay of the two-job trace with recently read storage
  (not training): no cache 21.9 s; static 25.7 s, known-order 26.9 s,
  progress-aware 27.0 s, LRU 29.9 s, identical for DRAM and CXL. With the
  dataset in the storage servers' memory the cache does not reduce I/O time.
  **[Analytical]** from the measured rates: if every miss were a cold read,
  known-order would shorten the replay by about 42% against no cache.
- **[Observed]**, first training measurements
  (`2026-11-16-workload-io-validation`, c28, RTX 4060 Ti, no cache): with a
  parallel reader CosmoFlow trains at 16.86 samples/s from first-read BeeGFS,
  re-read BeeGFS, and host memory alike, waiting for data 0.4% of the time.
  Host memory is the upper bound for a cache of file bytes, so no such cache
  can speed up this configuration. With the benchmark's sequential reader
  training waits 60% of the time on first reads and memory is 2.16 times
  faster; a parallel reader removes that without a cache.
- **[Observed]** The input pipeline costs 68 to 76 ms of CPU per sample; a
  16-core node supplies at most 209 samples/s from memory and 112 to 155
  from first reads. First-read supply is shared by all clients: 0.74 GB/s at
  32 streams, about 255 samples/s.
- **[Observed]** Once-read files were served from the storage servers'
  memory after 15 minutes and from disk after 60; twice-read files from
  memory after two hours and from disk after four (under this project's own
  read load). **[Analytical]** A
  full-dataset epoch (1.9 to 8.6 hours) is therefore a cold epoch, and
  storage limits training once the summed demand passes about 255 samples/s:
  about 15 jobs on RTX 4060 Ti cards or four A100-class GPUs.
- **[Observed]** (`2026-11-16-loader-gpu-scaling`, real training, cold files
  of the full dataset): a job waits for storage only with exactly one read
  stream. One GPU on c28: 12.5 samples/s and 26% waiting with one stream,
  16.85 with two or more; memory-resident input gives 16.86 (1.35 times).
  Eight concurrent jobs on eight GPU nodes: no waiting with the baseline
  reader or with two streams per job (135 samples/s, 0.39 GB/s in total);
  with one stream per job 9.9 samples/s each and 41.5% waiting, against 11.2
  for one such job and 16.84 from memory (1.70 times). Sharing the storage
  costs 11% at this scale. tf.data's interleave reads ahead up to three
  files per cycle slot, so the "8 readers" of the measurements above are up
  to 24 streams.
- **[Observed]** (`2026-11-17-multi-gpu-io-saturation`, real training, 7 to
  20 concurrent jobs on separate GPU nodes, each on its own cold files of the
  full dataset): with two read streams per job nobody waits up to 9 jobs;
  12 jobs waited 17% in one run and 0.3% in a repetition; 15 jobs wait 13%
  and 20 jobs 25%, at 83% and 73% of linear aggregate throughput. With eight
  read streams 15 jobs do not wait and 20 jobs wait 20% (81% of linear): the
  jobs get at most 0.76 GB/s of first reads, the demand of 16 to 17 jobs,
  and 20 jobs need 0.95 GB/s. Re-read data and memory-resident input give
  the full rate at every job count (1.24 to 1.38 times in aggregate at 20
  jobs). This is the first measured configuration in which a loader with
  enough read streams waits for storage in real training. Single short runs;
  every first read is cold by construction.
- **[Analytical]** from those runs: at 20 jobs a cache that served 19% of
  the bytes from memory would bring the remaining first reads down to the
  measured supply for jobs with eight streams (41% to 45% for jobs with two
  streams). A dataset shared by 20 jobs is re-read every 27 minutes on
  average, so part of it would be warm in the storage servers without any
  cache; the runs measure the upper end of the demand.
- **[Observed]**, first measurements with the cache in the path
  (`2026-11-17-cxl-cache-integration`, server on c28 with its store in CXL
  memory, 20 training jobs on 20 GPU nodes, 8 read streams each, single
  runs of 27 to 50 s):
  - Hits: 12.3 to 12.4 GB/s for 1 to 8 client nodes, from the CXL store and
    from a DRAM store alike. Training with every file from the cache runs at
    the memory-resident rate (331.3 against 331.4 samples/s in total).
  - On never-read data the 20 jobs wait 17.3% directly from BeeGFS (274.5
    samples/s). Through the cache with all misses: 260.2 (95% of direct).
    With half of each job's bytes in the cache: 331.4, 0.4% waiting.
  - The same full rate was reached without the cache whenever the data had
    been read before: half of each job's files read twice by another job
    10 minutes earlier (331.4), a quarter read twice 50 minutes earlier
    (331.3), and all of them read once, by the cache server, 95 minutes
    earlier (330.7, 0.5% waiting). Before the last run a
    single-thread probe had read those files at cold latency (21 ms per
    file, 0.14 GB/s); the expectation that the 20 jobs would stall was
    refuted, and the cause was not examined.
  - On a shared pool that the storage servers held in memory, the cache cut
    the bytes read from BeeGFS from 178 GB to 55 GB per run (known order,
    36% capacity) and training speed did not change (331 samples/s with
    every policy and without the cache).
- So the evidence on RQ3 is: the cache removes waiting for never-read data
  when it holds half of the bytes, costs nothing visible on hits and 5% on
  misses; **no gain over direct BeeGFS on reused data has been measured**.
  The statement above that once-read data is cold after 60 minutes rests on
  single-thread latency; what 20 jobs get from such data was full speed in
  the one run that tested it. Whether a full-dataset epoch is a cold epoch
  for 20 jobs is open again.
- **[Observed]** (`2026-11-18-large-working-set-reuse`): what the storage
  does with reused data at training concurrency.
  - The storage is 14 single hard disks. To 160 read streams they give 0.66
    to 0.78 GB/s of cold bytes, set by the slowest server; bytes in the
    servers' memory come on top. Measured at cold shares of 1, 0.5, and
    0.33: 0.66, 1.46, 2.20 GB/s. 20 jobs (0.96 GB/s) are limited only when
    more than 0.7 to 0.85 of their bytes are cold.
  - One thread times a file by its slowest chunk on four disks. The "cold"
    probe before the 95-minute re-read of 2026-11-17 was a half-resident
    cohort (**[Analytical]** from its latencies), which answers the open
    point above.
  - 20 emulated jobs on the full shared dataset, direct BeeGFS, one hour:
    0.8% waiting from minute 10, cold share 0.57 to 0.62. A full-dataset
    epoch is not a cold epoch for 20 jobs: the earlier inference from
    single-thread residency was wrong. 26 jobs: 3% waiting, the slowest
    server's disk 84% busy.
  - Under that load a server holds the last 6 to 10 minutes of what it
    read; data read twice lasts a few minutes longer, not hours.
- So at the job counts this cluster's GPUs allow, direct BeeGFS leaves a
  cache nothing to remove on reused data. **No end-to-end gain of the cache
  has been measured, and with 20 jobs none can be.**
- Not measured: any cache configuration on the full dataset; demand above
  the storage limit (more than about 26 jobs of this GPU class); the 256
  and 512 GiB capacities; real training on the full dataset.

## Hypotheses

The current working hypotheses are R1 to R13 in
[research_idea.md](research_idea.md); R9 to R13 were added with the
refinement of 2026-11-24 and concern lookahead and prefetching. The hypotheses recorded on 2026-11-11
and their state:

| ID | Hypothesis (2026-11-11) | State |
|---|---|---|
| H1 | When the whole dataset is retained, storage reads after the first epoch drop to near zero; the open part is the training time saved. | Unchanged, untested. |
| H2 | Caching improves training throughput only when the storage path cannot sustain the consumption rate. | **[Observed]** for the upper bound (2026-11-16): memory-resident data changes throughput where supply is below demand (sequential reader, 2.16 times) and not where it is above (parallel reader, 1.000). No cache was involved. **[Observed]** with the cache (`2026-11-17-cxl-cache-integration`, 20 jobs): 1.21 times where the jobs would otherwise read never-read data (half of the bytes from the cache), 1.000 where the storage servers serve the data fast (a warm shared pool; data read 10 to 95 minutes before). **[Observed]** (2026-11-18): on the full shared dataset the storage sustains 20 jobs (0.8% waiting), so the condition for a gain is not met at that job count; it begins to be met at 26 jobs (3% waiting). |
| H3 | For a single job that reads each file once per epoch, future-aware replacement does not avoid more storage reads than static pinning. | **[Simulated]** Confirmed on a real single-job trace. |
| H4 | When several jobs share a dataset and a cache, the single-job bound no longer applies and policy choice may matter. | **[Simulated]** Confirmed on a real two-job trace and on synthetic compositions. |

## Analytical notes

Both notes are **[Analytical]**: derived by reasoning from stated assumptions.

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

Consequences:

- For this access pattern, no replacement policy avoids more storage reads per
  epoch than static pinning. The fraction of all bytes that can avoid storage
  over a run is at most `(E-1)/E * min(1, C/D)`.
- The mean reuse distance of N-1 is a property of any once-per-epoch pattern.
  The short reuse distances at epoch boundaries do not create extra hits,
  because holding those files displaces others one for one.
- The bound does not apply when its assumptions break: several jobs or ranks
  sharing one dataset and cache, sampling with replacement, epochs that cover
  only part of the dataset, or workloads that mix datasets.

Check: **[Simulated]** in `2026-11-12-cache-policy-replay` the bound held exactly on a real single-job
trace: static pinning and the future-aware reference served `2c/3` of the
bytes over three epochs at every capacity fraction c. The same statement was
published as practice before (CoorDL's cache never evicts), so it is a
baseline fact, not a contribution.

### A2. Bandwidth-deficit model

A first-order model for when caching can matter. Let R be the rate at which
training consumes data and B the storage read rate the job can sustain.

- If `B >= R`, storage can keep up given enough read parallelism and lookahead.
  Expect little benefit from caching.
- If `B < R`, and a fraction f of the bytes is served from the cache with hits
  spread evenly over the epoch, storage has to supply `(1 - f) * R`. Data
  loading keeps up when `f >= 1 - B/R`.

Illustration with **[Historical]** c33 numbers, not a prediction for any
system: with R of about 0.21 GB/s and one BeeGFS stream at about 0.064 GB/s,
the model gives f of at least about 0.70. With eight streams (about 0.52 GB/s)
there is no deficit.

With several jobs on shared storage, R is the sum over the jobs. The model
ignores burstiness, decoding cost, the bandwidth of the cache path itself, and
the first epoch. Its purpose is to choose experiment conditions, not to
predict results.

## Revision log

| Date | Change | Reason |
|---|---|---|
| 2026-11-11 | Initial RQ1-RQ4, H1-H4, notes A1-A2 recorded | Repository setup |
| 2026-11-12 | RQ1-RQ4 replaced by RQ1 (reuse opportunity), RQ2 (online reuse-aware cache management), RQ3 (distributed CXL training acceleration). The earlier RQ1 and RQ3 are covered by the new RQ3, the earlier RQ2 by the new RQ2, and the earlier RQ4 by the new RQ1 and RQ3. H3 and H4 marked as confirmed in simulation. Working hypotheses moved to `research_idea.md`. | New task definition by the user (target: a FAST/ATC paper on online reuse-aware caching with a remote CXL cache), and the first trace replay (`2026-11-12-cache-policy-replay`) |
| 2026-11-12 | Evidence from `2026-11-12-cross-job-known-order` added to RQ1 and RQ2; the statement that the progress-based estimator loses to LRU corrected. Working hypotheses now R1 to R8: R3 (announced order approaches the offline reference) supported, R4 (progress alone is enough) not supported, R7 (keeping each job's order is required) and R8 (real job mixes have unequal speeds or partial overlap) added as the assumptions the idea now rests on. The questions themselves are unchanged. | Second trace replay: known-order policy, per-job caches, a Quiver-inspired replay, and an upper bound, on a real two-job trace with reconstructed job identity |
| 2026-11-12 | First hardware evidence added to RQ3 (direct BeeGFS path). The questions are unchanged. | `2026-11-12-remote-cxl-data-path`, interim |
| 2026-11-15 | Hardware evidence on the remote DRAM and CXL data path, admission, interference, and an I/O replay added to RQ3. The questions are unchanged; the user fixed the research idea and RQ1 to RQ3 on 2026-11-12 (see decisions.md, D005). | `2026-11-12-remote-cxl-data-path`, completed |
| 2026-11-16 | Evidence from `2026-11-16-workload-io-validation` added to RQ1 and RQ2 (a second real two-job trace, with logged job identity and unequal speeds) and to RQ3 (first training measurements: storage does not limit a parallel reader on the available GPUs; thresholds for when it would). H2 marked as observed for the memory-resident upper bound. The questions are unchanged. | Workload selection and training I/O validation |
| 2026-11-16 | Evidence from `2026-11-16-loader-gpu-scaling` added: RQ3 (waiting for storage against read streams and job count; only single-stream jobs wait) and RQ1, RQ2 (a real eight-job trace). The "readers" of the earlier entry corrected to interleave cycle lengths. The questions are unchanged. | Reader and GPU scaling experiment |
| 2026-11-24 | Evening, second part of `2026-11-24-large-scale-cache-evaluation` (fixes and checks before the comparison): RQ2 evidence updated (re-keying pass 0.07 to 0.09 s with unchanged decisions; the start-up cost; the transient of the hit share after a common cold start, simulated); RQ3 evidence updated (40-job check). No question or hypothesis changed. |
| 2026-11-24 | Evidence from the preliminary validation and pilot of `2026-11-24-large-scale-cache-evaluation` added: RQ2 (the mechanism is correct at full scale; two-epoch lookahead changes no decision on an epoch of 8.7 hours; the policy's cost and its re-keying pass; the prefetch window corrected; prefetches late at the storage limit), RQ3 (40 emulated jobs stall on cold storage; an empty cache is 11% behind direct BeeGFS in three minutes; the miss path through one BeeGFS client; identical sequences in consecutive configurations are not independent). The comparison of the configurations has not been run. The questions are unchanged. | Large-scale evaluation, preliminary validation and pilot |
| 2026-11-24 | Evidence from `2026-11-24-two-epoch-lookahead-prefetch` added: RQ1 (two-epoch announcement is available and exact; what it adds), RQ2 (two-epoch lookahead and a minimal prefetcher implemented; hit rates and prefetch accounting with four training jobs), RQ3 (prefetching removes latency-bound waiting; a loader with eight streams does too; no effect of the longer lookahead on waiting; simulated: none under a bandwidth deficit). The questions are unchanged. | Two-epoch lookahead and prefetching experiment |
| 2026-11-24 | The three questions refined by the user: RQ1 "Cross-Job Reuse Characterization" now includes the availability of future access information and what two-epoch lookahead adds; RQ2 "Reuse-Aware Cache Management" extends the existing known-order management with two-epoch lookahead, asynchronous prefetching, and joint management of prefetching, admission, and eviction; RQ3 "CXL-Based Training Acceleration" asks for the combined mechanism and for the separate contributions of replacement and prefetching. Earlier wordings kept under each question. Direction and number of questions unchanged; no evidence added or changed; hypotheses R9 to R13 added in research_idea.md. | Refinement given by the user; decision D009 |
| 2026-11-18 | Evidence from `2026-11-18-large-working-set-reuse` added: RQ3 (how the storage supplies reused data to many readers; 20 jobs on the full shared dataset do not wait; the inference that a full-dataset epoch is cold withdrawn), RQ1 (reuse and a storage stall do not coexist at the available job counts), RQ2 (simulated: known order's lead in cache hit rate does not reach the disks when the storage servers keep 600 GiB), H2. The questions are unchanged. | Storage residency and large working set experiment |
| 2026-11-17 | Evidence from `2026-11-17-cxl-cache-integration` added: RQ2 (the policies in a running cache with 20 real training jobs, decisions equal to the simulator), RQ3 (first measurements with the cache in the path; full rate with half of the bytes from the cache on never-read data; no gain over direct BeeGFS on reused data, including a direct re-read after 95 minutes that did not stall), RQ1 (reuse and slow storage not observed for the same bytes), H2. The questions are unchanged. | Cache integration experiment |
| 2026-11-17 | Evidence from `2026-11-17-multi-gpu-io-saturation` added to RQ3 (where shared storage limits real concurrent training: about 12 jobs with two read streams, 16 to 17 with eight; 20 jobs wait 20% to 26%) and to RQ1, RQ2 (a real twenty-job trace). The questions are unchanged. | Multi-GPU saturation experiment |
