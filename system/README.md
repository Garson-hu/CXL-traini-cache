# system/

Reserved for the implementation of the CXL training data cache.

**Status: nothing is implemented.** No internal architecture has been chosen.

## Possible future components

Listed to mark the scope of this directory, not as a design:

- Cache lookup.
- Cache admission.
- Cache eviction.
- Cache capacity management.
- CXL memory allocation.
- DataLoader integration.
- Cache statistics.

## Before adding code here

- The design must follow from measurements (Phases 1-3 of the
  [experiment plan](../docs/experiment_plan.md)), not precede them.
- Start with the simplest mechanism that the evidence supports. Static pinned
  caching with admission bypass is the baseline to beat.
- Record the architecture choice and its evidence in
  [docs/decisions.md](../docs/decisions.md).
- Do not hardcode storage or device paths. Large data is addressed through
  `CXL_TRAINING_DATA_ROOT` ([docs/storage.md](../docs/storage.md)).
- Changing CXL, DAX, or NUMA configuration needs explicit approval
  ([CLAUDE.md](../CLAUDE.md), "Hardware safety").
