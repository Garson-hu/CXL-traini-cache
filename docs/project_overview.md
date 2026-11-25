# Project Overview

Status: initial framing of 2026-11-11; the table in section 8 was last
updated on 2026-11-24. A minimal CXL cache exists since 2026-11-17
([system/](../system/README.md)). On 2026-11-24 the user refined the
research idea: the direction stays, and the mechanism is extended with
two-epoch lookahead and asynchronous prefetching (section 1 and
[research_idea.md](research_idea.md)). The framing sections contain no
performance results of this project; measured results are in the
experiments listed in [experiments/INDEX.md](experiments/INDEX.md).

## Evidence labels

Research documents in this repository tag claims with one of these labels.

| Label | Meaning |
|---|---|
| **[Observed]** | Measured or inspected in this project, with a recorded source |
| **[Historical]** | Reported from earlier work outside this repository; not reproduced here |
| **[Simulated]** | Output of a simulator or trace replay, not a hardware measurement |
| **[Analytical]** | Derived by reasoning from stated assumptions; not measured |
| **[Hypothesis]** | A claim we intend to test |
| **[Assumption]** | Taken as given for now; unverified |
| **[Planned]** | Future work |

## 1. Central question

How can CXL memory be effectively used and managed as a training data cache to
reduce storage I/O overhead and improve end-to-end training performance?

Fixed direction (2026-11-12, restated by the user on 2026-11-24): **Online
Reuse-Aware CXL Caching for Distributed Training.** A shared CXL-based
training data cache that exploits cross-job reuse and future access
sequences provided by the applications, to reduce storage stalls and
accelerate distributed training.

Mechanism under study since 2026-11-24: the existing known-order
replacement (keep what is needed soonest), jobs that announce their file
order two epochs ahead, asynchronous prefetching of upcoming files from
BeeGFS into CXL memory, and joint management of prefetching, admission, and
eviction. Replacement exists and has been measured. Since the evening of
2026-11-24 the other three parts exist in a minimal form and have been
measured with four training jobs (`2026-11-24-two-epoch-lookahead-prefetch`);
what they are worth at scale is still a **[Hypothesis]**. The full-scale
comparison is prepared (`2026-11-24-large-scale-cache-evaluation`:
validation and pilot) and not run.

## 2. Why training data caching matters

Multi-epoch training reads the same dataset repeatedly. When the dataset lives
on a shared parallel file system, every epoch pays the storage read cost again
unless the data is retained somewhere closer to the training process.

Whether that cost limits training depends on how the storage read rate compares
with the rate at which training consumes data:

- **[Historical]** In earlier CosmoFlow runs on c33, training consumed about
  0.21 GB/s. BeeGFS delivered about 0.064 GB/s with one read stream, 0.52 GB/s
  with eight, and 0.82 GB/s with thirty-two.
- **[Historical]** An earlier exploratory prefetching study suggested that
  storage prefetching can hide most I/O latency when storage bandwidth exceeds
  the sustained consumption rate.

Taken together: a single read stream could not have kept up with that workload,
while parallel reads could. A cache is therefore not automatically useful. It
matters when the storage path cannot sustain the consumption rate, for example
with limited read parallelism, contended shared storage, faster or more GPUs,
or several jobs reading at once. **[Hypothesis]**

Two ways in which the storage path fails to keep up have to be told apart,
because the refined mechanism addresses them differently (measured since;
see section 8):

- **Latency**: the storage has bandwidth to spare, but the job does not ask
  for enough at once (one or two read streams). Reading ahead of the job,
  which is what prefetching does, can hide this; so can more read streams in
  the job.
- **Bandwidth**: the jobs together ask for more bytes from disk than the
  storage can deliver for a sustained time. Reading earlier does not help.
  Only bytes that are served again from a cache are not read again.

## 3. Why CXL memory

CXL memory expanders add byte-addressable memory capacity beyond the DIMM slots.

- **[Observed]** c28 exposes 1024 GiB of CXL memory as three DAX devices,
  next to about 755 GiB of DRAM (read-only inspection, see
  [hardware/c28.md](../hardware/c28.md)).
- **[Assumption]** CXL memory has higher latency and lower bandwidth than local
  DRAM. The actual numbers on c28 have not been measured for this project.
- **[Hypothesis]** Holding cached training data in CXL memory leaves DRAM for
  the training process, the data-loading workers, and the framework, and allows
  a cache larger than DRAM alone would.

A cache hit served from CXL memory is not free. The data still has to be read
or copied at CXL speed and then decoded. Whether the CXL path is fast enough,
and how it behaves under concurrent access, is a measurement question for
Phase 3 of the [experiment plan](experiment_plan.md).

## 4. Why cross-epoch reuse may be useful

- **[Historical]** The CosmoFlow configuration used so far has 61,440 TFRecord
  files (about 178 GB), three epochs, a new shuffled file order each epoch, and
  one access per file per epoch. There is no reuse within an epoch. All reuse
  is across epochs.
- **[Historical]** Reuse distances between consecutive accesses to the same
  file ranged from 60 to 122,689 intervening file reads, with a mean of 61,439.
- **[Analytical]** A mean of N-1 is what any once-per-epoch access pattern
  produces for N = 61,440 files, so the mean alone says nothing about policy
  opportunity. The spread exists because a file read late in one epoch can be
  read early in the next.

The spread in reuse distance is what motivates looking at reuse-aware caching.
It does not show that such policies help. See the analytical note in
[research_questions.md](research_questions.md), which argues that for a single
job with once-per-epoch access no replacement policy can avoid more storage
reads than static pinning.

## 5. Role of CXL as a large-capacity cache

Conceptual data path:

```text
Persistent Storage (BeeGFS / NVMe)
              |
              v
      CXL Training Data Cache
              |
              v
       CPU / DataLoader
              |
              v
          GPU Training
```

This diagram is conceptual. The real path may involve DRAM buffers, memory
mapping, decoding, and prefetching. No implementation architecture has been
chosen, and none should be chosen before measurements justify it.

CXL memory is a cache tier only. Persistent copies of datasets stay on BeeGFS.

## 6. Why limited cache capacity matters

If the whole dataset fits in the cache, the cache fills during the first epoch
and replacement decisions stop mattering. The management problem only exists
when capacity is smaller than the data that would benefit from caching.

- **[Observed]** On c28 the 178 GB CosmoFlow dataset is smaller than both the
  DRAM (about 755 GiB) and the CXL capacity (1024 GiB).
- Consequence: with this dataset on this machine, capacity pressure does not
  arise naturally. Studying cache management requires deliberately constrained
  capacity budgets, larger datasets, or several jobs sharing the cache. Such
  constraints have to be realistic and stated explicitly, not chosen to make a
  policy look good.
- The DRAM page cache (or a tmpfs copy) is the obvious competitor. A CXL cache
  has to be compared against DRAM caching under the same, controlled memory
  budget.
- **[Analytical]** The files are gzip-compressed at a ratio of about 5.8. The
  61,440 samples decoded to `int16` are about 1.03 TB (960 GiB), which exceeds
  c28's DRAM but not DRAM plus CXL. A cache of decoded samples would face
  capacity pressure naturally. Whether decoding is worth caching depends on
  whether CPU work limits the input pipeline, which is not yet measured.

## 7. Goal: end-to-end training time

The metric that counts is end-to-end training performance: epoch time, training
throughput, and time the GPU spends waiting for data. Storage reads avoided and
cache hit ratio are intermediate metrics. A higher hit ratio does not guarantee
faster training, because the bottleneck may be decoding, the GPU, or the cache
path itself.

## 8. What is and is not known

| Topic | Status |
|---|---|
| CosmoFlow dataset, code, and input pipeline | **[Observed]** by inspection, see [workload_configs/cosmoflow/README.md](../workload_configs/cosmoflow/README.md) |
| CosmoFlow access pattern and reuse distances | **[Historical]**, to be re-derived from a trace in this project |
| BeeGFS bandwidth and training consumption rate | **[Historical]**: bandwidth from c33 and c28, consumption on c33 only |
| c28 hardware inventory | **[Observed]** by read-only inspection |
| Whether the model runs on c28's GPU | **[Observed]**: yes at batch size 2, no at 4. Training step alone 17.0 samples/s; training 16.86 (`2026-11-16-workload-io-validation`) |
| BeeGFS client page-cache behaviour on c28 | **[Observed]** on 16 files: not populated; re-reads still fast |
| CXL copy rates on c28, and the remote data path through Mercury | **[Observed]** in `2026-11-12-remote-cxl-data-path` ([experiments/INDEX.md](experiments/INDEX.md), [hardware/c28.md](../hardware/c28.md)). CXL latency is not measured. |
| Known-order replacement in a shared cache | **[Simulated]** on four real traces and **[Observed]** in the cache prototype with 20 training jobs: two to three times the bytes of static pinning or LRU from the cache (`2026-11-12-cross-job-known-order`, `2026-11-17-cxl-cache-integration`) |
| Two-epoch lookahead | **[Observed]** (`2026-11-24-two-epoch-lookahead-prefetch`): a seeded job announces its next epoch one epoch early, exactly, without changing its order. **[Simulated]**: 0.1 to 2.9 points of byte hit rate over one-epoch lookahead for replacement. **[Observed]**: no difference in waiting when used for prefetching, 2% fewer bytes from BeeGFS |
| Asynchronous prefetching into the cache, and its joint management with replacement | Minimal implementation since 2026-11-24. **[Observed]** with four training jobs: removes the waiting of one-stream jobs on cold files (39.5% to 0.5%), as do eight read streams in the job; reads 8% to 11% more from BeeGFS than replacement alone. **[Simulated]**: no effect when the storage's bandwidth is exceeded. **[Observed]** in a three-minute pilot with 40 emulated jobs at the storage limit (`2026-11-24-large-scale-cache-evaluation`): 35% of the prefetches in time. Not compared with no prefetching at that scale |
| The cache at full-dataset scale (524,288 files, 256 GiB store, 40 jobs) | **[Observed]** (`2026-11-24-large-scale-cache-evaluation`, preliminary validation and pilot): correct (decisions, bytes, the whole store); the miss path through one machine is fast enough; 40 emulated jobs stall on cold storage (53% waiting); an empty cache with prefetching is 11% behind direct BeeGFS in its first three minutes. The comparison of static pinning, known order, and prefetching at that demand has **not** been run **Evening of 2026-11-24:** the periodic re-keying of the known-order policy, 4.6 to 4.8 s at this scale, is computed with arrays in 0.07 to 0.09 s with unchanged decisions (checked against the simulator on 806,400 accesses); the client works on nodes with several RDMA devices; 40 jobs start and run through the comparison's scripts. **[Simulated]**: after a common cold start known order's hit share rises as 1 − exp(−n/N) for about N requests, so a 20-minute run ends before its steady state. The comparison is still not run. |
| Whether CosmoFlow data loading is storage-bound, and when | **[Observed]** on c28 (`2026-11-16-workload-io-validation`, [experiments/INDEX.md](experiments/INDEX.md)): not with a parallel reader (0.4% waiting from cold BeeGFS, no gain from data in host memory); yes with the benchmark's sequential reader on cold data (60% waiting). **[Analytical]**: storage would limit about 15 concurrent jobs on these GPUs. Not measured on an A100. **[Observed]** (`2026-11-16-loader-gpu-scaling`): the parallel reader of that experiment reads up to 24 files at once; with exactly one read stream, still asynchronous, a job waits 26% of the time on cold data and two streams remove that; eight concurrent jobs with two or more streams do not wait. **[Observed]** (`2026-11-17-multi-gpu-io-saturation`, real training on up to 20 GPU nodes): with two read streams per job, jobs wait from about 12 concurrent jobs on (13% at 15 jobs, 25% at 20); with eight streams they do not wait at 15 jobs and wait 20% at 20, where the storage delivers 0.76 GB/s against a demand of 0.95 GB/s. Memory-resident input and re-read data restore the full rate in every case (1.24 to 1.38 times in aggregate at 20 jobs). |
| How long BeeGFS serves read data from the storage servers' memory | **[Observed]** on one afternoon, under this project's own read load, by single-thread latency: once-read files warm after 15 minutes, cold after 60; twice-read files warm after two hours, cold after four; files read 18 to 19 hours earlier cold. **[Observed]** on 2026-11-17: files read once 95 minutes before were cold by that probe and still came back at the full rate for 20 training jobs; the probe does not say what many readers get. **[Observed]** on 2026-11-18 (`2026-11-18-large-working-set-reuse`, disk counters on the servers): data read twice stays for a day while a server has room; data read once stays until newer data has filled the server's free memory and inactive list; under 20 to 26 jobs reading the full dataset a server holds the last 6 to 10 minutes, whatever was read before |
| Full CosmoFlow training set size | **[Observed]**: 524,288 files, 1,519.75 GB |
| Cache policy comparison under limited capacity | **[Simulated]** in two trace-replay experiments ([experiments/INDEX.md](experiments/INDEX.md)). **[Observed]** in the running cache (`2026-11-17-cxl-cache-integration`): with 20 real training jobs on a shared pool, known order served 50.6% and 68.9% of the bytes at 18% and 36% capacity, progress-aware 26.0% and 46.4%, LRU 17.2% and 34.7%, static pinning 17.7% and 35.5%; the server's decisions equal the simulator's |
| Whether CXL caching speeds up training | **[Observed]** in part (`2026-11-17-cxl-cache-integration`, 20 jobs, reduced scale): against never-read data yes (331.4 against 274.5 samples/s with half of the bytes from the cache); against direct BeeGFS on reused data no gain measured, because BeeGFS served data read 10 to 95 minutes before at the full rate. **[Observed]** on 2026-11-18 (`2026-11-18-large-working-set-reuse`): 20 emulated jobs sharing the full dataset do not wait for direct BeeGFS (0.8%), so a cache has nothing to gain at that scale on this cluster; a stall begins at 26 jobs. No cache run on the full dataset; **[Simulated]** from about 32 jobs a cache would matter |

## 9. Constraints that shape the research

- CXL memory (c28) and the A100 GPU used for earlier training runs (c33) are in
  different machines. Their results cannot be combined into one end-to-end
  claim. c28 has an 8 GB RTX 4060 Ti.
- c28's GPU runs the CosmoFlow model only at batch size 1 and 2, at 16.9
  samples/s in training (measured 2026-11-16), 23% of the A100's historical
  rate. A single training job on c28 creates little data demand:
  0.05 GB/s.
- CXL access on c28: since 2026-11-11 the devdax devices `dax0.0` and `dax1.0`
  (512 GiB) can be opened by this user through group `kmem`. There is no file
  system on them. `dax2.0` is root-only and in use. Onlining CXL memory as
  system RAM needs root. See [hardware/c28.md](../hardware/c28.md).
- Proposed mechanisms must address a bottleneck that measurements have shown.

## 10. Non-goals

- LLM serving and KV cache research.
- Using CXL memory as persistent dataset storage.
- Designing a complex cache manager before a simple baseline has been shown to
  be insufficient.

Related documents: [research_questions.md](research_questions.md),
[experiment_plan.md](experiment_plan.md), [related_work.md](related_work.md),
[decisions.md](decisions.md), [storage.md](storage.md).
