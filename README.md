# CXL-Based Training Data Caching

A PhD systems research project on using CXL memory as a large-capacity cache
for machine learning training data.

> **Status:** the repository is initialized with structure, documentation, and
> conventions only. **The CXL caching implementation has not been developed.**
> No simulator, benchmark, or experiment exists yet, and this repository
> contains no performance results.

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

The tentative research questions are in
[docs/research_questions.md](docs/research_questions.md).

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
│   ├── research_questions.md Tentative research questions and hypotheses
│   ├── related_work.md       Literature tracking
│   ├── experiment_plan.md    Phased experimental roadmap
│   ├── decisions.md          Architecture and research decision log
│   ├── storage.md            Storage layout, quotas, cache redirection
│   └── experiments/
│       ├── TEMPLATE.md       Experiment report template
│       └── 001-training-io-characterization-plan.md   Plan of the first experiment
├── hardware/
│   ├── c28.md                CXL and development machine
│   └── c33.md                A100 machine of the earlier experiments
├── workload_configs/
│   └── cosmoflow/            Lightweight CosmoFlow configs and instructions
├── system/                   Future CXL cache implementation (empty)
├── benchmarks/               Future microbenchmarks (empty)
├── simulator/                Future trace-driven cache simulator (empty)
├── scripts/                  Future automation and analysis utilities (empty)
├── configs/
│   └── env.example.sh        Example environment configuration
├── tests/                    Future correctness and regression tests (empty)
└── experimental_results/
    ├── README.md
    └── metadata_template.json
```

## 6. Storage organization

The home directory has a strict 40 GB quota, so the repository holds only
lightweight files. Everything large lives on BeeGFS.

| Location | Content |
|---|---|
| Git repository (home) | Code, documentation, configurations, tests, small summaries and figures |
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
| First experiment (training I/O characterization) | Planned, not run |
| Trace-driven simulator | Not implemented |
| Microbenchmarks | Not implemented |
| CXL cache system | Not implemented |
| Experiments in this repository | None |

Earlier CosmoFlow measurements on a different machine (c33) are recorded as
historical context in [hardware/c33.md](hardware/c33.md). They are not results
of this repository and do not show that CXL caching accelerates training.

The latest state is always in [WORKLOG.md](WORKLOG.md).

## 9. Documentation navigation

| Document | Read it for |
|---|---|
| [docs/project_overview.md](docs/project_overview.md) | Motivation, evidence labels, what is and is not known |
| [docs/research_questions.md](docs/research_questions.md) | Tentative RQ1-RQ4, hypotheses, analytical notes |
| [docs/experiment_plan.md](docs/experiment_plan.md) | Phased roadmap, experiment ID and location conventions |
| [docs/related_work.md](docs/related_work.md) | Reading list and paper notes |
| [docs/decisions.md](docs/decisions.md) | Why the project is organized the way it is |
| [docs/storage.md](docs/storage.md) | Where data goes, quotas, environment setup |
| [docs/experiments/TEMPLATE.md](docs/experiments/TEMPLATE.md) | Writing an experiment report |
| [docs/experiments/001-training-io-characterization-plan.md](docs/experiments/001-training-io-characterization-plan.md) | Plan of the first experiment |
| [workload_configs/cosmoflow/README.md](workload_configs/cosmoflow/README.md) | CosmoFlow workload audit: data, code, input pipeline, cache insertion points |
| [hardware/c28.md](hardware/c28.md), [hardware/c33.md](hardware/c33.md) | Machine facts, verified versus provided |
| [experimental_results/README.md](experimental_results/README.md) | Recording experiment metadata and summaries |
| [CLAUDE.md](CLAUDE.md) | Working rules: integrity, workflow, hardware safety, storage |
| [WORKLOG.md](WORKLOG.md) | What was done, when, and what is open |
