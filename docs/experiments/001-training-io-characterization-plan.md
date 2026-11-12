# E001: Training I/O Characterization — Plan

**This is a plan. Nothing in it has been run and it contains no results.**
When the experiment is executed, its report goes to
`docs/experiments/E001-training-io-characterization.md`, written from
[TEMPLATE.md](TEMPLATE.md).

## 1. Experiment metadata

| Field | Value |
|---|---|
| Experiment ID | `E001-training-io-characterization` |
| Plan written | 2026-11-11 |
| Status | planned |
| Result type | real hardware (c28), plus one clearly marked emulation (Part E) |
| Machine | c28, see [hardware/c28.md](../../hardware/c28.md) |
| Workload | CosmoFlow, see [workload_configs/cosmoflow/README.md](../../workload_configs/cosmoflow/README.md) |
| Raw result location | `$CXL_TRAINING_DATA_ROOT/results/E001-training-io-characterization/` |
| Summary location | `experimental_results/E001-training-io-characterization/` |
| Related research questions | RQ3, and the precondition of RQ1 ([research_questions.md](../research_questions.md)) |
| Roadmap phase | Phase 1 ([experiment_plan.md](../experiment_plan.md)) |
| Uses CXL memory | No |

This plan replaces the candidate named `E001-cosmoflow-io-headroom` in the
first version of the experiment plan.

## 2. Research question

Is CosmoFlow training on c28 limited by data loading? If it is, which stage
limits it: storage reads, decompression and parsing, or the degree of
parallelism? And for which data demand rates is there a gap between what
BeeGFS can supply and what memory-resident data can supply?

The last part defines the performance opportunity for any training data cache,
CXL or DRAM. A cache of file bytes can only help where storage supply is below
demand and memory supply is not.

## 3. Motivation and what is already known

- **[Observed]** The model trains on c28's RTX 4060 Ti at batch size 2 but not
  4. A six-step check indicated roughly 11-13 samples/s of compute.
- **[Historical]** On c33's A100 the same model consumed 74.9 samples/s
  (0.217 GB/s of files) at batch size 4.
- **[Historical]** BeeGFS cold reads from c28: 0.057 GB/s with one stream,
  0.322 with four, 0.491 with eight. One stream is about 20 files per second.
- **[Historical]** With the benchmark's sequential reader, a pilot on c33
  reached 5.4 samples/s cold and 9.9 samples/s on re-read.
- **[Observed]** On c28, BeeGFS reads leave nothing in the client page cache,
  yet re-reads are about 30 times faster than first reads.

Taken together: c28's GPU asks for far less data than the A100 did, and
parallel BeeGFS reads supplied far more than that even when cold. The likely
outcome is that training on c28 is not limited by storage. This experiment
tests that directly instead of assuming it, and measures the supply side well
enough to say at which demand a cache would start to matter.

## 4. Hypotheses

Written before the experiment. Each states what would refute it.

| ID | Hypothesis | Refuted if |
|---|---|---|
| H1 | With a parallel input pipeline (8 concurrent readers, 4 parse threads, prefetch 8), training on c28 is GPU-bound from every data source: throughput from cold BeeGFS, warm BeeGFS, and host memory is the same within run-to-run variation, and the trainer waits for data less than 5% of the time. | Throughput from host memory exceeds throughput from cold BeeGFS by more than the variation, or the data-wait share is 5% or more. |
| H2 | With the benchmark's sequential pipeline, training on c28 is limited by the input pipeline, and once data is warm the limit is CPU work (decompression and parsing), not storage: throughput from host memory equals throughput from warm BeeGFS and is below the compute-only rate. | Throughput from host memory is clearly above warm BeeGFS, or the data-wait share is below 5%. |
| H3 | In a loader-only run, cold BeeGFS with four or more concurrent readers supplies more samples per second than c28's GPU consumes. | The cold supply rate at 4, 8, or 16 readers is below the compute-only rate. |

If H1 and H3 hold, a file-byte cache cannot speed up a single training job on
c28, and the opportunity has to be sought at higher demand: a faster GPU,
several GPUs, or several jobs. If H2 holds, caching decoded samples or adding
parallelism matters more than caching file bytes.

## 5. Hardware and workload requirements

| Requirement | Detail |
|---|---|
| Machine | c28, held through a Slurm allocation. GPU idle before each GPU run. |
| CPU budget | 16 physical cores, fixed with `taskset -c 0-15`, the same in every part |
| Memory | under 20 GiB including at most 12 GiB of tmpfs |
| Environment | `/mnt/beegfs/ghu4/envs/hvac_tf` (TensorFlow 2.14.0). No installation. |
| Model and parse code | `~/hvac/benchmark/cosmoflow-benchmark-master`, imported read-only, with the model settings of its own `cosmo.yaml` |
| Data | full dataset `train/` directory (524,288 files) on BeeGFS, read in place |
| Fresh files needed | 7,680 per repetition (about 22 GB), 23,040 for three repetitions |
| BeeGFS space | under 100 MB for results |
| Home quota | a few hundred KB (script and summary) |
| Privileges | none. No root, no CXL, no hardware or system setting changes. |
| Harness | one script, `scripts/e001_io_characterization.py`, still to be written. Its input pipeline follows `train_trace.py` from `~/CXL` (branch `explore/reuse-window-prefetch`); that origin must be stated in the script. |

## 6. Definitions

### Data sources

| Source | Meaning |
|---|---|
| `beegfs-cold` | Files from the full `train/` directory that this project has never read. Each file is used for one cold read only and then recorded in a ledger. |
| `beegfs-warm` | The same files, read again immediately afterwards. |
| `mem` | A copy of the same files in tmpfs, `/dev/shm/$USER/e001/`. Host memory. |

There is no system-wide cache clearing anywhere in this experiment. "Cold" is
obtained by choosing files that have not been read, not by evicting anything.

### Input pipelines

Both use the benchmark's parse function unchanged (gzip TFRecord, `decode_raw`
to `int16`, cast to `float32`, `log(x + 1)`), batch size 2, and the same
explicit seeded file order.

| Pipeline | Definition |
|---|---|
| `seq` | As the benchmark runs it: one file at a time, one parse thread, no explicit prefetch. |
| `par(r)` | `r` files read concurrently (interleave), 4 parse threads, prefetch 8 batches. `par(8)` is the configuration of the earlier c33 run. |

### Parts

| Part | What runs | Isolates |
|---|---|---|
| R: raw read | Threads read whole files, no decompression. Streams 1, 4, 8, 16. | Storage read throughput |
| L: loader only | The input pipeline, drained by a loop that discards the batches. GPU hidden. | Supply rate of the real input pipeline; with source `mem`, its processing cost |
| G: compute only | The training step repeated on one batch held in memory, 300 steps. | GPU computation time, i.e. the demand rate |
| T: training | The instrumented training loop on real data, 3 epochs. | Data-wait time, compute time, overall throughput |
| E: emulated demand (optional) | Part L with a consumer that takes batches at a fixed rate. | Whether the pipeline keeps up with a demand this GPU cannot generate |

## 7. Baselines and comparisons

| Comparison from the task | In this plan |
|---|---|
| A. Normal training using BeeGFS | Part T, source BeeGFS. Epoch 0 is cold, epochs 1-2 are warm. |
| B. Training with data resident in host memory | Part T, source `mem`, same files, same order, same seed |
| C. Data-loading-only benchmark of the real input pipeline | Part L, sources `beegfs-cold`, `beegfs-warm`, `mem` |

Additional references: Part G is the upper bound for training throughput
(no input cost at all). Part R is the upper bound for the loader (no CPU cost).
Pipeline `seq` is the benchmark as it ships; `par(8)` is a strong, simple
alternative that needs no cache.

Equivalence: A and B run the same script with the same model, optimizer, loss,
batch size, seed, file order, and pipeline. Only the directory differs. Part L
builds the identical pipeline graph. No validation pass and no checkpoint
writes in any part, so that no other I/O is mixed in. This differs from the
benchmark's default, which validates and writes a checkpoint every epoch.

## 8. Trial matrix

One repetition. Run at least three repetitions on different days or times.

| Part | Pipeline / streams | Sources | Files per trial | Fresh subsets |
|---|---|---|---|---|
| R | 1, 4, 8, 16 streams | cold, warm (twice), mem | 512 (about 1.5 GB) | 4 |
| L | `seq`, `par(1)`, `par(4)`, `par(8)`, `par(16)` | cold, warm, mem | 512 | 5 |
| G | — | synthetic batch from one parsed sample pair | — | 0 |
| T | `par(8)` | BeeGFS (A), mem (B) | 2,048 (about 5.9 GB), 3 epochs | 1 |
| T | `seq` | BeeGFS (A), mem (B) | 1,024, 2 epochs | 1 |
| E | `par(8)` | cold, mem | 512 per rate | 1 per rate |

Order within a repetition: R, L, G, T. Within each trial: cold, then warm, then
copy to tmpfs, then `mem`. Delete each tmpfs copy when its trials are done.

Estimated duration of one repetition: about 45 minutes. A reduced first pass
with R, L (`seq` and `par(8)` only), and G takes about 15 minutes and already
tests H3.

## 9. Metrics

| Quantity asked for | Metric | From |
|---|---|---|
| Storage read throughput | MB/s and files/s per source and stream count; per-file read latency | Part R |
| DataLoader processing overhead | Samples/s of the pipeline from `mem`; process CPU seconds per sample; ratio to Part R from `mem` | Part L |
| GPU data waiting time | Per step: time blocked waiting for the next batch. Per epoch: sum and share of wall time | Part T |
| GPU computation time | Per step: time in the training step. Compute-only steps/s | Parts T and G |
| Overall training throughput | Samples/s per epoch | Part T |
| GPU utilization (supporting) | `nvidia-smi` sampled once per second | Part T |

Timing in Part T uses a plain loop instead of `model.fit`, so that waiting and
computing can be separated:

```python
it = iter(dataset)
for step in range(steps):
    t0 = time.perf_counter()
    x, y = next(it)                    # blocks only when no batch is ready
    t1 = time.perf_counter()
    loss = model.train_on_batch(x, y)  # returns when the step has finished
    t2 = time.perf_counter()
    log(step, t1 - t0, t2 - t1, loss)  # data wait, compute
```

`data wait` is `t1 - t0`. `compute` is `t2 - t1` and includes the host-to-GPU
copy. The first 20 steps of every run are excluded from step statistics
because of start-up costs (the first step took several seconds in the fit
check). Epoch throughput is reported both with and without them.

Derived quantities:

- Data-wait share: sum of data wait divided by the sum of data wait and compute.
- Supply-to-demand ratio: loader-only samples/s divided by compute-only samples/s.
- Opportunity range: the demand rates D for which cold BeeGFS supply is below D
  and `mem` supply is at or above D, per pipeline.

## 10. Proposed commands

The harness script does not exist yet. The commands show the intended
interface. Paths are set once at the top; the script itself must not contain
machine-specific paths.

```bash
# --- setup (once per session) ---
source configs/env.local.sh        # sets CXL_TRAINING_DATA_ROOT
PY=/mnt/beegfs/ghu4/envs/hvac_tf/bin/python
BENCH=$HOME/hvac/benchmark/cosmoflow-benchmark-master
FULL=/mnt/beegfs/ghu4/hvac/cosmoUniverse_2019_05_4parE_tf_v2/train
MINI=/mnt/beegfs/ghu4/hvac/cosmoUniverse_2019_05_4parE_tf_v2_mini/train_61440/train
OUT=$CXL_TRAINING_DATA_ROOT/results/E001-training-io-characterization
MEM=/dev/shm/$USER/e001
RUN="taskset -c 0-15 env PYTHONDONTWRITEBYTECODE=1 $PY scripts/e001_io_characterization.py --bench $BENCH"
REP=rep1

# --- preconditions (record the output) ---
squeue -u $USER; uptime; nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv
df -h /mnt/beegfs /dev/shm; git rev-parse HEAD; git status --short

# --- file selection: fresh files only, recorded in a ledger ---
$RUN manifest --full-dir $FULL --exclude-names-of $MINI --ledger $OUT/used_files.txt \
     --seed 1 --out $OUT/$REP/manifests \
     --subsets R1:512 R4:512 R8:512 R16:512 Lseq:512 L1:512 L4:512 L8:512 L16:512 T8:2048 Tseq:1024

# --- Part R: raw read throughput ---
for r in 1 4 8 16; do
  $RUN raw-read --file-list $OUT/$REP/manifests/R$r.txt --streams $r --label cold  --out $OUT/$REP/R-$r
  $RUN raw-read --file-list $OUT/$REP/manifests/R$r.txt --streams $r --label warm  --out $OUT/$REP/R-$r
  $RUN raw-read --file-list $OUT/$REP/manifests/R$r.txt --streams $r --label warm2 --out $OUT/$REP/R-$r
done
$RUN stage --file-list $OUT/$REP/manifests/R1.txt --to $MEM/R      # copies to tmpfs, writes $MEM/R.txt
for r in 1 4 8 16; do
  $RUN raw-read --file-list $MEM/R.txt --streams $r --label mem --out $OUT/$REP/R-$r
done
rm -rf $MEM/R $MEM/R.txt

# --- Part L: loader only (GPU hidden) ---
export CUDA_VISIBLE_DEVICES=""
$RUN loader --file-list $OUT/$REP/manifests/Lseq.txt --pipeline seq --label cold --out $OUT/$REP/L-seq
$RUN loader --file-list $OUT/$REP/manifests/Lseq.txt --pipeline seq --label warm --out $OUT/$REP/L-seq
for r in 1 4 8 16; do
  $RUN loader --file-list $OUT/$REP/manifests/L$r.txt --pipeline par --read-par $r --label cold --out $OUT/$REP/L-par$r
  $RUN loader --file-list $OUT/$REP/manifests/L$r.txt --pipeline par --read-par $r --label warm --out $OUT/$REP/L-par$r
done
$RUN stage --file-list $OUT/$REP/manifests/Lseq.txt --to $MEM/L
$RUN loader --file-list $MEM/L.txt --pipeline seq --label mem --out $OUT/$REP/L-seq
for r in 1 4 8 16; do
  $RUN loader --file-list $MEM/L.txt --pipeline par --read-par $r --label mem --out $OUT/$REP/L-par$r
done
rm -rf $MEM/L $MEM/L.txt
unset CUDA_VISIBLE_DEVICES

# --- Part G: compute only ---
$RUN compute --steps 300 --batch-size 2 --out $OUT/$REP/G

# --- Part T: training, A (BeeGFS) then B (host memory) ---
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used --format=csv -l 1 > $OUT/$REP/gpu.csv &
$RUN train --file-list $OUT/$REP/manifests/T8.txt --pipeline par --read-par 8 \
     --epochs 3 --seed 0 --label A-beegfs --out $OUT/$REP/T-par8
$RUN stage --file-list $OUT/$REP/manifests/T8.txt --to $MEM/T8
$RUN train --file-list $MEM/T8.txt --pipeline par --read-par 8 \
     --epochs 3 --seed 0 --label B-mem --out $OUT/$REP/T-par8
rm -rf $MEM/T8 $MEM/T8.txt
$RUN train --file-list $OUT/$REP/manifests/Tseq.txt --pipeline seq --epochs 2 --seed 0 --label A-beegfs --out $OUT/$REP/T-seq
$RUN stage --file-list $OUT/$REP/manifests/Tseq.txt --to $MEM/Tseq
$RUN train --file-list $MEM/Tseq.txt --pipeline seq --epochs 2 --seed 0 --label B-mem --out $OUT/$REP/T-seq
rm -rf $MEM/Tseq $MEM/Tseq.txt
kill %1                                  # stop the GPU sampler
rmdir $MEM 2>/dev/null; df -h /dev/shm   # confirm tmpfs is clean
```

Part E, only if H1 and H3 hold:

```bash
export CUDA_VISIBLE_DEVICES=""
for d in 13 75 150 300; do   # samples/s; 13 is replaced by the Part G result, 75 is the earlier A100 rate
  $RUN loader --file-list <fresh 512-file list> --pipeline par --read-par 8 --pace $d --label cold --out $OUT/$REP/E-$d
  $RUN loader --file-list <tmpfs copy of the same list> --pipeline par --read-par 8 --pace $d --label mem --out $OUT/$REP/E-$d
done
```

The harness refuses to write into an existing run directory unless the label is
new, reads `CXL_TRAINING_DATA_ROOT` from the environment, and never writes into
the benchmark directory or the dataset directories.

## 11. Expected output format

Per run directory under `$OUT/<rep>/<part>/`:

| File | Content |
|---|---|
| `run-<label>.json` | Part, label, source, pipeline, parameters, seed, file-list path and hash, hostname, CPU set, software versions, Git commit and dirty flag, start and end time |
| `reads-<label>.csv` (Part R) | `file_id, bytes, thread, t_start_s, latency_s` |
| `steps-<label>.csv` (Parts T, E, G) | `epoch, step, t_start_s, data_wait_s, compute_s, loss` |
| `epochs-<label>.csv` (Parts L, T, E) | `epoch, samples, bytes, wall_s, samples_per_s, mb_per_s, data_wait_s, compute_s, cpu_s` |
| `gpu.csv` (Part T) | `timestamp, utilization.gpu, memory.used` |

In the repository, `experimental_results/E001-training-io-characterization/`:

- `metadata.json` from the metadata template.
- `summary.csv`, one row per trial:
  `rep, part, source, pipeline, read_par, parse_par, files, bytes, wall_s, samples_per_s, mb_per_s, files_per_s, data_wait_share, cpu_s_per_sample, cold_check`.
- Small figures: supply rate against concurrency per source; data-wait share per
  configuration.

## 12. Potential confounding factors

| Factor | Effect | Handling |
|---|---|---|
| Storage-server caching | Re-reads are fast although the client caches nothing. "Cold" cannot be forced and "warm" cannot be guaranteed. | Fresh files for every cold trial, with a ledger. Part R records per-file latency; a cold trial whose rate exceeds half of its warm rate is flagged and repeated on new files. |
| Other users of BeeGFS | Bandwidth varies with load on the shared servers. | Three repetitions at different times. Record time and date. Report the spread, not only the mean. |
| Metadata hiccups | A two-minute metadata error was seen on 2026-11-11. | Log errors and stalls. Repeat affected trials. |
| Small-file overhead | With 2.9 MB files, open and metadata cost is a large part of the read time. | Report files/s as well as MB/s. Do not transfer the numbers to large-file workloads. |
| Linux page cache | Not populated by BeeGFS reads on c28. tmpfs is memory by definition. | No eviction needed. No local file system is used in this experiment. If one is added later, evict per file, never system-wide. |
| Prefetch buffer | Overlaps I/O with computation and hides short stalls. | Same prefetch setting in A and B. For `seq`, log whether TensorFlow injected a prefetch. |
| Start-up effects | The first steps include cuDNN and graph set-up. | Exclude the first 20 steps from step statistics. |
| CPU budget | The decode rate scales with cores. c28 has 128. | Fixed 16 cores for all parts. The number is a choice, stated in every result. |
| Batch size | 2 on c28, 4 in the c33 history. | Compare per-sample rates. Do not equate the two machines. |
| Shared node | The Slurm allocation allows oversubscription. | Check load and GPU before each part. Record them. |
| Timer placement | Host-to-GPU copy is counted as compute. | Stated as a limitation. Part G uses the same loop, so the comparison holds. |
| tmpfs staging order | Copying to tmpfs reads the files and warms the servers. | Always after the cold and warm BeeGFS trials on those files. |
| Checkpoints and validation | Would add write I/O and extra reads. | Disabled in all parts. |

## 13. Criteria for interpreting the results

Differences smaller than 5%, or smaller than twice the spread between
repetitions if that is larger, are treated as no difference.

| Observation | Interpretation | Consequence |
|---|---|---|
| Part T, `par(8)`: data-wait share below 5% in A (including the cold epoch), A and B throughput equal | GPU-bound from cold storage. H1 holds. | No cache can speed up this configuration. Do not build a cache to accelerate single-job training on c28's GPU. Look at higher demand. |
| Data-wait share 5% or more in A, below 5% in B | Storage-bound. | A memory-resident copy helps. The possible gain is throughput B divided by throughput A. Proceed to a CXL-resident variant. |
| Data-wait share 5% or more in both A and B | Pipeline-bound: CPU work or parallelism. | Caching file bytes does not help. Parallelism is the cheap fix; caching decoded samples is the candidate mechanism. |
| Part L: cold supply at 4 or more readers above the Part G rate | H3 holds. Storage can feed this GPU. | Report the opportunity range. If it starts far above c28's demand, the case for caching needs a higher-demand setting. |
| Part L from `mem` far below Part R from `mem` | Decompression and parsing dominate the loader. | Supports caching after decoding over caching before it. |
| Cold and warm BeeGFS differ strongly in Parts R and L | Server caching matters. | Multi-epoch runs on BeeGFS already benefit from it. A client cache must be compared against warm BeeGFS, not only cold. |

A result that confirms H1 and H3 is a negative result for single-job caching on
c28. It is to be recorded as such, not explained away.

## 14. Limitations known in advance

- **No CXL memory is used.** This experiment bounds what any memory-resident
  cache could gain. It says nothing about CXL latency or bandwidth.
- **c28's GPU is small.** Real training on the CXL machine runs at batch size 2
  and, by indication, at about one sixth of the A100's rate. If training here
  is GPU-bound, that does not show that caching is useless on faster trainers.
- **No machine has both an A100 and CXL memory.** The c33 history must not be
  combined with c28 measurements into an end-to-end speedup. Part E is the
  controlled alternative: it paces the real input pipeline on c28 at stated
  demand rates, including the A100's historical rate, and reports whether the
  pipeline keeps up. Its result is "the loader on c28 does or does not sustain
  D samples/s from this source". It is an emulation, not a training
  measurement, and must be labeled that way.
- One workload, one file size, one CPU budget, subsets of 512 to 2,048 files.
- Single job. Contention between jobs is not covered.

## 15. What follows

| Outcome | Next step |
|---|---|
| Storage-bound somewhere | Repeat the storage-bound configuration with the data resident in CXL memory (`dax0.0` or `dax1.0`), next to the host-memory result |
| Pipeline-bound | Measure the cost split between decompression and parsing; consider a decoded-sample cache, where capacity is scarce |
| GPU-bound everywhere | Use Part E and concurrent loader runs to find the demand at which storage falls behind; decide whether that regime is realistic for this project |

## 16. Results

None. The experiment has not been run.
