# benchmarks/

Reserved for microbenchmarks.

**Status: no benchmarks are implemented and none have been run.**

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
