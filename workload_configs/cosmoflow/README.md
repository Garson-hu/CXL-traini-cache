# workload_configs/cosmoflow/

Audit of the CosmoFlow workload, the initial target workload of the project.

**Status (2026-11-11):** the training code, a working software environment,
and the datasets already exist on this cluster from earlier work. They were
inspected read-only. Nothing was installed, downloaded, copied, or moved, and
no training run was started. This directory holds no configuration or launch
script yet.

Evidence labels are defined in
[docs/project_overview.md](../../docs/project_overview.md).

## 1. What exists and where

| Item | Location | Notes |
|---|---|---|
| Benchmark code | `~/hvac/benchmark/cosmoflow-benchmark-master` | Locally modified copy of the older `cosmoflow-benchmark` (TensorFlow/Keras, Horovod). Not a Git repository, so there is no commit to cite. Its README points to the newer MLPerf HPC reference implementation. 695 MB including old checkpoints. |
| Trainer with explicit schedule and trace | `~/CXL`, branch `explore/reuse-window-prefetch`, `experimental_results/2026-10-27-reuse-window-prefetch/train/train_trace.py` | Used for the earlier c33 run. Reuses the benchmark's model and parse function. Not copied here. |
| Environment | `/mnt/beegfs/ghu4/envs/hvac_tf` | Python 3.9.21, TensorFlow 2.14.0, Horovod 0.28.1. See [hardware/c28.md](../../hardware/c28.md). |
| Full dataset | `/mnt/beegfs/ghu4/hvac/cosmoUniverse_2019_05_4parE_tf_v2/` | `train/` 524,288 files, `validation/` 65,536, `test/` 32,768 |
| 61,440-file subset | `/mnt/beegfs/ghu4/hvac/cosmoUniverse_2019_05_4parE_tf_v2_mini/train_61440/` | `train/` 61,440 files, `validation/` 1,024 |
| 1,024-file subset | `/mnt/beegfs/ghu4/hvac/cosmoUniverse_2019_05_4parE_tf_v2_mini/train_1024/` | `train/` 1,024 files, `validation/` 1,024 |

None of this is under `$CXL_TRAINING_DATA_ROOT`. The datasets are read in
place. Copying 178 GB or more is not needed and not planned.

Missing or unresolved:

- A version identifier for the benchmark code (no Git history).
- The script behind the earlier BeeGFS bandwidth probes.

## 2. Audit questions

### 2.1 Dataset location and approximate size

| Dataset | Files | Size | How determined |
|---|---|---|---|
| `train_61440/train` | 61,440 | 178,071,110,206 bytes (178.07 GB, 165.84 GiB) | **[Observed]** `stat` of every file, 2026-11-11 |
| `train_1024/train` | 1,024 | 2,970,777,238 bytes | **[Historical]** pilot `run.json` |
| Full `train/` | 524,288 | not summed | **[Observed]** directory entry count |
| Full `validation/`, `test/` | 65,536 / 32,768 | not summed | **[Observed]** directory entry count |
| Source archive | — | 1,805,152,143,360 bytes | **[Historical]** fetch script and log, 2026-10-04 |

Per the fetch script, the files of `train_61440/train` were also copied into
the full `train/` directory, so that content exists twice on BeeGFS.

### 2.2 Number and format of training files

**[Observed]** One sample per file. Each file is a gzip-compressed TFRecord
(magic bytes `1f 8b`; `compression: GZIP` in the configuration). Sizes in
`train_61440/train` range from 2,435,273 to 3,306,409 bytes, mean 2,898,293.
One decompressed file is 16,777,287 bytes: a 128x128x128x4 `int16` volume
(16,777,216 bytes) plus four `float32` targets and framing. The compression
ratio is about 5.8.

**[Analytical]** Decoded, the 61,440-sample set is about 1.03 TB (960 GiB) as
`int16` and twice that as `float32`. The compressed set fits in c28's DRAM; the
decoded set does not.

### 2.3 How TFRecord files are opened and read

Two input pipelines exist. Both use the same parse function.

| Step | Benchmark, `data/cosmo.py` (local copy) | `train_trace.py` (earlier c33 run) |
|---|---|---|
| File list | `sorted(glob('*.tfrecord'))`, first `n_train` names | `sorted(os.listdir())`, first `n_train` names |
| Reading | `tf.data.TFRecordDataset(names, compression_type='GZIP')`: one file at a time | `interleave` of one `TFRecordDataset` per file, `cycle_length = read_par` |
| Parsing | `map(parse, num_parallel_calls=1)`; the `n_parallel_reads` argument is ignored | `map(parse, num_parallel_calls = parse_par)` |
| Batching | `repeat(n_epochs)`, `batch(drop_remainder=True)` | `batch(drop_remainder=True)`, one dataset per epoch |
| Prefetch | no explicit `prefetch` (commented out) | `prefetch(N)` |

Files are opened by TensorFlow's C++ file layer with ordinary POSIX calls and
read through a 256 KB reader buffer (constant in the installed TensorFlow
source). Parsing is: parse the example, `decode_raw` to `int16`, reshape, cast
to `float32`, `log(x + 1)`. The benchmark can also copy files to a local
directory before training (`--stage-dir`, `utils/staging.py`), and earlier
work intercepted the file calls with an `LD_PRELOAD` library.

### 2.4 How files are shuffled between epochs

**[Observed in code]** Benchmark: `Dataset.from_tensor_slices(names)`
`.shuffle(len(names), reshuffle_each_iteration=True)`, then `.shard()`, then
reading, then `.repeat(n_epochs)`. The shuffle buffer holds every file name, so
each epoch is a fresh uniform permutation of the file list, and each file is
read once per epoch. The second, sample-level shuffle is off
(`shuffle_buffer_size=0`). The seed is set globally with
`tf.keras.utils.set_random_seed(seed)`, default 0. Validation is not shuffled.

`train_trace.py` replaces the shuffle with an explicit permutation per epoch
from `numpy.random.default_rng(seed * 1000003 + epoch)`.

### 2.5 Whether the file access order can be determined in advance

- Benchmark as written: the order is drawn inside the tf.data shuffle operation
  when each epoch starts and is not exposed to the application. It is
  reproducible for a fixed seed and TensorFlow version, but obtaining it ahead
  of time would mean re-running the same operation. Not verified.
- With an explicit permutation, as in `train_trace.py`: yes, the order of every
  epoch is known at job start. **[Historical]** The earlier study reports
  about 10 ms per epoch for 61,440 files.

Because there is one sample per file, no augmentation, and no dynamic
sampling, the sample order is the file read order.

### 2.6 Whether data loading uses concurrent workers

- Benchmark as written: no. One file is read at a time and one thread parses.
- `train_trace.py`: yes, `read_par` concurrent file readers and `parse_par`
  parse threads. The earlier c33 run used 8 and 4.
- tf.data uses threads inside the training process, not separate worker
  processes. With Horovod, each rank is a process that reads its own shard.

### 2.7 Whether storage I/O overlaps with GPU computation

- `train_trace.py`: yes. `prefetch(N)` lets background threads read and decode
  while the GPU trains on the previous batch.
- Benchmark as written: probably. There is no explicit prefetch, but the
  installed TensorFlow 2.14.0 documents an `inject_prefetch` optimization that
  defaults to on and appends a prefetch when the last transformation is
  synchronous. **[Assumption]** Whether it is active in this pipeline was not
  measured.
- In both cases the training step and the host-to-GPU copy run on the main
  thread. When no batch is ready, the main thread blocks and the GPU idles.

### 2.8 Whether the workload can run on c28's GPU

Yes, at reduced batch size.

- **[Observed]** In a six-step check on synthetic data the model trained at
  batch size 1 and 2 on the RTX 4060 Ti and failed with an out-of-memory error
  at batch size 4 ([hardware/c28.md](../../hardware/c28.md), section 3.2).
- **[Historical]** A job log from 2025-11-25 shows the benchmark starting on
  this GPU at batch size 2. The current configuration file has
  `batch_size: 2 # originally 4`.
- The same check indicated roughly 11-13 samples/s of compute. The earlier
  A100 run reached 74.9 samples/s at batch size 4. A training job on c28
  therefore asks for roughly one sixth of the data rate. That is an indication,
  not a measurement.

## 3. The data-loading pipeline

```text
BeeGFS storage servers (RDMA)
   |  open + read, 2.9 MB compressed per sample        reader thread(s)
   v
gzip decompression  ->  16.8 MB record                 reader thread(s)
   |
   v
parse + decode_raw + cast + log(x+1) -> 33.6 MB float32 tensor    parse thread(s)
   |
   v
batch (copy samples into one tensor)                   pipeline thread
   |
   v
prefetch buffer (host memory)                          boundary between pipeline and trainer
   |
   v
host-to-GPU copy  ->  forward, backward, update        main thread + GPU
```

What can overlap: reading, decompression, parsing, and batching run in
background threads and overlap with GPU computation as long as the prefetch
buffer is not empty.

What can block the GPU: an empty prefetch buffer. That happens when the
pipeline's supply rate is below the trainer's demand, because of storage
(reads too slow), CPU (decompression and parsing too slow), or parallelism
(too few reader or parse threads). The host-to-GPU copy is on the main thread
and is always part of the step.

Notes:

- **[Observed]** BeeGFS file data is not kept in the Linux page cache on c28,
  and re-reads are still much faster than first reads, apparently because the
  storage servers cache it ([hardware/c28.md](../../hardware/c28.md), section
  3.1). "Warm" BeeGFS therefore depends on the servers and on other users.
- **[Historical]** With the sequential reader the earlier pilot reached 5.4
  samples/s cold and 9.9 samples/s on re-read. The second number suggests a
  CPU limit of about ten samples per second for one reader and one parse
  thread on c33. Not measured on c28.

## 4. Where a CXL cache could be inserted

Options, from least to most intrusive. None is chosen and none is implemented.

| Insertion point | What is cached | Change to the trainer | Notes |
|---|---|---|---|
| A. File path | compressed files | none: point the data directory, or `--stage-dir`, at a CXL-backed file system | Needs a file system on CXL memory (famfs, or tmpfs on a CXL NUMA node). Both need root on c28 today. Whole-dataset copy, i.e. static caching. |
| B. File calls | compressed files | none: `LD_PRELOAD` interception of open/read/close | Cache fills on first read. Earlier work has such a library. The cache store could be a devdax mapping, which this user can open. |
| C. Input pipeline source | compressed files | small: replace the file reader in the tf.data graph with a lookup that returns the record bytes from a cache | Keeps decompression and parsing unchanged. Policy and order are visible at this level. |
| D. After decoding | decoded samples | moderate: cache `int16` volumes and skip decompression and parsing on a hit | 5.8 times more memory per sample. Removes the CPU cost as well as the I/O. This is the variant where capacity is naturally scarce on c28. |

Options A to C remove storage reads only. They help when storage limits the
pipeline. Option D also removes decompression, which helps when the CPU limits
it. Which of the two limits applies is what the first experiment has to show:
[docs/experiments/001-training-io-characterization-plan.md](../../docs/experiments/001-training-io-characterization-plan.md).

## 5. Rules for running this workload in this project

- The benchmark's default `output_dir` is inside its own directory in the home
  file system and each epoch writes a 71 MB checkpoint there. Always pass an
  output directory under `$CXL_TRAINING_DATA_ROOT`.
- `train.py` imports Horovod, wandb, and pynvml at start-up even for a
  single-process run.
- Do not modify the benchmark directory, the datasets, or `~/CXL`. They belong
  to other work.
- Any script taken from `train_trace.py` must state that origin.
- Use batch size 2 on c28 unless a larger one has been shown to fit.

## 6. Historical workload context (not reproduced in this repository)

The earlier measurements on c33 and their source are listed in
[hardware/c33.md](../../hardware/c33.md).
