# scripts/

Reserved for experiment automation and analysis utilities.

**Status: no scripts yet.**

## Conventions for future scripts

- Read the data root from `CXL_TRAINING_DATA_ROOT`. Exit with a clear error
  when it is unset. Do not fall back to a path in the home directory and do
  not hardcode `/mnt/beegfs/...`.
- Write raw output to `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/` and
  refuse to overwrite an existing result directory.
- Record experiment metadata from
  [experimental_results/metadata_template.json](../experimental_results/metadata_template.json):
  Git commit, hostname, timestamp, seed, configuration.
- Do not change machine state (CXL, DAX, NUMA, kernel parameters, mounts).
  See [CLAUDE.md](../CLAUDE.md), "Hardware safety".
- Keep scripts small and single-purpose. State usage at the top of each file.

The example environment file is [configs/env.example.sh](../configs/env.example.sh).
