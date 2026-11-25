#!/usr/bin/env python3
"""Build a SYNTHETIC multi-job trace: several training jobs reading overlapping datasets.

What is real: the file sizes (from a files.txt of a real run), and the way each job orders its
epochs, which is the code of the tracing trainer used for the real run:
    numpy.random.default_rng(seed * 1000003 + epoch).permutation(N)
What is assumed: that several jobs exist, how many, when each starts, how fast each one reads,
how many epochs it runs, and how much their datasets overlap. The output header labels the trace
as synthetic and records every parameter.

Job j uses seed --seed-base + j, starts j * --stagger epochs (of job 0) after job 0, and reads
--rates[j] files per time unit.

Dataset overlap: with --overlap f, the first f * N files are shared by all jobs and every job
has (1 - f) * N files of its own. With the default 1.0 all jobs read the same N files. File sizes
of private files reuse the real size list cyclically.

Usage:
  make_multijob_trace.py --files FILES.txt --jobs K --epochs E --out OUT.csv
        [--n-files N] [--stagger S] [--rates 1,2,...] [--epochs-per-job 3,2,...]
        [--overlap F] [--seed-base 0]                      (refuses to overwrite)
Needs numpy.
"""
import argparse
import heapq
import os
import sys

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", required=True, help='lines "<id> <name> <bytes>"')
    ap.add_argument("--jobs", type=int, required=True)
    ap.add_argument("--epochs", type=int, required=True)
    ap.add_argument("--n-files", type=int, default=0, help="use only the first N files (default: all)")
    ap.add_argument("--stagger", type=float, default=0.0, help="start offset between jobs, in epochs of job 0")
    ap.add_argument("--rates", default="", help="files per time unit for each job (default: 1 for all)")
    ap.add_argument("--epochs-per-job", default="", help="epochs for each job (default: --epochs for all)")
    ap.add_argument("--overlap", type=float, default=1.0, help="fraction of each job's dataset shared by all jobs")
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.exists(a.out):
        sys.exit(f"refusing to overwrite {a.out}")
    real = []
    with open(a.files) as f:
        for line in f:
            real.append(int(line.split()[2]))
    n = a.n_files or len(real)
    assert 0 < n <= len(real)
    rates = [float(x) for x in a.rates.split(",")] if a.rates else [1.0] * a.jobs
    epochs = [int(x) for x in a.epochs_per_job.split(",")] if a.epochs_per_job else [a.epochs] * a.jobs
    assert len(rates) == a.jobs and len(epochs) == a.jobs and 0.0 <= a.overlap <= 1.0
    shared = int(round(a.overlap * n))
    private = n - shared

    def dataset(j):                                   # object ids of job j
        return list(range(shared)) + [shared + j * private + i for i in range(private)]

    def size_of(obj):
        return real[obj % len(real)]

    def job_stream(j):
        ids = np.array(dataset(j))
        start = j * a.stagger * n / rates[0]
        pos = 0
        for e in range(epochs[j]):
            perm = np.random.default_rng((a.seed_base + j) * 1000003 + e).permutation(n)
            for obj in ids[perm].tolist():
                yield (start + pos / rates[j], j, e, obj)
                pos += 1

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    count = 0
    with open(a.out, "w") as out:
        out.write("# kind=synthetic; composition of several jobs on overlapping datasets\n")
        out.write(f"# real: file sizes from {os.path.abspath(a.files)}; per-job epoch order from the tracing trainer's code\n")
        out.write(f"# assumed: jobs={a.jobs} files_per_job={n} overlap={a.overlap} epochs={epochs} "
                  f"rates={rates} stagger={a.stagger} seed_base={a.seed_base}\n")
        out.write("# sampler: full shuffle without replacement, reshuffled every epoch; job j has seed seed_base + j\n")
        out.write("t,job,epoch,obj,size\n")
        for t, j, e, obj in heapq.merge(*(job_stream(j) for j in range(a.jobs))):
            out.write(f"{t:.4f},{j},{e},{obj},{size_of(obj)}\n")
            count += 1
    print(f"wrote {count} accesses ({a.jobs} jobs, {n} files each, overlap {a.overlap}) to {a.out}")


if __name__ == "__main__":
    main()
