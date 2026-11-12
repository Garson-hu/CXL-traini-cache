# Architecture and Research Decision Log

Record decisions that shape the system, the experiments, or the research
direction. Add new entries at the end. Do not rewrite old entries: if a
decision is reversed, add a new entry and mark the old one as superseded.

## Entry template

```markdown
## D<NNN>: <Title>

- **Decision ID:** D<NNN>
- **Date:** YYYY-MM-DD
- **Status:** Proposed | Accepted | Superseded by D<NNN>
- **Problem:** What needs to be decided and why now.
- **Alternatives:** Options considered, including doing nothing.
- **Chosen approach:** What was decided.
- **Rationale:** Why this option.
- **Supporting evidence:** Measurements, experiment IDs, documents. State
  "none" when the decision is not based on measurements.
- **Consequences:** What this enables, costs, or rules out.
```

---

## D001: Repository organization

- **Decision ID:** D001
- **Date:** 2026-11-11
- **Status:** Accepted
- **Problem:** The project needs one place for research documents, system
  code, simulation, benchmarks, experiment records, and hardware notes that
  stays navigable as the project grows.
- **Alternatives:**
  1. Single flat repository with ad hoc directories.
  2. Separate repositories for the system, the simulator, and the paper.
  3. One repository with a fixed top-level directory per concern.
- **Chosen approach:** Option 3. Top-level directories: `docs/`, `hardware/`,
  `workload_configs/`, `system/`, `benchmarks/`, `simulator/`, `scripts/`,
  `configs/`, `tests/`, `experimental_results/`. Directories for code that
  does not exist yet contain only a README. One addition to the initial
  specification: `docs/storage.md`, the single reference for storage layout
  and cache redirection, and `configs/env.example.sh`, the example environment.
- **Rationale:** One repository keeps code, the experiments that used it, and
  the claims based on them under the same commit history, which is what
  reproducibility needs. Placeholder READMEs fix where things go without
  committing to an internal design.
- **Supporting evidence:** None. Organizational decision.
- **Consequences:** No internal architecture for `system/` or `simulator/` is
  implied. Splitting a component into its own repository later remains
  possible. No build system, framework, or dependency is introduced yet.

## D002: Storage separation between home and BeeGFS

- **Decision ID:** D002
- **Date:** 2026-11-11
- **Status:** Accepted
- **Problem:** The home directory has a strict 40 GB quota, of which about
  26 GiB was already in use on 2026-11-11. Workloads, datasets (about 178 GB
  for CosmoFlow), traces, checkpoints, and raw results do not fit.
- **Alternatives:**
  1. Keep everything in the repository and rely on `.gitignore`.
  2. Keep large data on node-local NVMe (`/mnt/local`).
  3. Keep the repository in home and all large data under a dedicated BeeGFS
     root, addressed through one environment variable.
- **Amended 2026-11-12:** the root was created as
  `/mnt/beegfs/ghu4/cxl-training-cache` and renamed to
  `/mnt/beegfs/ghu4/cxl-train-cache` at the user's request, to match the
  repository name. The decision itself is unchanged.
- **Chosen approach:** Option 3. Large data lives under
  `/mnt/beegfs/ghu4/cxl-train-cache` with subdirectories `workloads/`,
  `datasets/`, `checkpoints/`, `traces/`, `results/`, `tmp/`. Code refers to
  it only through `CXL_TRAINING_DATA_ROOT`. The repository holds small
  summaries and references to raw results. Details: [storage.md](storage.md).
- **Rationale:** Option 1 still consumes home quota. Option 2 is machine-local
  and shared, and BeeGFS is also the storage system whose I/O the project
  studies. One environment variable keeps machine-specific paths out of code.
- **Supporting evidence:** Read-only checks on 2026-11-11: `quota -s` for home;
  mount, write access, and capacity for BeeGFS. Recorded in
  [storage.md](storage.md).
- **Consequences:** Raw results are not versioned by Git, so each experiment
  must record its raw result path and Git commit in its metadata. BeeGFS shows
  no per-user quota, so the project has to watch its own usage of the shared
  file system. CXL memory is not a storage location: it is a cache tier only.
