# Research Idea: Cross-Job Reuse-Aware Caching in CXL Memory for Distributed Training

Status: 2026-11-24. The user refined the idea on that day: the direction and
the three research questions stay, and the mechanism is extended from
known-order replacement to **known-order replacement with two-epoch lookahead
and asynchronous prefetching** (sections 1, 3, 4, and 9). The evidence in
section 2 and in the rows R1 to R8 is that of the experiments up to
`2026-11-18-large-working-set-reuse`, listed in
[experiments/INDEX.md](experiments/INDEX.md), and is unchanged by the
refinement; their summaries are kept locally and are not in the Git
repository. This document states the idea, what the evidence says, and the
refined version. A minimal cache exists since 2026-11-17
([system/](../system/README.md)); since the evening of 2026-11-24 it has
two-epoch lookahead and a minimal prefetcher, measured at small scale
(`2026-11-24-two-epoch-lookahead-prefetch`; rows R9 to R13 and section 9).
No claim that the cache speeds up training over direct BeeGFS on reused
data is supported yet (R5).

Evidence labels are defined in [project_overview.md](project_overview.md).
Sources for statements about other work are in [related_work.md](related_work.md).

## 1. The idea as given

Envisioned system: several independent GPU training jobs read their datasets
through a shared remote cache that holds data in CXL memory. Clients and
server talk over Mercury RPC. BeeGFS is the persistent store. The cache
manages its limited capacity by exploiting reuse across the jobs.

Current hypothesis, as given: when multiple training jobs access overlapping
datasets at different speeds and in different orders, coordinating cache
admission and eviction using their known upcoming access sequences can improve
cache effectiveness over conventional caching policies. **[Hypothesis]**

### Refinement of 2026-11-24

Fixed direction: **Online Reuse-Aware CXL Caching for Distributed Training.**
The goal is a shared CXL-based training data cache that exploits cross-job
reuse and future access sequences provided by the applications, to reduce
storage stalls and accelerate distributed training.

The mechanism is extended, the project is not changed:

1. **Known-order replacement** (existing): cached files are ranked by the
   earliest estimated next use across jobs; files needed sooner are kept.
2. **Two-epoch lookahead** (new): a job announces its upcoming file order two
   epochs ahead instead of for the rest of the current epoch only.
3. **Asynchronous prefetching** (new): the cache fetches upcoming files that
   it does not hold from BeeGFS into CXL memory before a job asks for them.
4. **Joint management** (new): prefetching, admission, and eviction are
   decided together under the limited CXL capacity.

The combination is a **[Hypothesis]**. Section 4 describes it and section 9
says which parts exist.

Three kinds of information are kept apart throughout:

| Kind | Meaning |
|---|---|
| Observed history | past accesses, completed epochs, each job's progress |
| Online-visible future | the part of its own upcoming file order that a job announces: until 2026-11-24 the rest of its current epoch, in the refined mechanism two epochs ahead. A loader with a seeded shuffle can compute the order of any later epoch at run time, so this is information a running job has. No future timestamps: when an announced access will happen is estimated from positions and measured rates. |
| Offline oracle | the complete recorded trace, including the true time of every access. A reference only. |

## 2. What the evidence says

All numbers are **[Simulated]**: byte hit rates from replaying access traces.
They are byte volumes, not training times.

### One job

Static pinning is optimal. Policies with future knowledge collapse onto it,
and history-based policies are worse. This holds on real single-job traces and
agrees with note A1 in [research_questions.md](research_questions.md) and with
published practice (CoorDL never evicts).

### Two jobs on one dataset, real trace

The trace is a real two-job run (2 jobs, 9,216 files, 5 epochs). The job of
every access was reconstructed from the jobs' seeds and checked against the
logged times.

| Policy | Information | 5% | 20% | 80% |
|---|---|---|---|---|
| LRU | history | 9.1 | 16.6 | 61.7 |
| Static pinned | none | 4.5 | 17.9 | 72.3 |
| Per-job static caches, same total size | history | 2.0 | 8.0 | 32.1 |
| Epoch progress only (`reuse-epoch`) | which jobs have read a file in their current epoch | 11.5 | 32.0 | 80.4 |
| Known order, rest of the current epoch | announced order, positions, measured rates | 25.3 | 43.5 | 81.8 |
| Known order, whole run | the same for the whole run | 26.5 | 46.0 | 82.2 |
| Offline reference | complete trace | 26.6 | 46.2 | 82.2 |
| Quiver-inspired replay (changes each job's order) | which jobs have consumed what | 52.9 | 62.0 | 62.0 |

Columns are cache capacities as a share of the data; values are the share of
bytes served from the cache.

### Two jobs on one dataset, second real trace (2026-11-16)

Recorded by this project: two jobs on two GPU nodes, 3,072 training and 384
validation files, five epochs each, job identity logged. The jobs run at
16.2 and 10.6 samples/s because their GPUs differ, and the second starts
three minutes later. The faster job ends first; 23% of the accesses come
after that.

| Policy | 5% | 20% | 80% |
|---|---|---|---|
| LRU | 1.5 | 6.3 | 49.8 |
| Static pinned | 4.5 | 18.0 | 72.0 |
| Epoch progress only (`reuse-epoch`) | 7.6 | 25.1 | 77.1 |
| Known order, rest of the current epoch | 14.0 | 30.9 | 77.3 |
| Known order, whole run | 14.7 | 33.8 | 78.0 |
| Offline reference | 15.2 | 34.3 | 78.0 |
| Quiver-inspired replay (changes each job's order) | 14.2 | 28.4 | 28.4 |

The order of the policies is the same as on the first trace. The room above
static pinning is smaller (16 points at 20% capacity instead of 28). The
order-changing replay is no longer far ahead: level at 5% capacity, 5 points
ahead at 10%, behind from 20% upward. This is one trace, and the replay is an
approximation of Quiver.

### Eight jobs on one dataset, real trace (2026-11-16)

Recorded by `2026-11-16-loader-gpu-scaling`: eight jobs on eight identical
GPU nodes, same start, 2,048 training and 256 validation files, three epochs
each, job identity logged.

| Policy | 5% | 20% | 80% |
|---|---|---|---|
| LRU | 12.4 | 27.3 | 82.9 |
| Static pinned | 4.8 | 19.1 | 76.6 |
| Per-job static caches, same total size | 0.4 | 1.7 | 6.7 |
| Epoch progress only (`reuse-epoch`) | 9.6 | 30.6 | 87.0 |
| Known order, rest of the current epoch | 34.3 | 57.3 | 91.7 |
| Known order, whole run | 34.5 | 58.3 | 92.8 |
| Offline reference | 34.7 | 58.6 | 92.8 |
| Quiver-inspired replay (changes each job's order) | 62.3 | 88.3 | 88.3 |

With more jobs the room above static pinning grows (39 points at 20%
capacity) and the known-order policy takes nearly all of it. The jobs have
equal speed and start together, the case in which the order-changing replay
is strongest, and it is far ahead here.

### Twenty jobs on one dataset, real trace (2026-11-17)

Recorded by `2026-11-17-multi-gpu-io-saturation`: twenty jobs on twenty GPU
nodes, same start, the same 2,048 training and 256 validation files as the
eight-job trace, three epochs each, exactly two files read at a time per
job, job identity logged. 138,240 accesses; 98% of them follow a read of the
same file by another job, a median of 4.1 s earlier, with 0.58 times the
dataset read in between.

| Policy | 5% | 20% | 80% |
|---|---|---|---|
| LRU | 9.8 | 27.5 | 86.3 |
| Static pinned | 4.9 | 19.6 | 78.7 |
| Per-job static caches, same total size | 0.1 | 0.7 | 2.7 |
| Epoch progress only (`reuse-epoch`) | 7.9 | 29.5 | 87.8 |
| Known order, rest of the current epoch | 33.9 | 59.5 | 95.2 |
| Known order, whole run | 34.0 | 59.8 | 95.5 |
| Offline reference | 34.4 | 60.0 | 95.5 |
| Quiver-inspired replay (changes each job's order) | 62.5 | 41.6 | 41.6 |

### Twenty jobs through the running cache (2026-11-17)

**[Observed]** `2026-11-17-cxl-cache-integration`: twenty real training jobs
on twenty GPU nodes, 8 read streams each, three epochs over a shared pool of
1,024 files, reading through the cache server (store in CXL memory). Share
of bytes served from the cache, counted by the server:

| Policy | 18% of the pool | 36% of the pool |
|---|---|---|
| LRU | 17.2 | 34.7 |
| Static pinned | 17.7 | 35.5 |
| Epoch progress only (`reuse-epoch`) | 26.0 | 46.4 |
| Known order, rest of the current epoch | 50.6 | 68.9 |

These are measured hit rates of a real system, and they equal the
simulator's on the same traces access by access. Training speed was the same
in all runs and without the cache (331 samples/s in total), because the
storage servers held that pool in memory.

**[Simulated]** The picture of the eight-job trace repeats with twenty jobs:
known order is within a point of the offline reference and 30 points above
progress-only and LRU at 20% capacity. The Quiver-inspired replay is ahead
at 5% and 10% capacity and falls to 41.6% above that on this trace, which
was not examined. **[Observed]** in the same experiment, real training:
twenty jobs that read cold data wait 20% to 26% of the time, so this is the
first job count at which the bytes a cache serves could shorten training on
this cluster. `2026-11-17-cxl-cache-integration` took that step from bytes
to time in part: see R5 below.

### What follows from the replay experiments

1. **Announced order is worth much more than history.** With each job's order
   for the rest of its current epoch, the cache recovers 83% to 96% of the gap
   between static pinning and the offline reference on the real trace. With
   the order of the whole run it is within 0.2 points of the reference.
   Progress alone recovers 32% to 82%.
2. **A shared cache beats per-job caches** of the same total size by a wide
   margin.
3. **The benefit holds in synthetic compositions** with 2, 4, and 8 jobs,
   speed ratios up to 1:4, staggered starts, partial dataset overlap, and a
   job that leaves.
4. **Little lookahead is needed.** A window of a quarter of an epoch gives at
   least 86% of the gain; a window of half an epoch that continues across the
   epoch boundary matches full knowledge at small and medium capacity.
5. **The policy tolerates imperfect information**: a rate estimate wrong by a
   factor of two costs about one point, progress seen every 512 accesses costs
   nothing measurable. It does need a smoothed rate estimate.
6. **An order-changing baseline is far ahead at small capacity.** A
   Quiver-inspired replay, in which all jobs consume the dataset chunk by
   chunk and take cached data first, serves 53% to 62% of the bytes on the
   real trace with a cache of 5% to 20%. That is more than the offline
   reference, because it changes the jobs' orders, which no order-preserving
   policy can do. In the synthetic compositions the known-order policy is
   ahead when jobs differ in speed by a factor of two or more (from 10% to
   20% capacity upward), when their datasets overlap only partly (from 5% to
   20% upward), and at large capacity. At 5% capacity the replay is still
   ahead or level in most of these cases.

## 3. Refined problem

**Several independent training jobs read overlapping datasets through one
shared cache that is smaller than the data. Which data should the cache hold
at each moment if every job keeps its own sampling order?**

Since 2026-11-24 the question has a second half: **and which data that it
does not hold should it fetch ahead of the jobs, and when?** Replacement
decides what stays; prefetching decides what arrives before it is asked for.

The restriction to unchanged orders is now the core of the problem statement,
and it has to be justified, because changing the order is the stronger lever
where it is acceptable. Reasons it may not be acceptable, each of which is an
**[Assumption]** to be checked, not a result:

- Unmodified training scripts and frameworks: an order-preserving cache needs
  only to be told the order, an order-changing one has to control the sampler.
- Jobs with different datasets, samplers, or speeds cannot be made to travel
  through the data together.
- Chunk-restricted shuffling changes the sampling distribution. Quiver reports
  no accuracy loss on two models; nothing is known for scientific workloads
  such as CosmoFlow.

## 4. The combined mechanism (refined 2026-11-24)

A description of what is to be built and evaluated, not a design: structure
and parameters are open (section 8).

| Part | What it does | Information it uses |
|---|---|---|
| Two-epoch lookahead | Every job has announced its file order two epochs ahead. Read here as: at every moment the cache knows the rest of the job's current epoch and the whole of the next one. | The job's own shuffle, computed by the job. Online-visible, not an oracle. |
| Known-order replacement | Unchanged rule: rank cached files by the earliest estimated next use across jobs, evict the farthest, admit a file only if it is needed sooner than every victim. With the longer lookahead the rank of a file no longer loses its basis when a job nears the end of an epoch. | Announced order, each job's position and measured rate. |
| Asynchronous prefetching | The cache server reads announced files that it does not hold from BeeGFS into a DRAM buffer and copies them into CXL memory (the admission path that was measured), ahead of the request. A request that finds the file is a hit; one that arrives while the fetch is running waits only for the rest of it. | The same announced order and rates: which uncached file is needed next, and how long until then. |
| Joint management | One ranking for all three decisions. A prefetched file takes a slot only if its estimated next use is sooner than that of what it displaces; prefetch reads and reads for misses share the storage; a prefetched file must not be evicted before its use by a later prefetch. | The ranking above, the cache's capacity, and what the storage can deliver. |

Two store modes are kept apart:

- **Evictable store**: the prototype's own slots in a devdax range. All four
  parts apply.
- **Non-evictable famfs mode**: the CXL tier of the earlier FitCache code
  ([related_work.md](related_work.md)) packs cached files into one
  pre-allocated file on a famfs mount and never frees space. Replacement
  does not exist there. What remains of the mechanism is the order in which
  the store is filled and prefetching ahead of first use, until the store is
  full. It is reported as its own mode and never mixed with results of the
  evictable store. **[Historical]** for the mode itself (read in the earlier
  code, not run by this project); this project has no famfs mount it may
  use.

What the earlier findings say about prefetching, before anything is built:

- **A prefetch has a deadline.** It hides the read only if it is complete
  when the file is requested. A late prefetch shortens the wait; a prefetch
  of a file that is evicted before use, or never used, costs storage and
  CXL traffic for nothing.
- **Lookahead gives time, not a guarantee.** With the rest of the current
  epoch as the horizon, nothing is known about a job's first reads of the
  next epoch until that epoch starts. Two-epoch lookahead removes that
  blind spot. Whether a transfer finishes in time still depends on what the
  storage delivers at that moment.
- **Prefetching cannot remove a sustained bandwidth deficit.**
  **[Observed]** (`2026-11-18-large-working-set-reuse`): the storage gives
  0.66 to 0.86 GB/s of bytes that are not in its servers' memory, however
  many streams ask. If the jobs' demand for such bytes stays above that,
  reading earlier only moves the queue. Only bytes that are reused from the
  cache are not read again.
- **Where it could help: latency, not bandwidth.** **[Observed]** Jobs with
  few read streams wait although the storage is below its limit: 26% to
  41.5% of the time with one stream per job
  (`2026-11-16-loader-gpu-scaling`), 25% with 20 jobs of two streams at 0.69
  GB/s (`2026-11-17-multi-gpu-io-saturation`). **[Historical]** An earlier
  exploratory study outside this repository suggested that prefetching
  hides most I/O latency when storage bandwidth exceeds the sustained
  consumption. Uneven demand is the other candidate: epoch boundaries,
  staggered jobs, validation passes.
- **The strong baseline is a well-configured loader.** **[Observed]** A
  second read stream removed the wait of up to eight jobs without any cache.
  Prefetching by the cache has to be compared with a job that simply reads
  with more streams.
- **The storage servers cache too.** **[Observed]** Under load a server
  keeps the last 6 to 10 minutes of what it read. A prefetch brings a file
  into CXL memory once and the cache can keep it until its announced use,
  however far away; whether that difference is worth anything is open.
- **Cache hits are not the result.** A prefetched file counts as a hit. The
  measure stays GPU data waiting and training throughput.

## 5. Refined hypotheses

| ID | Hypothesis | Status |
|---|---|---|
| R1 | Concurrent jobs on a shared dataset create reuse that neither static pinning nor recency- or frequency-based policies can exploit. | **[Simulated]** Supported on two real two-job traces, one real eight-job trace, and synthetic compositions. On the trace with unequal speeds the room is smaller; with eight jobs it is larger. |
| R2 | The information that predicts this reuse is each job's position in its epoch, not per-file history. | **[Simulated]** Supported. |
| R3 | If each job announces its upcoming order, a shared cache can approach the offline reference online, without touching the order. | **[Simulated]** Supported: within 0.2 points on the real trace with whole-run knowledge, 83% to 96% of the gap with current-epoch knowledge. **[Simulated]** caveat (`2026-11-18-large-working-set-reuse`): that is the cache's own hit rate. With a storage-server memory of 600 GiB modelled behind a 256 GiB cache on the full dataset, known order (49% of the bytes) leaves the disks no less to do than static pinning (15%), because it serves the re-reads the servers would have served; it is ahead when the servers keep 300 GiB or less. Not measured. |
| R4 | Without the order, per-job epoch progress is enough to get most of the benefit. | **[Simulated]** Not supported: a quarter to two thirds of the gap at 20% capacity and below, and worse than static pinning when datasets overlap only partly. |
| R5 | Fewer storage reads shorten training when several jobs load shared storage. | **[Hypothesis]** Untested. Depends on storage being the bottleneck. **[Observed]** on the direct BeeGFS path (`2026-11-12-remote-cxl-data-path`): first reads are 16 to 24 times slower than reads of data the storage servers still hold in memory, and the latter arrive at the client's link limit. The condition for R5 is therefore data that is not in the storage servers' memory: datasets beyond that memory, or eviction by other load. **[Observed]** (`2026-11-16-workload-io-validation`): that condition is met for the full dataset, since once-read data left the servers' memory within an hour and the dataset is 2.2 times their memory. The other condition is not met on the GPUs here: one job with a parallel reader does not wait for cold storage (0.4% of the time), and data in host memory gains nothing. First-read supply is shared, 0.74 GB/s at 32 streams. **[Analytical]** Storage limits training from about 15 concurrent jobs on these GPUs, or four A100-class GPUs. **[Observed]** (`2026-11-16-loader-gpu-scaling`): eight concurrent jobs on eight GPU nodes do not wait for cold storage with two or more read streams per job and draw 0.39 GB/s, about half of the shared supply. Jobs with exactly one read stream do wait (26% to 41.5%), and memory-resident data is then 1.35 to 1.70 times faster; a second stream removes the wait without a cache. **[Observed]** with the cache in the path (`2026-11-17-cxl-cache-integration`, 20 jobs, 8 read streams each): supported where the reads avoided are of never-read data (274.5 samples/s directly, 331.4 with half of the bytes from the cache, the memory-resident rate); not supported where the storage servers serve the data fast, which was every case of reuse in that experiment: a warm shared pool (178 GB or 55 GB read from BeeGFS, 331 samples/s either way) and direct reads of data read twice 10 and 50 minutes before or once 95 minutes before (full rate each time, the last against the expectation). A gain of the cache over direct BeeGFS on reused data is not measured; it needs reused data that the storage no longer serves fast. **[Observed]** (`2026-11-18-large-working-set-reuse`): that condition is not reached with 20 jobs even on the full shared dataset (0.8% waiting from direct BeeGFS, the storage servers' memory serving 40% of the bytes); it begins at 26 jobs (3% waiting). The storage stalls 20 jobs only when more than 0.7 to 0.85 of their bytes come from disk. **[Simulated]** From about 32 jobs a 256 GiB cache would bring the disks' load back under their limit. |
| R6 | CXL memory is a good medium for this cache: its capacity raises the hit rate, and a remote CXL cache performs close to remote DRAM. | Second half **[Observed]** (`2026-11-12-remote-cxl-data-path`): remote CXL equals remote DRAM for retrieval and for admission, both limited by the 100 Gb/s link, provided data enters CXL through the CPU and not by NIC writes (those are capped at 4.2 GB/s and starve reads). **[Observed]** in the cache itself (`2026-11-17-cxl-cache-integration`): the same server with its store in CXL memory or in DRAM gives the same hit throughput (12.3 to 12.4 GB/s, 1 to 8 clients), the same hit rates, and the same training speed. First half: hit rates grow with capacity in real training on a small pool (known order 50.6% at 18%, 68.9% at 36%); capacities beyond what DRAM offers (256 and 512 GiB) were not run. |
| R7 | Keeping each job's order is a requirement in practice, so that the order-changing approach is not available. | **[Assumption]** Unexamined. The value of the known-order policy over a Quiver-style design rests on it wherever jobs have equal speed. |
| R8 | In real job mixes, speeds differ and datasets overlap only partly often enough for the order-preserving policy to be the better choice on hit rate as well. | **[Simulated]** One real trace with unequal speeds now exists (speed ratio 1.5, produced by two different GPUs): the known-order policy is ahead of the Quiver-inspired replay from 20% capacity upward and behind by 5 points at 10%. How common such mixes are is still unknown; partial overlap is still synthetic only. |
| R9 | Two-epoch lookahead is available at run time, and what it adds is time for prefetching across epoch boundaries rather than hit rate for replacement. | **[Hypothesis]** for prefetching. For replacement **[Simulated]**, as a bracket only: the simulator has no two-epoch mode; between knowing the rest of the current epoch and knowing the whole run, the byte hit rate at 20% capacity differs by 2.5 and 2.9 points on the two real two-job traces, 1.0 on the eight-job trace, and 0.3 on the twenty-job trace. Availability: the training harness derives every epoch's order from the seed, so later epochs can be announced; not implemented. **Update, `2026-11-24-two-epoch-lookahead-prefetch`:** implemented. **[Observed]** announcement one epoch early is exact and leaves the order untouched. **[Simulated]** for replacement it equals whole-run knowledge on the three CosmoFlow traces (0.1 to 2.9 points over one-epoch lookahead). For prefetching the "time across epoch boundaries" turned out to be worth very little: the prefetcher catches up within a few requests after an epoch is announced; on hardware 661 cut windows against none, no difference in waiting, 2% fewer bytes from BeeGFS. Supported as stated for availability; the benefit is small. |
| R10 | Asynchronous prefetching into the shared cache removes data stalls that come from read latency while the storage has bandwidth to spare: jobs with few read streams, epoch boundaries, uneven demand. | **[Hypothesis]** No prefetching exists in the simulator or the cache. The regimes exist (**[Observed]**, see section 4). **Update, `2026-11-24-two-epoch-lookahead-prefetch`:** **[Observed]** supported for the one-stream case: four training jobs on their own cold files waited 39.5% directly, 18.7% through the cache without prefetching, 0.5% with it; 99.9% of the prefetches were complete in time. Epoch boundaries and uneven demand: no effect seen at this scale. |
| R11 | Prefetching does not remove stalls that come from a sustained deficit of storage bandwidth; there only reuse from the cache helps. | **[Analytical]** from the measured supply rule (cold limit divided by the share of bytes from disk). Not tested with a prefetcher. **Update:** **[Simulated]** with the prefetcher in a scheduling model fitted to this project's measurements: 40 jobs on the full dataset wait 24.4% with and without prefetching. Not run on hardware. **Update, pilot of `2026-11-24-large-scale-cache-evaluation`:** **[Observed]** with 40 emulated jobs at the storage limit and an empty cache, 35% of the prefetches were complete when the job asked, and the jobs received 11% fewer samples than directly from BeeGFS in three minutes. Prefetching against no prefetching was not compared there. |
| R12 | Managed together, replacement and prefetching do better than either alone, and their contributions can be measured separately. | **[Hypothesis]** **Update, `2026-11-24-two-epoch-lookahead-prefetch`:** the contributions separate cleanly on hardware (replacement decides what is served again without a storage read: 47% of the bytes; prefetching decides whether the rest arrives before it is asked for: 99.9%). "Better together" has a cost: with prefetching the cache read 8% to 11% more from BeeGFS than with replacement alone, because prefetched files take slots from files kept for reuse. Prefetching without known-order replacement was not run. |
| R13 | The gain of prefetching survives the comparison with a loader that reads with enough streams of its own. | **[Hypothesis]**, and the main risk: **[Observed]** more read streams in the job removed the stall in every case measured so far in which the storage was below its limit. **Update, `2026-11-24-two-epoch-lookahead-prefetch`:** **[Observed]** not supported at this scale: a direct job with eight read streams waited 0.5%, the same as the one-stream job behind the prefetching cache. |

## 6. Potential contributions

1. **A characterization of cross-job reuse in training**, with real traces:
   when replacement matters, what information predicts reuse, and how much of
   the offline optimum each kind of information recovers. In hand, in
   simulation.
2. **An order-preserving known-order policy for a cache shared by independent
   jobs**: jobs announce a bounded part of their order, the cache ranks files
   by the earliest estimated next use across jobs. In hand as a simulated
   policy, close to the offline reference, and since 2026-11-17 inside the
   cache prototype with the same decisions. Its claim to novelty is the
   combination of cross-job sharing with unchanged orders; the mechanism
   itself is simple.
3. **A remote CXL cache server** that makes the policy usable by unmodified
   jobs, compared with direct BeeGFS, remote DRAM, and a Quiver-style design.
   In hand as a prototype since 2026-11-17: correct, its decisions equal to
   the simulator's, the CXL store as fast as a DRAM store. No end-to-end gain
   over direct BeeGFS on reused data measured.
4. **Joint known-order replacement and asynchronous prefetching** with
   two-epoch lookahead in that shared cache (refinement of 2026-11-24): one
   ranking decides what is kept and what is fetched ahead. Not built, not
   simulated. Prefetching from a known order is established for one job
   (NoPFS); what is not is doing it in a cache shared by several jobs,
   together with replacement under limited capacity.

What the evidence does not support: a claim that this policy has a higher hit
rate than existing cross-job coordination in general. Where jobs travel
together, order-changing coordination wins.

## 7. What would end or redirect the idea

| Finding | Consequence |
|---|---|
| Changing the sample order turns out to be acceptable for the target workloads, and jobs mostly run at similar speeds | Build on order-changing coordination. The known-order policy is at most a component for the cases it does not cover. |
| Real traces with unequal speeds or partial overlap do not reproduce the synthetic results | R8 fails. The policy has no regime of its own. |
| Storage is not the bottleneck in any realistic multi-job setting here | Fewer reads do not buy time. No end-to-end result. Status 2026-11-16: not the bottleneck for one job on the available GPUs; the threshold is about 15 concurrent jobs (analytical). The user fixed the direction on 2026-11-12; the consequence drawn is the evaluation setup proposed in [decisions.md](decisions.md), D006. |
| Remote CXL performs like remote DRAM, and DRAM of that size is available | "Why CXL" has no answer beyond cost. |
| Sharing a dataset between concurrent jobs is rare on the target systems | The setting is not worth a system. |
| A loader with enough read streams removes every stall that prefetching could hide, and the only stalls left are sustained bandwidth deficits | Prefetching adds nothing end to end (R13 fails, R11 holds). The mechanism falls back to replacement. |
| Prefetches seldom finish before their deadline when the storage is loaded, or evict data that is needed sooner | Joint management does not work as described (R12 fails); prefetching would have to be restricted to times of spare bandwidth. |
| With the storage servers' memory behind the cache, the combined mechanism leaves the disks as much to do as static pinning (as the simulation of 2026-11-18 says for replacement alone) | The end-to-end case would rest on systems whose storage servers keep less than the cache; to be stated as a finding. |

## 8. Open design questions (not decided)

- How a job announces its order: through the sampler's seed, an explicit list,
  or a wrapped data loader. The announced order has to be the read order.
- Cache unit: compressed file or decoded sample. **[Observed]** The input
  pipeline costs about 73 ms of CPU per sample, 31 ms of it decompression,
  and caps a 16-core node at 209 samples/s. A cache of compressed files does
  not lift that cap.
- Whether order-changing coordination and the known-order policy can be
  combined: coordination where jobs agree to it, known-order ranking for the
  rest.
- How the short-distance reuse of unshuffled passes (validation data) is kept.
- Write traffic: the known-order policy admits 23 to 26 times as many bytes as
  static pinning at 20% capacity on the real trace, about half of all bytes
  the jobs request. **[Observed]** (`2026-11-12-remote-cxl-data-path`): this
  did not cost time in an I/O replay, and admissions into CXL do not disturb
  reads, as long as the CPU writes the data. NIC writes into CXL memory must
  be avoided (decisions.md, D005).
- The miss path. In the measured design a miss goes through the cache server
  and is slower than a direct BeeGFS read when storage is warm.
- One server port carries at most 12.3 GB/s for all clients together.

Added with the refinement of 2026-11-24:

- What "two epochs ahead" means exactly: the rest of the current epoch plus
  the next one (the reading used here), or two full epochs beyond the
  current one; and when a job announces the next epoch (at registration, at
  the start of each epoch, or continuously).
- How far ahead of a request a prefetch starts, and how many run at once.
  Too early costs capacity and risks eviction before use; too late misses
  the deadline.
- How prefetch reads and reads for misses share the storage, and how the
  cache learns what the storage can deliver at the moment (the storage
  servers' counters are readable; the cache's own read times are simpler).
- Whether a prefetched file is protected until its announced use, and for
  how long if the job falls behind or stops.
- Which process prefetches. In the prototype every miss is read by the
  server machine, a single BeeGFS client; prefetching through the same path
  adds to that load.
- How the estimate of a job's rate, on which every deadline rests, is kept
  good through stalls.
- What the non-evictable famfs mode needs: an order of filling and a rule
  for when to stop, since nothing can be taken back.

## 9. What exists, what is measured, what is hypothetical (2026-11-24)

| Part | Exists | Measured or simulated | Not yet |
|---|---|---|---|
| Known-order replacement, rest of the current epoch | Simulator (`known:epoch`); cache prototype (the same policy class behind the server) | **[Simulated]** 75% to 99% of the gap between static pinning and the offline reference on the four real traces of 2 to 20 jobs. **[Observed]** in the running cache with 20 training jobs: 50.6% and 68.9% of the bytes at 18% and 36% capacity, decisions equal to the simulator | A measured gain in training time |
| Longer lookahead | Simulator: the whole run (`known:all`), windows of a number of accesses (`known:<w>`), and since 2026-11-24 two epochs (`known:epoch2`); the same mode in the cache, with the next epoch announced one epoch early by the client and the harness | **[Simulated]** two-epoch lookahead equals whole-run knowledge on the three CosmoFlow traces (0.1 to 2.9 points over one-epoch lookahead). **[Observed]** exact and order-preserving in training | Loaders without a seeded order |
| Asynchronous prefetching | Since 2026-11-24 a minimal prefetcher in the cache (background reads behind demand work, a cap on reads in flight, a window of announced accesses per job). A scheduling model with time and a storage model exists as a script of that experiment, not in the simulator | **[Observed]**, four training jobs: one-stream jobs on cold files wait 0.5% instead of 39.5%; prefetches complete in time 99.9% to 100%; 8% to 11% more bytes from BeeGFS than replacement alone. **[Simulated]** no effect under a bandwidth deficit | More than four jobs; storage at its limit on hardware; tuning; a comparison at a consumer faster than these GPUs |
| Joint management | Minimal: a prefetch candidate goes through the unchanged ranked admission; a cap on prefetched files not yet used | **[Observed]** no prefetched file was evicted unused in the hardware runs | Behaviour under pressure (many demand reads, a full cache of sooner-needed files); a rule for the share of the capacity that prefetched files may hold |
| Data path for admission and for hits | Prototype: storage read into DRAM, CPU copy into CXL memory after the response; hits read by the NIC from CXL memory | **[Observed]** remote CXL equals remote DRAM (12.3 GB/s); admissions do not disturb reads; misses through the server cost 5% under saturation | The same path driven by a prefetcher |
| What the storage does | — | **[Observed]** cold limit 0.66 to 0.86 GB/s set by one server; supply = limit divided by the share of bytes from disk; 20 jobs on the full shared dataset do not wait, 26 begin to; latency-bound waiting with one or two read streams per job | Any of this with prefetching in the path |
| Non-evictable famfs mode | In the earlier FitCache code, outside this repository | Not by this project | Whether and where this project can run it (no famfs mount it may use) |

The experiments that are needed next are in
[experiment_plan.md](experiment_plan.md), "Extension: two-epoch lookahead and
asynchronous prefetching".

## 10. Non-goals

- A learned predictor. A simple rule with announced order is already close to
  the offline reference.
- Any claim about CXL or about training time from simulation.
- Prefetching as a way around a storage system that is too slow for the
  sustained demand: it cannot be one.
- Changing the order in which a job reads, for replacement or for
  prefetching.
