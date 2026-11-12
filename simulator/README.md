# simulator/

Reserved for trace-driven cache simulation.

**Status: the simulator is not implemented.** No simulation results exist.

## Intended scope

Replay file-access traces of training workloads through cache policies and
report storage reads avoided, under a given cache capacity.

Baseline policies to support eventually:

- No cache.
- LRU.
- Static pinned caching with bypass.
- Future-aware replacement.
- Offline oracle bounds.

Capabilities to support eventually:

- Cache capacity sweeps.
- Trace replay.
- Result generation (summary tables and figures).

## Conventions for the future implementation

- Simulator output is simulation. It is never reported as a hardware
  measurement and never as evidence of training speedup on its own.
- Large traces are read from `$CXL_TRAINING_DATA_ROOT/traces/`. Only small
  synthetic traces for tests live in the repository.
- Every policy needs a correctness test on a small hand-checked trace
  ([tests/README.md](../tests/README.md)).
- Seeds for synthetic traces are fixed and recorded.
- First check to run once it exists: analytical note A1 in
  [docs/research_questions.md](../docs/research_questions.md) predicts that
  static pinning matches the offline bound for single-job once-per-epoch traces.
