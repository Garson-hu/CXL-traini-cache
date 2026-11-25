# benchmarks/train_io/

Training I/O harness for CosmoFlow: how fast can the input pipeline supply
data, how fast does the GPU consume it, and how much of a training step is
spent waiting for data. Used by experiments `2026-11-16-workload-io-validation`,
`2026-11-16-loader-gpu-scaling`, and `2026-11-17-multi-gpu-io-saturation`
([docs/experiments/INDEX.md](../../docs/experiments/INDEX.md)).

It measures real training and the real input pipeline. It contains no cache
and uses no CXL memory. Reading from a tmpfs copy is the upper bound for any
cache of file bytes; it is not a CXL result.

## Contents

| File | Purpose |
|---|---|
| [cosmoflow_io.py](cosmoflow_io.py) | One script, six modes (below). Needs the existing TensorFlow environment and the CosmoFlow benchmark directory, both read-only. |

## Modes

| Mode | What it does | Output |
|---|---|---|
| `select` | Chooses disjoint random subsets of files not yet read by this project, from a `name,bytes` listing, and records them in a ledger | file lists (`path bytes` per line) |
| `rawread` | Reads whole files with N threads, no decoding | per-file latency |
| `stage` | Copies the files of a list to a directory, for example tmpfs, and writes the matching list | file list |
| `loader` | Runs the input pipeline without a model, GPU hidden; optional fixed consumption rate (`--pace`). With `--pace-step` the consumer waits one step time after every batch and does not make up time lost waiting for data, like a training job (an emulated job; added 2026-11-18 with `--step-log`, `--max-seconds`, and `--start-unix` for this mode). `--max-seconds-ends-run` makes the time limit end the run instead of the epoch (for a job with `--epochs 2` that announces two epochs but is observed for a limited time); `--cache-request-log` writes `requests-<label>.csv` with the timing of every request to the cache server and its parts on the server (both added 2026-11-24) | samples/s, CPU seconds per sample; with `--step-log` the wait of every batch |
| `compute` | Repeats the training step on one batch held in memory | step time, samples/s |
| `train` | Training loop that times, per step, the wait for the next batch and the training step; optional validation pass and access trace | per-step and per-epoch tables, trace |

Input pipelines (`--pipeline`):

- `seq`: the benchmark's reader. One file at a time, one parse thread, no
  explicit prefetch.
- `par`: tf.data's parallel interleave with cycle length `--read-par`,
  `--parse-par` parse threads, `--prefetch` batches. 8, 4, 8 is the
  configuration of the earlier c33 run. **The interleave reads ahead: it has
  up to three times `--read-par` files open at once** (measured on
  2026-11-16: 3, 6, and 24 files for 1, 2, and 8), so `--read-par` is not the
  number of concurrent read streams.
- `map`: exactly `--read-par` files are read and decompressed at a time (a
  parallel map over `read_file` and `decode_compressed`), then parsed by
  `--parse-par` threads, with the same prefetch buffer. It yields the same
  tensors as the other two. It assumes one record per file and does not
  check the record's CRC.

- `cache`: as `map`, but the bytes of a file come from the cache server of
  [system/](../../system/README.md) instead of `tf.io.read_file`
  (`--cache-addr-file`, `--cache-catalog`, `--cache-job`). The job registers
  with the server, announces the order of every epoch before its first
  request, and sends epoch and position with every request. With
  `--cache-lookahead 2` it also announces the next epoch's order one epoch
  early, computed from the seed as it will be when that epoch starts; the
  order it reads in is unchanged (checked on 2026-11-24). Note that the
  read stream of `map` and `cache` also decompresses each file: with one
  read stream a request through the cache keeps the stream busy for the
  fetch plus about 35 to 40 ms. Decompression,
  parsing, batching, prefetch, and order are those of `map`; the tensors are
  identical (checked). Only the training files go through the cache, not a
  validation list.

`par`, `map`, and `cache` are asynchronous: reading, parsing, and training
overlap. Use `map` when the reader count has to mean the number of streams.

Both read gzip TFRecord files and apply the benchmark's parse function.
The file order of every epoch is an explicit permutation from
`numpy.random.default_rng(seed * 1000003 + epoch)`, so it is known when the
job starts and is the same for every data source. With `--order list` the
files are read in list order in every epoch instead, which makes a second
epoch a re-read of the same sequence. `--start-unix` makes jobs on several
nodes begin their first epoch at the same wall-clock time.

## Origin and differences from the benchmark

- The pipeline, the explicit order, and the logging of file pulls follow
  `train_trace.py` of the earlier study (repository `~/CXL`, branch
  `explore/reuse-window-prefetch`, commit `a65c6e3`).
- `parse_data()` is copied from the benchmark's `data/cosmo.py`; importing
  that module would pull in Horovod. The model comes from the benchmark's own
  `models` package, imported from `--bench`.
- The training loop is a plain loop around one `tf.function`, not
  `model.fit`, so that waiting and computing are timed separately. Model, loss
  (MSE), and optimizer (SGD, momentum 0.9, fixed learning rate) are the
  benchmark's. No Horovod, no checkpoints, no learning-rate schedule.
- `compute_s` of a step includes the copy of the batch from host memory to
  the GPU.

## Usage

```bash
export COSMOFLOW_BENCH=<CosmoFlow benchmark directory>
export PYTHONDONTWRITEBYTECODE=1      # keep the benchmark directory unchanged
PY=<python of the TensorFlow environment>

$PY cosmoflow_io.py loader  --file-list L.txt --pipeline par --read-par 8 --parse-par 8 --out OUT --label par8
$PY cosmoflow_io.py compute --steps 300 --batch-size 2 --out OUT --label g
$PY cosmoflow_io.py train   --file-list L.txt --pipeline par --read-par 8 --parse-par 4 --epochs 3 \
                            --seed 0 --trace --job jobA --out OUT --label a
```

Restrict the CPUs with `taskset`; TensorFlow sizes its thread pools from the
allowed CPUs. An existing run label is never overwritten.

## Trace format (`reads-<label>.csv`)

With pipeline `cache` the per-epoch table has two more columns, `cache_hits`
and `cache_misses`, as the client counted them, and the run record has a
`cache` entry.

`t_unix, job, dataset, epoch, pos, file_id, bytes, name`: one line when the
pipeline pulls a file, in pull order. `dataset` is `train` or `valid`; `pos`
is the position in that pass. The sampler settings are in `run-<label>.json`.
The experiment's `make_trace.py` merges the logs of several jobs into the
simulator's format.

## Limits

- CosmoFlow only: one sample per file, gzip TFRecord.
- Cold storage cannot be created or verified by this harness. A "first read"
  is a file the ledger says this project has not read.
- Wall-clock timestamps come from each node's clock.
