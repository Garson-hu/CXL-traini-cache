# Work Log

Chronological research and development log. Newest entry first.

Add an entry after every meaningful change or work session. Write what was
actually done and actually verified. If something was not checked, say so.

## Entry format

```markdown
## YYYY-MM-DD — <Short title>

- **Date:** YYYY-MM-DD
- **Objective:** What this session set out to do.
- **Changes:** What was changed or produced.
- **Files affected:** Paths in the repository, and external locations.
- **Verification performed:** Checks that were actually run, with outcome.
- **Results:** Findings. Label measurements as real hardware, simulation, or analytical.
- **Open questions:** Unresolved issues and things not verified.
- **Next steps:** What should happen next.
```

---

## 2026-11-12 — Storage root renamed, DAX usage recorded, first commit

- **Date:** 2026-11-12
- **Objective:** Apply three decisions of the user: rename the BeeGFS project
  root, record who uses the DAX devices, and make the first commit and push.
- **Changes:**
  - Renamed the BeeGFS project root from
    `/mnt/beegfs/ghu4/cxl-training-cache` to `/mnt/beegfs/ghu4/cxl-train-cache`
    (`mv`, same parent directory). It contained only the marker `README.md`
    and six empty subdirectories created by this project. The marker file's
    title was updated.
  - Updated the path in `CLAUDE.md`, `README.md`, `docs/storage.md`,
    `docs/decisions.md` (D002, with a dated amendment note), and
    `configs/env.example.sh`. The environment variable name
    `CXL_TRAINING_DATA_ROOT` is unchanged.
  - Recorded the user's statement that only this user uses `/dev/dax0.0` and
    `/dev/dax1.0` in `hardware/c28.md`, `CLAUDE.md`, and
    `docs/experiment_plan.md`.
  - Removed the resolved root-name item from
    `workload_configs/cosmoflow/README.md`.
  - First commit on `main`, remote `origin` added, pushed.
- **Files affected:** the files named above, `WORKLOG.md`, and externally
  `/mnt/beegfs/ghu4/cxl-train-cache/` (renamed).
- **Verification performed:**
  - Before the rename: the old root held exactly eight entries, all created
    by this project; the new name did not exist.
  - After the rename: the new root exists with all six subdirectories
    writable; the old name is gone; the other directories in
    `/mnt/beegfs/ghu4` are unchanged.
  - `configs/env.example.sh` sourced in a subshell resolves to the new root.
  - No reference to the old name remains outside this log and the amendment
    note in `docs/decisions.md`.
  - Markdown links re-checked.
- **Results:** No experimental results.
- **Open questions:**
  - Carried over from the previous entry, except the two that are now
    answered (root name; other users of `dax0.0` and `dax1.0`).
  - Earlier entries in this log keep the old root name. They describe the
    state at that time.
- **Next steps:** Write the E001 harness and run the reduced first pass, once
  the user gives the go-ahead.

## 2026-11-11 — Environment and workload characterization

- **Date:** 2026-11-11 (about 23:00 to 23:40)
- **Objective:** Audit the hardware and the CosmoFlow workload read-only,
  document the data-loading pipeline, and design the first performance
  experiment. No training experiment, no benchmark, no cache code.
- **Changes:**
  - Rewrote `hardware/c28.md` and `hardware/c33.md` with the audit results,
    separating provided context, verified information, lightweight
    validations, and historical measurements with their source.
  - Rewrote `workload_configs/cosmoflow/README.md` as the workload audit:
    locations, the eight audit questions, the data-loading pipeline, and
    possible cache insertion points.
  - Added `docs/experiments/001-training-io-characterization-plan.md`
    (experiment `E001-training-io-characterization`, planned, not run). It
    replaces the candidate name `E001-cosmoflow-io-headroom` used in the
    previous entry.
  - Brought statements that the audit made stale up to date in `README.md`,
    `CLAUDE.md`, `docs/project_overview.md`, `docs/experiment_plan.md`, and
    `docs/storage.md`.
  - Nothing was committed.
- **Files affected:**
  - `hardware/c28.md`, `hardware/c33.md`
  - `workload_configs/cosmoflow/README.md`
  - `docs/experiments/001-training-io-characterization-plan.md` (new)
  - `README.md`, `CLAUDE.md`, `docs/project_overview.md`,
    `docs/experiment_plan.md`, `docs/storage.md`, `WORKLOG.md`
  - External: nothing created or changed. Read only:
    `/mnt/beegfs/ghu4/hvac`, `/mnt/beegfs/ghu4/envs`,
    `~/hvac/benchmark/cosmoflow-benchmark-master`, `~/CXL` (through
    `git show`, no checkout), `/mnt/local/ghu4` (listing only).
- **Verification performed:**
  - Hardware read with `lscpu`, `/proc/meminfo`, `lsmem`, `numactl`,
    `nvidia-smi`, `cxl list`, `daxctl list`, `/proc/iomem`, `findmnt`,
    `beegfs-ctl`, `beegfs-net`, `beegfs-check-servers`, `sinfo`, `scontrol`,
    `squeue`.
  - DAX access checked with `stat`, `access(2)`, and a read-only open and
    close. Nothing was mapped, read, or written.
  - Dataset: every file of `train_61440/train` was `stat`-ed (61,440 files,
    178,071,110,206 bytes). Directory entry counts of the full dataset read.
    One file checked for the gzip signature and decompressed to count bytes.
  - Code: `data/cosmo.py`, `train.py`, the configuration, and `train_trace.py`
    were read. The prefetch default and the reader buffer size were looked up
    in the installed TensorFlow 2.14.0 source.
  - Lightweight validation 1: 16 files (46 MB) read three times from BeeGFS
    with page-cache residency checked by `fincore`.
  - Lightweight validation 2: the CosmoFlow model run for six steps per batch
    size on synthetic tensors on the GPU. No dataset I/O, no files written.
  - Afterwards: no file in the benchmark directory, `~/CXL`, or the dataset
    directories is newer than the start of the session; no tmpfs files were
    left; the GPU is idle.
  - Markdown links and repository paths in all documents re-checked.
  - Not done: no training on real data, no bandwidth measurement, no CXL
    access beyond opening the device nodes, no login to c33.
- **Results:** No experimental results. Findings of the audit:
  - **Workload exists.** Benchmark code in
    `~/hvac/benchmark/cosmoflow-benchmark-master` (modified copy, no Git
    history), environment `hvac_tf` (TensorFlow 2.14.0) on BeeGFS, full
    dataset (524,288 / 65,536 / 32,768 files) and the 61,440-file and
    1,024-file subsets on BeeGFS under `hvac/`.
  - **Provenance of the historical numbers found.** `~/CXL`, branch
    `explore/reuse-window-prefetch`: run records, job scripts, the trainer
    `train_trace.py`, and BeeGFS bandwidth files for c33 and c28.
  - **Format.** One sample per file, gzip TFRecord, 2.9 MB compressed,
    16.8 MB decompressed (ratio about 5.8).
  - **Pipeline.** The benchmark reads one file at a time with one parse
    thread and no explicit prefetch. The earlier c33 run used a different,
    parallel pipeline (8 readers, 4 parse threads, prefetch 8) with an
    explicit seeded order.
  - **GPU (real hardware, six-step check).** The model runs on the RTX 4060 Ti
    at batch size 1 and 2 and fails at 4. Indicated compute rate roughly
    11-13 samples/s, against 74.9 samples/s recorded on the A100.
  - **Page cache (real hardware, 16 files).** BeeGFS reads leave nothing in
    the client page cache; first read 28.8 MB/s, re-reads about 900 MB/s.
  - **CXL access changed.** `/dev/dax0.0` and `/dev/dax1.0` became
    `root:kmem 0660` at 22:32 and can now be opened by this user. The previous
    entry's statement that all DAX devices are root-only was true at 21:22 and
    is outdated for these two. `dax2.0` is unchanged.
  - **BeeGFS incident.** For about two minutes around 23:03 the project root
    could not be `stat`-ed (metadata node c2, "Communication error on send").
    It recovered by itself.
- **Open questions:**
  - Storage root name: the task for this session names
    `/mnt/beegfs/ghu4/cxl-train-cache`, which does not exist. The root created
    in the previous session and used by all documents is
    `/mnt/beegfs/ghu4/cxl-training-cache`. Which name is intended? Nothing was
    created or renamed.
  - Who changed the DAX permissions, is the change persistent, and does anyone
    else use `dax0.0` or `dax1.0`? Mapping or writing them needs approval.
  - Real training on c28 creates about one sixth of the A100's data demand.
    If the first experiment confirms that it is GPU-bound, where does the
    project get a setting with enough demand: emulated consumers, several
    concurrent jobs, or other hardware?
  - Is the fast re-read on BeeGFS really served by the storage servers, and
    how long does it last under other users' load? A client-side cache has to
    beat warm BeeGFS, not only cold BeeGFS.
  - Should the cache hold compressed files or decoded samples? Decoded data is
    5.8 times larger and is the case where capacity is scarce.
  - The benchmark copy has no version history. Should it be pinned by a
    checksum, or replaced by the MLPerf HPC reference implementation?
  - The script behind the earlier BeeGFS bandwidth probes was not found.
- **Next steps:**
  - Decide the storage root name.
  - Write the harness `scripts/e001_io_characterization.py` (input pipeline
    after `train_trace.py`, with its origin stated) and run the reduced first
    pass of E001: raw read, loader-only (`seq` and `par(8)`), and compute-only.
    About 15 minutes on c28, no CXL, no root.
  - Then the full E001 matrix with instrumented training.

## 2026-11-11 — Repository initialization

- **Date:** 2026-11-11
- **Objective:** Establish the project structure, documentation, storage
  organization, and development conventions. No system implementation and no
  experiments.
- **Changes:**
  - Initialized a Git repository in `/home/ghu4/cxl-train-cache` on branch
    `main`. Nothing was committed or pushed.
  - Created the directory structure and initial documentation.
  - Created the BeeGFS project root `/mnt/beegfs/ghu4/cxl-training-cache`
    with `workloads/`, `datasets/`, `checkpoints/`, `traces/`, `results/`,
    `tmp/`, and a short `README.md` describing the layout.
  - Added `.claude/settings.json` so that Claude Code asks for confirmation
    before `sudo` and common device-changing commands.
  - Additions beyond the requested structure: `docs/storage.md` and
    `configs/env.example.sh`.
- **Files affected:**
  - `README.md`, `CLAUDE.md`, `WORKLOG.md`, `.gitignore`, `.claude/settings.json`
  - `docs/project_overview.md`, `docs/research_questions.md`,
    `docs/related_work.md`, `docs/experiment_plan.md`, `docs/decisions.md`,
    `docs/storage.md`, `docs/experiments/TEMPLATE.md`
  - `hardware/c28.md`, `hardware/c33.md`
  - `workload_configs/cosmoflow/README.md`, `system/README.md`,
    `benchmarks/README.md`, `simulator/README.md`, `scripts/README.md`,
    `configs/README.md`, `configs/env.example.sh`, `tests/README.md`
  - `experimental_results/README.md`, `experimental_results/metadata_template.json`
  - External: `/mnt/beegfs/ghu4/cxl-training-cache/` (new)
- **Verification performed:**
  - Directory was empty and not inside a Git repository before `git init`.
  - Home quota read with `quota -s`.
  - BeeGFS: mount type and options (`findmnt`, `mount`), ownership and write
    access of `/mnt/beegfs/ghu4` (empty probe file created and removed),
    capacity (`df -h`, `beegfs-df`), quota (`beegfs-ctl --getquota`), stripe
    pattern (`beegfs-ctl --getentryinfo`). The target directory did not exist
    before creation. Existing directories were not touched.
  - All six BeeGFS subdirectories exist and are writable.
  - Read-only hardware inspection of c28: `lscpu`, `free`, `numactl -H`,
    `nvidia-smi`, `lspci`, `cxl list`, `daxctl list`, `lsblk`, `findmnt`.
  - All expected files exist and are non-empty.
  - `experimental_results/metadata_template.json` and `.claude/settings.json`
    parse as valid JSON.
  - `configs/env.example.sh` passes `bash -n` and, sourced in a subshell, sets
    `CXL_TRAINING_DATA_ROOT` to an existing directory.
  - Relative Markdown links and backticked repository paths in all `.md` files
    resolve to existing files.
  - `.gitignore` tested with `git check-ignore` against sample paths: data,
    checkpoints, traces, raw results, environments, build output, and local
    configuration are ignored; source, documentation, templates, summaries,
    and configurations are not.
  - Repository size is about 140 KB excluding `.git` (24 files).
  - Venue, year, and authors of the three papers in `docs/related_work.md`
    were checked by web search. The papers themselves were not read.
- **Results:** No experimental results. Environment facts observed (details in
  `docs/storage.md` and `hardware/c28.md`):
  - Home: 26,759 MiB used of a 39,936 MiB soft / 40,960 MiB hard limit.
  - BeeGFS: 27T available of 127T, shared. Quota is not enabled; no per-user
    limit was found.
  - c28: AMD EPYC 9745 (128 cores, 256 threads), about 755 GiB DRAM on one
    online NUMA node, RTX 4060 Ti 8 GB, four 256 GiB Micron CXL devices, three
    devdax devices totalling 1024 GiB.
  - `/dev/dax*` are accessible to root only. `/dev/dax2.0` is in use by a
    famfs mount at `/mnt/famfs/dax2.0`.
  - BeeGFS client uses `tuneFileCacheType = buffered`.
- **Open questions:**
  - How will this project get access to CXL memory on c28? All options need
    administrator action and approval.
  - Who owns the famfs mount on `dax2.0`, and is any DAX device free to use?
  - Why are CXL memdevs `mem0` and `mem2` reported as disabled?
  - Does BeeGFS in `buffered` mode keep file data in the client page cache
    across epochs? Assumed not; unmeasured.
  - Where are the scripts and raw data of the earlier c33 experiments, and
    which CosmoFlow implementation and dataset version did they use?
  - The 178 GB dataset fits in both DRAM and CXL memory on c28. Which
    capacity-constrained settings are realistic enough to study?
  - c28 has CXL memory but a small GPU; c33 has an A100 but no CXL memory in
    this project. How will an integrated end-to-end measurement be obtained?
  - Analytical note A1 (`docs/research_questions.md`) argues that static
    pinning is optimal for single-job once-per-epoch access. Not yet checked
    by simulation.
  - `/mnt/local/train_cache` and `/mnt/local/ghu4` exist from earlier work and
    were not inspected.
- **Next steps:**
  - Review the initial documents, then make the first commit.
  - Proposed first experiment (not started): `E001-cosmoflow-io-headroom`,
    comparing CosmoFlow input-pipeline throughput from BeeGFS and from memory
    on c28. See `docs/experiment_plan.md`.
  - Before that: record the CosmoFlow implementation and dataset version, and
    place workload and data under `$CXL_TRAINING_DATA_ROOT`.
  - Read the three papers in `docs/related_work.md`.
