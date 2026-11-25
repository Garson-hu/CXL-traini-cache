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

## D003: Research direction and where to look for the contribution

- **Decision ID:** D003
- **Date:** 2026-11-12
- **Status:** Accepted (direction set by the user); the narrowing in "Chosen
  approach" is proposed on the basis of first evidence
- **Problem:** The project needs a contribution that can carry a systems paper
  (FAST or ATC). The user set the direction: an online reuse-aware cache in
  CXL memory, served remotely over Mercury, for distributed training. The
  first trace replay had to show whether that mechanism has a problem to solve.
- **Alternatives:**
  1. Reuse-aware replacement for a single training job.
  2. Reuse-aware replacement for a cache shared by concurrent jobs on one
     dataset, without changing any job's sample order.
  3. No policy contribution: a systems study of a remote CXL cache with static
     retention.
- **Chosen approach:** Pursue alternative 2 and drop alternative 1.
  Alternative 3 remains the fallback. No system design is fixed.
- **Rationale:** For one job, static retention is optimal, by argument (note
  A1), in simulation on a real trace, and in published practice. With two jobs
  on one dataset, a future-aware reference avoids far more storage reads than
  static retention or LRU on a real trace, so there is room for a policy.
- **Supporting evidence:** `2026-11-12-cache-policy-replay` ([experiments/INDEX.md](experiments/INDEX.md))
  (simulation on three real traces and four synthetic compositions);
  [related_work.md](related_work.md) for what exists. No hardware measurement
  supports this decision.
- **Consequences:** The contribution has to be argued against Quiver (shared
  cache across jobs, by changing the order) and NoPFS (known future order,
  within one job). The simple online candidate is not yet strong enough. The
  next experiments are a real multi-job trace with job identity and a policy
  that uses each job's known order. Nothing about CXL or training time follows
  from this decision.

## D004: Do not build the remote CXL cache yet; settle the order-preservation question first

- **Decision ID:** D004
- **Date:** 2026-11-12
- **Status:** Superseded by D005 (it was a proposal and was not adopted as
  stated)
- **Problem:** D003 chose order-preserving replacement for a cache shared by
  concurrent jobs. The second trace replay shows that this works, and also
  that coordination which reorders the jobs' reads (as in Quiver) serves far
  more from a small cache when jobs of equal speed share one dataset. The
  project has to decide what to do before any system is built.
- **Alternatives:**
  1. Start implementing the remote CXL cache with the known-order policy.
  2. First examine the three things the case rests on: whether keeping each
     job's sampling order is a requirement, whether real job mixes have
     unequal speeds or partial overlap, and whether storage limits training
     with concurrent jobs on this system.
  3. Switch to order-changing coordination as the basis and treat the
     known-order policy as a component for the cases it does not cover.
  4. Fall back to alternative 3 of D003: a systems study of a remote CXL cache
     without a policy contribution.
- **Chosen approach:** Proposed: alternative 2. Alternatives 3 and 4 stay
  open and depend on what alternative 2 finds.
- **Rationale:** The policy result is positive only among order-preserving
  caches. On the one real multi-job trace the Quiver-inspired replay is ahead
  by 18 to 28 points at 5% to 20% capacity. The settings in which the known-order policy is
  ahead (unequal speeds, partial overlap) exist only as synthetic
  compositions. None of the three open points needs the cache to be built.
- **Supporting evidence:** `2026-11-12-cross-job-known-order`
  ([experiments/INDEX.md](experiments/INDEX.md)), simulation only;
  [related_work.md](related_work.md) section 4;
  [research_idea.md](research_idea.md) sections 4 and 6 (numbered 5 and 7
  since 2026-11-24). No hardware
  measurement supports this proposal.
- **Consequences:** No cache implementation and no Mercury work for now. The
  next steps are an analysis of what order-changing coordination would require
  from CosmoFlow's input pipeline, collection of real multi-job traces with
  job identity logged, and `2026-11-11-training-io-characterization` with
  concurrent jobs. If keeping the order turns out not to be required, D003's
  choice has to be revised.

## D005: Research direction fixed; data path rules for the cache from measurements

- **Decision ID:** D005
- **Date:** 2026-11-15 (the direction was set by the user on 2026-11-12)
- **Status:** Part 1 accepted (decision of the user). Part 2 proposed, from
  measurements.
- **Problem:** D004 proposed to settle the order-preservation question before
  any system work. The user instead fixed the research idea and RQ1 to RQ3
  and asked for a characterization of the remote CXL data path. That
  characterization now constrains how a cache on this hardware has to move
  data.
- **Alternatives:** for the data path: (a) the NIC reads and writes the CXL
  store directly in both directions; (b) every transfer goes through a DRAM
  buffer, as in FitCache; (c) reads directly from the CXL store, writes into
  it only by the CPU.
- **Chosen approach:**
  1. Accepted: the central direction (online reuse-aware CXL caching for
     distributed training, RQ1 to RQ3) is fixed. Single results do not change
     it; limitations are analysed within it.
  2. Proposed: alternative (c). Hits are served by the NIC from the CXL store
     without a copy. Admissions enter CXL through the CPU: the server reads
     the file into the store, or data lands in a DRAM buffer and is copied.
     The NIC never writes into CXL memory.
- **Rationale:** measured on c28 with clients c39 and c44. NIC reads of CXL
  memory run at the link limit and equal DRAM. NIC writes into CXL memory are
  capped at 4.24 GB/s on both devices and cut concurrent reads by 94%. CPU
  writes into CXL cost the same as into DRAM and do not disturb reads.
- **Supporting evidence:** `2026-11-12-remote-cxl-data-path`
  ([experiments/INDEX.md](experiments/INDEX.md)), real hardware; no training
  run.
- **Consequences:** the same experiment shows two limits that any design in
  this direction has to address: the cache reduces I/O time only for data the
  storage servers do not hold in memory (with a dataset in their memory, no
  cache was faster in the replay), and one server port (12.3 GB/s) is the
  ceiling for all clients together. The evaluation therefore needs datasets
  or job mixes beyond the storage servers' memory, and a miss path that is
  not slower than a direct read. The cause of the NIC write limit is open.

## D006: Evaluation workload, and how the evaluation reaches a storage-bound regime

- **Decision ID:** D006
- **Date:** 2026-11-16
- **Status:** Proposed, for the user to confirm
- **Problem:** The cache can shorten training only where training waits for
  storage. Measured on this cluster: one CosmoFlow job on an RTX 4060 Ti needs
  17 samples/s, and with a parallel reader it gets 112 or more from cold
  BeeGFS and does not wait. Data in host memory, the upper bound for a cache
  of file bytes, gains nothing there. An end-to-end evaluation needs a
  workload and a demand level at which the cache can change something.
- **Alternatives:**
  1. Real training only, with as many concurrent jobs as GPU nodes can be
     obtained. The shared first-read supply of BeeGFS (0.74 GB/s at 32
     streams, about 255 samples/s) is passed at about 15 jobs on these GPUs.
  2. Real training with the benchmark's sequential reader, which does wait
     for storage (60% of the time on cold data).
  3. The real input pipeline with a consumer that takes batches at a measured
     GPU rate, for the demand that the available GPUs cannot generate; real
     training on the GPUs that exist. Reported as two separate tiers.
  4. A workload with higher demand per accelerator: MLPerf Storage 3D U-Net
     through DLIO, with emulated accelerators and synthetic data.
- **Chosen approach:** Proposed:
  - Workload: full CosmoFlow (1.52 TB), several concurrent jobs with
    independent seeds on the shared dataset. Alternative workload if a second
    one is wanted: alternative 4.
  - Baseline: every job uses the parallel reader. A cache has to beat
    parallel reading with prefetch, not the sequential reader.
  - Demand: alternative 3. Real training is reported as training; runs with
    emulated consumption are reported as I/O results and never as training
    speedup.
  - Alternative 2 may illustrate the cost of cold storage. It is not a
    comparison in which a cache is credited.
- **Rationale:** Alternative 1 alone needs about 15 GPU nodes for many hours
  and still sits at the edge of the limit. Alternative 2 credits a cache with
  what a configuration change gives for free. Alternative 4 leaves the
  workload for which the project has data, code, and traces. Alternative 3
  keeps real data, real decoding cost, and real access orders, and states
  openly which part is emulated; it is the method of MLPerf Storage.
- **Supporting evidence:** `2026-11-16-workload-io-validation`
  ([experiments/INDEX.md](experiments/INDEX.md)): real training and
  input-pipeline measurements on c28, c24, c38; storage probes; the demand
  thresholds are analytical. [workload_selection.md](workload_selection.md).
- **Consequences:**
  - A claim that the cache accelerates training needs real training to show
    it. The measurements predict that it will not on this cluster below about
    15 concurrent jobs. This is a limit of the available GPUs and has to be
    stated in any result.
  - On a 16-core node the input pipeline's CPU cost (about 73 ms per sample)
    caps supply at 209 samples/s. A cache of compressed files cannot lift
    that. The cache unit (compressed file or decoded sample) stays an open
    design point.
  - Runs at the storage limit read hundreds of GB of cold data per ten
    minutes from shared storage. They need the user's approval and a quiet
    time.
  - An instrumented run on c33's A100 becomes possible after 2026-11-21 (the
    node is allocated to another user until then).
- **Addendum, 2026-11-16 (evidence from `2026-11-16-loader-gpu-scaling`,
  the proposal itself is unchanged):** eight real concurrent jobs with the
  baseline reader do not wait for cold storage and draw 0.39 GB/s, half of
  the shared first-read supply; this supports the estimate that real training
  on these GPUs meets the storage limit only near 15 jobs. A job does wait
  with exactly one read stream (26% to 41.5% of the time; memory-resident
  data 1.35 to 1.70 times faster). Candidate configurations for the cache
  experiment are therefore: one read stream per job, alone and as eight
  concurrent jobs, with the baseline reader as the comparison in every case.
  A gain shown only against a single-stream loader is a gain that a second
  stream also gives; any result has to say so. The "8 readers" named in this
  entry are tf.data's interleave with cycle length 8, which reads up to 24
  files at once.
- **Addendum, 2026-11-17 (evidence from `2026-11-17-multi-gpu-io-saturation`,
  the proposal itself is unchanged and still waits for the user):**
  alternative 1 was tried with real training on up to 20 GPU nodes. The
  storage limit exists where it was estimated: jobs with eight read streams
  do not wait at 15 jobs and wait 20% of the time at 20 jobs, where the
  storage delivers 0.76 GB/s of first reads against a demand of 0.95 GB/s.
  Memory-resident input restores the full rate (1.24 times in aggregate;
  1.38 times against jobs with two read streams). So a real-training tier of
  the evaluation is possible on this cluster without emulated consumption:
  20 concurrent jobs, compared against the same jobs with enough read
  streams. Its cost and limits: it needs every idle RTX 4060 Ti node of the
  cluster at once (Slurm did not always start jobs on four of them), the
  headroom is at most 1.24 to 1.38 times, and the runs so far are single
  short runs in which every first read is cold by construction. Alternative
  3 (emulated consumption for higher demand) stays the way to go beyond
  that headroom.

## D007: Architecture of the minimal cache

- **Decision ID:** D007
- **Date:** 2026-11-17
- **Status:** Accepted for the prototype. Made while implementing the task
  "E008"; the user asked for a minimal working cache that builds on the
  existing Mercury code and the existing policies, and has not reviewed this
  entry.
- **Problem:** The policies exist as Python classes of the trace simulator.
  The data path that was measured to work (hits read by the NIC from CXL
  memory, admission by a CPU copy from DRAM) exists as a C benchmark over
  Mercury. A cache needs both, plus metadata that stays consistent while
  several jobs hit, miss, admit, and evict at once.
- **Alternatives:**
  1. Reimplement the policies in C inside the server.
  2. A separate metadata service that clients consult before they talk to
     an unchanged data server.
  3. One server process: the data plane in C as a library, the control plane
     in Python in the same process, calling the simulator's policy classes.
- **Chosen approach:** Alternative 3 ([system/](../system/README.md)).
  - Data plane derived from the data-path benchmark: one registered store of
    fixed slots, DRAM or a devdax byte range; hits are zero-copy; misses go
    BeeGFS, DRAM buffer, client, and then, if admitted, a CPU copy into the
    slot. The NIC never writes into the store.
  - Control plane: one thread owns every table and takes every decision.
    The data plane hands it events and executes its answers. A slot is
    reused only when no transfer reads it.
  - Policies are the simulator's classes, unchanged. Objects are one unit
    each and the capacity is a number of fixed slots.
  - A job announces its seed, epoch length, total accesses, and the order of
    each epoch; requests carry epoch and position and are processed in
    position order per job.
- **Rationale:** Alternative 1 creates a second implementation of the
  policies that has to be kept equal to the first. Alternative 2 adds a round
  trip per request and lets clients write into the store. Alternative 3 keeps
  one implementation of the policies, lets the simulator check the server on
  the server's own log, and removes races by giving the metadata one owner.
  Its cost, the interpreter on the request path, was measured.
- **Supporting evidence:** `2026-11-17-cxl-cache-integration`
  ([experiments/INDEX.md](experiments/INDEX.md)): the manager's decisions
  equal the simulator's on every recorded trace tried and on the logs of the
  running server; the control plane costs 7 to 9 microseconds of CPU per
  request and the server delivers 12.3 GB/s of hits from DRAM and from CXL
  memory alike, the limit of the link; every object returned in the tests
  equals its file.
- **Consequences:**
  - The request rate of the server is bounded by one interpreter thread.
    At 2.9 MB per object the link is the limit long before that; for small
    objects it would not be.
  - Fixed slots waste 15% of the store for CosmoFlow and tie the slot size
    to the largest object. Variable-size allocation is open.
  - The simulator and the server now share code: a change to a policy class
    changes the server.
  - No persistence, one server, trusted clients. These are limits of the
    prototype, not decisions about the final system.


## D008: How a cache configuration is judged on this cluster, and how demand beyond the GPUs is produced

- **Decision ID:** D008
- **Date:** 2026-11-18
- **Status:** Proposed. Follows from experiment
  `2026-11-18-large-working-set-reuse`; the user has not reviewed this
  entry. It does not change the research direction or RQ1 to RQ3.
- **Problem:** Two results of that experiment change what an evaluation of
  the cache has to measure. First, the storage servers' memory (about 650
  GiB, working like a recency cache of roughly 600 GiB under load) serves
  40% of the bytes of 20 jobs on the full shared dataset, and those jobs do
  not wait for direct BeeGFS; the storage limit is reached at about 26 jobs
  of the available GPU class, the number of suitable nodes that exist.
  Second, in simulation with that memory behind the cache, known order's
  lead in bytes served by the cache (49% against 15% for static pinning at
  256 GiB) does not reduce what the disks have to deliver, because the
  cache then serves the re-reads the servers would have served.
- **Alternatives:**
  1. Keep judging policies by the cache's byte hit rate and by training
     runs with 20 jobs.
  2. Judge a configuration by what reaches the disks (measured on the
     storage servers) and by the jobs' waiting, with the servers' memory in
     the path; produce demand above the storage limit by emulating the read
     side of more jobs (the harness's paced loader, the real input pipeline
     without a GPU), and confirm with real training at the largest job
     count the cluster allows.
  3. Look for another cluster or storage system first.
- **Decision (proposed):** Alternative 2.
- **Rationale:** With 20 jobs there is no storage stall to remove, so
  alternative 1 cannot show an end-to-end effect in either direction, and
  the hit rate alone is misleading when a server-side cache sits behind the
  CXL cache. Alternative 2 measures the quantity that limits training and
  can reach the regime the research question is about with the hardware at
  hand. Alternative 3 is not excluded by it.
- **Supporting evidence:** `2026-11-18-large-working-set-reuse`
  ([experiments/INDEX.md](experiments/INDEX.md)): supply to 160 streams
  equals the cold ceiling divided by the cold share (measured at 1, 0.5,
  0.33); 20 emulated jobs on the full dataset wait 0.8%, 26 wait 3%; the
  two-level result is simulated only.
- **Consequences:**
  - Results obtained with emulated jobs are measurements of the data path
    and the storage, not of training, and have to be labelled so.
  - A comparison of static pinning and known order through the real cache
    at 32 to 40 emulated jobs is the next experiment; it needs 9 to 10 TB
    of BeeGFS reads and the user's go-ahead.
  - If that comparison confirms the simulation, the value of a reuse-aware
    policy on this kind of storage has to be argued for systems whose
    servers keep less than the cache does; that would be a finding to
    report, not a reason to change direction on one experiment.

## D009: Mechanism extended with two-epoch lookahead and asynchronous prefetching

- **Decision ID:** D009
- **Date:** 2026-11-24
- **Status:** Accepted (decision of the user, given as a refinement of the
  research idea and the research questions). The details listed under
  "Consequences" are open.
- **Problem:** The mechanism studied so far is replacement: a shared cache
  keeps the files that the jobs' announced orders say are needed soonest.
  It serves two to three times the bytes of static pinning from the cache
  in simulation and in the prototype. No end-to-end gain has been measured:
  with 20 jobs on reused data the storage, with its servers' memory, keeps
  up (`2026-11-17-cxl-cache-integration`,
  `2026-11-18-large-working-set-reuse`). Replacement acts only on data that
  is read again; it does nothing for the time a first read takes.
- **Alternatives:**
  1. Keep the mechanism as it is and look only for a regime in which
     replacement alone shows a gain.
  2. Extend it: jobs announce their order two epochs ahead, and the cache
     prefetches upcoming files that it does not hold, managed together with
     admission and eviction.
  3. Change the direction.
- **Decision:** Alternative 2. The direction (Online Reuse-Aware CXL
  Caching for Distributed Training) and the three research questions stay;
  their wording is refined ([research_questions.md](research_questions.md),
  revision log of 2026-11-24). The existing known-order replacement is kept
  and not redesigned without need. Cross-job reuse and the distributed CXL
  architecture stay the focus. The non-evictable famfs mode of the earlier
  code is supported separately where relevant.
- **Rationale (as given with the refinement, and from the measurements):**
  the announced order that replacement uses also says which uncached files
  will be asked for and roughly when, so the cache can fetch them before
  the request. A prefetch hides a read only if it finishes before the
  request; two-epoch lookahead gives more time for that, most of all near
  epoch boundaries, without guaranteeing it. Prefetching cannot remove a
  sustained deficit of storage bandwidth, and cache hits alone do not show
  that training is faster.
- **Supporting evidence:** none for prefetching in this project: it is not
  implemented and not simulated. Context from measurements
  ([experiments/INDEX.md](experiments/INDEX.md)): jobs with one or two read
  streams wait for storage while the storage is below its limit
  (`2026-11-16-loader-gpu-scaling`, `2026-11-17-multi-gpu-io-saturation`);
  a second read stream in the job removed that wait for up to eight jobs;
  the storage supplies a cold limit of 0.66 to 0.86 GB/s
  (`2026-11-18-large-working-set-reuse`). Longer lookahead for replacement:
  simulated only, small effect on hit rate
  (`2026-11-12-cross-job-known-order`).
- **Consequences:**
  - Hypotheses R9 to R13 in [research_idea.md](research_idea.md); phases 7
    to 9 in [experiment_plan.md](experiment_plan.md).
  - Prefetching was listed as a baseline in the project's rules. It stays
    one in the form "prefetching without reuse-aware replacement", next to
    static pinning and a loader with enough read streams; the evaluation
    measures replacement and prefetching separately and together.
  - Open, to be decided with measurements: the exact meaning of "two epochs
    ahead" (read for now as the rest of the current epoch plus the next
    one) and when a job announces it; how far ahead and how many prefetches
    at once; how prefetching and misses share the storage; how long a
    prefetched file is protected.
  - D008 (how a configuration is judged, proposed) applies unchanged and
    still awaits review; D006 is still proposed.
  - Nothing was implemented or run with this decision.
- **Addendum, 2026-11-24, after `2026-11-24-two-epoch-lookahead-prefetch`:**
  the extension exists in a minimal form (two-epoch lookahead read as the
  rest of the current epoch plus the next one; prefetch candidates go
  through the unchanged ranked admission). First evidence: prefetching
  removes the waiting of one-stream training jobs on cold files (39.5% to
  0.5%), a direct job with eight read streams waits as little, prefetching
  reads 8% to 11% more from BeeGFS than replacement alone, and two-epoch
  lookahead changed no waiting. Simulated only: no effect under a
  bandwidth deficit. The decision stands; what prefetching is for (jobs
  that cannot raise their own read parallelism) has to be stated when it
  is evaluated further.
