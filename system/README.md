# system/ — minimal shared CXL training cache

A cache server that keeps training files in CXL memory (or DRAM) and serves
them to several training jobs over Mercury, with the replacement policies of
the trace simulator. Written for experiment `2026-11-17-cxl-cache-integration`
([docs/experiments/INDEX.md](../docs/experiments/INDEX.md)); the architecture
choice is decision D007 in [docs/decisions.md](../docs/decisions.md).

**Status: a working prototype, not a product.** One server, no persistence
across restarts, no protection against faulty clients, fixed-size slots.

## Parts

| File | Runs on | What it is |
|---|---|---|
| [cc_server.c](cc_server.c) | server | Data plane, a shared library. One store of fixed slots (anonymous DRAM, or a byte range of a devdax device), registered once and read-only for the NIC; Mercury RPCs; worker threads for file reads and copies. Takes no decision. Derived from the data-path benchmark ([benchmarks/remote_cache](../benchmarks/remote_cache/README.md)). |
| [cc_manager.py](cc_manager.py) | server | Control plane. Object table, slot table, reference counts of running transfers, job table, statistics; one thread owns all of it. Calls the simulator's policy classes ([simulator/](../simulator/README.md)) for every access, unchanged. |
| [cc_server.py](cc_server.py) | server | The server process: loads the data plane, runs the manager on its events, writes the access log and the summary. |
| [cc_client.c](cc_client.c) | training nodes | Client library: Mercury client with a pool of registered buffers; blocking `get`, callable from many threads. |
| [cc_client.py](cc_client.py) | training nodes | Python binding (`CacheClient`) used by the training input pipeline, and two test programs: `replay` (a recorded trace, one request at a time) and `load` (one job with seeded epochs). |
| [cc_verify.py](cc_verify.py) | anywhere | Compares the manager's decisions with the simulator: on a recorded trace without a server, or on the access log a server wrote. |
| [cc_common.h](cc_common.h) | both | Wire structures and helpers. |

The training harness uses the client through its input pipeline `cache`
([benchmarks/train_io](../benchmarks/train_io/README.md)).

## Data paths

| Case | Path | CPU copies of the payload on the server |
|---|---|---|
| Hit | store slot → NIC (RDMA) → client buffer | 0 |
| Miss | BeeGFS → DRAM buffer (worker thread) → NIC → client buffer; the response is sent; then, if the object is admitted, DRAM buffer → store slot (`memcpy`) | 0 before the response, 1 for the admission |

The NIC never writes into the store: the store is registered read-only, and
admission is a CPU copy from DRAM, the combination measured to be free of
interference in `2026-11-12-remote-cxl-data-path`. The client copies the
payload once, from its registered buffer into the string TensorFlow gets.

## What a job tells the cache

- At registration: a numeric job identifier, its seed, its epoch length, and
  the total number of accesses it will make.
- Before each epoch: the order of that epoch, as object identifiers, in
  pieces of 256.
- With every request: epoch and position.

That is the `known:epoch` lookahead of the simulator and nothing beyond it.
With policy `known:epoch2` (two-epoch lookahead, since 2026-11-24) a job
also announces the next epoch, one epoch early (`cc_client.py load
--lookahead 2`, harness option `--cache-lookahead 2`); the policy then sees
the rest of the current epoch and the whole next one.
Objects are the files of a **catalog** (lines `path bytes`) that server and
clients share; the identifier is the line number.

## Prefetching (since 2026-11-24, optional)

`cc_server.py --prefetch-par N [--prefetch-lead S] [--prefetch-unused M]`,
with a known-order policy only.

- For every job the manager keeps the announced accesses of the next `S`
  seconds (5 by default; the job's measured rate turns seconds into
  accesses). Files in that window that are not resident are candidates,
  soonest estimated need first across jobs. The window is checked again,
  at the rate measured then, when a candidate is offered (correction of
  2026-11-24, experiment `2026-11-24-large-scale-cache-evaluation`: a job
  with several read streams sends its first requests at once, the rate
  measured at that moment is far too high, and without the second check
  the prefetcher ran ahead until the `unused` limit; the jobs of
  `2026-11-24-two-epoch-lookahead-prefetch` had one read stream and did
  not show it).
- A candidate is offered to the policy with `KnownOrder.offer`: the ranked
  admission of a miss, with the file's current key and without moving any
  job's position. The replacement rule itself is unchanged. If admitted,
  the data plane reads the file into a DRAM buffer and copies it into the
  slot, as for an admission, without a client.
- Demand first: workers take request work before prefetch reads; at most
  `N` prefetch reads run at once (`N` may be at most half of the workers
  and of the DRAM buffers); at most `M` prefetched files wait for their
  first use (default: a quarter of the capacity).
- A request for a file whose prefetch is still running waits for that read
  (the client sees a hit that waited).
- Counters in the summary: `prefetch_issued`, `prefetch_in_time`,
  `prefetch_late`, `prefetch_evicted_unused`, `prefetch_unused_now`,
  `prefetch_declined` (not needed sooner than what it would displace),
  `prefetch_passed` (the job got there first), `prefetch_window_cut` (the
  announced order ended inside the window). Log kinds 5 and 6 mark a hit
  on a prefetched file in time and late.
- With prefetching the server's log cannot be compared with the simulator:
  the simulator has no prefetching.

## How decisions are taken

1. A request waits until every earlier position of its job has been
   processed (a job with several read streams sends them slightly out of
   order). A request that waits longer than 0.5 s for a predecessor is
   processed anyway and counted as an order gap.
2. The manager checks the object against the announced order (a difference
   is counted), builds the access `(time, job, epoch, object, 1)`, and asks
   the policy: `contains`, then `on_hit` or `on_miss`. Evictions decided by
   the policy take effect in the metadata at once.
3. Hit: the slot's reference count goes up until the transfer has finished.
   A slot whose object was evicted is reused only when its count is zero.
4. Miss: served from BeeGFS; if admitted, the object gets a free slot and is
   copied in after the response. Requests for an object whose copy is still
   running wait for it and are then served from the store.

Policies: `static` (pinned, admission bypass), `lru`, `reuse-epoch`
(progress-aware), `known:epoch` (known order). The policy sees every object
as one unit; the capacity is a number of slots. A slot is 3,407,872 bytes
(3.25 MiB) by default, enough for the largest CosmoFlow file; the mean file is
2.90 MB, so 15% of the store is unused. The store has `--spare` slots more
than the capacity for objects in transit.

Time is passed to the policy in seconds since the server started, rounded to
the microsecond, and logged with the same value, so the simulator can be run
on the log with identical inputs.

## Build

Out of tree, never into the home directory:

```bash
make MERCURY_PREFIX=<mercury install> BUILD_DIR=$CXL_TRAINING_DATA_ROOT/tmp/build/cxlcache
```

Used with Mercury 2.0.1 (the installation FitCache links against) and
libfabric 1.19.0. Every process that loads a library needs `RDMAV_FORK_SAFE=1`
and libfabric on the library path.

## Run

```bash
# server (on the machine with the memory)
python3 cc_server.py --catalog CATALOG --policy known:epoch --capacity-slots 4096 --backend dram \
    --proto 'ofi+verbs;ofi_rxm://<server InfiniBand address>' --addr-file ADDR --out OUTDIR --pin 0-47
python3 cc_server.py ... --backend dax --dax-path /dev/daxX.Y --dax-offset 0 --dax-agreed /dev/daxX.Y:START:END

# one test job with 8 requests in flight, every byte verified against the files
python3 cc_client.py load --addr-file ADDR --catalog CATALOG --job 1 --seed 1 --objects 0:2048 --epochs 3 --threads 8 --verify
python3 cc_client.py ctl shutdown --addr-file ADDR      # writes OUTDIR/accesses.csv and summary.json

# decisions against the simulator
python3 cc_verify.py offline TRACE.csv --capacities 0.05,0.2 [--delay 64]
python3 cc_verify.py log OUTDIR/accesses.csv

# training through the cache
python3 ../benchmarks/train_io/cosmoflow_io.py train --pipeline cache --cache-addr-file ADDR --cache-catalog CATALOG \
    --cache-job 1 --file-list LIST --read-par 8 --parse-par 4 --epochs 3 --seed 1 --out OUT --label j1
```

**A devdax store is real memory that may hold someone's data.** The server
maps exactly `[dax-offset, dax-offset + store bytes)` and writes there. It
refuses to start unless that range lies inside `--dax-agreed` and no other
process of the user maps the device (other servers of the same experiment
are named with `--dax-other-servers`). Use only a device and byte range the
user has agreed to ([CLAUDE.md](../CLAUDE.md), hardware safety).

## Options for large catalogs and for measurements (since 2026-11-24)

Added for `2026-11-24-large-scale-cache-evaluation` (full CosmoFlow
catalog, 524,288 objects, 40 jobs, 80,659 slots). None takes part in a
decision.

- `--no-gc`: switches Python's cyclic garbage collector off. The manager
  and the policies build no reference cycles; with millions of announced
  positions the collector made the first request of a job take up to 4.5 s
  (0.6 s without it).
- `--timeline N`: a line of cumulative counters every `N` seconds in
  `timeline.csv` (requests, hits, bytes, admissions, evictions, prefetch
  counters, read times, the data plane's counters, CPU, and the longest
  single pass of the manager since the last line).
- `summary.json` also has `read_ms_histogram` (time of every file read for
  a miss and for a prefetch, in powers of two of a millisecond) and
  `manager_longest_pass_s`.
- `--slots-high-first`: fills the store from its last slot downwards; a
  test of the top of a large store.
- Hold timeout: with a backlog of events the server judges "the
  predecessor did not arrive within 0.5 s" on the arrival time of the last
  event processed, not on the wall clock, so that a long pass of the
  manager is not taken for a missing predecessor.
- `cc_client.py load --objects-file FILE`: the job's objects as catalog
  identifiers from a file, instead of a contiguous range.
- **Re-keying with arrays** (2026-11-24, evening). The manager builds its
  known-order policy with `KnownOrder(dense=N)`: the objects are the
  catalog's line numbers, so the policy keeps, per job, an array of the
  next announced position of every object and a byte of flags beside its
  dictionaries, and computes the periodic re-keying of all residents for
  all of them at once (numpy). Same expressions, same operands: the keys
  are equal to the last bit and no decision changes. The simulator keeps
  the per-object pass and is the reference. With 80,659 residents and 40
  jobs a pass takes 0.07 to 0.09 s instead of 4.6 to 4.8 s. Memory: 4.7 MB
  per job for a catalog of 524,288 objects.
- **Client address** (2026-11-24, evening). `cc_client.py` names the RDMA
  device of `ib0` in its Mercury address
  (`ofi+verbs;ofi_rxm://mlx5_0/<address>`). With the address alone Mercury
  did not initialise on c51 and c52, which have two RoCE devices besides
  the InfiniBand one.

## Tests

`tests/test_cc_manager.py`: the manager against the simulator on synthetic
traces for all five policies, with and without delayed completions; the
prefetcher's accounting and limits and the two-epoch lookahead; slot
reuse, waiting for a running admission, eviction during a copy, ordering,
and refusal of unknown jobs; the prefetch window after a burst of first
requests; the array re-keying against the simulator's per-object pass with
a pass every 29 requests, also with prefetching and a job that leaves its
announced order. No server needed. The known-order tests need numpy.

## Limits

- The control plane is one Python thread; the data plane is C. Cost per
  request: about 10 µs on small catalogs; with the full CosmoFlow catalog,
  40 jobs, and 80,659 slots 4 µs for `static` and 70 µs for the known-order
  policies (130 µs with prefetching), measured without a server on
  2026-11-24.
- The known-order policy re-keys every resident file every
  `max(4096, objects / 4)` accesses, and no request is answered during
  that pass. With 80,659 residents and 40 jobs it took 4.6 to 4.8 s
  (every 195 s at 672 requests/s) until 2026-11-24; computed with arrays
  it takes 0.07 to 0.09 s (measured without a server; the decisions are
  unchanged). The same pass runs when a job starts, changes its epoch, or
  ends.
- The first request of a job still costs 0.3 s (one announced epoch) to
  0.6 s (two) with `--no-gc`: the policy takes in every announced
  position. This was not changed.
- Memory of the manager with 40 jobs on the full catalog: under 20 GiB
  with one announced epoch per job, under 25 GiB with two (largest resident
  size of the check without a server; the running server's was not
  recorded).
- Start-up with long epochs is slow: 40 jobs that announce two epochs of
  524,288 files each kept the manager busy for 40 s (passes of up to 8.5 s)
  before they ran at their rate (`2026-11-24-large-scale-cache-evaluation`).
- Every miss and every prefetch is read by the server machine, one BeeGFS
  client with at most 12 connections to a storage server. Its capacity is
  not the limit (12.1 GB/s on data in the storage servers' memory, the
  100 Gb/s link), but when the storage is saturated and other users read as
  well, it received a smaller share than 20 client nodes reading directly
  (0.78 against 0.92 GB/s in one pilot), and its requests queue on the
  server machine, not at the storage servers.
- The client assumes the InfiniBand interface is `ib0` and takes the
  first RDMA device under it. Naming the device was needed on c51 and c52
  (two RoCE devices besides the InfiniBand one); why c58, with the same
  devices, worked without it was not examined.
- Fixed slots: 15% internal fragmentation for CosmoFlow; one object per file.
- A job that stops without deregistering keeps its announced future in the
  known-order policy.
- No persistence: a restart loses the content. No replication, no second
  server, no prefetching.
- Prefetching is minimal: one window and one concurrency limit for all
  jobs, no adaptation to what the storage delivers, no protection of a
  prefetched file beyond its rank, and every prefetch is read by the server
  machine. It was measured with four jobs only
  (`2026-11-24-two-epoch-lookahead-prefetch`).
- Clients are trusted. A client can ask for any object of the catalog.
- The validation pass of the harness (`--valid-list`) does not go through
  the cache.
