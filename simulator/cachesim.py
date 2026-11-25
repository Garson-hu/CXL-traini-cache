#!/usr/bin/env python3
"""Minimal trace-driven cache policy simulator (first used in experiment 2026-11-12-cache-policy-replay).

Replays a file-access trace through cache policies and reports how many bytes
each policy would still have to read from storage. Objects are whole files and
the cache capacity is in bytes. There is no notion of time, bandwidth, memory
type, or network: the output is hit rates and byte volumes only. Everything
this program prints is SIMULATION output, not a hardware measurement.

Trace format (CSV): columns t,job,epoch,obj,size. Lines starting with '#' are
comments; a comment containing 'kind=real' or 'kind=synthetic' labels the
trace, and the label is copied into every result row.

Usage:
  cachesim.py --trace TRACE.csv --out RESULT.csv
              [--capacities 0.05,0.1,0.2,0.4,0.8] [--policies lru,static,...] [--check]

Cross-job policies ('known:...', 'perjob-...', 'quiver...', 'bound') live in crossjob.py.
Policies and the information each one uses are described in
the plan of that experiment (experimental_results/2026-11-12-cache-policy-replay/plan.md, kept locally).
Standard library only.
"""
import argparse
import collections
import csv
import heapq
import math
import os
import sys
import time

INF = float("inf")
Access = collections.namedtuple("Access", "t job epoch obj size")


# --------------------------------------------------------------------------- trace

def load_trace(path):
    """Return (accesses, kind). kind is 'real', 'synthetic', or 'unlabeled'."""
    accesses, kind = [], "unlabeled"
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "kind=real" in line:
                    kind = "real"
                elif "kind=synthetic" in line:
                    kind = "synthetic"
                continue
            if line.startswith("t,"):
                continue
            t, job, epoch, obj, size = line.split(",")
            accesses.append(Access(float(t), int(job), int(epoch), int(obj), int(size)))
    return accesses, kind


def trace_info(accesses):
    """Facts about the trace that the simulator and some policies need.

    working_set_bytes, mean_size: used to size the cache and TinyLFU's aging period.
    epoch_len[job]: accesses in the job's first epoch. A data loader knows this
        number (its dataset size) before the first batch; 'reuse-epoch' uses it.
    next_use[i]: index of the next access to the same object, INF if none.
        Offline information, used only by 'oracle'.
    _job_seq, _last_index: each job's own access sequence and its last access. Offline here;
        an online policy sees a bounded part of its jobs' sequences only through crossjob.Lookahead.
    """
    sizes, epoch_len, first_epoch = {}, collections.Counter(), {}
    for a in accesses:
        if sizes.setdefault(a.obj, a.size) != a.size:
            raise ValueError(f"object {a.obj} changes size in the trace")
        first_epoch.setdefault(a.job, a.epoch)
        if a.epoch == first_epoch[a.job]:
            epoch_len[a.job] += 1
    next_use, seen = [INF] * len(accesses), {}
    for i in range(len(accesses) - 1, -1, -1):
        next_use[i] = seen.get(accesses[i].obj, INF)
        seen[accesses[i].obj] = i
    job_seq, last_index = collections.defaultdict(list), {}
    for i, a in enumerate(accesses):
        job_seq[a.job].append((a.obj, a.epoch))
        last_index[a.job] = i
    ws = sum(sizes.values())
    return dict(working_set_bytes=ws, objects=len(sizes), mean_size=ws / max(1, len(sizes)),
                min_size=min(sizes.values()) if sizes else 0, sizes=sizes, jobs=sorted(job_seq),
                epoch_len=dict(epoch_len), first_epoch=first_epoch,
                next_use=next_use, _job_seq=dict(job_seq), _last_index=last_index)


OFFLINE_KEYS = ("next_use", "_job_seq", "_last_index")


def online_view(info):
    """The part of the trace facts an online policy may be given: no future accesses.
    'epoch_len' and 'jobs' are things jobs announce when they start. A policy that is allowed to
    see part of a job's upcoming order gets it through crossjob.Lookahead, never from here."""
    return {k: v for k, v in info.items() if k not in OFFLINE_KEYS}


# --------------------------------------------------------------------------- policies

class Policy:
    """Base class. A policy owns the set of resident objects and decides admission and eviction."""
    name = "base"

    def __init__(self, capacity, info):
        self.capacity = capacity
        self.used = 0
        self.resident = {}       # obj -> size
        self.evicted = []        # (obj, size) evicted since the engine last looked

    def contains(self, a):
        """Is this access a cache hit?"""
        return a.obj in self.resident

    def on_hit(self, i, a):
        pass

    def on_miss(self, i, a):
        """Return True if the object was admitted."""
        return False

    def metadata_entries(self):
        return len(self.resident)

    def _insert(self, obj, size):
        self.resident[obj] = size
        self.used += size

    def _evict(self, obj):
        size = self.resident.pop(obj)
        self.used -= size
        self.evicted.append((obj, size))


class NoCache(Policy):
    name = "none"


class LRU(Policy):
    """Admit everything, evict the least recently used object."""
    name = "lru"

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.order = collections.OrderedDict()

    def on_hit(self, i, a):
        self.order.move_to_end(a.obj)

    def on_miss(self, i, a):
        if a.size > self.capacity:
            return False
        while self.used + a.size > self.capacity:
            victim, _ = self.order.popitem(last=False)
            self._evict(victim)
        self.order[a.obj] = None
        self._insert(a.obj, a.size)
        return True


class LFU(Policy):
    """Admit everything, evict the lowest access count (ties: least recent). Counts survive eviction."""
    name = "lfu"

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.count, self.last, self.heap = {}, {}, []

    def _touch(self, i, obj):
        self.count[obj] = self.count.get(obj, 0) + 1
        self.last[obj] = i

    def on_hit(self, i, a):
        self._touch(i, a.obj)
        heapq.heappush(self.heap, (self.count[a.obj], i, a.obj))

    def on_miss(self, i, a):
        self._touch(i, a.obj)
        if a.size > self.capacity:
            return False
        while self.used + a.size > self.capacity:
            c, last, v = heapq.heappop(self.heap)
            if v in self.resident and self.count[v] == c and self.last[v] == last:
                self._evict(v)
        self._insert(a.obj, a.size)
        heapq.heappush(self.heap, (self.count[a.obj], i, a.obj))
        return True

    def metadata_entries(self):
        return len(self.count)


class SLRU(Policy):
    """Segmented LRU: new objects enter a probation segment, a hit promotes to a protected segment."""
    name = "slru"
    PROTECTED_FRACTION = 0.8

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.prob, self.prot = collections.OrderedDict(), collections.OrderedDict()
        self.prot_bytes, self.prot_cap = 0, self.PROTECTED_FRACTION * capacity

    def on_hit(self, i, a):
        o = a.obj
        if o in self.prot:
            self.prot.move_to_end(o)
            return
        del self.prob[o]
        self.prot[o] = None
        self.prot_bytes += self.resident[o]
        while self.prot_bytes > self.prot_cap and len(self.prot) > 1:
            d, _ = self.prot.popitem(last=False)      # demote the protected LRU object
            self.prot_bytes -= self.resident[d]
            self.prob[d] = None

    def on_miss(self, i, a):
        if a.size > self.capacity:
            return False
        while self.used + a.size > self.capacity:
            if self.prob:
                v, _ = self.prob.popitem(last=False)
            else:
                v, _ = self.prot.popitem(last=False)
                self.prot_bytes -= self.resident[v]
            self._evict(v)
        self.prob[a.obj] = None
        self._insert(a.obj, a.size)
        return True


class TinyLFU(Policy):
    """Simplified TinyLFU: LRU eviction, and a newcomer is admitted only if its access count
    exceeds that of every victim it would displace. Exact counters, halved periodically."""
    name = "tinylfu"

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.order, self.freq, self.events = collections.OrderedDict(), {}, 0
        self.sample = max(16, int(10 * capacity / max(1.0, info["mean_size"])))

    def _count(self, obj):
        self.freq[obj] = self.freq.get(obj, 0) + 1
        self.events += 1
        if self.events >= self.sample:                 # aging
            self.freq = {k: v // 2 for k, v in self.freq.items() if v // 2 > 0}
            self.events = 0

    def on_hit(self, i, a):
        self._count(a.obj)
        self.order.move_to_end(a.obj)

    def on_miss(self, i, a):
        self._count(a.obj)
        if a.size > self.capacity:
            return False
        need, victims = self.used + a.size - self.capacity, []
        if need > 0:
            f = self.freq.get(a.obj, 0)
            for v in self.order:                       # least recently used first
                if self.freq.get(v, 0) >= f:
                    return False                       # not more popular than the victim: bypass
                victims.append(v)
                need -= self.resident[v]
                if need <= 0:
                    break
        for v in victims:
            del self.order[v]
            self._evict(v)
        self.order[a.obj] = None
        self._insert(a.obj, a.size)
        return True

    def metadata_entries(self):
        return max(len(self.freq), len(self.resident))


class Static(Policy):
    """Static pinned cache with admission bypass: admit while space is free, never evict."""
    name = "static"

    def on_miss(self, i, a):
        if self.used + a.size > self.capacity:
            return False
        self._insert(a.obj, a.size)
        return True


class _Ranked(Policy):
    """Shared rule of the next-use-ranked policies: evict the resident whose (estimated) next
    use is farthest, and admit a newcomer only if its (estimated) next use is sooner than that
    of every victim it would displace. Otherwise the newcomer bypasses the cache."""

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.key, self.heap = {}, []     # resident obj -> next-use key; lazy max-heap of (-key, obj)

    def _set(self, obj, key):
        self.key[obj] = key
        heapq.heappush(self.heap, (-key, obj))
        if len(self.heap) > 8 * len(self.key) + 1024:  # drop stale entries; decisions are unchanged
            self.heap = [(-k, o) for o, k in self.key.items()]
            heapq.heapify(self.heap)

    def _admit_ranked(self, a, key):
        if a.size > self.capacity:
            return False
        need, victims, popped = self.used + a.size - self.capacity, [], []
        while need > 0:
            while self.heap:
                nk, v = self.heap[0]
                if v in self.resident and self.key.get(v) == -nk and v not in victims:
                    break
                heapq.heappop(self.heap)               # stale entry
            if not self.heap:
                break
            nk, v = heapq.heappop(self.heap)
            popped.append((nk, v))
            if -nk <= key:                             # victim is at least as valuable: bypass
                for e in popped:
                    heapq.heappush(self.heap, e)
                return False
            victims.append(v)
            need -= self.resident[v]
        if need > 0:
            for e in popped:
                heapq.heappush(self.heap, e)
            return False
        for v in victims:
            del self.key[v]
            self._evict(v)
        self._insert(a.obj, a.size)
        self._set(a.obj, key)
        return True


class Oracle(_Ranked):
    """Offline reference: Belady's rule with admission bypass, using the exact next use.
    Minimizes misses for equal-sized objects. Not optimal in general for variable sizes."""
    name = "oracle"

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.next_use = info["next_use"]

    def on_hit(self, i, a):
        self._set(a.obj, self.next_use[i])

    def on_miss(self, i, a):
        nu = self.next_use[i]
        if nu == INF:
            return False
        return self._admit_ranked(a, nu)


class ReuseGap(_Ranked):
    """Online candidate 1, generic history: the next use of an object is estimated as its last
    access plus its last observed inter-access gap. An object with no observed gap uses the
    running mean gap of all objects. A prediction that passes without an access is pushed out
    by one more estimated gap."""
    name = "reuse-gap"

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.last, self.gap = {}, {}
        self.gsum, self.gn, self.next_refresh = 0, 0, 1
        self.due, self.unknown = [], set()   # min-heap of (key, obj); residents without an own gap

    def _key_for(self, i, obj):
        g = self.gap.get(obj)
        if g is None:
            if not self.gn:
                return INF
            g = self.gsum / self.gn
        k = self.last[obj] + g
        if k < i:
            k += g * math.ceil((i - k) / g)
        return k

    def _rekey(self, i, obj):
        k = self._key_for(i, obj)
        self._set(obj, k)
        if k != INF:
            heapq.heappush(self.due, (k, obj))

    def _observe(self, i, obj):
        prev = self.last.get(obj)
        if prev is not None:
            g = i - prev
            self.gap[obj] = g
            self.gsum += g
            self.gn += 1
            self.unknown.discard(obj)
        self.last[obj] = i

    def _housekeeping(self, i):
        if self.gn >= self.next_refresh:               # mean gap changed enough: refresh defaults
            self.next_refresh = 2 * self.gn
            for o in [o for o in self.unknown if o in self.resident]:
                self._rekey(i, o)
            self.unknown = {o for o in self.unknown if o in self.resident}
        while self.due and self.due[0][0] < i:         # overdue predictions
            k, o = heapq.heappop(self.due)
            if o in self.resident and self.key.get(o) == k:
                self._rekey(i, o)

    def on_hit(self, i, a):
        self._observe(i, a.obj)
        self._housekeeping(i)
        self._rekey(i, a.obj)

    def on_miss(self, i, a):
        self._observe(i, a.obj)
        self._housekeeping(i)
        k = self._key_for(i, a.obj)
        if not self._admit_ranked(a, k):
            return False
        if k != INF:
            heapq.heappush(self.due, (k, a.obj))
        if a.obj not in self.gap:
            self.unknown.add(a.obj)
        return True

    def metadata_entries(self):
        return len(self.last)


class ReuseEpoch(Policy):
    """Online candidate 2, epoch-aware: assumes each job reads its dataset once per epoch without
    replacement and reports its epoch length. For every job it tracks which objects the job has
    already read in its current epoch. An object is 'pending' for a job that has not read it yet.
    The expected wait until job j reads an object is (remaining_j + 1) / 2 accesses of that job if
    pending, and remaining_j + (L_j + 1) / 2 if already read. The estimated next use combines the
    jobs as 1 / sum_j(1 / wait_j). Uses no seed and no future order. Same admit/evict rule as the
    other ranked policies; objects with the same set of pending jobs form one class."""
    name = "reuse-epoch"

    def __init__(self, capacity, info):
        super().__init__(capacity, info)
        self.epoch_len = info["epoch_len"]
        self.jobs = {}                # job -> [bit, current_epoch, done]
        self.consumed = {}            # job -> set of objects read in its current epoch
        self.mask = {}                # resident obj -> bitmask of jobs for which it is pending
        self.buckets = {}             # mask -> OrderedDict of resident objects

    def _wait(self, mask):
        """Estimated accesses (all jobs together) until an object of this class is read next."""
        k, hazard = len(self.jobs), 0.0
        for job, (bit, _, done) in self.jobs.items():
            length = self.epoch_len[job]
            remaining = max(0, length - done)
            w = (remaining + 1) / 2 if mask & bit else remaining + (length + 1) / 2
            hazard += 1.0 / (w * k)
        return 1.0 / hazard if hazard else INF

    def _all_pending_for(self, bit):
        """A job started a new epoch: every resident object is pending for it again."""
        merged = {}
        for m, objs in self.buckets.items():
            merged.setdefault(m | bit, collections.OrderedDict()).update(objs)
        self.buckets = merged
        for o in self.mask:
            self.mask[o] |= bit

    def _begin(self, a):
        st = self.jobs.get(a.job)
        if st is None:
            st = self.jobs[a.job] = [1 << len(self.jobs), a.epoch, 0]
            self.consumed[a.job] = set()
            self._all_pending_for(st[0])
        elif st[1] != a.epoch:
            st[1], st[2] = a.epoch, 0
            self.consumed[a.job].clear()
            self._all_pending_for(st[0])
        st[2] += 1
        self.consumed[a.job].add(a.obj)
        return st[0]

    def on_hit(self, i, a):
        bit = self._begin(a)
        m = self.mask[a.obj]
        if m & bit:
            del self.buckets[m][a.obj]
            if not self.buckets[m]:
                del self.buckets[m]
            self.mask[a.obj] = m & ~bit
            self.buckets.setdefault(m & ~bit, collections.OrderedDict())[a.obj] = None

    def on_miss(self, i, a):
        self._begin(a)
        if a.size > self.capacity:
            return False
        m = 0
        for job, (bit, _, _) in self.jobs.items():
            if a.obj not in self.consumed[job]:
                m |= bit
        need, victims = self.used + a.size - self.capacity, []
        if need > 0:
            mine = self._wait(m)
            for w, bm in sorted(((self._wait(bm), bm) for bm in self.buckets), reverse=True):
                if w <= mine:                          # the rest is at least as valuable: bypass
                    break
                for v in self.buckets[bm]:
                    victims.append(v)
                    need -= self.resident[v]
                    if need <= 0:
                        break
                if need <= 0:
                    break
            if need > 0:
                return False
        for v in victims:
            bm = self.mask.pop(v)
            del self.buckets[bm][v]
            if not self.buckets[bm]:
                del self.buckets[bm]
            self._evict(v)
        self._insert(a.obj, a.size)
        self.mask[a.obj] = m
        self.buckets.setdefault(m, collections.OrderedDict())[a.obj] = None
        return True

    def metadata_entries(self):
        return len(self.resident) + sum(len(s) for s in self.consumed.values())


POLICIES = collections.OrderedDict((p.name, p) for p in
                                   (NoCache, LRU, LFU, SLRU, TinyLFU, Static, ReuseGap, ReuseEpoch, Oracle))
ONLINE_BASELINES = ("lru", "lfu", "slru", "tinylfu", "static")
ONLINE_CANDIDATES = ("reuse-gap", "reuse-epoch")


# --------------------------------------------------------------------------- engine

def simulate(accesses, policy, info, check=False, hits_out=None):
    """Replay the trace through one policy and return a dict of metrics.
    hits_out, if given, receives one boolean per access (hit or miss)."""
    first_epoch = info["first_epoch"]
    n = hits = hit_bytes = total_bytes = 0
    warm_n = warm_hits = warm_bytes = warm_hit_bytes = 0
    admissions = admission_bytes = evictions = evicted_bytes = peak_meta = occupancy = 0
    resident, evicted = policy.resident, policy.evicted
    t0 = time.perf_counter()
    for i, a in enumerate(accesses):
        warm = a.epoch != first_epoch[a.job]
        n += 1
        total_bytes += a.size
        if warm:
            warm_n += 1
            warm_bytes += a.size
        hit = policy.contains(a)
        if hits_out is not None:
            hits_out.append(hit)
        if hit:
            policy.on_hit(i, a)
            hits += 1
            hit_bytes += a.size
            if warm:
                warm_hits += 1
                warm_hit_bytes += a.size
        elif policy.on_miss(i, a):
            admissions += 1
            admission_bytes += a.size
        if evicted:
            evictions += len(evicted)
            evicted_bytes += sum(s for _, s in evicted)
            evicted.clear()
        occupancy += policy.used
        if check:
            assert policy.used <= policy.capacity, (policy.name, i, policy.used)
            if i % 997 == 0:
                assert policy.used == sum(resident.values()), (policy.name, i)
        if i % 4096 == 0:
            peak_meta = max(peak_meta, policy.metadata_entries())
    elapsed = time.perf_counter() - t0
    peak_meta = max(peak_meta, policy.metadata_entries())
    return dict(
        policy=policy.name, capacity_bytes=int(policy.capacity), accesses=n, bytes=total_bytes,
        hits=hits, obj_hit_rate=hits / n if n else 0.0,
        byte_hit_rate=hit_bytes / total_bytes if total_bytes else 0.0,
        warm_obj_hit_rate=warm_hits / warm_n if warm_n else 0.0,
        warm_byte_hit_rate=warm_hit_bytes / warm_bytes if warm_bytes else 0.0,
        storage_read_bytes=total_bytes - hit_bytes, admission_bytes=admission_bytes,
        admissions=admissions, evictions=evictions, evicted_bytes=evicted_bytes,
        final_resident_bytes=policy.used, peak_metadata_entries=peak_meta,
        policy_us_per_access=1e6 * elapsed / n if n else 0.0,
        mean_occupancy=occupancy / (n * policy.capacity) if n and policy.capacity else 0.0)


FIELDS = ["trace", "trace_kind", "policy", "capacity_frac", "capacity_bytes", "accesses", "bytes",
          "obj_hit_rate", "byte_hit_rate", "warm_obj_hit_rate", "warm_byte_hit_rate",
          "storage_read_bytes", "admission_bytes", "admissions", "evictions", "evicted_bytes",
          "peak_metadata_entries", "policy_us_per_access", "mean_occupancy"]


def replay(name, accesses, info, capacity, check=False, hits_out=None):
    """Replay one policy, given by name, and return its metrics.
    Plain names are the classes in POLICIES. 'known:...', 'perjob-...', 'quiver...' and 'bound' are
    the cross-job policies and references in crossjob.py."""
    if name in POLICIES:
        cls = POLICIES[name]
        policy = cls(capacity, info if cls is Oracle else online_view(info))
        return simulate(accesses, policy, info, check=check, hits_out=hits_out)
    import crossjob
    return crossjob.replay(name, accesses, info, capacity, check=check, hits_out=hits_out)


def run(trace_path, capacities, policies, check=False):
    accesses, kind = load_trace(trace_path)
    info = trace_info(accesses)
    name = os.path.splitext(os.path.basename(trace_path))[0]
    if name.startswith("trace"):                       # <trace-directory>/trace[-suffix].csv: use the directory name
        name = os.path.basename(os.path.dirname(os.path.abspath(trace_path))) + name[len("trace"):]
    rows = []
    for frac in capacities:
        cap = int(frac * info["working_set_bytes"])
        for p in policies:
            r = replay(p, accesses, info, cap, check=check)
            r.update(trace=name, trace_kind=kind, capacity_frac=frac)
            rows.append(r)
    return rows, info, kind


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trace-driven cache policy simulator (simulation output only).")
    ap.add_argument("--trace", required=True)
    ap.add_argument("--out", required=True, help="result CSV; refuses to overwrite")
    ap.add_argument("--capacities", default="0.05,0.1,0.2,0.4,0.8", help="fractions of the working set")
    ap.add_argument("--policies", default=",".join(POLICIES))
    ap.add_argument("--check", action="store_true", help="assert capacity and accounting invariants")
    args = ap.parse_args(argv)
    if os.path.exists(args.out):
        sys.exit(f"refusing to overwrite {args.out}")
    policies = args.policies.split(",")
    prefixes = ("known:", "perjob-", "quiver", "bound")
    unknown = [p for p in policies if p not in POLICIES and not p.startswith(prefixes)]
    if unknown:
        sys.exit(f"unknown policies: {unknown}; known: {list(POLICIES)} and the cross-job names in crossjob.py")
    rows, info, kind = run(args.trace, [float(c) for c in args.capacities.split(",")], policies, args.check)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()})
    print(f"SIMULATION  trace={rows[0]['trace']}  kind={kind}  accesses={rows[0]['accesses']}  "
          f"objects={info['objects']}  working_set={info['working_set_bytes'] / 1e9:.2f} GB")
    print(f"{'capacity':>8} {'policy':<12} {'obj_hit':>8} {'byte_hit':>8} {'warm_byte':>9} "
          f"{'read_GB':>9} {'admit_GB':>9} {'evictions':>9}")
    for r in rows:
        if r.get("byte_hit_rate") is None:               # an object-count bound has no byte figures
            print(f"{r['capacity_frac']:>8.2f} {r['policy']:<12} {r['obj_hit_rate']:>8.4f}  (upper bound on object hits)")
            continue
        print(f"{r['capacity_frac']:>8.2f} {r['policy']:<12} {r['obj_hit_rate']:>8.4f} {r['byte_hit_rate']:>8.4f} "
              f"{r['warm_byte_hit_rate']:>9.4f} {r['storage_read_bytes'] / 1e9:>9.2f} "
              f"{r['admission_bytes'] / 1e9:>9.2f} {r['evictions']:>9d}")


if __name__ == "__main__":
    main()
