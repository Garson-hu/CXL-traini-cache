# configs/

Lightweight, version-controlled configuration.

**Status: contains only the example environment file.**

## Contents

| File | Purpose |
|---|---|
| [env.example.sh](env.example.sh) | Example shell environment. Sets `CXL_TRAINING_DATA_ROOT` and lists optional cache and temporary-directory redirections. |

## Usage of the environment file

```bash
cp configs/env.example.sh configs/env.local.sh   # git-ignored
source configs/env.local.sh
echo "$CXL_TRAINING_DATA_ROOT"
```

Nothing modifies `~/.bashrc` or `~/.profile` automatically. Add the `source`
line to a startup file yourself if you want it permanent.

## Conventions for future experiment configurations

- One file per experiment configuration, named after the experiment ID where
  it applies.
- Configurations must be reproducible: fixed seeds, explicit parameter values,
  no dependence on unrecorded local state.
- Paths are relative to `CXL_TRAINING_DATA_ROOT`, not absolute.
- Do not store datasets, credentials, or machine-specific secrets here.
- Local overrides use a `.local.` name (for example `env.local.sh`) and are
  git-ignored.

Workload-specific launch settings live in
[workload_configs/](../workload_configs/). Storage layout:
[docs/storage.md](../docs/storage.md).
