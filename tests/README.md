# tests/

Reserved for correctness and regression tests.

**Status: no tests yet, and no test framework has been chosen.** A framework is
introduced together with the first code that needs testing.

## Conventions for future tests

- Tests are small and fast. They must not need a real dataset, a GPU, or CXL
  hardware. Use small synthetic inputs kept in the repository.
- Tests that need large data or special hardware are experiments, not tests.
- Cache policies are checked against hand-computed results on small traces.
- A cache implementation must be tested for data correctness: bytes served
  from the cache equal bytes read from storage.
- Record in [WORKLOG.md](../WORKLOG.md) which tests were actually run after a
  change. "Tests pass" is only written when they were run.
