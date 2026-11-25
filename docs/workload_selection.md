# Workload Selection

Status: 2026-11-16, revised after experiment
`2026-11-16-workload-io-validation` ([experiments/INDEX.md](experiments/INDEX.md)).
The first version (2026-11-12) compared candidates on six criteria without
any measurement of training. This version uses the twelve criteria of the
task of 2026-11-16 and the first training measurements.

The selection is made on the criteria, not on which cache policy looks good.
Evidence labels are defined in [project_overview.md](project_overview.md).
Numbers taken from other projects' configuration files are marked
**[Published configuration]**; they are not measurements of this project.

## 1. Criteria

1. Dataset size.
2. File size distribution.
3. Storage read bandwidth demand.
4. Metadata and random I/O demand.
5. Reuse across epochs.
6. Reuse across independent training jobs.
7. Ability to preserve a known upcoming access order.
8. Feasibility on the available GPU nodes.
9. Expected GPU sensitivity to data stalls.
10. Ease of obtaining reproducible real traces.
11. Availability of datasets and implementations here.
12. Suitability for evaluating a limited-capacity shared CXL cache.

## 2. What the candidates are compared against

**[Observed]** unless marked, with the experiment that measured it.

| Quantity | Value | Source |
|---|---|---|
| DRAM of the cache server c28 | 755 GiB | [hardware/c28.md](../hardware/c28.md) |
| CXL memory this user can open on c28 | 512 GiB (1,024 GiB installed) | [hardware/c28.md](../hardware/c28.md) |
| Memory of the BeeGFS storage servers | 93 GiB each on the three inspected, almost all of it file cache; about 630 GiB for seven **[Analytical]** | [hardware/c39.md](../hardware/c39.md), section 5 |
| BeeGFS, first read, one client | 0.07 GB/s (1 thread) to 0.73 GB/s (32 threads) | `2026-11-12-remote-cxl-data-path` |
| BeeGFS, recently read, one client | 2.3 to 12.3 GB/s | same |
| Remote DRAM or CXL through Mercury | 10 to 12.3 GB/s | same |
| Client link | 12.5 GB/s (100 Gb/s) | same |

A cache of file bytes can shorten training only if training waits for
storage and the data is not already in the storage servers' memory.

## 3. Candidates

| | Workload | Dataset size | Files | Available here |
|---|---|---|---|---|
| A | Full CosmoFlow, several jobs or one | 1,519.75 GB training set **[Observed]**, plus 189.9 GB validation and 95.0 GB test | 524,288 gzip TFRecord files, one sample each, 2.37 to 3.35 MB, mean 2.90 MB, standard deviation 0.08 MB **[Observed]** | data, code, and environment: yes |
| B | MLPerf Storage through DLIO: 3D U-Net, ResNet-50, CosmoFlow profile | generated; by rule at least five times the client memory | 3D U-Net: one 146.6 MB sample per `.npz` file (standard deviation 68 MB). ResNet-50: 1,251 samples of 114.7 kB per TFRecord file. CosmoFlow: 524,288 records of 2.83 MB **[Published configuration]** | tool not installed; data would have to be generated (625 GiB or more for a 125 GiB client) |
| C | Image or video training (ImageNet-class and larger) | ImageNet-1k is 135 to 154 GB in the papers cited in [related_work.md](related_work.md); larger sets were not checked | many small files, or shards | no dataset found; the BeeGFS top level holds only per-user directories, which were not searched |
| D | LLM or multimodal training | tokenized text: large; image-text sets: larger still (not checked) | token arrays, or shards | no |

Considered earlier and unchanged: importance sampling in the style of SHADE
(only CIFAR-10 here, far smaller than any cache) and DeepCAM (no data here).

## 4. Storage demand per accelerator

File bytes per second that one accelerator consumes.

| Workload and accelerator | Samples/s | Bytes per sample | GB/s | Label |
|---|---|---|---|---|
| CosmoFlow, RTX 2060 SUPER, batch 2 | 10.6 | 2.90 MB | 0.031 | **[Observed]** training on c38 (training step alone: 11.0) |
| CosmoFlow, RTX 4060 Ti, batch 2 | 16.9 | 2.90 MB | 0.049 | **[Observed]** training on c28 (training step alone: 17.0; c24 at batch 4: 16.2) |
| CosmoFlow, A100, batch 4 | 74.9 | 2.90 MB | 0.217 | **[Historical]** c33, 2026-10-27 |
| CosmoFlow profile, emulated A100 | 181 | 2.83 MB | 0.51 | **[Published configuration]**, MLPerf Storage v1.0 |
| 3D U-Net, emulated A100 | 11.0 | 146.6 MB | 1.61 | **[Published configuration]** |
| ResNet-50, emulated A100 | 920 | 114.7 kB | 0.105 | **[Published configuration]** |
| Tokenized text, any GPU | 10^4 to 10^5 tokens/s assumed | 2 to 4 bytes per token | below 0.001 | **[Analytical]**, assumed ranges |

Reading:

- One accelerator of this cluster asks for 0.03 to 0.05 GB/s of CosmoFlow
  data. One client's first-read supply through the real input pipeline is
  0.32 to 0.45 GB/s with 8 to 32 readers (section 6). Storage is far from
  binding.
- The published CosmoFlow profile assumes an accelerator 2.4 times faster
  than the A100 run recorded for this project. The two are not comparable
  without knowing the model settings behind the profile, which were not
  checked.
- 3D U-Net is the only profile in which a single emulated accelerator asks
  for more than one client's first-read supply. Its computation is a sleep
  and its data is synthetic.
- Tokenized text is three or more orders of magnitude below any storage
  limit measured here.

## 5. Assessment against the criteria

| Criterion | A. Full CosmoFlow | B. MLPerf Storage, 3D U-Net | C. Image or video | D. LLM or multimodal |
|---|---|---|---|---|
| 1 Dataset size | 1,415 GiB: 2.8 times the usable CXL memory, 1.9 times c28's DRAM, 2.2 times the storage servers' memory | set by rule above client memory; freely scalable | ImageNet-1k fits in every memory tier here; larger sets unknown here | text: fits or is streamed once; image-text: beyond memory |
| 2 File sizes | uniform, 2.9 MB | 146.6 MB mean, wide spread | about 0.1 MB per image, or shards | shards |
| 3 Read demand | low per GPU here (0.03 to 0.05 GB/s), 0.22 GB/s per A100 | 1.6 GB/s per emulated A100 | about 0.1 GB/s per emulated A100 for ResNet-50 | text: negligible; image-text: like C **[Assumption]** |
| 4 Metadata and random I/O | one open and one whole-file read per sample, files in random order: 524,288 opens per epoch | few large files | many opens if images are single files | sequential shard reads **[Assumption]** |
| 5 Reuse across epochs | every file once per epoch | every file once per epoch, 5 epochs | every file once per epoch | text pretraining: about one pass **[Assumption]**; multimodal: several epochs |
| 6 Reuse across jobs | yes: every job on the dataset reads every file each epoch; two real two-job traces | only if several instances are pointed at one dataset; that is our construction, not the benchmark's | yes in hyperparameter search (CoorDL's setting) | not examined |
| 7 Known order | yes with an explicit seeded permutation (the harness does this); the benchmark's own tf.data shuffle is reproducible but not exposed | seeded shuffles; deriving the order from DLIO was not tried | yes for file reads with a seeded sampler; augmentation happens after the read | shard order with a seeded sampler **[Assumption]** |
| 8 Feasible on GPUs here | yes: batch 2 on 8 GiB, batch 4 on 16 GiB | needs no GPU | small models only | no at any realistic scale |
| 9 Sensitivity to data stalls | **[Observed]** none with a parallel reader on these GPUs (0.4% waiting); 60% waiting with the benchmark's sequential reader on first reads | by construction: the pass mark is 90% accelerator utilization | decoding on the CPU is the known stall source in published work | text: none expected |
| 10 Real traces | easy: the harness logs every file pull with job identity | DLIO logs; not tried | would need an instrumented loader | not possible here |
| 11 Availability | everything is here | install and generate | download and registration | none |
| 12 Fit for a limited shared cache | capacity pressure in every tier; no replacement opportunity for one job, a real one for several jobs | capacity pressure by construction; the same single-job limit | no capacity pressure at ImageNet-1k size | text: no I/O problem to solve |

## 6. Measured evidence for CosmoFlow

**[Observed]** in `2026-11-16-workload-io-validation` on c28 (RTX 4060 Ti,
batch size 2, process restricted to 16 cores, the core count of this
cluster's GPU nodes). Medians of three repetitions on fresh files.

Samples per second. "First read" files had never been read by this project;
"re-read" is the same files minutes later; "memory" is a tmpfs copy.

| | BeeGFS, first read | BeeGFS, re-read | Host memory |
|---|---|---|---|
| Training, parallel reader (8 readers, 4 parse threads, prefetch) | 16.86 | 16.85 | 16.86 |
| Training, the benchmark's sequential reader | 6.79 | 14.01 | 14.68 |
| Input pipeline alone, 1 reader | 19.4 | 32.1 | 32.1 |
| Input pipeline alone, 4 readers | 70.8 | 119.8 | 120.0 |
| Input pipeline alone, 8 readers | 111.8 | 204.9 | 208.7 |
| Input pipeline alone, 16 readers | 155.1 | 208.1 | 209.1 |
| Input pipeline alone, 32 readers | 149.9 | 203.3 | 203.8 |
| Input pipeline alone, 64 readers on 64 cores (one run) | 223.6 | 538.5 | 523.2 |

The training step alone, with the batch copied from host memory as in
training, runs at 17.01 samples/s.

**Correction (2026-11-16, later the same day).** The reader counts in this
table are cycle lengths of tf.data's parallel interleave. That pipeline
reads ahead: it keeps up to three times as many files open at once (24 for
the 8-reader configuration), as measured in `2026-11-16-loader-gpu-scaling`.
The numbers stand; "8 readers" means up to 24 concurrent read streams. With
exactly one stream, asynchronous and with prefetch, training does wait for
cold storage; that experiment reports it.

What follows from it:

1. **Parallel reader: not storage-bound.** Training waits for data 0.4% of
   the time from every source and runs at 99% of the compute-only rate.
   Data in host memory gains nothing (factor 1.000).
2. **Benchmark's reader: storage-bound on first reads.** 60% of the time is
   spent waiting; data in memory is 2.16 times faster. Against recently read
   BeeGFS data memory gains 5%; the remaining wait is CPU work in a
   single-threaded pipeline. A parallel reader removes all of it without a
   cache, so parallel reading with prefetch is the baseline a cache must beat.
3. **The CPU caps what a file cache can add on a 16-core node.** The pipeline
   costs 68 to 76 ms of CPU time per sample, 31 ms of it decompression, and
   delivers at most 209 samples/s from memory. First reads deliver 112 to
   155. With 64 cores the cap is 523 samples/s against 224 from first reads.
4. **First-read supply is one limit shared by all clients.** One, two, and
   four client nodes with 8 threads each read 0.36, 0.58, and 0.74 GB/s in
   total, the values a single client reached with the same number of streams
   the day before. At 32 streams that is about 255 samples/s for all jobs
   together. More streams were not measured across clients.
5. **The storage servers do not keep an epoch's data.** Files read once were
   all served from memory after 15 minutes and all from disk after 60
   minutes; files read twice in quick succession were still in memory after
   two hours and gone after four; files read 18 to 19 hours earlier were
   cold, however often they had been read then. These hours included this
   project's own reads (60 GB of first reads in the first hour, about 190 GB
   more before the four-hour probe). **[Analytical]** A full-dataset epoch takes 8.6 hours on
   an RTX 4060 Ti (1.9 hours at the A100's historical rate), and the dataset
   is 2.2 times the storage servers' memory. Every epoch of a full-dataset
   job therefore reads from disk.
6. **Cross-job reuse appears in a second real trace.** Two jobs on two GPU
   nodes (16.2 and 10.6 samples/s, second job three minutes later, job
   identity logged). **[Simulated]** At a cache of 20% of the data: static
   pinning 18.0%, progress-aware 25.1%, known order 30.9%, offline reference
   34.3%, Quiver-inspired replay 28.4%. The margin above static pinning is
   smaller than on the earlier trace (offline reference 46.2%), and the
   order-changing replay, far ahead there, is level or behind here.

### Reader and job scaling (`2026-11-16-loader-gpu-scaling`)

**[Observed]**, real training on cold files of the full training set, batch
size 2. "Streams" are files read and decompressed at a time, counted
exactly.

| Configuration | Per job, cold data | Waiting | Per job, memory |
|---|---|---|---|
| One GPU (c28), 1 stream | 12.5 samples/s | 26% | 16.86 |
| One GPU (c28), 2 to 16 streams | 16.85 | 0.4% | 16.85 |
| 8 jobs on 8 GPU nodes, baseline reader (up to 24 streams each) | 16.87 | 0.4% | 16.83 |
| 8 jobs, 2 or 4 streams each | 16.88 | 0.4% | 16.85 |
| 1 job on a GPU node, 1 stream | 11.2 | 34% | 16.84 |
| 8 jobs, 1 stream each | 9.9 | 41.5% | 16.84 |

- A job waits for storage only with exactly one read stream. A second
  stream removes the wait.
- Eight jobs draw 0.39 GB/s of cold data, about half of the shared supply,
  and do not slow each other with two or more streams. With one stream each,
  sharing costs 11%.
- The candidate configurations for the cache experiment follow from this:
  one read stream per job (storage-sensitive), eight such jobs (shared
  demand), and the baseline reader as the comparison a cache result has to
  be shown against.

### Up to 20 concurrent jobs (`2026-11-17-multi-gpu-io-saturation`)

**[Observed]** Real training, one job per GPU node (RTX 4060 Ti), each job
on its own never-read files of the full training set, exactly 2 or 8 files
read at a time. Values on nodes at full CPU clock; one run per row, 12 jobs
twice.

| Jobs | Read streams per job | Per job, cold data | Waiting | All jobs, share of linear | Per job, memory |
|---|---|---|---|---|---|
| 1, 7, 9 | 2 | 16.2 samples/s | 0.2% | 98% to 100% | 16.1 to 16.3 |
| 12 | 2 | 13.5 (first run of the day); 16.2 (repetition) | 17%; 0.3% | 78%; 93% | 16.1 |
| 15 | 2 | 14.1 | 13% | 83% | 16.1 |
| 20 | 2 | 12.2 | 25% | 73% | 16.2 |
| 15 | 8 | 16.2 | 0.4% | 101% | 16.2 |
| 20 | 8 | 13.4 | 20% | 81% | 16.2 |

- Storage becomes the bottleneck of real training at about 16 to 17 jobs of
  this GPU class when each job has enough read streams: the jobs get at most
  0.76 GB/s of first reads, and 20 jobs need 0.95 GB/s. With two streams per
  job, waiting starts at about 12 jobs.
- At 20 jobs more read streams do not remove the wait. Memory-resident input
  and re-read data do, at every job count.
- This is the first configuration in which a loader with enough streams
  waits for storage in real training: 20 jobs, 1.24 times slower than from
  memory in aggregate (1.38 times with two streams per job).
- Limits: single short runs; the 12-job pair disagrees; every first read is
  cold by construction, which a shared dataset read by 20 jobs is not
  entirely.

## 7. Selection

**Primary: full CosmoFlow with several concurrent jobs on the shared
dataset.** Reasons:

- It is the only candidate whose data, code, and environment are here, and
  whose real traces can be recorded with job identity.
- Its data exceeds every memory tier: the usable CXL memory, c28's DRAM, and
  the storage servers' memory. A full-dataset epoch is a cold epoch.
- The order of each job is known in advance, and two real two-job traces
  show cross-job reuse that static pinning cannot use.

Its weakness, measured: on this cluster's GPUs one job needs 0.03 to 0.05
GB/s, and with a parallel reader it does not wait for storage even when the
data is cold. **[Analytical]** Storage becomes the limit when the summed
demand of the jobs exceeds the shared first-read supply, about 255 samples/s:
15 jobs at the RTX 4060 Ti rate, or 3.4 at the A100 rate. On a single
16-core node the window between first-read supply and the CPU cap is narrow.

**Alternative: MLPerf Storage 3D U-Net through DLIO.** The profile with the
highest byte demand: one emulated A100 asks for 1.6 GB/s, more than the
first-read supply of the whole file system at 32 streams, and the data is
sized above memory by rule. It is a storage benchmark: computation is a
sleep, data is synthetic, and several jobs on one dataset would be our own
construction. It needs an installation and several hundred GiB of generated
data on shared storage, both subject to approval. Its results could be stated
as supported accelerators at the benchmark's utilization mark, never as
training speedup.

**Not selected.**

- MLPerf Storage ResNet-50 and ImageNet-class training: low byte demand per
  accelerator, no capacity pressure at ImageNet-1k size, no dataset here.
- Tokenized-text LLM training: no storage demand to speak of, and typically
  little reuse.
- Multimodal training: plausible in principle, cannot be run or traced here.
- CosmoFlow as one job on many GPUs: no replacement opportunity (static
  pinning is optimal); it remains the baseline workload for capacity.

**Raising the demand of the primary workload.** The real input pipeline can
be driven by a consumer that takes batches at a fixed rate (`--pace` in
[benchmarks/train_io](../benchmarks/train_io/README.md)), the method MLPerf
Storage uses, with real data and real decoding cost. That reaches demand
levels the GPUs here cannot, and its results are I/O results with emulated
consumption. It is an option for the evaluation, recorded as proposed in
[decisions.md](decisions.md) (D006), not a change of workload.

## 8. Gaps

- No real training run in which storage is the limit with two or more read
  streams per job. Eight concurrent jobs were measured and do not get there;
  the estimate is about 15 jobs of this GPU class.
- The A100's waiting time was never measured; only its throughput is known,
  historically (63.5 samples/s in the first epoch against 74.9 later).
- First-read supply beyond 32 streams, and its variation between days and
  under other users' load.
- Residency on a quiet day. Today's one-hour result includes this
  experiment's own reads.
- Real traces with more than two jobs, with partial dataset overlap, or from
  another workload.
- How often jobs share a dataset on real clusters: still taken from other
  papers' motivation.
- Candidates B, C, and D were assessed from published configurations and
  arithmetic. None was run.
