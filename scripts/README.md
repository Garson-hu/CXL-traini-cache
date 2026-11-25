# scripts/

Experiment automation and analysis utilities.

**Status:** three trace preparation scripts, used in experiments
`2026-11-12-cache-policy-replay` and `2026-11-12-cross-job-known-order`. Measurement harnesses live in
[benchmarks/](../benchmarks/README.md): the training I/O harness is `benchmarks/train_io/cosmoflow_io.py`.

## Contents

| File | Purpose | Output label |
|---|---|---|
| [convert_train_trace.py](convert_train_trace.py) | Converts a trace of the earlier tracing trainer (`reads.txt`) to the simulator's CSV format | `kind=real` |
| [convert_fitcache_log.py](convert_fitcache_log.py) | Converts FitCache server logs (file opens with timestamps) to the CSV format. Reconstructs epoch and job labels, because the logs record neither, and says so in the output header. | `kind=real`, labels reconstructed |
| [make_multijob_trace.py](make_multijob_trace.py) | Builds a multi-job trace from real file sizes and the real run's ordering code, with assumed job counts, start times, speeds, epochs per job, and dataset overlap. Needs numpy. | `kind=synthetic` |

All three refuse to overwrite an existing output file. Usage is at the top of
each file.

## Conventions

- Read the data root from `CXL_TRAINING_DATA_ROOT`, or take paths as
  arguments. Do not hardcode `/mnt/beegfs/...`, and do not fall back to a path
  in the home directory.
- Write raw output to `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/` and
  refuse to overwrite existing results.
- Every generated trace states in its header whether it is real or synthetic,
  and what was reconstructed or assumed.
- A script derived from earlier work states its origin.
- Record experiment metadata from
  [experimental_results/metadata_template.json](../experimental_results/metadata_template.json).
- Do not change machine state (CXL, DAX, NUMA, kernel parameters, mounts).
  See [CLAUDE.md](../CLAUDE.md), "Hardware safety".
- Keep scripts small and single-purpose.

The example environment file is [configs/env.example.sh](../configs/env.example.sh).
