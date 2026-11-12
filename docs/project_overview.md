# Project Overview

Status: initial framing, 2026-11-11. No experiment has been run in this
repository and no CXL caching system exists yet. Nothing in this document is a
performance result of this project.

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
| Whether the model runs on c28's GPU | **[Observed]** in a six-step check: yes at batch size 2, no at 4 |
| BeeGFS client page-cache behaviour on c28 | **[Observed]** on 16 files: not populated; re-reads still fast |
| CXL latency and bandwidth on c28 | Unknown, **[Planned]** |
| Whether CosmoFlow data loading is storage-bound, and when | Unknown, **[Planned]** as [E001](experiments/001-training-io-characterization-plan.md) |
| Cache policy comparison under limited capacity | Unknown, **[Planned]** |
| Whether CXL caching speeds up training | Unknown, **[Planned]** |

## 9. Constraints that shape the research

- CXL memory (c28) and the A100 GPU used for earlier training runs (c33) are in
  different machines. Their results cannot be combined into one end-to-end
  claim. c28 has an 8 GB RTX 4060 Ti.
- c28's GPU ran the CosmoFlow model only at batch size 1 and 2, at an indicated
  rate of roughly one sixth of the A100's historical rate. A single training
  job on c28 therefore creates little data demand.
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
