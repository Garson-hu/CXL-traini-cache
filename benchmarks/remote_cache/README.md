# remote_cache — remote cache data-path benchmark (`rcb`)

Measures what it costs to move training data objects between a client node
and a memory region on a server through Mercury, and to admit objects from
the file system into that region. Written for experiment
`2026-11-12-remote-cxl-data-path`.

It is a measurement tool, not a cache. The server holds objects in fixed slots
and does what the client tells it. There is no index, no policy, no eviction.

| Program | Runs on | Purpose |
|---|---|---|
| `rcb_server` | the machine with the memory under test | serves GET, PUT, FETCH on a store that is either DRAM or a byte range of a devdax device |
| `rcb_client` | a client node | executes a workload file with N blocking threads and records every request |
| `rcb_membw` | the server machine | local copy rates of the same kind of store, no network, no storage |

Transport and RPC pattern follow FitCache: Mercury over libfabric, protocol
`ofi+verbs;ofi_rxm://`, the client registers a buffer and sends its bulk
handle, the server moves data with `HG_Bulk_transfer` and then responds.

## Data paths

| Request | Flags | Path | CPU copies on the server |
|---|---|---|---|
| GET | 0 | NIC reads the store, RDMA into the client's buffer | 0 |
| GET | 1 (COPY) | store to a pooled, registered DRAM buffer, then RDMA | 1 |
| GET | 11 (COPY+ALLOC+INLINE) | FitCache's read path: on the progress thread, `calloc`, `memcpy`, register, RDMA, free | 1, plus zeroing and registration |
| PUT | 0 | RDMA from the client's buffer into the store | 0 |
| PUT | 1 | into a DRAM buffer, then `memcpy` into the store | 1 |
| FETCH | 0 | the server reads the file into the slot and sends it from there | 0 beyond the file system's |
| FETCH | 1 | file into a DRAM buffer, `memcpy` into the slot, send from the buffer | 1 |
| FETCH | +4 (NOPUSH) | admission only, nothing sent back | as above |
| FETCH, slot -1 | 0 | file into a DRAM buffer, sent to the client, not stored | 0 |
| direct (`B`) | — | the client reads the file itself; no server | — |

Flag values: 1 COPY, 2 ALLOC, 4 NOPUSH, 8 INLINE (see `rcb_common.h`).

## Build

Out of tree, never into the home directory:

```bash
make MERCURY_PREFIX=<mercury install> BUILD_DIR=$CXL_TRAINING_DATA_ROOT/tmp/build/remote_cache
```

Used so far with Mercury 2.0.1 (the installation FitCache links against) and
libfabric 1.19.0. No `-march=native`: server and client run on different CPUs.

## Run

```bash
# server: 16 GiB DRAM store, or a devdax byte range
rcb_server --backend dram --store-bytes $((16<<30)) --proto 'ofi+verbs;ofi_rxm://<server IB address>' \
           --addr-file ADDR --workers 16 --pin 0-23
rcb_server --backend dax --dax-path /dev/daxX.Y --dax-offset 0 --store-bytes $((16<<30)) ...

# client
rcb_client --workload W.txt --threads 16 --out run.csv --server-file ADDR \
           --proto 'ofi+verbs;ofi_rxm://<client IB address>' [--repeat R] [--seconds S] [--verify]

# local copy rates
rcb_membw --backend dram|dax ... --readers 8 --writers 8 --seconds 4
```

Both need `RDMAV_FORK_SAFE=1` and libfabric on the library path. The driver
scripts of the experiment set this up.

**A devdax store is real memory that may hold someone's data.** The server
maps exactly `[dax-offset, dax-offset + store-bytes)` and writes there when a
client sends PUT or FETCH; `rcb_membw` writes there when `--writers` is above
zero. Use only a device and byte range the user has agreed to
([CLAUDE.md](../../CLAUDE.md), hardware safety).

## Workload file

One operation per line: `OP FLAGS SLOT SIZE [PATH]`, with OP one of `G` (get),
`P` (put), `F` (fetch), `N` (null RPC), `B` (direct read). Threads take
operations in file order. A write to a slot waits for earlier operations on
that slot, and a get waits for an earlier write of its slot, so a recorded
admission and eviction sequence is replayed in order.

## Output

- Client, standard output: one JSON line (operations, bytes, wall time, GB/s,
  requests/s, client CPU seconds, errors, mismatches, start time).
- Client, `--out`: one CSV row per request: thread, operation, slot, size,
  result, start time, latency as seen by the thread, and the server's time
  split into queueing, file read, copy, and bulk transfer.
- Server, at exit: totals and its CPU seconds.
- `--verify` compares every object received with the file it came from.
  `--sum` on the server adds a checksum of the stored object to each response.
  Both are for correctness checks and slow the run down.

## What it does not measure

Decompression and parsing of the data, GPU work, an object index or
allocator, more than one client link, and failure handling.

## Verified

2026-11-12, functional checks only: data returned through every GET path and
through FETCH compared equal to the files; with a server on c28 and a client
on c39 the bytes moved appear on the InfiniBand port counters and not on the
Ethernet or IPoIB interfaces. There are no unit tests: the programs need
Mercury and an RDMA network.
