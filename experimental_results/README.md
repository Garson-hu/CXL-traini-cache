# experimental_results/

Small, version-controlled records of experiments. Status: no experiments yet.

## What belongs here

- Experiment metadata (`metadata.json`, from [metadata_template.json](metadata_template.json)).
- Small summary tables (CSV or Markdown).
- Small figures.
- References to the location of raw results.

## What does not belong here

Raw measurements, logs, traces, checkpoints, and anything large. These go to
`$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/` (and `traces/`,
`checkpoints/`) on BeeGFS. See [docs/storage.md](../docs/storage.md).

Keep individual files below about 1 MB. Anything in a `raw/` subdirectory is
git-ignored.

## Layout

```text
experimental_results/
├── README.md
├── metadata_template.json
└── <experiment_id>/
    ├── metadata.json
    ├── summary.csv        (or summary.md)
    └── figures/
```

The written report for each experiment is `docs/experiments/<experiment_id>.md`.

## Metadata fields

| Field | Content |
|---|---|
| `experiment_id` | `E<NNN>-<short-name>`, never reused |
| `timestamp` | Start time, ISO 8601 with time zone |
| `git_commit` | Commit of this repository used for the run |
| `git_working_tree_clean` | `true` or `false` at run time |
| `hostname` | Machine the experiment ran on |
| `hardware_config_ref` | Path of the hardware file, e.g. `hardware/c28.md` |
| `result_type` | `real_hardware`, `simulation`, or `analytical` |
| `software_versions` | OS, kernel, Python, framework, driver, workload version |
| `configuration` | Config file path and parameter values |
| `dataset` | Name, path, file count, total bytes |
| `random_seed` | Seed or list of seeds; `null` only if no randomness is involved |
| `raw_result_path` | Location of raw results, relative to `$CXL_TRAINING_DATA_ROOT` |
| `summary_result_path` | Location of the summary in this repository |
| `status` | `planned`, `running`, `completed`, `failed`, or `invalidated` |

## Rules

- Never overwrite existing raw results without explicit approval. A re-run gets
  a new experiment ID or a new run subdirectory.
- Keep failed and negative results. Set `status` instead of deleting.
- A summary must be reproducible from the raw results it references.
- Simulation output is never presented as a hardware measurement.
