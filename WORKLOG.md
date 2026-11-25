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

## 2026-11-24 — Large-scale evaluation, second part: fixes and checks; main comparison approved and queued (not run yet)

- **Date:** 2026-11-24 (20:42 to 21:47)
- **Objective:** The user's second task sheet for
  `2026-11-24-large-scale-cache-evaluation`: remove the 4.6 to 4.8 s stall
  of the known-order policy's periodic re-keying without changing a
  decision; fix or avoid the Mercury initialisation failure on nodes with
  several RDMA devices; verify that 40 jobs start and run; confirm
  disk-level monitoring of the BeeGFS servers; prepare the comparison of
  five runs of 20 minutes and **ask for approval before starting it**.
- **Changes:**
  - `simulator/crossjob.py`: `KnownOrder(dense=N)`. For callers whose
    objects are the integers 0 to N-1 the pass that re-keys all residents
    is computed for all of them at once from arrays kept beside the
    policy's dictionaries (numpy), and the heap is rebuilt from the new
    keys. Same expressions and operands, so the same keys; the simulator's
    replays keep the per-object pass and are the reference. The loop that
    takes in newly announced positions was tightened (no behaviour change)
    so that a job's first request is not slower with the arrays.
  - `system/cc_manager.py`: builds the policy with `dense=len(catalog)`.
  - `system/cc_client.py`: the Mercury address names the RDMA device of
    `ib0` (`ofi+verbs;ofi_rxm://mlx5_0/<address>`).
  - `system/cc_verify.py`: `refresh` argument for tests.
  - Tests: 7 new (58 in all): the array pass against the per-object pass
    in the policy (all lookahead modes, different datasets, stale
    positions, wrong rates, repeated files, tiny and full cache) and in
    the manager (frequent passes, prefetching, a job that leaves its
    order).
  - Experiment directory (untracked): `run_main.sh`, `monitors.sh`,
    `disk_monitor.sh`, `userstats.sh`, `residency_probe.py`,
    `quick_window.py`, `analyze_main.py`, `make_tables_main.sh`,
    `preflight.sh`, `transient_probe.py`; `scale_check.py` extended (pass
    timing, key comparison, hit share per minute); plan section 11
    (fixes F1 to F4, the comparison's configuration, windows, steady-state
    criteria, questions Q1 to Q5 with what counts as an outcome, stop
    rules, budget); summary section 13.
- **Files affected:** `simulator/crossjob.py`, `simulator/README.md`,
  `system/cc_manager.py`, `system/cc_client.py`, `system/cc_verify.py`,
  `system/README.md`, `tests/test_crossjob.py`, `tests/test_cc_manager.py`,
  `tests/README.md`, `hardware/c39.md`, `docs/experiments/INDEX.md`,
  `docs/research_questions.md`, `docs/experiment_plan.md`,
  `docs/project_overview.md`, `README.md`, `CLAUDE.md` (state sentence),
  this file; the experiment directory (local); raw results under
  `$CXL_TRAINING_DATA_ROOT/results/2026-11-24-large-scale-cache-evaluation/`
  (`verify2/`, `series/`, `mon/`, `runs/reh-*`, `runs/chk-*`,
  `servers/reh-*`, `servers/chk-*`, `servers/rdma-check`). Nothing
  committed or pushed.
- **Verification performed:**
  - 58 unit tests pass with numpy 1.26.4 (the server's environment) and
    2.2.6 (system Python). Ten deliberate errors in the array code, one
    at a time, were each caught by the new tests.
  - Manager without a server, full catalog, 40 jobs, 806,400 accesses
    (the request sequences of a 20-minute run): `known:epoch` and
    `known:epoch2` 0 decisions differ from the simulator, resident sets
    equal; with prefetching 0 differ from the same manager with the
    per-object pass, prefetch counters equal; keys equal for all 80,659
    residents after each of 24 periodic passes.
  - Clients on c51, c52, c58, c50 against a server on c28: 128 objects
    each, bytes verified, no error.
  - Rehearsal of the series scripts (4 jobs, five configurations, 60 s
    each): all ran; logs of `static` and `known:epoch` equal the
    simulator; prefetch accounting closes.
  - 40-job check (known order, then with two-epoch lookahead and
    prefetching; 90 s each): 40 of 40 jobs, no error line, no request out
    of order; 28,254 requests with 0 decisions differing from the
    simulator; prefetch accounting closes (17,738).
  - Not verified: a periodic re-keying pass inside a running server (none
    fell into the short runs); `disk_monitor.sh` on a storage server; why
    c58 initialises Mercury where c51 does not.
- **Results:**
  - **[Observed]** (manager's code on c28, no server): one re-keying pass
    over 80,659 residents with 40 jobs takes 0.066 to 0.090 s (per-object
    pass, measured again: 4.53 to 4.82 s). Outside a job's first request
    no request of the manager takes longer than 0.2 s. A job's first
    request: 0.25 to 0.27 s (one announced epoch), 0.58 to 0.61 s (two),
    as before.
  - **[Observed]** Mercury with the address alone fails on c51 and c52
    (two RoCE devices besides the InfiniBand one) and works with the
    device named; c58, with the same devices, works either way.
  - **[Observed]**, training-demand emulation, 40 jobs, 90 s from an
    empty cache on storage not read by these seeds: known order 305
    samples/s (45% of the full rate) and 54% waiting in seconds 45 to 90;
    with two-epoch lookahead and prefetching 316 (47%) and 53%, 37% of the
    prefetches finished before their request. First batches 3 to 14 s
    (one epoch announced) and 5 to 33 s (two) after the common start.
  - **[Observed]** Disk counters: not available; all seven storage
    servers were fully allocated to other users (until 2026-11-25 05:45
    to 14:00, c11 until 2026-11-26). The servers export no metrics.
    `beegfs-ctl --userstats` gives each user's reads; other users read in
    bursts of 0.4 to 1.0 GB/s for tens of seconds during the rehearsal
    and 0.02 to 0.03 GB/s during the 40-job check.
  - **[Simulated]** and **[Analytical]**: after a common cold start the
    hit share of known order follows 1 − exp(−n/N) until the jobs have
    made about N = 524,288 requests in all (61% in minute 13 at the full
    rate), then falls by about 20 points and swings towards 50%. Not
    caused by the re-keying (same curve with any refresh interval). At
    the 300 to 450 requests/s of a stalled run, 20 minutes end inside the
    first rise: about 15% to 22% hits in the first 10 minutes (static
    pinning: 15% once full) and 40% to 53% in the second.
  - BeeGFS reads of this part: 0.23 TB (rehearsal 0.058, 40-job check
    0.171). With the first part 1.21 TB, 0.01 TB above the 1.2 TB the user
    approved at 17:01.
- **Open questions:**
  - The comparison itself: every question of the task (known order
    against static pinning, hits against waiting, the share of the
    storage servers' memory, prefetching, the central miss path) is
    unanswered on hardware.
  - Whether 20 minutes per run are enough: the second window is expected
    to separate known order from static pinning but not to be a steady
    state; 35 to 45 minutes per run would pass the first peak and cost
    about twice the reads.
  - When the storage servers have free CPUs for the monitors.
  - The start-up of the known-order policy (up to 33 s for 40 jobs that
    announce two epochs) is unchanged.
- **Approval and state at 21:47:** the user approved the comparison for an
  unattended start and suggested queueing ahead ("我允许你在本会话里从 14:05
  起定时检查、条件满足就自动启动。或者你考虑提前申请呢? 用 salloc 提前申请排队上");
  runs of 20 minutes as in the task sheet. Done with it: the seven monitor
  jobs wait in the Slurm queue (jobs 347216 to 347222; c17 eligible from
  12:30, the others when their servers have a free CPU, expected 13:53 to
  14:00 on 2026-11-25); `autostart.sh` runs detached on c28 and starts
  the series once when monitors run on three storage servers including
  c14, 20 client nodes are idle, and no process maps a DAX device; it
  gives up at 19:30. The client nodes are not held ahead. `run_main.sh`
  now also ends the series when a job fails. At 21:51 the user confirmed
  that it may start before 14:05 ("可以提前启动,不用等到 14:05"); the
  starter then got a stricter check (a monitor counts only while it
  writes fresh disk counters; a monitor that writes nothing ends the wait
  without a start) and was restarted at 21:54. **Nothing of the
  comparison has run yet.**
- **Publication (22:07):** at the user's request everything tracked that
  had accumulated since the first push of 2026-11-11 was committed in four
  commits (simulator and its tests; benchmarks; cache prototype and its
  tests; documents) on branch `progress-2026-11-24` and pushed to
  `origin`. `main` was not moved. Experiment directories and slides stay
  local. The files were scanned before for addresses, account names of
  other users, and keys: none. No attribution line in any commit message.
  Runs started from now on record the repository's commit themselves
  (`launch_emu.sh`), so the main comparison will carry the new commit.
- **Correction (22:10):** a monitor job does not take one CPU of a
  storage server but the whole node: Slurm allocates whole nodes here
  (`select/linear`). Seen when c11 became free at 22:02 and the queued
  monitor started there with 16 CPUs allocated. It validated the new
  monitor script on a real storage server (data disks found by their
  mount points, counters once a second) and was then cancelled so that it
  does not keep c11 from other users until the series starts. The
  monitors of c11 and c17 are queued again with a dependency: they start
  only once the monitor on c14 has started. Those of c12, c13, c15, c16
  stay queued as they were. Wording corrected in `hardware/c39.md`,
  `docs/storage.md`, `docs/experiment_plan.md`, `CLAUDE.md`, and the
  experiment index; "a free CPU" in older entries of this log means a
  free node.
- **Next steps:** when the series has run: `tables-m.md` (built by the
  starter), verification of the logs, figures, and the assessment against
  the plan's Q1 to Q5 and the predictions of the earlier simulations. If
  it does not start by 19:30 on 2026-11-25: cancel what is left and ask
  the user. While it runs, nothing else of this user should map a DAX
  device on c28.

## 2026-11-24 — Large-scale evaluation: preliminary validation and pilot (main comparison not run)

- **Date:** 2026-11-24 (16:52 to 18:01; documents until 18:09)
- **Objective:** Task sheet "E011": evaluate the existing cache under a
  large working set and a storage-bandwidth limit (direct BeeGFS, static
  pinning, known order, known order with two-epoch prefetching; 256 GiB in
  CXL memory; 32 to 40 jobs). Asked for now: the preliminary validation
  (full-dataset correctness, the centralized miss path, storage state) and
  the smallest useful pilot; approval is required before the full
  comparison.
- **Changes:**
  - Experiment `2026-11-24-large-scale-cache-evaluation`: plan with
    hypotheses written before any measurement, summary, tables, two
    figures, metadata, scripts (offline scale check, catalog check, list
    maker, server and launch scripts for emulated jobs, miss-path tests,
    log checker with whole announced orders, analysis).
  - `system/cc_server.py`: `--no-gc`, `--timeline`, read-time histograms,
    the manager's longest pass, `--slots-high-first`; the hold timeout is
    judged on event time when there is a backlog.
  - `system/cc_manager.py`: the prefetcher checks its window again when it
    offers a candidate (it ran far ahead with jobs of several read streams).
  - `system/cc_client.py`: `load --objects-file`.
  - `benchmarks/train_io/cosmoflow_io.py`: `--max-seconds-ends-run`,
    `--cache-request-log`.
  - `tests/test_cc_manager.py`: one new test (51 in all).
  - `CLAUDE.md`: the user's standing instruction on the DAX devices (use
    without asking when no process maps a DAX device) and the new state.
  - Evidence and status in `docs/research_questions.md`,
    `docs/research_idea.md` (R11), `docs/project_overview.md`,
    `docs/experiment_plan.md`, `docs/storage.md` (two notes on method),
    `hardware/c39.md`, `system/README.md`, `benchmarks/train_io/README.md`,
    `tests/README.md`, `README.md`, and the experiment index.
- **Files affected:**
  - Repository: the files above.
  - Local, not tracked: `experimental_results/2026-11-24-large-scale-cache-evaluation/`.
  - BeeGFS: `results/2026-11-24-large-scale-cache-evaluation/` (41 MB).
  - CXL memory: `/dev/dax1.0`, bytes [0, 278.4 GB), inside the whole device
    the user agreed to at 17:01 (asked before anything was mapped). No
    other device, no configuration change.
  - Not touched: the CosmoFlow benchmark directory, the datasets, earlier
    results.
- **Verification performed:**
  - 51 unit tests pass.
  - Catalog: 524,288 files, names equal to the directory, 4,096 sizes
    equal to `stat`.
  - Manager against the simulator at full scale without a server (40
    jobs, 403,200 accesses, 80,659 slots): no differing decision for
    `static`, `known:epoch`, `known:epoch2`; the two known-order modes take
    the same decisions.
  - Through the server with the full 278.4 GB store: 40,960 requests
    compared byte for byte, none differs, including slots at the top of
    the store and a run with 11,140 evictions; its log equals the
    simulator. Logs of two pilot runs equal the simulator given the whole
    announced orders.
  - At the end: no server process, no process mapping a DAX device, no
    Slurm job of this experiment.
  - Not verified: anything in steady state; the re-keying pause in a run
    (measured without a server only); what the disks read (no counters).
- **Results:** real hardware; the jobs are training-demand emulation
  (real input pipeline with 8 read streams, paced consumer, no GPU).
  - The manager costs 70 µs per request with known order at this scale
    (131 with prefetching) and stops for 4.6 to 4.8 s every 131,072
    requests to re-key all resident files. Left unchanged (policy code).
  - Miss path through c28: 12.1 GB/s on data in the storage servers'
    memory (direct from 20 nodes: 37.2); cold with 320 streams 0.81 against
    0.78 GB/s; half cold 1.58 against 1.56; one cold pair 0.63 against 0.82.
  - P1, 8 jobs: 0.3% to 0.5% waiting in all four configurations.
  - P2, 40 jobs from cold storage, three minutes: direct BeeGFS 317
    samples/s of 672 (53% waiting); cache with known order and two-epoch
    prefetching, empty at the start, 281 samples/s (58% waiting) after a
    start-up of 40 s; 35% of its prefetches in time. The server got 0.78
    GB/s of the storage's output, the direct jobs 0.92.
  - **Negative, on method:** P1's cache runs read files the storage
    servers held from the direct run before them (same seeds). P2 used
    separate seeds.
  - BeeGFS reads: 0.98 TB (approved: at most 1.2).
- **Open questions:**
  - The comparison itself: known order against static pinning at the
    storage limit, disk reads, steady state, prefetching against none.
  - Sequences for it: a new seed base per configuration (proposed) or the
    same seeds as the task sheet says.
  - Disk counters need a free CPU on the storage servers; none before
    2026-11-25 14:00.
  - Whether the re-keying pass and the start-up should be reworked before
    or after the comparison (both are in the policy code).
  - The 23% gap of one miss-path pair is unexplained (single tests).
- **Next steps:**
  - With the user's approval: the main comparison as proposed in the
    summary (40 emulated jobs, five runs of 20 minutes, at most 9.8 TB of
    BeeGFS reads, 6 to 7 expected), when storage servers can be monitored.

## 2026-11-24 — Two-epoch lookahead and prefetching: implementation, scheduling analysis, small runs

- **Date:** 2026-11-24 (14:10 to 15:31; documents until 15:45)
- **Objective:** Task sheet "E010": verify that jobs can announce two
  epochs ahead without changing their order, extend the known-order cache
  with asynchronous prefetching coordinated with the unchanged replacement,
  and evaluate whether prefetching reduces data waiting: first by a
  trace-driven scheduling analysis, then with a few real clients. No
  multi-terabyte run.
- **Changes:**
  - `simulator/crossjob.py`: lookahead mode `epoch2` (policy name
    `known:epoch2`), `Lookahead.complete` and `ahead`, `KnownOrder.offer`
    (ranked admission of a file that is not resident, for prefetching) and
    `next_need`. The methods used on hits and misses are unchanged.
  - `system/cc_server.c`: background prefetch path (second work queue
    behind all demand work, cap on reads in flight, event `PREFETCHED`, two
    more counters). `system/cc_manager.py`: policy `known:epoch2`,
    prefetcher, accounting. `system/cc_server.py`: `--prefetch-par`,
    `--prefetch-lead`, `--prefetch-unused`. `system/cc_client.py`:
    `load --lookahead`, `--pace`. `system/cc_verify.py`: two-epoch
    announcement, `--prefetch`.
  - `benchmarks/train_io/cosmoflow_io.py`: `--cache-lookahead 2` (the next
    epoch is announced one epoch early).
  - `tests/test_cc_manager.py`: 6 new tests (50 in all).
  - Experiment `2026-11-24-two-epoch-lookahead-prefetch`: plan with
    hypotheses P1 to P7 written before any code, summary, tables, two
    figures, metadata, scripts (scheduling model `sched_sim.py`, series
    driver, analysis).
  - Evidence and status in `docs/research_questions.md`,
    `docs/research_idea.md` (R9 to R13, section 9),
    `docs/project_overview.md`, `docs/experiment_plan.md` (phases 7 to 9),
    `docs/related_work.md`, `docs/decisions.md` (addendum to D009),
    `system/README.md`, `simulator/README.md`,
    `benchmarks/train_io/README.md`, `tests/README.md`, `hardware/c39.md`,
    `README.md`, `CLAUDE.md`, and the experiment index.
- **Files affected:**
  - Repository: the files above.
  - Local, not tracked: `experimental_results/2026-11-24-two-epoch-lookahead-prefetch/`.
  - BeeGFS: `results/2026-11-24-two-epoch-lookahead-prefetch/`; libraries
    built into `tmp/build/cxlcache-e010/` (the earlier build is untouched).
  - CXL memory: `/dev/dax1.0`, bytes [0, 2.3 GB), inside the range the user
    agreed to on 2026-11-24 for this experiment (the whole device, asked
    before anything was mapped). No other device, no configuration change.
  - Not touched: the CosmoFlow benchmark directory, the datasets, earlier
    results, the earlier FitCache code.
- **Verification performed:**
  - 50 unit tests pass.
  - Without prefetching the manager decides as the simulator for all five
    policies including `known:epoch2`: 60 replays of three recorded traces
    (4.56 million accesses, immediate and delayed completions) and the logs
    of three training runs (53,248 accesses): no differing decision.
  - With prefetching: accounting closes in 24 replays; with the real server
    6,144 requests verified byte for byte, none differs; metadata
    invariants checked after every batch of events.
  - Order: identical request sets with one-epoch and two-epoch
    announcement (test clients and training harness); no request out of
    its announced order in any run.
  - The storage model of the scheduling analysis against measured waiting
    without a cache: refuted with the plan's parameters, within 10 points
    in eight cases after one refit. Against the hardware runs: one
    expectation refuted (below), the others within 5 points.
  - At the end: no server process, no process mapping a DAX device, no
    Slurm job of this experiment; link check unchanged (the ten known
    entries).
  - Not verified: anything with more than four jobs or with the storage at
    its limit on hardware; demand priority under contention; how much of
    each run the storage servers served from memory (no server had a free
    CPU for a monitor).
- **Results** (real hardware unless marked):
  - Four training jobs, own cold files, one pass, one read stream: 39.5%
    waiting directly from BeeGFS (10.2 samples/s per job); 18.7% through
    the cache with known order and no prefetching; 0.5% with prefetching
    (16.9 samples/s; 4,092 of 4,096 files prefetched in time). Direct with
    eight read streams: 0.5%.
  - Four training jobs on a shared pool of 2,048 files, three epochs, cache
    of 20%: bytes from the cache 18.4% (static), 47.2% (known order), 99.9%
    and 100.0% (with prefetching, one-epoch and two-epoch lookahead).
    Waiting differs only in the first epoch (4.0% direct, 1.1%, 1.2%, 0.5%,
    0.5%); afterwards 0.4% to 0.5% everywhere, the pool being in the
    storage servers' memory. BeeGFS reads: 71.2 GB direct, 58.1, 37.6, 41.7,
    40.8 GB.
  - One-epoch against two-epoch lookahead with prefetching: no difference
    in waiting; 2% fewer BeeGFS bytes; 661 cut prefetch windows against
    none.
  - **Negative or limiting:** a job with eight read streams does without a
    cache what prefetching does for a one-stream job; prefetching reads 8%
    to 11% more from BeeGFS than replacement alone; two-epoch lookahead
    changed no waiting.
  - **[Simulated]** Replacement alone: two-epoch lookahead equals
    whole-run knowledge on the three CosmoFlow traces (0.1 to 2.9 points
    over one-epoch lookahead). Scheduling model: 40 jobs on the full
    dataset wait 24.4% with and without prefetching (static pinning 21.6%,
    direct 34.8%).
  - Refuted expectation: the model had no waiting for the one-stream job
    behind the cache without prefetching; 18.7% was measured, because the
    harness's read stream also decompresses each file. Model corrected
    afterwards (14.1%).
  - 78 GB of files not read for days were read (limit 150 GB).
- **Open questions:**
  - What prefetching is for in this project, given that more read streams
    in the job do the same at this scale.
  - Whether anything changes at scale: the model says prefetching does
    nothing under a bandwidth deficit; not measured.
  - The exact meaning of "two epochs ahead" (read as current plus next).
- **Next steps:**
  - Proposed, not started: the one-stream case with a faster consumer;
    decompression out of the read stream of the cache pipeline; a smaller
    share of the capacity for prefetched files; with the user's approval,
    the bandwidth-bound comparison of 2026-11-18 with prefetching as one
    more configuration.
  - D006 and D008 still proposed, D007 not reviewed.

## 2026-11-24 — Research idea refined: two-epoch lookahead and asynchronous prefetching

- **Date:** 2026-11-24
- **Objective:** Update the research documentation with the refinement the
  user gave: direction and the three research questions kept, the mechanism
  extended from known-order replacement to known-order replacement with
  two-epoch lookahead and asynchronous prefetching, jointly managed.
  Documentation only: no code, no experiment, no commit.
- **Changes:**
  - `docs/research_idea.md`: status; the refinement and the fixed direction
    (section 1); the second half of the problem statement (section 3); new
    section 4, the combined mechanism, with the two store modes (evictable
    store, non-evictable famfs mode) and what the earlier findings say
    about prefetching; hypotheses R9 to R13 (section 5); contribution 4 and
    the state of contribution 3 (section 6); three findings that would
    redirect the extension (section 7); open design questions (section 8);
    new section 9, what exists, what is measured, what is hypothetical.
    Sections after 3 are renumbered. The evidence in section 2 and in rows
    R1 to R8 is unchanged.
  - `docs/research_questions.md`: direction statement; RQ1, RQ2, RQ3 in the
    refined wording with the earlier wording kept under each; the state of
    every added part; revision log. Evidence bullets unchanged.
  - `docs/decisions.md`: D009 (accepted, decision of the user); one
    cross-reference in D004 adjusted to the new section numbers.
  - `docs/experiment_plan.md`: phases 7 to 9 and the section "Extension:
    two-epoch lookahead and asynchronous prefetching" with the experiments
    needed next.
  - `docs/project_overview.md`: direction and mechanism in section 1,
    latency against bandwidth in section 2, three rows in section 8.
  - `docs/related_work.md`: prefetching in the novelty analysis (NoPFS is
    the prior work for prefetching from a known order in one job), the
    famfs tier of the earlier FitCache code, one item under "Not verified".
  - `README.md`, `CLAUDE.md` (project paragraph; rule 1.5 extended by one
    sentence on measuring replacement and prefetching separately),
    `system/README.md` and `simulator/README.md` (what is not implemented).
- **Files affected:** the documents above. Nothing under
  `experimental_results/`, no code, no data. The earlier FitCache code was
  read (header of its CXL pool), not changed and not run.
- **Verification performed:**
  - Read before writing: the research documents, the experiment index, and
    the summaries' conclusions as recorded in the tracked documents.
  - Numbers quoted for the new hypotheses were taken from tables already in
    `docs/research_idea.md` (hit rates with the rest of the epoch against
    the whole run on the four real traces) and from the index.
  - Link check unchanged (the ten known entries). No test was run: no code
    changed.
  - Not verified: any property of two-epoch lookahead or prefetching. No
    literature search was made for prefetching into a cache shared by
    several jobs.
- **Results:** none (documentation). State recorded: known-order
  replacement exists and is measured; two-epoch lookahead and asynchronous
  prefetching are not implemented and not simulated; the simulator has no
  notion of time.
- **Open questions:**
  - What "two epochs ahead" means exactly: read as the rest of the current
    epoch plus the next one; to be confirmed by the user.
  - Whether prefetching survives the comparison with a loader that has
    enough read streams (R13); where it can help at all on this cluster
    (latency-bound configurations) and where it cannot (bandwidth-bound).
  - Whether and where the non-evictable famfs mode is to be run: this
    project has no famfs mount it may use.
- **Next steps:**
  - Phase 7 of the experiment plan: characterize what two-epoch lookahead
    adds on the existing traces, then simulate the combined mechanism
    (needs simulator additions). Phases 8 and 9 need a go-ahead to implement
    and approval for storage traffic.
  - D006 and D008 are still proposed, D007 not reviewed.

## 2026-11-18 — Storage residency and a large working set: why reused data stays fast

- **Date:** 2026-11-18 (13:46 to 15:43; simulations and documents until 16:40)
- **Objective:** Task sheet "E009": explain why reused data stayed fast for
  20 jobs in the previous experiment, find out whether a large-working-set
  workload on this cluster has cross-job reuse and a storage stall at once,
  and compare the cache's policies there if it does.
- **Changes:**
  - Experiment `2026-11-18-large-working-set-reuse`: plan with hypotheses
    S1 to S5 written before the first measurement (changes, the user's
    approval, and the expectations for the large run in its section 10),
    summary, tables, four figures, metadata, scripts (server monitor, BeeGFS
    statistics logger, target map, multi-node reader, emulated-job
    launcher, probe selection by read history, workload simulation).
  - `benchmarks/train_io/cosmoflow_io.py`: `loader` mode can emulate a
    training job on the read side: `--pace-step` (a fixed step time after
    every batch), `--step-log`, `--max-seconds`, and `--start-unix` for this
    mode. Other modes unchanged.
  - `docs/decisions.md`: D008 (proposed), how a cache configuration is
    judged on this cluster.
  - Evidence and status in `docs/research_questions.md`,
    `docs/research_idea.md`, `docs/project_overview.md`,
    `docs/experiment_plan.md`, `docs/storage.md` (how the storage serves
    many readers), `hardware/c39.md` (storage servers: disks, settings,
    memory), `benchmarks/train_io/README.md`, `README.md`, `CLAUDE.md`, and
    the experiment index.
- **Files affected:**
  - Repository: the files above.
  - Local, not tracked: `experimental_results/2026-11-18-large-working-set-reuse/`.
  - BeeGFS: `results/2026-11-18-large-working-set-reuse/`.
  - CXL memory: none mapped. The user agreed to the whole of `/dev/dax1.0`
    for cache runs of this experiment; no cache run was made.
  - Not touched: the cache (`system/`), the simulator's policy classes, the
    CosmoFlow benchmark directory, the datasets, earlier results, any
    system setting. Storage servers were only read (`/proc`).
- **Verification performed:**
  - The cold share from disk counters against known cases: 1.00 to 1.06 on
    never-read files and 0.00 on files read seconds before, on four
    servers.
  - Supply against cold share at three set values (1, 0.5, 0.33), measured
    shares equal to the set ones.
  - The emulated job against files in memory: 16.67 samples/s, 0.8%
    waiting (a real training job: 16.83, 0.4%). Not checked against a real
    job on cold data: the run did not start cold.
  - Concurrency of the large run from the step logs; all 26 jobs reported;
    13 nodes at a CPU clock near 3 GHz.
  - The server-memory model of the simulation against the run: cold share
    0.59 simulated, 0.57 to 0.62 measured (20 jobs); 0.59 and 0.61 to 0.65
    (26 jobs).
  - At the end: no job of this experiment in Slurm, no process mapping a
    DAX device, link check unchanged (the ten known entries), 44 unit tests
    pass.
  - Not verified: anything about the cache on the full dataset (simulated
    only); the four unmonitored storage servers; why c14 is slow.
- **Results** (real hardware unless marked):
  - The storage is 14 single hard disks. To 160 read streams they give 0.66
    to 0.78 GB/s of cold bytes, about 50 MB/s each; the slowest server
    (c14, disks 74% to 94% busy, 67 to 114 requests queued) sets that.
  - Supply = cold ceiling / share of bytes from disk: 0.66, 1.46, 2.20 GB/s
    at shares of 1, 0.5, 0.33. 20 jobs wait only above a share of 0.7 to
    0.85.
  - One thread times a file by its slowest chunk. Yesterday's "cold" probe
    was a cohort with about half of its chunks in memory (**[Analytical]**).
  - Files read twice or more were in the servers' memory 18 hours later;
    files read once were not. Files read once stay while a server has room
    (in memory after 30 minutes) and leave when newer data has filled it.
  - **Negative for the cache at this scale:** 20 emulated jobs on the full
    shared dataset, direct BeeGFS, one hour (3.70 TB, approved by the user
    beforehand): 0.8% waiting from minute 10, the same as from memory; the
    servers serve 40% of the bytes from memory. 26 jobs: 3% waiting, c14's
    disk 84% busy.
  - Under that load a server holds the last 6 to 10 minutes of what it
    read; a second read adds minutes; yesterday's data in memory was gone
    after the run.
  - **[Simulated]** Full shared dataset, 256 GiB cache: known order serves
    49% of the bytes, static pinning and LRU 15%, progress-aware 17%. With
    the servers' memory behind the cache (600 GiB, the size that reproduces
    the measured cold share) the disks get 0.58 GB/s without a cache, 0.43
    with static pinning, 0.46 with known order at 20 jobs; 0.91, 0.68, 0.73
    at 32 jobs. Known order is ahead only if the servers keep less (0.50
    against 0.63 at 300 GiB).
  - Hypotheses: S1 to S5 held (S4's second part by minutes only). Refuted:
    that the large run would stall in its first minutes (the dataset was
    partly in memory), and that yesterday's twice-read data would survive
    the run.
  - No cache run and no real training run were made.
- **Open questions:**
  - Does the simulated two-level result hold on hardware: does known order
    leave the disks less to do than static pinning when demand is above the
    storage limit?
  - Why is c14 the slow server?
  - How does an emulated job compare with a real one on cold data?
- **Next steps:**
  - Asked at about 16:35 with these results, the user chose to read the report
    before anything else is run. Offered and left for a later task: 32 to 40 emulated jobs, direct
    BeeGFS against static pinning and known order through the cache (256
    GiB of `/dev/dax1.0`), 9 to 10 TB of BeeGFS reads, about 2.5 hours of 14
    to 20 nodes; before it, a small check of the cache server with the full
    catalog. D008 and D007 await review; D006 is still proposed.

## 2026-11-17 — Minimal CXL cache: implementation, validation, first training runs

- **Date:** 2026-11-17 (18:33 to 21:40; documents until 23:55)
- **Objective:** Task sheet "E008": implement a minimal shared CXL training
  cache (server on c28 with CXL memory as its store, Mercury, the existing
  policies, CosmoFlow's input pipeline), validate correctness and the
  known-order policy before any large run, and evaluate end to end as far as
  hardware and shared storage allow.
- **Changes:**
  - `system/`: the cache. Data plane `cc_server.c` (shared library, derived
    from the data-path benchmark), control plane `cc_manager.py` (all
    metadata, calls the simulator's policy classes), server process
    `cc_server.py`, client `cc_client.c` and `cc_client.py`, checker
    `cc_verify.py`, `Makefile`, `README.md`.
  - `benchmarks/train_io/cosmoflow_io.py`: input pipeline `cache` (file
    bytes from the cache server; everything else as pipeline `map`), options
    `--cache-addr-file`, `--cache-catalog`, `--cache-job`; per-epoch columns
    `cache_hits`, `cache_misses`.
  - `tests/test_cc_manager.py`: 12 tests of the manager without a server.
  - Experiment `2026-11-17-cxl-cache-integration`: plan with hypotheses C1
    to C8 written before any code existed (ten changes, the outcome of the
    late pair, and one correction recorded in its section 10), summary, tables, three figures, metadata, scripts.
  - `docs/decisions.md`: D007, the architecture of the cache.
  - Evidence and status in `docs/research_questions.md`,
    `docs/research_idea.md`, `docs/experiment_plan.md` (phase 4 done),
    `docs/project_overview.md`, `docs/storage.md` (what one thread's
    latency does not say about many readers), `hardware/c28.md` (cache
    server), `hardware/c39.md` (nodes of the evening),
    `workload_configs/cosmoflow/README.md`, `simulator/README.md`,
    `tests/README.md`, `benchmarks/train_io/README.md`, `README.md`,
    `CLAUDE.md`, and the experiment index.
- **Files affected:**
  - Repository: the files above.
  - Local, not tracked: `experimental_results/2026-11-17-cxl-cache-integration/`.
  - BeeGFS: `results/2026-11-17-cxl-cache-integration/` and the build
    directory `tmp/build/cxlcache/`.
  - CXL memory: `/dev/dax1.0`, bytes [0, 53.2 GB) and [64 GiB, 66.1 GiB),
    inside the range the user agreed to on 2026-11-17 (the whole device,
    asked before anything was mapped). `/dev/dax0.0`, `/dev/dax2.0`, and all
    device configuration untouched.
  - Not touched: the data-path benchmark (copied, not edited), the CosmoFlow
    benchmark directory, the datasets, `~/CXL`, FitCache, earlier results.
- **Verification performed:**
  - Policies: the manager against the simulator on five recorded and two
    synthetic traces without a server (120 comparisons, 10,660,464 accesses,
    also with completions delayed by up to 160 requests): no differing
    decision. Through the running server, one request at a time: 12 replays;
    one differed in 140 of 30,000 decisions, traced to the replay client
    announcing another epoch length than the simulator derives from that
    trace; none differs with the same number. The simulator on the logs of
    47 server runs (1,272,960 accesses, up to 20 training
    jobs): no differing decision; one reported difference was a comparison
    that renumbered objects.
  - Data: 877,280 objects returned by the server compared byte for byte with
    their files (hits and misses, four policies, DRAM and CXL stores, 1 to 8
    concurrent clients): none differs.
  - Metadata invariants (capacity, one object per slot, no slot reused while
    a transfer reads it) checked after every batch of events in all test
    runs; a bookkeeping fault for objects evicted during their admission
    copy was found by the delayed-completion test and fixed.
  - Training: tensors of pipeline `cache` identical to pipeline `map` (64
    batches); every (job, epoch, position) requested exactly once and equal
    to the harness's own log; no request out of the announced order in any
    run.
  - Concurrency of the 20-job runs from step timestamps; storage servers'
    counters logged; all nodes at full CPU clock.
  - At the end: no server process left, no process mapping a DAX device, no
    Slurm job of this experiment; no tmpfs copy on the four training nodes
    that could be checked (c37, c73, c78, c79; the other 16 were allocated
    to other users by then, and the job script removes its copy when it
    exits); link check unchanged (the ten known entries).
  - Found while writing up: the files that the runs X2d and X3d reuse had
    been read twice, not once (the memory pass copies them from BeeGFS
    again). Descriptions corrected; recorded in the plan.
  - 44 unit tests pass.
  - Not verified: anything at the scale of the full dataset; a limited cache
    with a policy under cold storage; behaviour when a job dies.
- **Results** (real hardware unless marked):
  - Hits over Mercury, 1 to 8 client nodes: 12.3 to 12.4 GB/s from the CXL
    store and from the DRAM store alike (the link limit); 7 to 9 µs of
    control plane per request; about 0.1 CPU cores on the server.
  - 20 training jobs, 8 read streams, never-read files: direct BeeGFS 274.5
    samples/s in total (17.3% waiting); through the cache with all misses
    260.2 (95% of direct); with half hits 331.4 (0.4% waiting); with all hits
    331.3; memory-resident 331.4.
  - Direct BeeGFS with half or a quarter of each job's files read by another
    job 10 or 50 minutes earlier (twice then: by its training and by its copy
    to tmpfs): 331.4 and 331.3 samples/s. At that distance
    the storage servers' memory does what the cache does.
  - **Negative, against the stated expectation:** 95 minutes after the cache
    was filled, a single-thread probe read the same files at cold latency
    (21 ms per file, 0.14 GB/s), and 20 direct jobs then re-read all of them
    at 330.7 samples/s with 0.5% waiting (through the cache: 331.6). The
    storage servers delivered 1.0 GB/s with a short queue. The run that was
    to show reuse beyond the storage servers' memory did not show it; no run
    has the cache ahead of direct BeeGFS on reused data. Cause not examined.
  - 20 training jobs on a shared pool of 1,024 files (in the storage
    servers' memory), bytes served from the cache at 18% and 36% capacity:
    known order 50.6% and 68.9%, progress-aware 26.0% and 46.4%, LRU 17.2%
    and 34.7%, static 17.7% and 35.5%; training 331 samples/s in every run
    and without the cache.
  - 155.8 GB of never-read files read, and 44.5 GB read directly a second
    time in the late run: 200.3 GB against a stated limit of 200 GB.
  - Hypotheses: C1, C3, C4, C5, C6 held; C2 held after an explained
    difference was removed; C7 held for half hits, its quarter point was not
    run through the cache; C8 held except that static pinning is slightly
    above LRU. Of the expectations added on the way, the one for the late
    direct re-read (15% waiting or more) was refuted.
- **Open questions:**
  - Why did 20 jobs get data at the full rate that one thread read at cold
    latency minutes before, and from which age or volume on does a direct
    re-read stall? Untested candidates: files partly in memory, file system
    metadata still cached on the storage servers, other users' load.
  - Does a capacity-limited cache with the known-order policy shorten
    training against direct BeeGFS on a dataset the storage servers cannot
    serve fast? Not run: it needs the full dataset, hundreds of gigabytes of
    cold reads, and hours of 20 GPU nodes.
  - Fixed slots waste 15% of the store; the server is the only BeeGFS reader
    for misses; one interpreter thread decides.
- **Next steps:**
  - Measure the 20-job re-read rate of once-read data against its age and
    the volume read in between, before designing the full-scale run.
  - The user decides whether to run the full-dataset evaluation (256 GiB
    cache in `/dev/dax1.0`, 20 jobs, cold reads far above the limits used so
    far) and reviews D007. D006 is still proposed.
  - Variable-size allocation; a job-death path; more than one reader for
    misses.

## 2026-11-17 — Multi-GPU training I/O saturation

- **Date:** 2026-11-17 (14:36 to 16:30; documents until about 18:15)
- **Objective:** Task sheet "E007": find, with real training, the number of
  concurrent GPU jobs at which shared BeeGFS limits CosmoFlow training
  although every job has a parallel, asynchronous loader; measure waiting
  and aggregate throughput against linear scaling; compare with
  memory-resident input; name a multi-job configuration for the later cache
  experiment. No cache implementation.
- **Changes:**
  - Experiment `2026-11-17-multi-gpu-io-saturation`: plan with hypotheses M1
    to M7 written before the measurements (eight changes recorded in its
    section 9), summary, tables, four figures, metadata.
  - No change to the harness. New scripts in the experiment directory: a
    launcher that selects never-read files per configuration, starts all
    jobs at one wall-clock time, logs the storage servers' counters, and
    cancels a configuration before its start if Slurm has not started every
    job; an analysis that works on the window in which all jobs read
    together and verifies concurrency from step timestamps.
  - Evidence added to `docs/research_questions.md` (RQ3; RQ1 and RQ2 for the
    twenty-job trace), `docs/research_idea.md`, `docs/workload_selection.md`,
    `docs/decisions.md` (second addendum to D006, still proposed),
    `docs/experiment_plan.md`, `docs/project_overview.md`, `docs/storage.md`
    (supply ceiling, server counters), `hardware/c39.md` (the nodes used,
    three nodes at half CPU clock, Slurm notes, storage targets),
    `workload_configs/cosmoflow/README.md`, `benchmarks/train_io/README.md`,
    `README.md`, `CLAUDE.md`, and the experiment index.
- **Files affected:**
  - Repository: the files above.
  - Local, not tracked: `experimental_results/2026-11-17-multi-gpu-io-saturation/`.
  - BeeGFS: `results/2026-11-17-multi-gpu-io-saturation/` and
    `traces/cosmoflow-twenty-job-20261117/` (new real trace with a provenance
    note).
  - Not touched: the CosmoFlow benchmark directory, the datasets, `~/CXL`,
    FitCache, any DAX device, the CPU clock setting found on three nodes,
    earlier results. tmpfs copies were deleted when each job ended.
- **Verification performed:**
  - Before the runs: compute-only check on 24 candidate nodes (no dataset
    read); the scripts tested end to end on two nodes with 128 files that
    were already read.
  - Concurrency of every reported configuration from the jobs' step
    timestamps: first steps within 0.2 to 0.8 s of each other, 39 to 50 s
    with all jobs reading together. One planned 8-job run had 7 concurrent
    jobs (found in the analysis, confirmed in `sacct`); it is reported as
    such.
  - Eight start attempts were cancelled before their start time; their step
    and access logs were checked to be empty.
  - Storage servers' counters against the jobs' own byte counts: equal within
    0.06 GB/s in every measured window.
  - CPU clock of every node recorded in each job from 15:00 on.
  - Every table row of the summary compared by script with `configs.csv`;
    four figures rendered and inspected; replay of the twenty-job trace with
    the simulator's invariant checks on; the 32 simulator unit tests pass.
  - After the runs: `/dev/shm` of all 20 nodes holds nothing of this user;
    no job of this project is running.
  - Not verified: that first-read files were cold (their speed and the
    servers' busy counters say so); the 15-job and 20-job results with two
    streams a second time; the cause of the slower first run.
- **Results** (real hardware unless marked; values in the window in which
  all jobs of a configuration read together):
  - Two read streams per job, nodes at full CPU clock, first reads: 16.2
    samples/s and 0.2% waiting at 1, 7, and 9 jobs; 12 jobs 13.45 samples/s
    and 17.2% waiting in the first run of the day, 16.19 and 0.3% in a
    repetition 70 minutes later; 15 jobs 14.14 and 13.0%; 20 jobs 12.21 and
    25.4%.
  - Aggregate on first reads: 111.5, 142.8, 150.7 or 180.7, 201.8, 237.0
    samples/s at 7, 9, 12, 15, 20 jobs: 99%, 98%, 78% or 93%, 83%, 73% of
    linear.
  - Eight read streams per job: 15 jobs 16.21 samples/s per job and 0.4%
    waiting (0.71 GB/s read, 10 requests queued at the servers on average);
    20 jobs 13.26 samples/s and 20.0% waiting (0.76 GB/s read, 0.80 GB/s
    leaving the servers, 43 requests queued; demand 0.945 GB/s).
  - Re-read data and memory-resident input: the node's full rate with 0.3%
    waiting in every configuration; 326 samples/s for 20 jobs. Memory against
    first reads in aggregate: 1.38 times (20 jobs, 2 streams), 1.24 times (20
    jobs, 8 streams), 1.20 times (15 jobs, 2 streams).
  - Three nodes with the CPU clock at 1.5 GHz wait 11% to 40% with two
    streams at every job count, also alone, and not from memory.
  - Twenty jobs on one shared subset, three epochs: full rate throughout; a
    trace of 138,240 accesses with logged job identity, 98% of them
    re-accesses after another job.
  - **Simulation** on that trace, cache of 20% of the data: LRU 27.5%, static
    19.6%, progress-aware 29.5%, known order 59.5%, offline reference 60.0%.
  - **Analytical:** storage limit for a loader with enough streams at 16 to
    17 jobs of this GPU class; at 20 jobs a cache would have to serve 19% of
    the bytes to bring the rest under the measured supply.
  - 249.3 GB of first reads, under the planned limit of 250 GB.
  - Hypotheses: M1 held on the seven jobs that ran together; M2 refuted in
    both directions (17.9% and 0.4% against a predicted 1% to 10%); M3, M4,
    M5, M6, M7 held. Of the expectations added while running, the one for
    the 12-job repetition was refuted and the one for 15 jobs with 8 streams
    held.
- **Open questions:**
  - Why was the first run of the day about 60% slower per file than later
    runs at the same load?
  - Do 15 and 20 jobs with two read streams wait as much in a repetition?
    Not run: the limit of first reads was reached (78 GB more).
  - How much of the demand of 20 jobs on one shared full dataset do the
    storage servers serve from their own memory? Every first read here was
    cold by construction.
  - What makes Slurm hold back jobs on c74 to c77 for minutes after a job
    ended there?
- **Next steps:**
  - The user decides on D006; a real-training tier with 20 jobs is now
    backed by measurements.
  - Configuration for the cache experiment: 20 jobs with 8 read streams
    each (storage-limited against a well-configured loader), the same with 2
    streams, and 9 jobs with 2 streams or 15 jobs with 8 as the control
    without headroom.

## 2026-11-16 — Training I/O against reader count and job count

- **Date:** 2026-11-16 (15:25 to about 17:45)
- **Objective:** Task sheet "E006": characterize how the number of data-loader
  readers and the number of concurrent GPU jobs change training throughput
  and waiting for storage, with asynchronous loading kept, and name candidate
  configurations for the later cache experiment. No cache implementation.
- **Changes:**
  - Experiment `2026-11-16-loader-gpu-scaling`: plan with hypotheses S1 to
    S7 written before the measurements (one design change recorded in it),
    summary, tables, three figures, metadata.
  - Harness `benchmarks/train_io/cosmoflow_io.py`: new pipeline `map`
    (exactly `--read-par` files read and decompressed at a time), `--order
    list` (the same file sequence in every epoch), `--start-unix`
    (synchronized start on several nodes). The README now states that the
    `par` pipeline, tf.data's interleave, keeps up to three files open per
    cycle slot.
  - Correction notes about that in the earlier experiment's summary and
    index row and in `docs/workload_selection.md`, `hardware/c28.md`,
    `workload_configs/cosmoflow/README.md`.
  - Evidence added to `docs/research_questions.md`, `docs/research_idea.md`
    (eight-job trace), `docs/workload_selection.md`, `docs/decisions.md`
    (addendum to D006, still proposed), `docs/experiment_plan.md`,
    `docs/project_overview.md`, `hardware/c28.md`, `hardware/c39.md` (eight
    GPU nodes, a Slurm epilog note), `README.md`, `CLAUDE.md`, and the
    experiment index.
- **Files affected:**
  - Repository: the files above.
  - Local, not tracked: `experimental_results/2026-11-16-loader-gpu-scaling/`.
  - BeeGFS: `results/2026-11-16-loader-gpu-scaling/` and
    `traces/cosmoflow-eight-job-20261116/` (new real trace with a provenance
    note).
  - Not touched: the CosmoFlow benchmark directory, the datasets, `~/CXL`,
    FitCache, any DAX device. tmpfs copies were deleted after each pass, on
    c28 and on the GPU nodes.
- **Verification performed:**
  - Before the runs: c28 idle, no other experiment of the user, no DAX
    mapping; the eight GPU nodes idle and identical (compute-only check on
    each).
  - New harness options smoke-tested; the `map` pipeline yields tensors
    identical to `par` and `seq` on 16 files; the multi-job node script was
    tested end to end on one node with 32 already-read files.
  - The number of files the interleave has open was measured (3, 6, 24 at
    cycle length 1, 2, 8) before the reader count was redefined.
  - Two 8-job configurations ran with 7 jobs (a job killed by the previous
    job's epilog). Found from the job count in the analysis, confirmed in
    `sacct`, the launcher fixed, both runs kept as 7-job runs and repeated
    with 8 jobs.
  - Replay of the eight-job trace with the simulator's invariant checks on;
    the 32 simulator unit tests pass.
  - Numbers in the summary and tracked documents compared with `results.csv`
    and the replay output; three figures rendered and inspected.
  - Not verified: that first-read files were cold (their speed says so);
    anything beyond eight jobs; a faster GPU.
- **Results** (real hardware unless marked):
  - One GPU (c28), exactly r read streams, cold files, three repetitions:
    12.52 samples/s and 26.0% waiting with 1 stream; 16.85 samples/s and 0.4%
    waiting with 2, 4, 8, or 16. Re-read data and memory: 16.83 to 16.86 at
    every count. Memory against cold with one stream: 1.35 times.
  - Loader only: one stream supplies 11.9 samples/s from cold storage, 25.5
    from re-read data, 28.0 from memory.
  - Eight identical GPU nodes, one job each, baseline reader (interleave
    cycle length 8): 16.85 to 16.90 samples/s per job for 1, 2, 4, 7, and 8
    jobs, 0.4% waiting; 135.0 samples/s and 0.391 GB/s in total at 8 jobs.
  - Exact streams and jobs combined: with 1 stream per job, 11.19 / 11.27 /
    10.93 / 10.13 / 9.93 samples/s per job at 1 / 2 / 4 / 7 / 8 jobs, waiting
    33.8% to 41.5%; with 2 streams, 16.81 to 16.88 at 1 to 8 jobs; with 4
    streams at 8 jobs, 16.87. Memory: 16.84 to 16.85 per job.
  - Eight jobs on one shared subset, three epochs: 16.84 to 16.86 samples/s
    each; a trace of 55,296 accesses with logged job identity.
  - **Simulation** on that trace, cache of 20% of the data: LRU 27.3%, static
    19.1%, progress-aware 30.6%, known order 57.3%, offline reference 58.6%,
    Quiver-inspired replay 88.3%.
  - 205.9 GB of first reads, under the planned limit of 250 GB.
  - Hypotheses: S1, S3, S4, S6, S7 held; S2 held in direction but
    underestimated the wait (26% against a predicted 2% to 25%); S5 refuted
    (waiting grows 1.23 times from 1 to 8 single-stream jobs, not 1.5 times).
- **Open questions:**
  - Does the baseline reader wait near 15 concurrent jobs, as estimated? Not
    run: it sits at the storage limit for about a minute and needs the
    user's decision. Fifteen idle nodes of this GPU class existed at 16:27.
  - How many streams does an A100-class job need on cold data?
  - Which real training setups are limited to one read stream, so that the
    single-stream configurations are more than a demonstration?
- **Next steps:**
  - The user decides on D006 and on the 15-job run.
  - Candidate configurations for the cache experiment: one read stream per
    job, alone and as eight jobs, each compared against the baseline reader.

## 2026-11-16 — Workload selection and training I/O validation

- **Date:** 2026-11-16 (13:25 to about 15:00; two residency probes later)
- **Objective:** Task sheet "E005": find and validate a workload in which a
  shared CXL cache has a real opportunity. Compare candidate workloads,
  characterize how long BeeGFS serves data from the storage servers' memory,
  and measure for the best available workload whether training waits for
  storage. No cache implementation.
- **Changes:**
  - Experiment `2026-11-16-workload-io-validation`: plan with hypotheses W1
    to W8 written before the measurements, summary, tables, four figures,
    metadata. It supersedes `2026-11-11-training-io-characterization`, which
    was never run.
  - New harness `benchmarks/train_io/cosmoflow_io.py`: file selection with a
    ledger, raw reads, staging to tmpfs, loader only, compute only, and
    training with per-step wait and compute times and an access trace that
    records job identity. Derived from the earlier `train_trace.py`; origin
    stated in the file.
  - `docs/workload_selection.md` rewritten against the twelve criteria of the
    task, with the measured evidence and the selection.
  - `docs/decisions.md`: D006 (evaluation workload and how to reach a
    storage-bound regime), status proposed.
  - Evidence added to `docs/research_questions.md` (RQ1 to RQ3, H2, revision
    log), `docs/research_idea.md` (second real trace, R1, R5, R8),
    `docs/experiment_plan.md` (Phase 1 done), `docs/project_overview.md`,
    `docs/related_work.md` (MLPerf Storage demand values from the v1.0
    workload files), `docs/storage.md` (read behaviour of BeeGFS),
    `hardware/c28.md` (training measurements), `hardware/c39.md` (c24, c38,
    storage servers), `workload_configs/cosmoflow/README.md` (dataset sizes,
    measured rates), `benchmarks/README.md`, `scripts/README.md`,
    `README.md`, `CLAUDE.md`, and the experiment index.
- **Files affected:**
  - Repository: the files above; `benchmarks/train_io/` (new).
  - Local, not tracked: `experimental_results/2026-11-16-workload-io-validation/`.
  - BeeGFS: `results/2026-11-16-workload-io-validation/` (48 MB: raw tables,
    file lists, the ledger `used_files.txt`, a size listing of the full
    dataset) and `traces/cosmoflow-two-job-20261116/` (new real trace with a
    provenance note).
  - Not touched: the CosmoFlow benchmark directory, the datasets, `~/CXL`,
    FitCache, any DAX device. tmpfs copies under `/dev/shm` were deleted after
    each trial.
- **Verification performed:**
  - Before the runs: c28 idle, GPU idle, no other experiment of the user, no
    process mapping a DAX device. c33 (A100) and c44 were allocated to other
    users and were not used.
  - All modes of the harness smoke-tested on 48 files before the plan's
    measurements. 0 failed phases in the main run.
  - A 5% gap between training and "compute only" was traced to the synthetic
    compute-only batch living on the GPU; compute-only was repeated with a
    batch in host memory.
  - The replay of the new trace ran with the simulator's invariant checks on.
    The 32 simulator unit tests pass.
  - All numbers in the summary and in the tracked documents were compared
    with `results.csv` and the replay output.
  - Both figures of the training results and the policy figure were rendered
    and inspected.
  - Link check over all Markdown files: only the 10 known references to the
    other repository and to historical paths.
  - Not verified: that "first read" files were cold (only their speed says
    so); the storage servers' memory beyond three of seven; the cause of the
    weak LRU result on the new trace; anything about candidates B, C, and D
    beyond published configuration files.
- **Results** (real hardware unless marked):
  - Full CosmoFlow training set: 524,288 files, 1,519.75 GB (measured, no
    longer an estimate).
  - c28, RTX 4060 Ti, batch 2, 16 cores, three repetitions on fresh files.
    Training step alone: 17.01 samples/s. Training with a parallel reader:
    16.86 samples/s from first-read BeeGFS, re-read BeeGFS, and host memory
    alike, 0.4% of the time waiting for data. Training with the benchmark's
    sequential reader: 6.79 / 14.01 / 14.68 samples/s, waiting 60% / 17% /
    13%.
  - Input pipeline alone, 16 cores: from memory at most 209 samples/s (68 to
    76 ms of CPU per sample, 31 ms of it decompression); from first reads 112
    to 155 samples/s with 8 to 32 readers. With 64 readers on 64 cores: 224
    from first reads, 523 from memory.
  - First reads from 1, 2, and 4 client nodes at once (8 threads each, one
    run per level): 0.36, 0.58, 0.74 GB/s in total. The total follows the
    number of streams, not of clients.
  - Residency: once-read files 100% warm after 15 minutes, 0% after 60;
    twice-read files 100% warm after 60 minutes; files read 18 to 20 hours
    earlier 0% warm. The experiment read 60.6 GB for the first time, 52 GB
    of it between those two probes.
  - Two concurrent jobs on c24 (16.2 samples/s) and c38 (10.6 samples/s):
    a trace of 34,560 accesses with logged job identity.
  - **Simulation** on that trace, cache of 20% of the data: LRU 6.3%, static
    18.0%, progress-aware 25.1%, known order 30.9%, offline reference 34.3%,
    Quiver-inspired replay 28.4%.
  - **Analytical**: a full-dataset epoch takes 1.9 to 8.6 hours and the
    dataset is 2.2 times the storage servers' memory, so its epochs are cold;
    storage would limit training from a summed demand of about 255 samples/s,
    which is about 15 jobs on these GPUs or four A100-class GPUs.
  - Hypotheses: W1, W2, W3, W5 held; W4 refuted (the pipeline is cheaper than
    expected); W6 half refuted (multiply-read data was cold after 18 hours);
    W8 order held, threshold missed (79.3% against 80%); W7 held (added
    17:45: once-read files 0% warm after one, two, and four hours;
    twice-read files warm after two hours and cold after four, after the
    next experiment had read about 190 GB).
- **Open questions:**
  - D006 is a proposal: how should the evaluation reach a regime in which
    storage limits training, given that real training on the available GPUs
    does not?
  - How long is once-read data kept on a quiet day, without this
    experiment's own reads?
  - First-read supply beyond 32 streams, and on other days.
  - Does the A100 wait for data with a parallel reader? Only its throughput
    is known, historically.
  - Why is LRU so much weaker on the new trace?
- **Next steps:**
  - The user decides on D006.
  - Cheap follow-ups without a cache: the residency cohorts on a quiet day
    (about 2 GB of reads); an instrumented run on c33 after 2026-11-21.
  - Runs at the storage limit read hundreds of GB of cold data per ten
    minutes and need the user's approval.

## 2026-11-15 — Remote CXL cache data path: measurements on c28 completed

- **Date:** 2026-11-15 (18:14 to about 19:45)
- **Objective:** Finish experiment `2026-11-12-remote-cxl-data-path` (task
  sheet "E004"): remote DRAM and remote CXL retrieval through Mercury,
  admission cost, concurrent reads and writes, and an I/O replay of the
  two-job trace. The c28 part had waited since 2026-11-12 for another
  experiment of the user to leave the machine.
- **Changes:**
  - Checked before starting: the other experiment's queue ended on
    2026-11-14 16:21; no process mapped a DAX device; c28 idle.
  - Client node c44 instead of c39 (allocated to another user); c44 inspected
    and found identical in the items checked. Direct BeeGFS path measured
    again from c44.
  - Plumbing tests with the CXL store, then the main session on
    `/dev/dax1.0` bytes [0, 16 GiB) (phases load, B, C, D, E; 302 client
    runs, none failed) and a second session on `/dev/dax0.0` bytes
    [0, 16 GiB) (phases load, B, D; 148 runs, none failed). Both ranges as
    agreed by the user on 2026-11-12. Nothing else was mapped.
  - Driver: cells for puts through a DRAM buffer and a repetition setting
    added before the main session (after a plumbing test showed slow NIC
    writes into CXL); recorded in the plan as a dated note, hypotheses
    unchanged.
  - Summary rewritten as the final report; two figures; result tables;
    metadata; index row.
  - `hardware/c28.md` (copy rates of DRAM and CXL, devdax registration for
    RDMA, the NIC write limit), `hardware/c39.md` (now also c44),
    `docs/research_questions.md` (RQ3 evidence), `docs/research_idea.md`
    (R6, open design points), `docs/decisions.md` (D005; D004 superseded),
    status lines in `README.md`, `CLAUDE.md`, `benchmarks/README.md`,
    `docs/experiment_plan.md`, `docs/project_overview.md`.
- **Files affected:** `WORKLOG.md`, `README.md`, `CLAUDE.md`,
  `benchmarks/README.md`, `hardware/c28.md`, `hardware/c39.md`,
  `docs/experiments/INDEX.md`, `docs/decisions.md`,
  `docs/research_questions.md`, `docs/research_idea.md`,
  `docs/experiment_plan.md`, `docs/project_overview.md`. Local, not tracked:
  `experimental_results/2026-11-12-remote-cxl-data-path/` (summary, plan
  note, driver, figure script, tables, figures). On BeeGFS:
  `results/2026-11-12-remote-cxl-data-path/run-20261115-*` (786 MB in total
  for the experiment). The benchmark sources were not changed on this day.
- **Verification performed:**
  - Objects fetched from the DRAM and the CXL store compared equal to the
    files (256 per store in the main session and in the second session).
  - No client run reported an error or a mismatch (450 measured runs).
  - Server InfiniBand counters match the bytes moved in the runs inspected.
  - Numbers in the summary were recomputed from the result tables; three
    were corrected after the check.
  - Both figures were rendered and inspected; overlapping labels fixed.
  - After the sessions: no benchmark process left, no DAX mapping left, the
    client node released. 32 unit tests of the simulator pass.
  - Not verified: the cause of the NIC write limit into CXL; the cause of
    the two regimes of FitCache's read path; anything with more than one
    client node; any cold-storage replay.
- **Results:** real hardware (client c44, server c28), medians of 3:
  - Zero-copy gets: remote DRAM 10.1 / 12.3 / 12.3 GB/s and remote CXL
    10.2 / 11.5 / 12.3 GB/s at 1 / 4 / 16 threads; the link carries 12.5.
    Server CPU 0.05 cores. Null RPC about 30 µs.
  - Direct BeeGFS from c44: first reads 0.07 / 0.23 / 0.56 GB/s, recently
    read 2.27 / 8.48 / 12.32 GB/s at 1 / 4 / 16 threads; 6.5 client cores at
    16 threads against 0.2 through the cache. Files read on 2026-11-12 were
    cold again.
  - Local copy rates on c28: CXL about 52 GB/s read and 47 GB/s write; DRAM
    up to 136 and 73.
  - Admission from BeeGFS into the store: DRAM and CXL equal, 2.6 / 9.2 /
    12.3 GB/s on recently read files and 0.07 / 0.24 / 0.6 GB/s on cold files
    at concurrency 1 / 4 / 16.
  - Gets with admissions: under 1% loss. Gets with puts through a DRAM
    buffer: 12.3 + 12.3 GB/s, for DRAM and CXL. NIC writes into CXL: 4.24
    GB/s, and concurrent gets fall to 0.77 GB/s; same on both devices.
  - I/O replay of the two-job trace at 20% capacity, storage recently read
    (not training): no cache 21.9 s; static 25.7 s; known-order 26.9 s;
    progress-aware 27.0 s; LRU 29.9 s; identical for DRAM and CXL.
  - Analytical, not measured: with every miss a cold read, known-order would
    take about 280 s against about 480 s without a cache.
  - Hypotheses: D1, D2, D3, D7, D10, D11 held; D4, D6, D8, D12 partly; D5,
    D9, D13 refuted (D9 in the favourable direction).
- **Open questions:**
  - Why NIC writes into CXL memory are limited to 4.24 GB/s and why they
    stall reads.
  - How the cache behaves with several clients on one server port.
  - Whether training on this cluster is storage-limited for data that the
    storage servers do not hold in memory, and how often that state occurs.
  - D005 part 2 (data path rules) is a proposal and awaits the user.
- **Next steps:** a workload beyond the storage servers' memory or a
  cold-storage replay agreed with the user; the planned training I/O
  characterization with concurrent jobs; a miss path that is not slower than
  a direct read. Nothing of this session is committed.

## 2026-11-12 — Remote CXL cache data path: audit, benchmark, direct BeeGFS path (interim)

- **Date:** 2026-11-12 (evening, about 18:00 to 18:40)
- **Objective:** Characterize the data path of a remote CXL training data
  cache: retrieval through Mercury from remote DRAM and remote CXL against
  direct BeeGFS, admission cost, concurrent reads and writes, and a replay of
  the earlier traces. Task sheet "E004"; experiment
  `2026-11-12-remote-cxl-data-path`. The research idea and RQ1 to RQ3 are
  fixed by the user for now; this experiment does not change them.
- **Changes:**
  - Phase A audit (read-only): c28 memory, DAX devices, network, libfabric,
    Mercury; FitCache's communication and CXL pool code (read, not modified);
    c33 (occupied by another user's job, not entered); c39 as the client node.
  - New benchmark `benchmarks/remote_cache/` (`rcb_server`, `rcb_client`,
    `rcb_membw`), built out of tree on BeeGFS against FitCache's Mercury 2.0.1.
    A standalone tool instead of FitCache, because FitCache's CXL pool needs a
    file system and cannot use the devdax devices, and its read path cannot be
    driven without its preload client. FitCache's read path is one of the
    benchmark's modes.
  - Experiment directory with plan (hypotheses D1 to D13, written before the
    measurement run), workload generator, drivers for the direct path and for
    the server-side phases, replay workload generator, analysis script,
    interim summary, metadata, and one result table.
  - New `hardware/c39.md`; `hardware/c28.md`: network and RPC software, other
    use of the machine by the same user, agreed DAX use.
  - Status lines in `README.md`, `CLAUDE.md` (also: check for processes of
    the user's other projects before using a DAX device), `benchmarks/README.md`,
    `docs/experiment_plan.md`; evidence notes in `docs/research_questions.md`
    (RQ3) and `docs/research_idea.md` (R5); one row in
    `docs/experiments/INDEX.md`.
- **Files affected:** `benchmarks/remote_cache/` (new: `rcb_common.h`,
  `rcb_server.c`, `rcb_client.c`, `rcb_membw.c`, `Makefile`, `README.md`),
  `benchmarks/README.md`, `hardware/c39.md` (new), `hardware/c28.md`,
  `README.md`, `CLAUDE.md`, `WORKLOG.md`, `docs/experiments/INDEX.md`,
  `docs/experiment_plan.md`, `docs/research_questions.md`,
  `docs/research_idea.md`. Local, not tracked:
  `experimental_results/2026-11-12-remote-cxl-data-path/`. On BeeGFS:
  `tmp/build/remote_cache/` (binaries),
  `results/2026-11-12-remote-cxl-data-path/` (`workloads/`,
  `replay-two-job-c20/`, `run-20261112-182026-direct-c39/`, and
  `run-20261112-182621-remote-smoke/`, a plumbing test that is not a
  measurement).
- **Verification performed:**
  - Mercury transport between c39 and c28 checked with counters: 2.967 GB of
    payload raised c28's InfiniBand transmit counter by 2.984 GB, `eth0` by
    72 kB, the IPoIB device by 0 bytes. The address reported by Mercury is
    `ofi+verbs;ofi_rxm://` on the InfiniBand interface.
  - Data correctness: objects returned through zero-copy and COPY gets after
    admission from BeeGFS compared equal to the files (64 of 64 from c39,
    16 of 16 locally).
  - All phases of the server-side driver except phase E passed a plumbing
    test with a DRAM-only server. Its one reported mismatch count comes from
    the test's own truncation (only 256 of 2,048 objects were loaded) and was
    confirmed as such by the numbers; it is not a data error.
  - The replay workloads reproduce the simulator's hit, admission, and
    eviction counts for four policies on the re-sized two-job trace.
  - 32 unit tests of the simulator still pass (the simulator was not changed).
  - Not verified: whether a devdax mapping can be registered for RDMA; phase
    E's driver section; anything on CXL memory. No DAX device was opened.
- **Results:** real hardware, direct BeeGFS reads from c39 only (CosmoFlow
  files of 2.9 MB, three repetitions per cell):
  - First reads: 0.11 GB/s with 1 thread, 0.36 with 4, 0.64 with 16, 0.77
    with 32; median latency per file 27 ms at 1 thread and 98 ms at 32.
  - Recently read files: 2.03 GB/s with 1 thread, 8.8 with 4, 12.2 with 16,
    12.3 with 32, which is the limit of the client's 100 Gb/s link; median
    latency 1.3 to 1.4 ms up to 4 threads.
  - Two of the seven storage servers inspected: 93 GiB of memory each, 50 to
    52 GiB of cached file data.
  - Consequence for RQ3: a remote cache behind the same kind of link can help
    only with data the storage servers do not hold in memory, where the
    direct path is 16 to 24 times slower.
- **Open questions:**
  - Everything about remote DRAM, remote CXL, admission cost, and
    interference. Hypotheses D1 to D5 and D8 to D13 are untested.
  - The trace replay against "storage as it is" will mostly see recently read
    data, because the 26.7 GB trace fits the storage servers' memory. A
    cold-miss regime would mean reading on the order of a terabyte through
    the shared storage servers; not done without the user's agreement.
  - How long data stays in the storage servers' memory under normal load.
- **Blocked, by decision of the user (2026-11-12):** all measurements on c28
  wait until the queue of the user's LLM serving study has finished there. It
  maps both DAX devices in many of its stages. Agreed for this experiment
  afterwards: the first 16 GiB of `/dev/dax1.0` (main CXL store) and of
  `/dev/dax0.0` (second check of the read path).
- **Next steps:** when c28 is free: confirm that nothing maps the DAX devices,
  re-establish the storage state of the object set, run phases load, B, C, D
  (about 30 minutes of load on c28) with DRAM and CXL interleaved, then phase
  E, then analysis and the final assessment. The steps are in section 8 of
  the experiment's summary. Nothing of this session is committed.

## 2026-11-12 — Cross-job known-order cache management (trace replay)

- **Date:** 2026-11-12 (evening)
- **Objective:** Test whether independent jobs can expose enough of their
  upcoming access order for a shared cache to beat history-based policies, and
  compare that with per-job caches, with coordination that changes the jobs'
  order (Quiver), and with an offline reference. Task sheet "E003"; experiment
  name `2026-11-12-cross-job-known-order`.
- **Changes:**
  - Reviewed the earlier simulator (model, accounting, reference). Online
    policies are now built from `online_view()`, which leaves out the offline
    facts of the trace.
  - New `simulator/crossjob.py`: the known-order policy (`known:<lookahead>`,
    with options for a wrong rate, delayed progress, and the rate-averaging
    window), per-job caches (`perjob-static`, `perjob-lru`), a Quiver-inspired
    replay (`quiver`, `quiver-full`; an approximation that changes the jobs'
    read order, not a reproduction), and `bound`, an upper bound on the object
    hit rate of order-preserving policies.
  - `simulator/cachesim.py`: dispatch to the cross-job policies, mean
    occupancy as a new result column, heap compaction for ranked policies
    (no change in decisions).
  - `scripts/make_multijob_trace.py`: options for job speeds, epochs per job,
    dataset overlap, and a smaller file count.
  - Job identity of the real two-job run reconstructed from the jobs' seeds
    and checked against the logged open times (99.95% to 100% of adjacent
    training opens in increasing time order per job and epoch). New trace
    `trace-jobs.csv` with its script and provenance note next to it.
  - Thirteen synthetic compositions with 16,384 files: 1, 2, 4, 8 jobs;
    staggered and joint starts; speed ratios 1:2, 1:4, 1:1:2:4; 50% and 25%
    overlap; one job leaving.
  - Experiment directory with plan (hypotheses K1 to K7 written before the
    run), driver, table and figure scripts, summary, results, four figures,
    and metadata. One row added to `docs/experiments/INDEX.md`.
  - `docs/research_idea.md` rewritten around the result (hypotheses R1 to R8);
    `docs/related_work.md`: Quiver and NoPFS mechanisms in more detail and a
    comparison with the candidate; `docs/research_questions.md`: evidence and
    revision log; `docs/decisions.md`: D004, proposed.
  - Correction note added to the summary and index row of
    `2026-11-12-cache-policy-replay`. Its reported numbers were left as they
    were.
- **Files affected:** `simulator/cachesim.py`, `simulator/crossjob.py` (new),
  `simulator/README.md`, `tests/test_crossjob.py` (new), `tests/README.md`,
  `scripts/make_multijob_trace.py`, `scripts/README.md`, `README.md`,
  `CLAUDE.md` (current-state paragraph), `WORKLOG.md`,
  `docs/research_idea.md`, `docs/related_work.md`,
  `docs/research_questions.md`, `docs/decisions.md`,
  `docs/experiment_plan.md`, `docs/project_overview.md`,
  `docs/experiments/INDEX.md`. Local, not tracked:
  `experimental_results/2026-11-12-cross-job-known-order/` and one note in
  `experimental_results/2026-11-12-cache-policy-replay/summary.md`. On BeeGFS:
  `traces/fitcache-two-job-20260514_040247/{trace-jobs.csv,reconstruct_jobs.py,PROVENANCE.md}`,
  `traces/2026-11-12-cross-job-synthetic/`,
  `results/2026-11-12-cross-job-known-order/` (two run directories).
- **Verification performed:**
  - `python3 -m unittest discover -s tests`: 32 tests pass (14 earlier, 18
    new), rerun after the last code change. The new tests cover capacity
    accounting, admission and bypass, eviction, per-job progress, the
    cross-job next-use estimate, absence of oracle leakage (decisions do not
    change when the unannounced future changes), and deterministic replay.
  - All 20 replay jobs of the reported run finished with exit code 0 with
    invariant checks on.
  - The extended simulator reproduces the earlier experiment on the real
    single-job trace: 20 rows compared, identical.
  - Numbers quoted in the summary were recomputed from `results.csv`.
  - The four figures were rendered and inspected; label collisions fixed.
  - Not verified: the figure palette with the validator script (`node` is not
    installed); the Quiver-inspired replay against the real Quiver (no code
    available here, and the paper reports no hit rates).
- **Results:** all **simulation** (trace replay; byte hit rates, no timing).
  - Real two-job trace, capacity 5 / 10 / 20 / 40 / 80% of the data. LRU 9.1 /
    11.5 / 16.6 / 28.5 / 61.7. Static pinning 4.5 / 8.9 / 17.9 / 35.8 / 72.3.
    Progress-only policy 11.5 / 19.0 / 32.0 / 53.5 / 80.4. Known order for the
    rest of the epoch 25.3 / 32.6 / 43.5 / 58.8 / 81.8. Known order for the
    whole run 26.5 / 34.6 / 46.0 / 63.5 / 82.2. Offline reference 26.6 / 34.7
    / 46.2 / 63.5 / 82.2. Quiver-inspired replay 52.9 / 55.6 / 62.0 / 62.0 /
    62.0.
  - Per-job caches of the same total size: 8.0% at 20% capacity.
  - A quarter-epoch lookahead gives 86% or more of the gain. A rate estimate
    wrong by 2x costs about 1 point; progress every 512 accesses costs nothing.
  - Synthetic compositions: the advantage over order-preserving baselines
    holds for 2, 4, 8 jobs and speed ratios up to 1:4. Against the
    Quiver-inspired replay the known-order policy is ahead with unequal speeds
    from 10% to 20% capacity upward, with partial overlap, and at large
    capacity.
  - All seven hypotheses held, including K7, which predicted that
    order-changing coordination beats the candidate for equal-speed jobs.
  - One job: announced order gives nothing beyond static pinning.
  - The known-order policy writes about half of all requested bytes into the
    cache (26 times static pinning at 20% capacity).
- **Open questions:**
  - Whether keeping each job's sampling order is a requirement. The case for
    the known-order policy over a Quiver-style design rests on it.
  - No real trace with more than two jobs, unequal speeds, or partial overlap.
  - The default rate-averaging window was changed after the first run, when a
    20-access average made the policy fall below static pinning on the
    single-job trace. Both runs are kept; the multi-job results do not depend
    on the setting.
  - Whether fewer storage reads shorten training; nothing about CXL or RPC.
  - Nothing of this session is committed.
- **Next steps:** (1) examine what order-changing coordination would need from
  CosmoFlow's input pipeline and what it does to sampling; (2) collect real
  multi-job traces with job identity logged; (3) run
  `2026-11-11-training-io-characterization` with concurrent jobs. Building the
  remote cache is not recommended yet (D004, proposed).

## 2026-11-12 — Experiments reorganized by date; experiment content kept out of Git

- **Date:** 2026-11-12 (later the same day)
- **Objective:** Apply the user's instruction on how experiments are
  organized, modeled on the `~/CXL` repository: one dated directory per
  experiment with a summary, experiment content not pushed, and an untracked
  `docs/slides/` directory.
- **Changes:**
  - Experiments are now named `YYYY-MM-DD-<short-name>`. The earlier IDs map
    as follows: E001 is `2026-11-11-training-io-characterization`, E002 is `2026-11-12-cache-policy-replay`.
  - Each experiment has one directory under `experimental_results/` holding
    its `plan.md`, `summary.md`, `metadata.json`, and small results. The two
    existing experiments were moved there from `docs/experiments/` and from
    `experimental_results/E002-cache-policy/`.
  - `.gitignore`: everything under `experimental_results/` except `README.md`
    and `metadata_template.json` is ignored, and so is `docs/slides/`.
  - New tracked `docs/experiments/INDEX.md`: one row per experiment with a
    short outcome. This is the only experiment record that goes to GitHub.
  - `docs/slides/` created (empty).
  - On BeeGFS, `results/E002-cache-policy/` was renamed to `results/2026-11-12-cache-policy-replay/` and
    `traces/E002-synthetic/` to `traces/2026-11-12-synthetic-multijob/`.
  - References in `CLAUDE.md`, `README.md`, the documents under `docs/`,
    `hardware/c28.md`, the READMEs, and the simulator's header were changed
    to the new names. Tracked documents no longer link into experiment
    directories.
  - `docs/experiments/001-training-io-characterization-plan.md` was tracked
    and pushed earlier. It now lives in the untracked experiment directory, so
    the next commit removes it from the repository (it stays in the history).
- **Files affected:** `.gitignore`, `CLAUDE.md`, `README.md`, `WORKLOG.md`,
  `docs/experiments/INDEX.md` (new), `docs/experiments/TEMPLATE.md`,
  `docs/experiment_plan.md`, `docs/storage.md`, `docs/decisions.md`,
  `docs/research_idea.md`, `docs/research_questions.md`,
  `docs/related_work.md`, `docs/workload_selection.md`,
  `docs/project_overview.md`, `hardware/c28.md`,
  `workload_configs/cosmoflow/README.md`, `simulator/README.md`,
  `simulator/cachesim.py` (header text only), `scripts/README.md`,
  `experimental_results/README.md`; the two experiment directories (local).
- **Verification performed:**
  - `git status` lists no file under the experiment directories or
    `docs/slides/`; `git check-ignore` confirms both are ignored, and that
    `experimental_results/README.md` and `metadata_template.json` are not.
  - Unit tests pass after the header change in the simulator.
  - Markdown links re-checked; no tracked document links into an experiment
    directory.
  - No reference to the old experiment IDs remains outside this log.
- **Results:** None.
- **Open questions:**
  - Experiment directories now exist only on the home file system. There is
    no copy on GitHub.
  - Earlier entries of this log use the old IDs and paths. They describe the
    state at that time.
- **Next steps:** Unchanged from the entry below.

## 2026-11-12 — Research idea check: related work, workloads, policy simulator, first trace replay

- **Date:** 2026-11-12 (afternoon)
- **Objective:** Validate the research problem behind "online reuse-aware
  caching with CXL memory for distributed training" and build a minimal
  cache-policy evaluation framework. No distributed cache system.
- **Changes:**
  - New documents: `docs/research_idea.md`, `docs/workload_selection.md`.
  - Experiment `2026-11-12-cache-policy-replay` (local directory under `experimental_results/`):
    `plan.md` (hypotheses written before the run), `summary.md` (results),
    `results.csv`, `metadata.json`.
  - `docs/related_work.md` rewritten with facts checked against the full text
    of NoPFS, Quiver, SHADE, DeepMemoryDL, FitCache, HVAC, and CoorDL, and a
    novelty analysis.
  - `docs/research_questions.md`: RQ1-RQ4 replaced by the RQ1-RQ3 of the new
    task; revision log updated. `docs/decisions.md`: D003.
  - New code: `simulator/cachesim.py` (nine policies, replay engine),
    `tests/test_cachesim.py` (14 tests), `scripts/convert_train_trace.py`,
    `scripts/convert_fitcache_log.py`, `scripts/make_multijob_trace.py`.
  - READMEs of `simulator/`, `tests/`, `scripts/`, the top-level `README.md`,
    `docs/experiment_plan.md`, and `CLAUDE.md` brought up to date.
  - Nothing was committed.
- **Files affected:** the files above, and on BeeGFS under
  `/mnt/beegfs/ghu4/cxl-train-cache/`:
  - `traces/cosmoflow-c33-run61440/` (extracted from `~/CXL` with `git show`)
  - `traces/fitcache-two-job-20260514_040247/` (extracted from the log archive
    on `/mnt/local`, plus the converted trace)
  - `traces/fitcache-16gpu-20261006/` (converted trace; logs read in place)
  - `traces/2026-11-12-synthetic-multijob/` (four synthetic compositions)
  - `results/2026-11-12-cache-policy-replay/run-20261112-140742/` (first, partial run) and
    `run-20261112-142837/` (complete run)
  - Read only, not modified: `~/CXL`, `~/hvac/FitCachePP`, `~/benchmark/SHADE`,
    `/mnt/local/ghu4/hvac-server-logs-2026-11-10`.
- **Verification performed:**
  - 14 unit tests pass (run before the replay and again after each change to
    the simulator), including `oracle` against an exhaustive search and the
    capacity and byte-accounting checks.
  - The replay ran with invariant checks on.
  - Job 0 of the synthetic traces reproduces the file order of the real c33
    run exactly.
  - Two replay runs: all 270 result rows of the six traces present in both are
    identical.
  - LRU on the real single-job trace matches its closed form to within 0.11
    percentage points.
  - The two-job log is complete in volume: 93,211 opens against 92,160
    expected, 8,778 of 9,217 files with exactly ten opens.
  - Paper facts were checked against the primary PDFs by a delegated reading,
    with quotes and URLs. They were not re-read by hand.
  - The FitCache source was read by a delegated inspection, in part. Nothing
    there was built, run, or modified.
  - Markdown links re-checked.
  - Not done: no training run, no hardware measurement, no CXL access, no
    measurement of Mercury or of any network path.
- **Results:** Simulation only (trace replay; byte volumes, no timing). Details
  in `experimental_results/2026-11-12-cache-policy-replay/summary.md` (local).
  - One job (real trace, 3 epochs): static pinning, the epoch-aware candidate,
    and the future-aware reference read exactly the same bytes at every
    capacity. LRU, LFU, SLRU, TinyLFU, and the history-based candidate are
    worse. No opportunity for reuse-aware replacement.
  - One job on 16 GPUs (real trace, four full epochs and a partial fifth):
    static pinning and the epoch-aware candidate are identical and ahead of
    every other online policy. The reference is 0.8 to 3.4 points ahead,
    which comes from the trace ending mid-epoch (0.3 to 0.5 points on the four
    complete epochs). The history-based candidate was not run on this trace:
    its simulation did not finish in 30 minutes.
  - Two jobs on one dataset (real trace, 5 epochs): at 20% capacity the
    future-aware reference serves 46.2% of the bytes, static pinning 17.9%,
    LRU 16.6%, the epoch-aware candidate 27.2%. At 5% capacity LRU (9.1%) is
    ahead of the candidate (7.1%); the reference serves 26.6%.
  - Synthetic two- and four-job compositions: same picture, with static
    pinning as the strongest simple policy and the candidate recovering 25% to
    87% of the gap to the reference, more at larger capacities.
  - Hypotheses H1 to H5 of the plan confirmed; H6 (the simple online candidate
    recovers most of the gap) not confirmed.
  - Related work: static retention for one job is published practice (CoorDL);
    Quiver already coordinates eviction across jobs, by changing the sample
    order; NoPFS already uses the known future order, within one job;
    DeepMemoryDL used emulated CXL. FitCache has no replacement policy.
- **Open questions:**
  - Does the multi-job gap hold on real traces with job identity, more than
    two jobs, different speeds, and staggered starts?
  - Can a policy that is given each job's sample order reach the reference
    online? It was not built.
  - How does a chunk-based policy in the style of Quiver compare?
  - How common are concurrent jobs on one dataset on the target systems?
  - Does avoiding storage reads shorten training? `2026-11-11-training-io-characterization` is still not run.
  - Nothing is known about a remote CXL cache: Mercury overhead, CXL
    bandwidth, comparison with remote DRAM.
  - `reuse-gap` is slow to simulate on traces with repeated opens.
- **Next steps:**
  - Collect a real multi-job trace with job identity (two to four short
    CosmoFlow jobs through the tracing trainer, different seeds, staggered).
  - Add a known-order policy and a chunk-based baseline to the simulator and
    repeat the trace replay on that trace.
  - Run the reduced first pass of `2026-11-11-training-io-characterization`.
  - Decide on committing this work.

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
  - The GitHub repository is public. Before publishing, the repository was
    scanned for credentials, e-mail addresses, and addresses; the NFS
    server's internal address was removed from `docs/storage.md`.
  - `origin` uses the SSH URL of the repository. The push over the HTTPS URL
    failed because no credential helper is configured on this machine; SSH is
    what the user's other repository uses.
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
  - After each push, local `main` and `origin/main` pointed to the same commit.
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
