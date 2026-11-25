#!/usr/bin/env python3
"""Convert FitCache server logs into the CSV trace format of simulator/cachesim.py.

Input: fitcache_server_log.* files (plain or .gz) of ONE run. Every line containing
"Open RPC: requested path <path>" is one file open with a millisecond timestamp. The logs of
all servers of the run (and of all jobs that shared the cache) must be given together.

What the logs contain: time and path of every open that reached a server.
What they do NOT contain: which job or rank opened the file, and how many bytes were read.
Therefore this script reconstructs two labels, and says so in the output header:
  epoch  from time windows. Files with exactly --jobs * --epochs opens are used to find the
         boundaries between epochs; every open is then labeled by the window it falls in.
         Jobs whose epochs are not aligned in time get one common boundary, so opens close
         to a boundary can carry the neighbouring epoch's label.
  job    the i-th open of a file inside one epoch window is attributed to job i. This is a
         pseudo-identity: it is correct as a count of how many jobs have read the file in the
         epoch, not as the identity of the job.
Sizes come from --sizes (lines "<id> <name> <bytes>") by file name, else from os.stat().

Usage:
  convert_fitcache_log.py --jobs K --epochs E --out OUT.csv [--sizes FILES.txt] LOG [LOG ...]
Refuses to overwrite.
"""
import argparse
import bisect
import collections
import datetime
import gzip
import os
import re
import sys

MARK = b"Open RPC: requested path "
COPY_SUFFIX = re.compile(r"_copy\d+(?=\.)")


def read_opens(paths):
    events = []
    for fi, p in enumerate(sorted(paths)):
        opener = gzip.open if p.endswith(".gz") else open
        with opener(p, "rb") as f:
            for li, raw in enumerate(f):
                k = raw.find(MARK)
                if k < 0:
                    continue
                try:
                    stamp = raw[:21].decode("ascii")          # "YYYYMMDD HH:MM:SS.mmm"
                    t = datetime.datetime.strptime(stamp, "%Y%m%d %H:%M:%S.%f").timestamp()
                    path = raw[k + len(MARK):].strip().decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
                if "\x00" in path or not path.startswith("/"):
                    continue                                   # damaged log line
                events.append((t, fi, li, path))
    events.sort()
    return events


def lookup_size(path, names):
    """Size of a logged file and how it was found. Files that no longer exist under their logged
    name (older dataset copies named <name>_copyNN.tfrecord) fall back to the original file."""
    base = os.path.basename(path)
    if base in names and "/train/" in path:
        return names[base], "list"
    try:
        return os.stat(path).st_size, "stat"
    except (OSError, ValueError):
        pass
    orig = COPY_SUFFIX.sub("", base)
    if orig != base:
        if orig in names and "/train/" in path:
            return names[orig], "list-original"
        try:
            return os.stat(os.path.join(os.path.dirname(path), orig)).st_size, "stat-original"
        except (OSError, ValueError):
            pass
    return None, "mean-of-known"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--jobs", type=int, required=True, help="jobs that read the dataset concurrently")
    ap.add_argument("--epochs", type=int, required=True)
    ap.add_argument("--sizes", help='file with lines "<id> <name> <bytes>"')
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if os.path.exists(a.out):
        sys.exit(f"refusing to overwrite {a.out}")

    events = read_opens(a.logs)
    if not events:
        sys.exit("no open events found")
    times = collections.defaultdict(list)
    for t, _, _, path in events:
        times[path].append(t)
    expected = a.jobs * a.epochs
    regular = [ts for ts in times.values() if len(ts) == expected]
    if not regular:
        sys.exit(f"no file has exactly {expected} opens; check --jobs and --epochs")

    # Boundary between epochs e and e+1: midway between the late tail of epoch e and the early
    # tail of epoch e+1 (2% quantiles, so that a few irregular opens do not move it).
    per_epoch = [sorted(t for ts in regular for t in ts[e * a.jobs:(e + 1) * a.jobs]) for e in range(a.epochs)]
    boundaries = []
    for e in range(a.epochs - 1):
        late = per_epoch[e][int(0.98 * (len(per_epoch[e]) - 1))]
        early = per_epoch[e + 1][int(0.02 * (len(per_epoch[e + 1]) - 1))]
        boundaries.append((late + early) / 2)
    # Quality: opens of regular files whose time window disagrees with their position in the file's own sequence.
    disagree = sum(1 for ts in regular for k, t in enumerate(ts) if bisect.bisect_right(boundaries, t) != k // a.jobs)
    disagree_share = disagree / (len(regular) * expected)

    names = {}
    if a.sizes:
        with open(a.sizes) as f:
            for line in f:
                p = line.split()
                names[p[1]] = int(p[2])
    size_of, obj_of, how = {}, {}, collections.Counter()
    for path in times:
        size_of[path], method = lookup_size(path, names)
        how[method] += 1
    known = [s for s in size_of.values() if s is not None]
    if not known:
        sys.exit("no file size could be determined")
    mean_known = int(sum(known) / len(known))
    for path, s in size_of.items():
        if s is None:
            size_of[path] = mean_known

    t0 = events[0][0]
    seen_in_epoch = collections.Counter()
    per_label = collections.Counter()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as out:
        out.write("# kind=real; file opens logged by FitCache servers during a training run\n")
        out.write(f"# logs: {len(a.logs)} files, first: {os.path.abspath(sorted(a.logs)[0])}\n")
        out.write(f"# opens={len(events)} files={len(times)} files_with_exactly_{expected}_opens={len(regular)}\n")
        out.write("# RECONSTRUCTED labels: epoch from time windows, job = order of the open within the "
                  "epoch window (the logs record neither); sizes from file metadata, not from read sizes\n")
        out.write(f"# size source per file: {dict(how)}\n")
        out.write(f"# epoch boundaries (s after first open): {[round(b - t0, 1) for b in boundaries]}; "
                  f"opens of regular files whose time window disagrees with their order: {100 * disagree_share:.1f}%\n")
        out.write("t,job,epoch,obj,size\n")
        for t, _, _, path in events:
            epoch = bisect.bisect_right(boundaries, t)
            job = min(seen_in_epoch[(path, epoch)], a.jobs - 1)
            seen_in_epoch[(path, epoch)] += 1
            per_label[(epoch, job)] += 1
            obj = obj_of.setdefault(path, len(obj_of))
            out.write(f"{t - t0:.3f},{job},{epoch},{obj},{size_of[path]}\n")
    total_bytes = sum(size_of.values())
    print(f"wrote {len(events)} opens of {len(times)} files ({total_bytes / 1e9:.2f} GB distinct) to {a.out}")
    print(f"files with exactly {expected} opens: {len(regular)} of {len(times)}; size source per file: {dict(how)}")
    print(f"epoch boundaries at {[round(b - t0, 1) for b in boundaries]} s; "
          f"regular-file opens whose time window disagrees with their order: {100 * disagree_share:.1f}%")
    print("opens per (epoch, reconstructed job):", dict(sorted(per_label.items())))


if __name__ == "__main__":
    main()
