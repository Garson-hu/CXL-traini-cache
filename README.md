# CXL-Based Training Data Caching

A PhD systems research project on using CXL memory as a large-capacity cache
for machine learning training data.

> **Status:** **a minimal cache prototype exists** ([system/](system/README.md),
> 2026-11-17): one server with its store in CXL memory, the simulator's
> replacement policies, and CosmoFlow's input pipeline reading through it. The
> repository also holds documentation, audits, the trace-driven policy
> simulator, two simulation experiments, a data-path benchmark, a training I/O
> harness, and hardware experiments on the remote data path, on training I/O
> without a cache (up to 20 concurrent jobs), and on the prototype. With 20
> jobs on never-read data, serving half of the bytes from the cache restored
> the full training rate (21% above direct BeeGFS on such data). Direct
> BeeGFS reached the same rate on data that had been read 10 to 95 minutes
> before, so no gain of the cache over direct BeeGFS on reused data has been
> measured, and a capacity-limited cache with a policy has not yet been
> shown to shorten training. On 2026-11-18 the reason was measured: the
> shared storage supplies its cold limit divided by the share of bytes that
> comes from disk, the storage servers' memory serves 40% of the bytes of 20
> jobs even on the full dataset, and those jobs do not wait; a stall begins
> at about 26 jobs. On 2026-11-24 the research idea was refined: known-order
> replacement is to be combined with two-epoch lookahead and asynchronous
> prefetching. A minimal version of both was built and measured the same
> day with four training jobs: prefetching removes the waiting of jobs with
> one read stream on cold files (39.5% to 0.5%), which eight read streams in
> the job also do; the longer lookahead changed no waiting.

## 1. Project overview

Data-intensive training workloads read their dataset from storage once per
epoch. This project investigates whether keeping training data in CXL memory
between epochs reduces storage I/O and whether that makes training faster.

The research is meant to be driven by measurements: a mechanism is only
proposed once a bottleneck has been shown. More in
[docs/project_overview.md](docs/project_overview.md).

## 2. Primary research goal

**How can CXL memory be effectively used and managed as a training data cache
to reduce storage I/O overhead and improve end-to-end training performance?**

Fixed direction: **Online Reuse-Aware CXL Caching for Distributed Training**,
a shared CXL-based training data cache that exploits cross-job reuse and
future access sequences provided by the applications. The mechanism under
study since 2026-11-24 combines the existing known-order replacement with
two-epoch lookahead and asynchronous prefetching; the last two are not
implemented.

The research questions are in
[docs/research_questions.md](docs/research_questions.md), the idea and the
state of its parts in [docs/research_idea.md](docs/research_idea.md).

## 3. Initial workload: CosmoFlow

The first target workload is CosmoFlow. The configuration used in earlier
experiments (historical context, not reproduced in this repository):

- 61,440 TFRecord files, approximately 178 GB.
- Three epochs, file order shuffled each epoch.
- Each file read once per epoch, so all reuse is across epochs.

The benchmark code, a TensorFlow environment, and the datasets exist on this
cluster from earlier work and are used in place. See
[workload_configs/cosmoflow/README.md](workload_configs/cosmoflow/README.md).

## 4. Conceptual CXL caching architecture

```text
Persistent Storage (BeeGFS / NVMe)
              |
              v
      CXL Training Data Cache
              |
              v
       CPU / DataLoader
              |
              v
          GPU Training
```

This diagram is conceptual. The actual data path may involve DRAM buffers,
memory mapping, decoding, and prefetching. No implementation architecture has
been chosen.

## 5. Repository structure

```text
.
├── .claude/                  Claude Code project settings
├── CLAUDE.md                 Long-term working rules for Claude sessions
├── README.md
├── WORKLOG.md                Chronological research and development log
├── .gitignore
├── docs/
│   ├── project_overview.md   Motivation and current state of knowledge
│   ├── research_idea.md      The research idea, first evidence, refined hypotheses
│   ├── workload_selection.md Comparison of candidate workloads
│   ├── research_questions.md Tentative research questions and hypotheses
│   ├── related_work.md       Literature tracking
│   ├── experiment_plan.md    Phased experimental roadmap
│   ├── decisions.md          Architecture and research decision log
│   ├── storage.md            Storage layout, quotas, cache redirection
│   ├── experiments/
│   │   ├── INDEX.md          One row per experiment: the tracked record
│   │   └── TEMPLATE.md       Template of an experiment summary
│   └── slides/               Slides, local only (not tracked)
├── hardware/
│   ├── c28.md                CXL and development machine
│   └── c33.md                A100 machine of the earlier experiments
├── workload_configs/
│   └── cosmoflow/            Lightweight CosmoFlow configs and instructions
├── system/                   Minimal shared CXL cache: server, client, checker
├── benchmarks/               Future microbenchmarks (empty)
├── simulator/
│   └── cachesim.py           Trace-driven cache policy simulator
├── scripts/                  Trace conversion and generation scripts
├── configs/
│   └── env.example.sh        Example environment configuration
├── tests/
│   ├── test_cachesim.py      Simulator tests
│   └── test_cc_manager.py    Tests of the cache manager
└── experimental_results/
    ├── README.md
    ├── metadata_template.json
    └── YYYY-MM-DD-<name>/    One directory per experiment, local only (not tracked)
```

## 6. Storage organization

The home directory has a strict 40 GB quota, so the repository holds only
lightweight files. Everything large lives on BeeGFS.

| Location | Content |
|---|---|
| Git repository (home) | Code, documentation, configurations, tests, and the experiment index |
| `experimental_results/<YYYY-MM-DD-name>/` (home, not tracked) | Each experiment's plan, summary, and small results |
| `docs/slides/` (home, not tracked) | Slides |
| `/mnt/beegfs/ghu4/cxl-train-cache` | Workloads, datasets, checkpoints, traces, raw results, temporary files |

```text
/mnt/beegfs/ghu4/cxl-train-cache/
├── workloads/     Workload installations and runtime dependencies
├── datasets/      Training datasets
├── checkpoints/   Training checkpoints and model states
├── traces/        Large access traces, I/O traces, profiling outputs
├── results/       Raw experimental measurements
└── tmp/           Temporary training and benchmarking files
```

CXL memory is an experimental cache tier and is never used as persistent
storage. Details, observed capacity, and how to keep caches and builds out of
the home directory: [docs/storage.md](docs/storage.md).

## 7. Environment variable configuration

Large data is addressed through one environment variable:

```bash
export CXL_TRAINING_DATA_ROOT=/mnt/beegfs/ghu4/cxl-train-cache
```

An example configuration is provided in
[configs/env.example.sh](configs/env.example.sh):

```bash
cp configs/env.example.sh configs/env.local.sh   # git-ignored
source configs/env.local.sh
```

Shell startup files are not modified automatically. Scripts must read
`CXL_TRAINING_DATA_ROOT` and must not hardcode machine-specific paths.

## 8. Current development status

| Component | Status |
|---|---|
| Repository structure, documentation, conventions | Done (2026-11-11) |
| BeeGFS project directories | Created (2026-11-11) |
| CosmoFlow code, environment, and datasets | Found from earlier work and audited (2026-11-11); read in place, nothing installed |
| Hardware and workload audit | Done (2026-11-11) |
| Training I/O characterization | Done (2026-11-16) as `2026-11-16-workload-io-validation`: real training on c28 from BeeGFS and from host memory, loader only, compute only, storage residency, a two-job trace. Outcome in [docs/experiments/INDEX.md](docs/experiments/INDEX.md). The plan of 2026-11-11 was superseded by it. |
| Trace-driven simulator | Minimal policy simulator with tests (2026-11-12) |
| Cache policy comparison by trace replay | First pass done on real and synthetic traces: simulation only |
| Cross-job known-order policy by trace replay | Done (2026-11-12): simulation only; see [docs/experiments/INDEX.md](docs/experiments/INDEX.md) |
| Two-epoch lookahead and asynchronous prefetching (research idea refined 2026-11-24) | Minimal implementation in [system/](system/README.md) and small-scale measurements (`2026-11-24-two-epoch-lookahead-prefetch`, 2026-11-24); not evaluated at scale; see phases 7 to 9 of [docs/experiment_plan.md](docs/experiment_plan.md) |
| Full-scale evaluation (full dataset, 40 jobs, 256 GiB in CXL memory) | Preliminary validation, pilot, and the fixes and checks for the comparison done (`2026-11-24-large-scale-cache-evaluation`, 2026-11-24); the comparison of the five runs is approved and queued, not run yet (it starts when disk counters run on the storage servers) |
| Microbenchmarks | Remote cache data-path benchmark ([benchmarks/remote_cache/](benchmarks/remote_cache/README.md), 2026-11-12); training I/O harness ([benchmarks/train_io/](benchmarks/train_io/README.md), 2026-11-16) |
| CXL cache system | Minimal prototype ([system/](system/README.md), 2026-11-17): one server, C data plane, Python control plane with the simulator's policies; correctness and decisions verified; not a finished system |
| Hardware experiments | `2026-11-12-remote-cxl-data-path` done (2026-11-15): direct BeeGFS, remote DRAM, remote CXL, admission, concurrent reads and writes, and an I/O replay of the two-job trace. Outcome in [docs/experiments/INDEX.md](docs/experiments/INDEX.md). No training run. `2026-11-16-workload-io-validation` done (2026-11-16): the first training measurements, without a cache. `2026-11-16-loader-gpu-scaling` done (2026-11-16): training against the number of read streams and of concurrent jobs (up to eight GPU nodes), without a cache. `2026-11-17-multi-gpu-io-saturation` done (2026-11-17): 7 to 20 concurrent training jobs, to find where shared storage limits them, without a cache. `2026-11-17-cxl-cache-integration` done in reduced form (2026-11-17): the cache prototype, its validation, and the first training runs through it with 20 jobs. `2026-11-18-large-working-set-reuse` done in part (2026-11-18): how the storage serves reused data to many readers, and 20 to 26 emulated jobs on the full dataset without a cache; the cache comparison on the full dataset was not run. |

Earlier CosmoFlow measurements on a different machine (c33) are recorded as
historical context in [hardware/c33.md](hardware/c33.md). They are not results
of this repository and do not show that CXL caching accelerates training.

The latest state is always in [WORKLOG.md](WORKLOG.md).

## 9. Documentation navigation

| Document | Read it for |
|---|---|
| [docs/project_overview.md](docs/project_overview.md) | Motivation, evidence labels, what is and is not known |
| [docs/research_idea.md](docs/research_idea.md) | The research idea, what the first evidence says, refined hypotheses and contributions |
| [docs/research_questions.md](docs/research_questions.md) | Tentative RQ1-RQ3, hypotheses, analytical notes |
| [docs/workload_selection.md](docs/workload_selection.md) | Candidate workloads against the selection criteria |
| [docs/experiments/INDEX.md](docs/experiments/INDEX.md) | Which experiments were done, with a one-line outcome each |
| [docs/experiment_plan.md](docs/experiment_plan.md) | Phased roadmap, experiment ID and location conventions |
| [docs/related_work.md](docs/related_work.md) | Reading list and paper notes |
| [docs/decisions.md](docs/decisions.md) | Why the project is organized the way it is |
| [docs/storage.md](docs/storage.md) | Where data goes, quotas, environment setup |
| [docs/experiments/TEMPLATE.md](docs/experiments/TEMPLATE.md) | Writing an experiment summary |
| [workload_configs/cosmoflow/README.md](workload_configs/cosmoflow/README.md) | CosmoFlow workload audit: data, code, input pipeline, cache insertion points |
| [hardware/c28.md](hardware/c28.md), [hardware/c33.md](hardware/c33.md), [hardware/c39.md](hardware/c39.md) | Machine facts, verified versus provided |
| [experimental_results/README.md](experimental_results/README.md) | How experiments are organized by date, and what stays out of Git |
| [CLAUDE.md](CLAUDE.md) | Working rules: integrity, workflow, hardware safety, storage |
| [WORKLOG.md](WORKLOG.md) | What was done, when, and what is open |
