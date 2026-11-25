#!/usr/bin/env python3
"""Convert a trace written by the earlier tracing trainer (train_trace.py, repository ~/CXL,
branch explore/reuse-window-prefetch) into the CSV format of simulator/cachesim.py.

Input:  <run_dir>/reads.txt with lines "R <t_s> <epoch> <pos> <id> <bytes>", one per file pull.
Output: CSV "t,job,epoch,obj,size" with a header that labels the trace as REAL.
The run is a single job, so job is always 0.

Usage: convert_train_trace.py <run_dir> <out.csv>      (refuses to overwrite)
"""
import os
import sys


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    run_dir, out = sys.argv[1], sys.argv[2]
    if os.path.exists(out):
        sys.exit(f"refusing to overwrite {out}")
    n = 0
    with open(os.path.join(run_dir, "reads.txt")) as src, open(out, "w") as dst:
        dst.write("# kind=real; single-job training access trace\n")
        dst.write(f"# source={os.path.abspath(run_dir)}/reads.txt (see PROVENANCE.md there)\n")
        dst.write("t,job,epoch,obj,size\n")
        for line in src:
            p = line.split()
            if len(p) != 6 or p[0] != "R":
                continue
            dst.write(f"{p[1]},0,{p[2]},{p[4]},{p[5]}\n")
            n += 1
    print(f"wrote {n} accesses to {out}")


if __name__ == "__main__":
    main()
