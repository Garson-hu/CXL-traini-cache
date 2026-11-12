# Storage Organization

The project uses two storage locations with different roles.

| Location | Role | Limit |
|---|---|---|
| Home (`/home/ghu4`, NFS) | Git repository: code, docs, configs, small summaries | 40 GB quota, strict |
| BeeGFS (`$CXL_TRAINING_DATA_ROOT`) | Everything large: workloads, datasets, checkpoints, traces, raw results, temporary files | Shared file system, no per-user quota found |

CXL memory is an experimental cache tier. It is never used as persistent
storage for datasets or results.

## 1. Home directory (Git repository)

Allowed: source code, documentation, configuration files, small scripts,
simulator and microbenchmark source, tests, small result summaries, small figures.

Not allowed: workload installations, datasets, checkpoints, large traces, raw
experiment output, large temporary files, Python environments, build trees.

Never download or copy large files into the home directory, even temporarily.

State observed on 2026-11-11 (`quota -s`):

| Item | Value |
|---|---|
| File system | NFS v4.2 export `/home` |
| Used | 26,759 MiB |
| Soft limit | 39,936 MiB (39 GiB) |
| Hard limit | 40,960 MiB (40 GiB) |
| Headroom to soft limit | about 12.9 GiB |
| File count | 362k, no file-count limit |

About two thirds of the quota was already used by other work when this project
started. Check before adding anything non-trivial:

```bash
quota -s
du -sh ~/cxl-train-cache
```

## 2. BeeGFS project root

```text
$CXL_TRAINING_DATA_ROOT = /mnt/beegfs/ghu4/cxl-train-cache/
├── workloads/     Workload installations and runtime dependencies (e.g. CosmoFlow, Python environments)
├── datasets/      Training datasets (e.g. TFRecord files)
├── checkpoints/   Training checkpoints and model states
├── traces/        Large access traces, I/O traces, profiling outputs
├── results/       Raw experimental measurements and large result artifacts
└── tmp/           Temporary training, benchmarking, cache, and build files
```

Suggested layout inside these directories:

- `workloads/<workload>/` — one directory per workload; environments under `workloads/envs/<name>/`.
- `datasets/<dataset>/` — one directory per dataset version.
- `results/<experiment_id>/` — one directory per experiment, never reused.
- `traces/<experiment_id>/` — traces produced by an experiment.
- `checkpoints/<experiment_id>/` — checkpoints produced by an experiment.
- `tmp/` — disposable. Anything here may be deleted when no job is running.

State observed on 2026-11-11:

| Item | Value | Source |
|---|---|---|
| Mount | `/mnt/beegfs`, type `beegfs`, read-write | `findmnt`, `mount` |
| `/mnt/beegfs/ghu4` | owned by `ghu4:ncsu`, writable | `ls -ld`, write probe |
| Total / used / available | 127T / 100T / 27T (79% used) | `df -h` |
| Per-user quota | reported as 0 bytes used, unlimited | `beegfs-ctl --getquota --uid` |
| Group quota (`ncsu`) | reported as 0 bytes used, unlimited | `beegfs-ctl --getquota --gid` |
| Client `quotaEnabled` | `false` | `/etc/beegfs/beegfs-client.conf` |
| Storage targets | 14 targets of 9239.5 GiB, each 14-25% free | `beegfs-df` |
| Default stripe pattern | RAID0, 512K chunks, 4 targets | `beegfs-ctl --getentryinfo` |

How to read this:

- The 27T shown by `df` is shared by all BeeGFS users. It is not reserved for
  this project and can shrink at any time.
- Quota tracking appears to be disabled: the tool reports 0 bytes used although
  `/mnt/beegfs/ghu4` already contains data. No per-user limit was found, which
  also means nothing stops this project from filling the shared file system.
  Size large writes deliberately.
- Files are striped over 4 targets. A write can fail when an individual target
  fills up even if `df` still shows free space. The emptiest target had 2291 GiB
  free and the fullest 1274 GiB free.
- Existing directories in `/mnt/beegfs/ghu4` (`envs`, `hvac`, `kvadm`,
  `restore`) belong to other work and must not be modified.
- The CosmoFlow datasets and the TensorFlow environment from earlier work live
  in `hvac/` and `envs/`, outside this project root. They are read in place
  and not copied ([workload_configs/cosmoflow/README.md](../workload_configs/cosmoflow/README.md)).
- BeeGFS file data is not kept in the client page cache on c28, and repeated
  reads appear to be served from the storage servers' caches
  ([hardware/c28.md](../hardware/c28.md), section 3.1).

Check usage:

```bash
df -h /mnt/beegfs
beegfs-df
du -sh "$CXL_TRAINING_DATA_ROOT"/*
```

## 3. Environment variable

All scripts locate large data through one variable:

```bash
export CXL_TRAINING_DATA_ROOT=/mnt/beegfs/ghu4/cxl-train-cache
```

Rules:

- Source code and scripts read `CXL_TRAINING_DATA_ROOT`. They do not contain
  `/mnt/beegfs/...` or any other machine-specific path.
- Scripts fail with a clear error when the variable is unset. They do not fall
  back to a path in the home directory.
- The example configuration is [configs/env.example.sh](../configs/env.example.sh).
  Copy it to `configs/env.local.sh` (git-ignored) and `source` it. Shell startup
  files are not modified automatically.

## 4. Temporary files, caches, and build outputs

Many tools write to the home directory or the working directory by default.
Redirect them before installing or running anything large. The optional exports
are listed, commented out, in [configs/env.example.sh](../configs/env.example.sh).

| Purpose | Typical default | Use instead | How |
|---|---|---|---|
| Training temporary files | `/tmp` or `$TMPDIR` | `$CXL_TRAINING_DATA_ROOT/tmp` | `export TMPDIR=...` |
| Large build directories | `./build` in the repository | `$CXL_TRAINING_DATA_ROOT/tmp/build/<name>` | out-of-tree build, e.g. `cmake -B "$CXL_BUILD_DIR/<name>"` |
| pip cache | `~/.cache/pip` | `$CXL_TRAINING_DATA_ROOT/tmp/pip-cache` | `export PIP_CACHE_DIR=...` |
| conda package cache | `~/.conda/pkgs` | `$CXL_TRAINING_DATA_ROOT/tmp/conda-pkgs` | `export CONDA_PKGS_DIRS=...` |
| Python environments | `~/.conda/envs`, `./.venv` | `$CXL_TRAINING_DATA_ROOT/workloads/envs/<name>` | `conda create --prefix ...` or `python -m venv <path>` |
| Dataset download caches | `~/.cache`, `~/tensorflow_datasets`, `~/.keras` | `$CXL_TRAINING_DATA_ROOT/tmp/...`, final data in `datasets/` | `XDG_CACHE_HOME`, `TFDS_DATA_DIR`, `KERAS_HOME`, `HF_HOME` |
| Checkpoints | working directory | `$CXL_TRAINING_DATA_ROOT/checkpoints/<experiment_id>` | pass the path to the training script |
| Profiling outputs and traces | working directory | `$CXL_TRAINING_DATA_ROOT/traces/<experiment_id>` | pass the path to the profiler (`perf record -o`, `strace -o`, ...) |
| Raw results and logs | working directory | `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>` | pass the path to the run script |

Notes:

- Small in-repository builds are fine: `build/` is git-ignored. Move a build to
  BeeGFS when it grows beyond a few hundred MB.
- BeeGFS is slow for workloads with very many small files (package caches,
  build trees). Node-local scratch (`/tmp`, `/mnt/local`) is faster but is
  shared, machine-local, and not backed by this project's directory layout. Use
  it only for disposable data and clean up afterwards.
- Storage location is part of an experiment's configuration. A benchmark that
  reads from `/mnt/local` measures a different system than one that reads from
  BeeGFS. Record the path in the experiment metadata.
- Nothing is installed and no environment is created by the repository setup.

## 5. What goes where: quick reference

| Artifact | Location |
|---|---|
| Code, docs, configs, tests | Git repository |
| Experiment report | `docs/experiments/<experiment_id>.md` |
| Experiment metadata, summary tables, small figures | `experimental_results/<experiment_id>/` |
| Raw measurements, logs | `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/` |
| Access and I/O traces, profiles | `$CXL_TRAINING_DATA_ROOT/traces/<experiment_id>/` |
| Datasets | `$CXL_TRAINING_DATA_ROOT/datasets/<dataset>/` |
| Workload code and environments | `$CXL_TRAINING_DATA_ROOT/workloads/` |
| Checkpoints | `$CXL_TRAINING_DATA_ROOT/checkpoints/<experiment_id>/` |
| Disposable files | `$CXL_TRAINING_DATA_ROOT/tmp/` |

Rule of thumb for the repository: individual tracked files stay below about
1 MB. Anything larger goes to BeeGFS and is referenced by path.
