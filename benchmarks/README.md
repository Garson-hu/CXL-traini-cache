# benchmarks/

Microbenchmarks.

**Status:** two benchmarks exist.

| Directory | What it measures | Used by |
|---|---|---|
| [remote_cache/](remote_cache/README.md) | Moving training data objects between a client node and DRAM or CXL memory on a server through Mercury; admission from the file system; direct file system reads; local copy rates | `2026-11-12-remote-cxl-data-path` |
| [train_io/](train_io/README.md) | CosmoFlow training I/O: supply of the real input pipeline, the GPU's compute-only rate, time spent waiting for data in training, raw file reads, and access traces with job identity. No cache, no CXL. | `2026-11-16-workload-io-validation` |

## Intended scope

- BeeGFS and NVMe access.
- CXL read/write bandwidth.
- Data movement overhead.
- Cache lookup overhead.
- Concurrent cache traffic.
- Training data loading paths.

## Conventions for future benchmarks

- Add a benchmark when an experiment needs it, not in advance.
- One subdirectory per benchmark with its source and a short README (what it
  measures, how to build, how to run, output format).
- Build out of tree. `build/` is git-ignored. Large builds go to
  `$CXL_TRAINING_DATA_ROOT/tmp/build/` ([docs/storage.md](../docs/storage.md)).
- Write raw output to `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/`.
- Record the machine, the storage or memory target, thread count, and data
  size with every result. A number without its configuration is not a result.
- Benchmarks run on shared machines. Note other load at the time, and never
  write test data to a device or file system that others use without approval.
- Benchmarks that need CXL access depend on an approved access path
  ([hardware/c28.md](../hardware/c28.md)).
