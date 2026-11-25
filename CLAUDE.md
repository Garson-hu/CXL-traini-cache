# CLAUDE.md

Persistent working instructions for Claude sessions in this repository.

## Project

PhD systems research on **CXL-based training data caching**: using CXL memory
as a large-capacity cache for training data to reduce storage I/O and improve
end-to-end training performance. Initial workload: CosmoFlow.

Current state: the hardware and workload have been audited, a minimal cache
policy simulator exists (`simulator/cachesim.py`, `simulator/crossjob.py`),
and two simulation experiments (`2026-11-12-cache-policy-replay`,
`2026-11-12-cross-job-known-order`) have been run. A data-path benchmark
exists (`benchmarks/remote_cache/`), and one hardware experiment
(`2026-11-12-remote-cxl-data-path`, done 2026-11-15) has measured the remote
cache data path: direct BeeGFS, remote DRAM, and remote CXL through Mercury,
admission, concurrent reads and writes, and an I/O replay. A training I/O
harness exists (`benchmarks/train_io/`), and experiment
`2026-11-16-workload-io-validation` measured CosmoFlow training and its input
pipeline on c28 from BeeGFS and from host memory, storage residency, and a
two-job trace. Experiment `2026-11-16-loader-gpu-scaling` measured training
against the number of read streams and of concurrent jobs (up to eight GPU
nodes). Experiment `2026-11-17-multi-gpu-io-saturation` measured 7 to 20
concurrent training jobs and found where shared BeeGFS limits them (about 12
jobs with two read streams per job, 16 to 17 with eight). A minimal cache
prototype exists (`system/`): one server with its store in CXL memory or
DRAM, the simulator's policies, and the harness's input pipeline `cache`.
Experiment `2026-11-17-cxl-cache-integration` validated it (data, decisions,
DRAM against CXL) and ran the first training jobs through it, 20 at a time,
in reduced form; the full-dataset evaluation with 256 and 512 GiB caches has
not been run. Experiment `2026-11-18-large-working-set-reuse` measured how
the storage serves reused data to many readers (cold limit divided by the
share of bytes from disk; one thread's latency does not show it) and found
that 20 jobs on the full shared dataset do not wait for direct BeeGFS, so a
cache comparison there needs more demand than 20 jobs; it was not run.
Experiment `2026-11-24-large-scale-cache-evaluation` did the preliminary
validation and a pilot for that comparison with 40 emulated jobs (real
input pipeline, paced consumer, no GPU): the cache is correct with the
full catalog and a 256 GiB store, 40 jobs stall on cold storage, and an
empty cache is behind direct BeeGFS in its first three minutes; **the
comparison of direct BeeGFS, static pinning, known order, and prefetching
has not been run** and needs the user's approval of its budget. Its
second part (evening of 2026-11-24) made the fixes the comparison needs
(the known-order policy's periodic re-keying computed with arrays, same
decisions; the cache client on nodes with several RDMA devices), checked
that 40 jobs start and run, and prepared the series (`run_main.sh` and its
scripts in the experiment directory); the comparison also needs disk
counters on the BeeGFS storage servers, which need a Slurm job on each
server (Slurm gives it the whole node, so the server must be free). The
user approved the comparison on 2026-11-24 for an unattended start; it
was queued that evening (`autostart.sh`, plan section 11.8). Check the
experiment's `plan.md` and `$ROOT/series/` for whether it has run before
doing anything else with it. Check [WORKLOG.md](WORKLOG.md) for the latest state
before starting work.

Research direction, fixed by the user: **Online Reuse-Aware CXL Caching for
Distributed Training.** Since 2026-11-24 the mechanism under study is the
existing known-order replacement extended with two-epoch lookahead (jobs
announce their file order two epochs ahead) and asynchronous prefetching
from BeeGFS into CXL memory, with prefetching, admission, and eviction
managed together (`docs/research_idea.md`, sections 4 and 9; decision D009).
Replacement exists in the simulator and the prototype. Two-epoch lookahead
(policy `known:epoch2`) and a minimal prefetcher exist since
`2026-11-24-two-epoch-lookahead-prefetch` and were measured with four
training jobs only: prefetching removed the waiting of one-stream jobs on
cold files, as eight read streams in the job also do; the longer lookahead
changed no waiting; under a storage-bandwidth deficit prefetching is
expected to do nothing (simulated). Treat every statement about them at
scale as a hypothesis. The three research questions are
unchanged in number and direction (`docs/research_questions.md`).

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
| `docs/research_idea.md` | The research idea, first evidence, refined hypotheses |
| `docs/workload_selection.md` | Candidate workloads against the selection criteria |
| `docs/research_questions.md` | Tentative RQs, hypotheses, analytical notes |
| `docs/experiment_plan.md` | Phased roadmap and experiment conventions |
| `docs/related_work.md` | Literature tracking |
| `docs/decisions.md` | Architecture and research decision log |
| `docs/storage.md` | Home vs. BeeGFS layout, quotas, cache redirection |
| `docs/experiments/` | `INDEX.md`: one row per experiment (the tracked record). `TEMPLATE.md`: summary template |
| `docs/slides/` | Slides made on request. Local only, not tracked |
| `hardware/` | Machine facts: `c28.md` (CXL, development), `c33.md` (A100, historical), `c39.md` (client nodes c39 and c44 for data-path measurements; GPU nodes c24 and c38 and the nodes of the multi-job training runs; BeeGFS storage servers) |
| `workload_configs/` | Lightweight workload configs and launch instructions |
| `system/` | Minimal cache prototype: data plane (`cc_server.c`), control plane (`cc_manager.py`), server (`cc_server.py`), client (`cc_client.c`, `cc_client.py`), checker against the simulator (`cc_verify.py`) |
| `simulator/` | Trace-driven cache policy simulator (`cachesim.py`, `crossjob.py`); its policy classes are also the cache server's |
| `benchmarks/` | Microbenchmarks: `remote_cache/` (Mercury data path to DRAM or CXL memory), `train_io/` (CosmoFlow input pipeline, compute-only, instrumented training, access traces) |
| `scripts/`, `configs/`, `tests/` | Automation, configurations, tests |
| `experimental_results/` | One dated directory per experiment: plan, summary, small results. Local only, not tracked |

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
   Since prefetching is part of the mechanism (2026-11-24): measure
   replacement and prefetching separately and together, and keep
   prefetching without reuse-aware replacement and a loader with enough
   read streams of its own as baselines.
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

Never list Claude, or any AI tool, as author or co-author of anything that is
committed or pushed. Add no attribution line or trailer (`Co-Authored-By`,
"Generated with", session links) to commit messages or pull requests. Commits
are authored by the user only. Check `git log` for such trailers before every
push.

## 3. Experiment workflow

Every experiment must include:

- Experiment name (`YYYY-MM-DD-<short-name>`, the day it starts; never reused).
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
- Do not start training runs, benchmarks, or long jobs without being asked.

Organization of experiments (set by the user on 2026-11-12):

- Experiments are organized by date. Each experiment has one directory,
  `experimental_results/YYYY-MM-DD-<short-name>/`, named after the day it
  starts. Everything about it goes there: `plan.md` (hypotheses, written
  before the run), `summary.md`, `metadata.json` (from
  `experimental_results/metadata_template.json`), small tables, figures, and
  scripts used only by that experiment.
- `summary.md` is required whenever the directory holds results or more than
  a few files. It says what was done on which day, the results, the
  interpretation, and the limitations. Template: `docs/experiments/TEMPLATE.md`.
- An experiment that continues on a later day stays in its directory. A new
  question gets a new dated directory.
- Large raw data goes to `$CXL_TRAINING_DATA_ROOT/results/<same name>/`.
- Experiment directories are **not tracked by Git and not pushed**. The only
  tracked record is one row per experiment in `docs/experiments/INDEX.md`:
  date, name, question, type, status, and a one- or two-sentence outcome,
  including negative outcomes. Keep that row current.
- Tracked documents refer to an experiment by its name and to the index. They
  do not link into `experimental_results/`.
- Slides go to `docs/slides/` with dated file names. That directory is not
  tracked either. Do not edit past decks; add a new one.

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
two devices. The user's own other projects do use them at times (seen on
2026-11-12): check for processes that map them before every use. They have no
file system, so a write overwrites whatever earlier work left there. Since
2026-11-24 the user's standing instruction is: these two devices may be
mapped and written in full without asking again, as long as no process maps
a DAX device at that moment. Name the device and byte range in the
experiment plan all the same. `dax2.0` and its famfs mount stay off limits.

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
