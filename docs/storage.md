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
- `results/<experiment>/` — one directory per experiment, never reused.
- `traces/<experiment>/` — traces produced by an experiment.
- `checkpoints/<experiment>/` — checkpoints produced by an experiment.
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

Read behaviour that experiments have to plan for (**[Observed]**, experiments
`2026-11-12-remote-cxl-data-path`, `2026-11-16-workload-io-validation`, and
`2026-11-17-multi-gpu-io-saturation` in
[experiments/INDEX.md](experiments/INDEX.md)):

- **Two speeds.** A file the storage servers hold in memory is read at 2 to
  12 GB/s by one client; a file they do not hold comes from their disks at
  0.05 to 0.1 GB/s per stream.
- **First-read supply is shared.** It grows with the total number of
  concurrent streams, whichever clients they come from: about 0.36, 0.57,
  and 0.74 GB/s at 8, 16, and 32 streams. A measurement of cold reads
  competes with every other cold reader on the cluster, including this
  project's own jobs.
- **The supply has a ceiling near 0.8 GB/s.** On 2026-11-17, 20 training
  jobs with 160 read streams got 0.76 GB/s of first reads, and the storage
  servers delivered 0.80 GB/s to all clients, with 43 requests queued on
  average; 40 streams got 0.69 GB/s. Recently read data came out at 0.95 GB/s
  for the same jobs without any queue, so the ceiling is the disks.
- **The time to get one cold file grows with the load**, from about 45 ms
  with few readers to about 120 ms when 20 jobs read 0.69 GB/s (derived from
  training runs). It was 60% longer in the first run of that day than later
  at the same load, for a reason that was not found.
- **The servers' counters are readable.** `beegfs-ctl --serverstats
  --nodetype=storage` gives bytes read and written per second, queue length,
  and busy worker threads for all clients, without privileges. Log it during
  every measurement of cold reads: it is the only view of other users' I/O.
- **Residency is short and depends on the read history.** On 2026-11-16,
  files read once were in memory after 15 minutes and gone after 60; files
  read twice within two minutes were still in memory after one and two hours
  and gone after four; files read 18 to 19 hours earlier were gone, however
  often they had been read. This project's own experiments read 60 GB for
  the first time in the first hour and about 190 GB more between the second
  and the fourth: a few training jobs' worth of reads turns the storage
  servers' memory over within hours.
- **That residency is measured with one thread, and one thread does not say
  what many readers get.** On 2026-11-17
  (`2026-11-17-cxl-cache-integration`) 44.5 GB that had been read once were
  probed 90 minutes later: 21 ms per file, 0.14 GB/s, cold by the measure
  above. Five minutes after the probe 20 training jobs re-read all of it at
  1.0 GB/s with a short queue at the storage servers and without waiting,
  where never-read files gave the same jobs 0.76 to 0.86 GB/s. Why was not
  examined (files partly in memory, cached file system metadata on the
  servers, and other users' load are untested candidates). Before relying on
  data being cold for many readers, measure it with many readers.
- **How the storage serves many readers, measured on 2026-11-18**
  (`2026-11-18-large-working-set-reuse`, with disk counters read on the
  storage servers):
  - A storage target is one 10 TB hard disk with ext4; 14 targets, no RAID;
    a 2.9 MB file needs four of them. The disks give 0.66 to 0.78 GB/s of
    cold bytes to 160 streams, about 50 MB/s each. One server (c14) is the
    slow one on both days: its disks are 74% to 94% busy and the requests
    queue there while the other servers have spare time. Why was not
    examined.
  - Supply = that cold ceiling divided by the share of the bytes that has
    to come from disk. Half of the bytes in memory doubles what all readers
    get. 20 training jobs (0.96 GB/s) wait only above a cold share of 0.7
    to 0.85.
  - One thread times a file by its slowest chunk: a cohort with half of its
    chunks in memory reads "cold" (median 20 ms, a few files at 2 ms). To
    know what many readers will get, read the servers' disk counters or
    read with many streams.
  - What a server keeps: data read twice or more stays for a day as long
    as the server has room; data read once stays until newer data has
    filled the server's free memory and inactive file list (tens of GiB).
    Under 20 to 26 jobs reading the full dataset a server holds the last 6
    to 10 minutes of what it read, a second read adds a few minutes, and
    everything older goes, including what earlier experiments had left.
  - A server that runs another user's job keeps less than the others.
  - Read-only monitoring: a Slurm job on a storage server can read
    `/proc/diskstats`, `/proc/meminfo`, and `/proc/vmstat`; the chunk
    directories are not readable. Slurm gives such a job the whole node
    even if it asks for one CPU (`hardware/c39.md`, section 5), so the
    server must be free of other jobs and is kept from them meanwhile.
  - A file that a job on another node is still writing is not readable
    from c28 until the job closes it (the BeeGFS client buffers writes):
    logs of running jobs cannot be followed from the launch node. Files
    written line by line with open, append, close are visible at once.
- **A memory pass reads the files a second time.** The training harness
  copies a job's files from BeeGFS to tmpfs for its memory-resident pass, so
  the files of a run with such a pass have been read twice within minutes
  and stay in the storage servers' memory longer than files read once. Say
  which it was when such files are reused later.
- **Runs with the same seeds read the same files.** Consecutive
  configurations of an experiment that give their jobs the same seeds ask
  for the same files in the same order, and the later run gets them from
  the storage servers' memory if the earlier one read them minutes before
  (seen on 2026-11-24 in `2026-11-24-large-scale-cache-evaluation`: 82% to
  95% of a cache's misses read in 1 to 2 ms instead of 26 ms). Give every
  configuration its own seed base, or enough unrelated traffic in between,
  and say which.
- **Other users' reads share the disks.** On the evening of 2026-11-24
  they were 0.22 to 0.34 GB/s, a quarter to a third of the cold supply.
  Record the BeeGFS servers' statistics before every run. Reading with
  hundreds of streams from many nodes leaves other users almost nothing
  (0.02 to 0.07 GB/s in those tests); keep such runs short.
- **The storage servers are also compute nodes**, with 93 GiB of memory each
  on the three inspected ([hardware/c39.md](../hardware/c39.md), section 5).
  **[Analytical]** About 630 GiB of file data can be in their memory at most.
- Consequences: state for every read whether the file was a first read, a
  re-read within minutes, or of unknown history; never assume that data read
  earlier in the day is still warm; choose never-read files for cold
  measurements and keep a ledger; nothing may be evicted on purpose
  ([CLAUDE.md](../CLAUDE.md), hardware safety).

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
| Checkpoints | working directory | `$CXL_TRAINING_DATA_ROOT/checkpoints/<experiment>` | pass the path to the training script |
| Profiling outputs and traces | working directory | `$CXL_TRAINING_DATA_ROOT/traces/<experiment>` | pass the path to the profiler (`perf record -o`, `strace -o`, ...) |
| Raw results and logs | working directory | `$CXL_TRAINING_DATA_ROOT/results/<experiment>` | pass the path to the run script |

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
| Record of which experiments were done | `docs/experiments/INDEX.md` (tracked) |
| Experiment plan, summary, metadata, small tables and figures | `experimental_results/<YYYY-MM-DD-name>/` (local, not tracked) |
| Slides | `docs/slides/` (local, not tracked) |
| Raw measurements, logs | `$CXL_TRAINING_DATA_ROOT/results/<experiment>/` |
| Access and I/O traces, profiles | `$CXL_TRAINING_DATA_ROOT/traces/<experiment>/` |
| Datasets | `$CXL_TRAINING_DATA_ROOT/datasets/<dataset>/` |
| Workload code and environments | `$CXL_TRAINING_DATA_ROOT/workloads/` |
| Checkpoints | `$CXL_TRAINING_DATA_ROOT/checkpoints/<experiment>/` |
| Disposable files | `$CXL_TRAINING_DATA_ROOT/tmp/` |

Rule of thumb for the repository: individual tracked files stay below about
1 MB. Anything larger goes to BeeGFS and is referenced by path.
