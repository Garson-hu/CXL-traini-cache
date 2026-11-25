# Related Work and Novelty Analysis

Status: 2026-11-12. The six papers in section 2 were checked against their
full text on 2026-11-12 by an automated reading of the primary PDFs, with
quotes. They have not yet been read by the researcher. Every statement about a
paper below carries its source. Anything not checked is listed in section 5.

Rules for this file:

- Do not record a claim about a paper that was not checked against the paper.
- Quote where the wording matters.
- "Relationship to our project" is our assessment, not the paper's claim.

Reading status values: `not read`, `checked against full text`, `read`, `read in detail`.

## 1. Summary

| Work | Venue | What the policy knows | Cache smaller than dataset | Jobs | Cache medium |
|---|---|---|---|---|---|
| NoPFS | SC 2021 | The PRNG seed: the exact future order of one job | Each worker keeps its most frequently accessed samples; placement is static | one | per-node RAM and SSD |
| Quiver | FAST 2020 | Which jobs have consumed a chunk; substitutability of samples | Two chunks resident; a chunk is evicted when all jobs have passed it; sample order is changed | many | shared SSD cache |
| SHADE | FAST 2023 | Per-sample loss as importance | Keeps important samples and changes the sampler to repeat them | one | shared in-memory store |
| DeepMemoryDL | ICPP 2022 | The batching schedule | FIFO eviction; emulated CXL as an extra tier | one | DRAM plus emulated CXL |
| FitCache | IPDPS 2026 | Nothing about reuse | Fills tiers in order; no replacement policy | one | DRAM, PMem, NVMe (CXL tier in the extended code) |
| HVAC | CLUSTER 2022 | Nothing about reuse | "eviction and replacement randomly" | one | node-local NVMe |
| CoorDL | VLDB 2021 | Nothing about reuse | "MinIO will not evict any items" | one, and co-located hyperparameter jobs | DRAM |

## 2. Entries

### NoPFS

| Field | Content |
|---|---|
| Paper | Clairvoyant Prefetching for Distributed Machine Learning I/O. N. Dryden, R. Böhringer, T. Ben-Nun, T. Hoefler. |
| Venue / year | SC 2021. DOI 10.1145/3458817.3476181 (from the authors' page). arXiv 2101.08734. |
| Main research problem | PFS I/O in distributed training: "at large scale, I/O takes as much as 85% of training time". |
| Key mechanism | Uses the PRNG seed: "we know exactly which process will access a given sample when, arbitrarily far in the future". Each worker's access sequence is distributed to all workers at setup. Computes per-worker access frequency over all epochs. "A worker fetches samples with the largest r_k to its fastest storage class, and so on for slower classes until either it has cached the entire dataset or filled its local storage." Only the staging buffer evicts ("immediately dropping samples from the staging buffer after access"). "dynamic cache management, where samples can migrate between caches" is named as future work. Timing comes from a performance model, not from the seed; workers at different speeds are handled by a heuristic. The application sees "an iterator-style interface" and needs "changes to only a few lines of code in existing training scripts". One distributed job; several independent jobs on one dataset are not considered. |
| Evaluation workloads | ResNet-50 on ImageNet-1k (135 GB) and ImageNet-22k (1.3 TB); CosmoFlow (262,144 samples, 4 TB). Piz Daint and Lassen, up to 1024 GPUs. |
| Relationship to our project | Shows that the future order is available online to a cooperating data loader. Uses it for prefetching and static placement inside one job with per-node caches. It does not replace cached data over time and does not consider several jobs on one dataset. With one shared cache, the per-worker frequency differences it exploits disappear. |
| Potential limitations | Needs the seed and shuffling without replacement; static assignment; assumes "no network congestion". The result for datasets above aggregate storage is a simulation. |
| Reading status | checked against full text |
| Source | https://arxiv.org/pdf/2101.08734v2 |

### Quiver

| Field | Content |
|---|---|
| Paper | Quiver: An Informed Storage Cache for Deep Learning. A. V. Kumar, M. Sivathanu. |
| Venue / year | USENIX FAST 2020, pp. 283-296. |
| Main research problem | Many jobs reading the same dataset from remote storage: "A cache that can hold say 20% of the training data would simply thrash because of random I/O." |
| Key mechanism | The unit is one data item, addressed by content hash. Substitutable hits: "the loader looks up lot more (e.g., 10x) indices from the cache and fills the mini-batch opportunistically with whichever 512 it is able to fetch from the cache"; misses are marked pending and read in later passes. "the digest file representing the complete dataset, is partitioned into a fixed number of chunks, such that each chunk is, say, 10% of the dataset"; the cost is "2 chunks for double buffering", and "intermediate sizes for caching are useless, as the benefits are the same as with caching two chunks". Jobs read uncached items of the current chunk from the remote store and insert them. Eviction is coordinated: "A chunk is marked for eviction when another chunk of the dataset is fully loaded into cache", and "When all existing jobs have exhausted their pass over the first chunk (and notify the cache server), the first chunk is actually evicted." Slow jobs trigger "a forced-eviction of a chunk after a threshold time has expired from the completion of the first job on that chunk"; no threshold value is given. New jobs "get hits only from the latest chunk". Cache space goes to the datasets with the best benefit-to-cost ratio, measured by probing mini-batch times. |
| Sample order | Every item is still read exactly once per epoch, but the order is changed: "restricting the shuffle to a fraction of the dataset rather than the entire dataset) has no impact on accuracy", checked on two models with two runs each. The justification given is "the exact sequence of data items does not matter for the correctness or accuracy of the job". The paper reports no hit rates and compares against no policy that keeps each job's own order. |
| Evaluation workloads | ResNet50/ImageNet (154 GB), Inception v3/OpenImages (531 GB), DeepSpeech2/LibriSpeech (90 GB); 48 GPUs on Azure; caches of 100 to 700 GB against about 780 GB of data. Baselines: no cache, LRU. |
| Relationship to our project | The closest prior work for several jobs on one dataset with a small cache. Its eviction rule already uses "which jobs have consumed this data in the current epoch", at chunk granularity. The difference to our candidate: Quiver changes the order in which samples are consumed and restricts shuffling to chunks, with a modified PyTorch; our candidate leaves every job's order unchanged. For one job it states: "If the dataset does not fit in cache, the DLT job does not benefit from Quiver". Any novelty claim for multi-job caching has to be made against Quiver. |
| Potential limitations | Changes sampling order; accuracy checked for two models with two runs each; cache is SSD, not memory. The headline cluster-throughput gain is stated as 2.1x in the introduction and as 1.6x to 2.3x in the evaluation. |
| Reading status | checked against full text |
| Source | https://www.usenix.org/conference/fast20/presentation/kumar |

### SHADE

| Field | Content |
|---|---|
| Paper | SHADE: Enable Fundamental Cacheability for Distributed Deep Learning Training. R. I. S. Khan, A. H. Yazdani, Y. Fu, A. K. Paul, B. Ji, X. Jian, Y. Cheng, A. R. Butt. |
| Venue / year | USENIX FAST 2023, pp. 135-152. |
| Main research problem | Random-order training I/O with a small in-memory cache: "there is no recency or frequency pattern to exploit". |
| Key mechanism | Ranks samples by loss within the minibatch and caches the important ones. A sampler repeats important samples: "SHADE manipulates the sampler to create the desired future sample access pattern". On a miss with a full cache the sample is admitted only if its score is at least the cached minimum; then the least important cached sample is evicted. |
| Evaluation workloads | ImageNet-1K (138 GB) and CIFAR-10; AlexNet, ResNet, VGG; cache 10% to 75% of the dataset; 8 P100 GPUs; HDD-based NFS. Baselines include LRU, Belady MIN, NoPFS, and emulated CoorDL and Quiver. |
| Relationship to our project | States the same starting point as our note A1: uniform random order leaves nothing for recency or frequency. Its answer is to change the access pattern. Ours keeps the access pattern. It is the reference for importance-based reuse, and its code is on this cluster (`~/benchmark/SHADE`, CIFAR-10 only). |
| Potential limitations | Alters the sampling distribution; vision classification only; competitors re-implemented. |
| Reading status | checked against full text |
| Source | https://www.usenix.org/conference/fast23/presentation/khan |

### DeepMemoryDL

| Field | Content |
|---|---|
| Paper | Exploiting CXL-based Memory for Distributed Deep Learning. M. Arif, K. Assogba, M. M. Rafique, S. Vazhkudai. |
| Venue / year | ICPP 2022. DOI 10.1145/3545008.3545054. |
| Main research problem | Data and model exceed DRAM and cause swapping; TensorFlow is unaware of memory tiers. |
| Key mechanism | A manager prefetches by priority: "1) main memory; 2) CXL-based memory; 3) storage tier 0, i.e., CXL scratch storage; and 4) storage tier 1". "data is evicted in FIFO order". The unit is the batch. |
| Evaluation workloads | ImageNet with ResNet50, Inception-V3, MobileNetV2; "3 epochs with a batch size of 64"; eight dual-Xeon servers. Baselines are TensorFlow configurations, not other training caches. |
| Relationship to our project | The closest work on CXL for training data. Its CXL is emulated: "We emulate the provisioning of CXL-based memory by allocating memory from the remote NUMA domain and CXL-based storage devices by creating a RAMDisk on the remote NUMA domain." It says "there are no production CXL devices available yet". Real CXL hardware, a remote cache server, and a replacement policy are all outside it. |
| Potential limitations | Emulated CXL; no GPU mentioned; three epochs; no training-cache baseline. |
| Reading status | checked against full text |
| Source | https://par.nsf.gov/servlets/purl/10407225 |

### FitCache (and HVAC)

| Field | Content |
|---|---|
| Paper | FITCACHE: A Transparent Drop-In Framework for Multi-Tier Caching to Accelerate Distributed Deep Learning Workloads. G. Hu, A. Khan, C. Zimmer, M. J. Brim, F. Mueller. |
| Venue / year | IPDPS 2026 according to a co-author's publication list. DOI not found. This is the user's own earlier work. |
| Main research problem | PFS I/O at scale; existing training caches use one storage tier. |
| Key mechanism | An `LD_PRELOAD` client forwards open, read, and close through Mercury to a server chosen by "a consistent hash of the file path". Files are cached on first access in the fastest tier with space, under "a FIFO (First-In, First-Out) placement policy, with tier-specific capacity thresholds". No future or importance information is used. |
| Evaluation workloads | CosmoFlow (524,288 samples, 1.3 TB) and DeepCAM (2.4 TB) on Frontier and on an 80-node cluster. Baselines: the PFS directly, and HVAC. |
| Relationship to our project | The candidate communication layer. A reading of the extended source on this cluster (`~/hvac/FitCachePP`, 2026-11-12, code not run) found: whole files are admitted at first open; tiers fill in a fixed order; when nothing fits the file is skipped; there is no eviction in single-job mode; in cross-job mode a reaper picks victims by a reference count and an access count that are never updated; the CXL pool never frees space. In effect it is a static cache with admission bypass. A replacement policy would be new to it. Its CXL tier is the "non-evictable famfs mode" named in our refinement of 2026-11-24: one pre-allocated file per server on a famfs mount with the cached files packed into it, because famfs files have to be created at their final size and cannot be renamed or deleted (header of `src/server/fitcache_cxl_pool.h`, read on 2026-11-24, code not run). Its server logs are the source of two real traces used in `2026-11-12-cache-policy-replay`. |
| Potential limitations | No behaviour defined for a cache smaller than the dataset beyond spilling to slower tiers. One Mercury progress thread per process runs all handlers. |
| Reading status | checked against full text (paper); source code read in part |
| Source | https://moss.csc.ncsu.edu/~mueller/ftp/pub/mueller/papers/ipdps26-2.pdf |

HVAC (CLUSTER 2022, pp. 324-335) is FitCache's main baseline and uses Mercury
as well. Above its capacity, "HVAC is designed to perform eviction and
replacement randomly". Source: https://www.osti.gov/servlets/purl/1902810

### CoorDL

| Field | Content |
|---|---|
| Paper | Analyzing and Mitigating Data Stalls in DNN Training. J. Mohan, A. Phanishayee, A. Raniwala, V. Chidambaram. |
| Venue / year | PVLDB 14(5), 2021. |
| Key mechanism | A cache that never replaces: "Once the cache capacity is reached, MinIO will not evict any items in the cache". Adds partitioned caching across servers and coordinated preprocessing for concurrent hyperparameter-search jobs. |
| Relationship to our project | Static retention for one job reading each item once per epoch is published practice. Our note A1 explains why it is optimal; it is not a contribution by itself. |
| Reading status | checked against full text |
| Source | https://arxiv.org/pdf/2007.06775v3 |

## 3. MLPerf Storage and DLIO (workload definitions, not papers)

- Workloads at v2.0 per https://mlcommons.org/benchmarks/storage/ : 3D U-Net,
  ResNet-50, CosmoFlow, and checkpointing. The repository README lists more
  under development (https://github.com/mlcommons/storage).
- Dataset shapes from the DLIO workload configurations: 3D U-Net `.npz`, one
  sample of 146,600,628 bytes per file; ResNet-50 `.tfrecord`, 1251 samples of
  114,660 bytes per file; CosmoFlow `.tfrecord`, one sample of 2,828,486 bytes
  per file. Five epochs each.
- Dataset size is scaled to at least five times the client memory, "to a size
  that prevents significant caching".
- Access pattern: "During each epoch, the whole data is read once", with seeded
  file and sample shuffling.
- Computation is emulated by sleeping, so no GPU is needed.
- Emulated demand per accelerator, from the v1.0 workload files
  (`storage-conf/workload/*_a100.yaml`, repository tag `v1.0`, read
  2026-11-16): `unet3d_a100` batch 7 every 0.636 s with 4 read threads;
  `cosmoflow_a100` batch 1 every 0.00551 s with 4 read threads, pass mark 70%
  accelerator utilization; `resnet50_a100` batch 400 every 0.435 s with 8
  read threads; pass mark 90% for the other two. **[Analytical]** from these
  values: 1.61 GB/s, 0.51 GB/s, and 0.105 GB/s of file data per emulated A100.
  The CosmoFlow value is 181 samples/s; the real A100 run recorded for this
  project reached 75 samples/s ([hardware/c33.md](../hardware/c33.md)).
- A ready-made per-sample access log was not found; DFTracer can record
  POSIX-level calls.

Sources: https://raw.githubusercontent.com/mlcommons/storage/main/Rules.md ,
https://dlio-benchmark.readthedocs.io/en/latest/overview.html

## 4. Novelty analysis

What is already established by others:

1. **One job, uniform shuffling, small cache: do not replace.** CoorDL's cache
   never evicts. SHADE and Quiver both state that such a cache has no pattern
   to exploit. Our simulation on a real trace agrees (`2026-11-12-cache-policy-replay`). There is no
   contribution to be had in single-job replacement without changing the
   access pattern.
2. **The future order is knowable.** NoPFS derives it from the seed, for one
   job, for prefetching and static placement.
3. **Several jobs on one dataset can share cached data, and eviction can wait
   for all jobs.** Quiver does this with chunks and by changing the sample
   order.
4. **Changing the sampler creates reuse.** SHADE.
5. **CXL as an extra tier for training data.** DeepMemoryDL, with emulated CXL
   and FIFO eviction.

What we did not find in these works:

- Replacement for a cache shared by several jobs that leaves each job's sample
  order untouched, and that works at file or sample granularity.
- Use of the known future order (as in NoPFS) for replacement in a shared
  cache across jobs, as opposed to prefetching within one job.
- Prefetching from the known order into a cache shared by several jobs,
  decided together with replacement under limited capacity. NoPFS
  prefetches for one job with a static placement and names dynamic cache
  management as future work. (Added on 2026-11-24, when prefetching became
  part of our mechanism; no further search was made for this point, see
  section 5.)
- A training cache on real CXL memory, and one served remotely over RPC.
- A comparison of a remote CXL cache with remote DRAM under equal budgets.

### Our candidate against Quiver and NoPFS

From experiment `2026-11-12-cross-job-known-order`
([experiments/INDEX.md](experiments/INDEX.md)). **[Simulated]**: trace replay,
byte hit rates, no timing. The Quiver column is our approximation built from
the paper's description, not a reproduction, and the paper itself reports no
hit rates. NoPFS was not simulated.

| | Quiver | NoPFS | Known-order policy (ours, simulated) |
|---|---|---|---|
| Jobs | many, on one dataset | one | many, on overlapping datasets |
| Uses the future order | no | yes, from the seed | yes, announced by each job |
| What the order is used for | — | prefetching and static placement per worker; no replacement | replacement in one shared cache; since 2026-11-24 also planned: asynchronous prefetching into it, two epochs ahead (not implemented, not simulated) |
| Sample order | changed: shuffling restricted to chunks | unchanged | unchanged |
| Real two-job trace, cache 5% / 20% / 80% of the data | 52.9 / 62.0 / 62.0 (approximation) | — | 25.3 / 43.5 / 81.8 |

- **Unsolved by these works:** replacement in a cache shared by independent
  jobs that keeps every job's sampling order.
- **Assumptions that differ:** Quiver assumes that restricting the shuffle to
  chunks is acceptable and that jobs travel through the data together. Our
  candidate assumes that jobs announce their order truthfully and read in that
  order.
- **Mechanism required:** per-job announcement of a bounded part of the order,
  per-job rate tracking, and ranking by the earliest estimated next use across
  jobs. This is Belady's rule with estimated times. It is simple and is not a
  new idea in itself.
- **Metric improved:** not hit rate in general. For jobs of equal speed on one
  dataset, the Quiver-inspired replay serves about twice as many bytes from a
  5% cache as any order-preserving policy can (the upper bound for
  order-preserving policies is 27.7% on the real trace). The known-order
  policy is ahead at large capacity and, in synthetic compositions only, with
  speed ratios of 1:2 and more (from 10% to 20% capacity upward) and with
  partly overlapping datasets. For one job both approaches are at or below
  static pinning.
- **NoPFS in a shared cache:** its placement keeps the samples a worker reads
  most often. When every job reads every file once per epoch, all files have
  the same frequency, so the rule corresponds to static pinning. This is our
  reasoning, not a statement of the paper.

Where a contribution could lie, and the risk attached to each part:

| Candidate contribution | Evidence so far | Main risk |
|---|---|---|
| A characterization of cross-job reuse: which information predicts it and how much of the offline reference each kind recovers | Trace replay on a real two-job trace and synthetic compositions: history little, epoch progress 32% to 82% of the gap, announced order 83% to 100% | One real multi-job trace; a characterization alone may not carry a systems paper |
| Order-preserving known-order replacement for a cache shared by concurrent jobs | Trace replay: within 0.2 points of the offline reference with whole-run knowledge; robust to short lookahead and 2x rate errors | Quiver-style coordination has a much higher hit rate at small capacity when jobs travel together. The case rests on the need to keep each job's order, which is unexamined, and on job mixes with unequal speeds, for which no real trace exists |
| An online policy that needs only per-job epoch progress | Trace replay: a quarter to two thirds of the gap at 20% capacity and below; below static pinning with partial overlap | Too weak. Superseded by the known-order policy |
| Remote CXL cache server over Mercury | Prototype since 2026-11-17: correct, decisions equal to the simulator, CXL store as fast as a DRAM store | No end-to-end gain over direct BeeGFS on reused data measured; whether CXL adds anything beyond capacity is open |
| Joint known-order replacement and asynchronous prefetching with two-epoch lookahead in a shared cache (added 2026-11-24) | Minimal implementation and small-scale measurements (`2026-11-24-two-epoch-lookahead-prefetch`): prefetching removes latency-bound waiting of one-stream jobs; a job with eight read streams gets the same without a cache; the longer lookahead changes no waiting | Prefetching from a known order is NoPFS's idea for one job, so the claim can only be the shared, capacity-limited, jointly managed case; a loader with enough read streams may hide the same latency; prefetching cannot serve a sustained bandwidth deficit |

Not a contribution: static pinning for one job; "reuse-aware beats LRU" for one
job; a claim of higher hit rate than Quiver.

## 5. Not verified

- FitCache: DOI and proceedings entry; behaviour when all tiers are full, from
  the paper.
- NoPFS: the DOI rests on the authors' page (the proceedings page was not
  reachable).
- Prefetching from a known order into a cache shared by several jobs: no
  literature search was made for this after the refinement of 2026-11-24.
  The statement in section 4 that the entries above do not contain it rests
  on those entries only.
- SHADE: limitations as stated by its authors.
- DeepMemoryDL: exact dataset size; whether GPUs were used.
- MLPerf Storage: formats of the newer workloads; shuffle settings of the
  ResNet-50 configuration; whether DFTracer events carry file names.
- Bibliographic data only, mechanisms not checked: iCache (HPCA 2023,
  DOI 10.1109/HPCA56546.2023.10070964), Lobster (ICPP 2022,
  DOI 10.1145/3545008.3545090), Hoard (arXiv 1812.00669).
- Not looked at: DIESEL, FanStore.
- A systematic search for work on schedule-aware caching across jobs has not
  been done. The "not found" list in section 4 covers only the works above.

## 6. Entry template

```markdown
### <Short name>

| Field | Content |
|---|---|
| Paper | |
| Venue / year | |
| Main research problem | |
| Key mechanism | |
| Evaluation workloads | |
| Relationship to our project | |
| Potential limitations | |
| Reading status | not read |
| Source | |
```
