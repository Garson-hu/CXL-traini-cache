# CLAUDE.md

Persistent working instructions for Claude sessions in this repository.

## Project

PhD systems research on **CXL-based training data caching**: using CXL memory
as a large-capacity cache for training data to reduce storage I/O and improve
end-to-end training performance. Initial workload: CosmoFlow.

Current state: the repository is initialized and the hardware and workload
have been audited. No cache system, simulator, benchmark, or experiment result
exists yet. Check [WORKLOG.md](WORKLOG.md) for the latest state before
starting work.

The CosmoFlow code, its TensorFlow environment, and the datasets come from
earlier work and live outside this repository and outside the project's BeeGFS
root. They are used in place and must not be modified. Earlier experiments are
in `~/CXL` (other branches); cite them as historical, with their source. See
`workload_configs/cosmoflow/README.md` and `hardware/c33.md`.

## Where things are

| Path | Content |
|---|---|
| `README.md` | Overview and navigation |
| `WORKLOG.md` | Chronological log; update after meaningful changes |
| `docs/project_overview.md` | Motivation, evidence labels, what is known |
| `docs/research_questions.md` | Tentative RQs, hypotheses, analytical notes |
| `docs/experiment_plan.md` | Phased roadmap and experiment conventions |
| `docs/related_work.md` | Literature tracking |
| `docs/decisions.md` | Architecture and research decision log |
| `docs/storage.md` | Home vs. BeeGFS layout, quotas, cache redirection |
| `docs/experiments/` | Experiment reports (`TEMPLATE.md`) |
| `hardware/` | Machine facts: `c28.md` (CXL, development), `c33.md` (A100, historical) |
| `workload_configs/` | Lightweight workload configs and launch instructions |
| `system/` | Future cache implementation (empty) |
| `simulator/` | Future trace-driven simulator (empty) |
| `benchmarks/` | Future microbenchmarks (empty) |
| `scripts/`, `configs/`, `tests/` | Automation, configurations, tests |
| `experimental_results/` | Small summaries, metadata, figures |

## 1. Research integrity

1. Never fabricate experimental results. If a number was not measured, do not
   write it as a result.
2. Never describe simulated measurements as real hardware measurements. Label
   every result as real hardware, simulation, or analytical.
3. Clearly label hypotheses and assumptions. Use the evidence labels defined in
   `docs/project_overview.md`: Observed, Historical, Simulated, Analytical,
   Hypothesis, Assumption, Planned.
4. Preserve negative results. Do not delete or bury experiments that
   disappoint.
5. Compare new policies against strong baselines. Static pinned caching with
   admission bypass, DRAM caching under the same memory budget, and
   prefetching are the baselines to beat. LRU alone is not a strong baseline.
6. Do not overstate novelty or performance improvements.
7. Prioritize end-to-end training performance over intermediate metrics.
8. Do not assume a cache hit rate improvement guarantees faster training.
9. Results from c28 (CXL memory, RTX 4060 Ti) and c33 (A100, earlier CosmoFlow
   runs) come from different systems. Never combine them as if they were one
   integrated end-to-end CXL experiment.
10. The numbers in the project brief (c33 throughput, BeeGFS bandwidth, reuse
    distances) are historical context. Do not present them as new measurements
    or as proof that CXL caching accelerates training.

## 2. Development workflow

Before modifying code:

1. Inspect the relevant existing files.
2. Understand the current implementation.
3. Check existing documentation and experimental results.
4. Identify the smallest necessary change.
5. Avoid unrelated refactoring.

After meaningful changes:

1. Run appropriate tests when available.
2. Document what changed.
3. Record what was actually verified, and what was not.
4. Update `WORKLOG.md`.
5. Document unresolved issues.

Git: do not commit or push unless asked. Do not create nested repositories.

## 3. Experiment workflow

Every experiment must include:

- Experiment ID (`E<NNN>-<short-name>`, never reused).
- Objective.
- Hypothesis, written before the run.
- Baselines.
- Hardware environment (reference `hardware/<host>.md`).
- Software environment.
- Configuration.
- Methodology.
- Raw result location.
- Results.
- Interpretation.
- Limitations.
- Git commit identifier when available.

Also:

- Record the timestamp, and random seeds where relevant.
- Never overwrite existing raw results without explicit approval. Use a new
  experiment ID or run directory.
- Report: `docs/experiments/<experiment_id>.md` from `docs/experiments/TEMPLATE.md`.
- Metadata and small summaries: `experimental_results/<experiment_id>/`, from
  `experimental_results/metadata_template.json`.
- Raw results: `$CXL_TRAINING_DATA_ROOT/results/<experiment_id>/`.
- Do not start training runs, benchmarks, or long jobs without being asked.

## 4. Hardware safety

Do not perform machine-level changes without explicit approval. This includes:

- BIOS changes.
- CXL decoder configuration.
- DAX device reconfiguration.
- NUMA memory online/offline operations.
- Kernel parameter changes.
- Device formatting.
- Mount/unmount operations.
- Modifications affecting other users.

Read-only inspection (`lscpu`, `numactl -H`, `cxl list`, `daxctl list`,
`nvidia-smi`, `df`, `quota`) is allowed.

c28 is a shared machine. `/dev/dax2.0` is in use by a famfs mount at
`/mnt/famfs/dax2.0`, and other users have data on `/mnt/local` and BeeGFS.
Do not touch what this project did not create.

`/dev/dax0.0` and `/dev/dax1.0` can be opened by this user (group `kmem`,
since 2026-11-11). The user stated on 2026-11-12 that nobody else uses these
two devices. They have no file system, so a write overwrites whatever earlier
work left there. Map or write them only as part of an experiment plan the user
has agreed to, and name the device and byte range in that plan. `dax2.0` and
its famfs mount stay off limits.

Do not clear caches system-wide (`drop_caches`) or run other disruptive
operations on shared machines. Get cold reads by choosing files that have not
been read, and evict per file if a local file system is involved.

`.claude/settings.json` makes Claude Code ask for confirmation before `sudo`
and common device-changing commands. It is a backstop, not a complete list.
The rule above applies to every command.

## 5. Storage rules

- Respect the 40 GB home quota. The repository must stay lightweight.
- Use BeeGFS for large datasets, workloads, traces, checkpoints, results, and
  temporary files: `CXL_TRAINING_DATA_ROOT=/mnt/beegfs/ghu4/cxl-train-cache`
  with `workloads/`, `datasets/`, `checkpoints/`, `traces/`, `results/`, `tmp/`.
- Never silently download or copy large files into home. This includes package
  caches, Python environments, and build trees. See `docs/storage.md` before
  installing anything.
- Code and scripts read `CXL_TRAINING_DATA_ROOT`. Do not hardcode
  machine-specific storage paths in source code.
- Do not modify `~/.bashrc`, `~/.profile`, or other shell startup files.
- BeeGFS is shared and has no per-user quota. Do not assume the space shown by
  `df` is available to this project. Do not overwrite, move, or delete files
  this project did not create.
- CXL memory is an experimental cache tier, never persistent dataset storage.

## 6. Research focus

- Keep the repository dedicated to CXL-based caching for training acceleration.
- Do not introduce unrelated LLM serving or KV cache research.
- Do not design additional system components merely to increase apparent
  research complexity.
- Every proposed mechanism should address an experimentally supported problem.
- Do not commit to an implementation architecture before measurements justify
  it. Do not assume future-aware replacement beats simple policies; see
  analytical note A1 in `docs/research_questions.md`.
- Do not add frameworks, dependencies, or abstraction layers before they are
  needed.

## 7. Documentation

Use English for source code, comments, research documents, experiment reports,
commit messages, and figure labels.

Keep documentation concise, technically precise, and reproducible.

- Record direction-changing choices in `docs/decisions.md`.
- Record changes to research questions in the revision log of
  `docs/research_questions.md`.
- In `hardware/`, keep provided context, verified observations (with date and
  command), and open items separate.
- In `docs/related_work.md`, do not record paper details that were not checked
  against the paper.
