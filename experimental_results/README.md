# experimental_results/

One directory per experiment, named by date. The experiment directories are
local working material: **they are not tracked by Git and are not pushed.**
Only this file and `metadata_template.json` are tracked. The tracked record of
what was done is one row per experiment in
[docs/experiments/INDEX.md](../docs/experiments/INDEX.md).

## Layout

```text
experimental_results/
├── README.md                      (tracked)
├── metadata_template.json         (tracked)
└── YYYY-MM-DD-<short-name>/       (not tracked)
    ├── plan.md                    hypotheses and method, written before the run
    ├── summary.md                 what was done, results, interpretation, limitations
    ├── metadata.json              from metadata_template.json
    ├── results.csv, *.txt         small result tables
    ├── figures/
    └── scripts used only by this experiment, job scripts, small logs
```

## Rules

- **Name:** `YYYY-MM-DD-<short-name>`, the day the experiment starts. Names are
  never reused. An experiment that continues on later days stays in its
  directory, and `summary.md` says what was done on which day. A new question
  gets a new directory.
- **`summary.md`:** required as soon as the directory holds results or more
  than a few files. Template: [docs/experiments/TEMPLATE.md](../docs/experiments/TEMPLATE.md).
- **`plan.md`:** when hypotheses are stated before a run, they go here, with
  the date, and are not edited after the run.
- **Size:** the home quota applies. Keep files small (about 1 MB each). Large
  raw data, traces, and checkpoints go to
  `$CXL_TRAINING_DATA_ROOT/results/<same name>/` on BeeGFS, and `summary.md`
  names that location. See [docs/storage.md](../docs/storage.md).
- **Index:** add or update the experiment's row in `docs/experiments/INDEX.md`.
- **Integrity:** never overwrite existing results; keep failed and negative
  results; say whether a number is a hardware measurement or a simulation.
- **No backup through Git:** these directories exist only on this file system.

## Metadata fields

| Field | Content |
|---|---|
| `experiment_id` | the directory name |
| `timestamp` | start time, ISO 8601 with time zone |
| `git_commit` | commit of this repository used for the run |
| `git_working_tree_clean` | `true` or `false` at run time |
| `hostname` | machine the experiment ran on |
| `hardware_config_ref` | path of the hardware file, e.g. `hardware/c28.md` |
| `result_type` | `real_hardware`, `simulation`, or `analytical` |
| `software_versions` | OS, kernel, Python, framework, driver, workload version |
| `configuration` | config file path and parameter values |
| `dataset` | name, path, file count, total bytes |
| `random_seed` | seed or list of seeds; `null` only if no randomness is involved |
| `raw_result_path` | location of raw results, relative to `$CXL_TRAINING_DATA_ROOT` |
| `summary_result_path` | location of the summary in this directory |
| `status` | `planned`, `running`, `completed`, `failed`, or `invalidated` |
