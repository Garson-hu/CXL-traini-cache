#!/usr/bin/env python3
"""Cross-job policies and reference replays for the trace-driven cache simulator.

Everything here produces SIMULATION output. Used through cachesim.py by policy name:

  known:<lookahead>[:rate=<factor>@<job>][:stale=<n>][:refresh=<n>][:alpha=<a>]
      Known-order policy. Each job tells the cache part of its own upcoming file order
      (<lookahead> = 'all' for the whole run, 'epoch' for the rest of the current epoch, a
      fraction such as 0.05 of the epoch length, or an integer number of accesses). The cache
      estimates when each job will reach a file from the job's position and its measured rate,
      and ranks cached files by the earliest estimated next use across jobs.
      rate=2@0 makes the cache believe job 0 is twice as fast as it is. stale=512 lets the cache
      see each job's position only every 512 accesses of that job. alpha sets the memory of the
      rate estimate: a running average over about 1/alpha accesses (default 0.002, about 500).
  perjob-static, perjob-lru
      Independent caches, one per job, the total capacity split equally. No sharing.
  quiver, quiver-full
      A Quiver-INSPIRED replay, not a reproduction of Quiver: jobs consume the dataset chunk by
      chunk in a shared cyclic order and take cached files first, so the order in which a job
      reads its files is CHANGED. 'quiver' keeps two chunks resident as in the paper;
      'quiver-full' is an extension that keeps as many chunks as the capacity allows.
  bound
      Upper bound on the OBJECT hit rate of any policy: object sizes are relaxed to the smallest
      size and Belady's rule with bypass, optimal for equal sizes, is applied.
"""
import array
import collections
import heapq
import time

from cachesim import INF, LRU, Access, Oracle, Policy, Static, _Ranked, online_view, simulate


# --------------------------------------------------------------------------- what jobs announce

class Lookahead:
    """The part of each job's own future order that the job has announced to the cache.

    The cache calls reveal() when a job makes an access and gets the positions that became
    visible. It has no other way to see a job's sequence. Modes: 'all', 'epoch', 'epoch2' (the
    rest of the current epoch and the whole next one: two-epoch lookahead), or a number (a float
    below 1 is a fraction of the job's epoch length, otherwise a count of accesses)."""

    def __init__(self, job_seq, mode, epoch_len):
        self._seq = job_seq                      # job -> [(obj, epoch), ...]; private
        self.mode = mode
        self._shown = {j: 0 for j in job_seq}    # exclusive index of what has been revealed
        self._window = {}
        if mode not in ("all", "epoch", "epoch2"):
            for j in job_seq:
                self._window[j] = max(1, int(mode * epoch_len[j])) if mode < 1 else int(mode)
        self._epoch_end = {}
        for j, seq in job_seq.items():
            ends, end = [0] * len(seq), len(seq)
            for p in range(len(seq) - 1, -1, -1):
                if p + 1 < len(seq) and seq[p + 1][1] != seq[p][1]:
                    end = p + 1
                ends[p] = end
            self._epoch_end[j] = ends

    def _horizon(self, job, pos):
        if self.mode == "all":
            return len(self._seq[job])
        if self.mode == "epoch":
            return self._epoch_end[job][pos]
        if self.mode == "epoch2":
            end = self._epoch_end[job][pos]
            return self._epoch_end[job][end] if end < len(self._seq[job]) else end
        return min(len(self._seq[job]), pos + 1 + self._window[job])

    def reveal(self, job, pos):
        """Job is at position pos of its own sequence. Return newly visible [(position, obj)]."""
        seq, h = self._seq[job], self._horizon(job, pos)
        start = max(self._shown[job], pos + 1)
        self._shown[job] = max(self._shown[job], h)
        return [(q, seq[q][0]) for q in range(start, h)]

    def shown(self, job):
        return self._shown[job]

    def is_last(self, job, pos):
        """A job deregisters with its last access."""
        return pos == len(self._seq[job]) - 1

    def complete(self, job):
        """Everything up to the end of the job's run is visible."""
        return self._shown[job] >= len(self._seq[job])

    def ahead(self, job, pos, n):
        """The next visible accesses after position pos, at most n: [(position, obj)]. For prefetching."""
        seq = self._seq[job]
        return [(q, seq[q][0]) for q in range(pos + 1, min(self._shown[job], pos + 1 + n))]


# --------------------------------------------------------------------------- known-order policy

class _Job:
    __slots__ = ("pos", "epoch", "done", "t_last", "dt", "ndt", "active", "full")

    def __init__(self, epoch, t):
        self.pos, self.epoch, self.done, self.t_last, self.dt, self.ndt = -1, epoch, 0, t, None, 0
        self.active, self.full = True, False


class KnownOrder(_Ranked):
    """Online candidate that uses the upcoming order announced by the jobs.

    For a cached file and a job, the estimated time of the job's next access is
      now + (announced position - job's position) / job's measured rate      if the access is visible,
    and otherwise an estimate from the epoch structure, as in 'reuse-epoch':
      now + (remaining + (L + 1) / 2) / rate     if the job already read the file in this epoch,
      now + (v + (remaining - v + 1) / 2) / rate if not, where v accesses ahead are visible.
    The file's key is the minimum over the active jobs. Eviction and admission follow the common
    ranked rule: evict the farthest key, admit only if sooner than every victim.
    Uses no information beyond what Lookahead reveals and what the cache has observed.

    dense=N states that the objects are the integers 0..N-1 (the cache server's catalog). The pass
    that gives every resident a new key (_rekey_all) is then computed for all residents at once
    from arrays kept beside future, consumed and member. Keys and decisions are the same to the
    last bit; only the time of the pass changes. Needs numpy. Without dense nothing changes."""
    name = "known"
    check_rekey = False     # tests: compare every array pass with the per-object computation

    def __init__(self, capacity, info, look, rate_bias=None, stale=1, refresh=None, alpha=0.002, dense=0):
        super().__init__(capacity, info)
        assert "next_use" not in info and "_job_seq" not in info, "offline information leaked"
        self.look, self.epoch_len = look, info["epoch_len"]
        self.rate_bias, self.stale, self.alpha = rate_bias or {}, max(1, stale), alpha
        self.refresh, self.since = refresh or max(4096, info["objects"] // 4), 0
        self.jobs, self.future, self.consumed, self.member = {}, {}, {}, {}
        self.nfuture = 0
        # With dense, per job: head[obj] = future[job][obj][0] or -1 if there is none;
        # flag[obj] = 1 if obj is in member[job], 3 if it is also in consumed[job], else 0.
        self.dense, self._head, self._flag, self._view = dense, {}, {}, {}
        if dense:
            import numpy
            self._np = numpy

    # -- estimates
    def _rate(self, j):
        dt = self.jobs[j].dt
        if not dt or dt <= 0:
            known = [s.dt for s in self.jobs.values() if s.dt and s.dt > 0]
            dt = sum(known) / len(known) if known else 1.0
        return self.rate_bias.get(j, 1.0) / dt

    def _eta(self, now, j, obj):
        st = self.jobs[j]
        if not st.active:
            return INF
        rate = self._rate(j)
        dq = self.future[j].get(obj)
        if dq:
            known_pos = st.pos - (st.pos % self.stale)
            return now + max(1, dq[0] - known_pos) / rate
        if self.look.mode == "all":
            return INF                                   # not in the rest of the job's run
        if self.look.mode == "epoch2" and self.look.complete(j):
            return INF                                   # two-epoch lookahead reaches the end of the run
        if st.full and obj not in self.member[j]:
            return INF                                   # not in this job's dataset
        length = self.epoch_len[j]
        remaining = max(0, length - st.done)
        visible = max(0, self.look.shown(j) - st.pos - 1)
        if obj in self.consumed[j] or visible >= remaining:
            return now + (remaining + (length + 1) / 2) / rate
        return now + (visible + (remaining - visible + 1) / 2) / rate

    def _key(self, now, obj):
        return min((self._eta(now, j, obj) for j in self.jobs), default=INF)

    def _rekey_all(self, now):
        if not self.dense:
            for o in list(self.key):
                self._set(o, self._key(now, o))
            return
        if not self.key:
            return
        # The same keys as the loop above, job by job for all residents at once. Every expression is the one of
        # _eta with the same operands in the same order, so the floating-point results are identical.
        np = self._np
        objs = np.fromiter(self.key, np.int64, len(self.key))
        best = np.full(len(objs), INF)
        for j, st in self.jobs.items():
            if not st.active:
                continue
            rate = self._rate(j)
            head, flag = self._view[j]
            h = head[objs]
            eta = now + np.maximum(1, h - (st.pos - (st.pos % self.stale))) / rate
            none = h < 0                                     # no announced access ahead: the estimates of _eta
            if none.any():
                if self.look.mode == "all" or (self.look.mode == "epoch2" and self.look.complete(j)):
                    eta[none] = INF
                else:
                    length = self.epoch_len[j]
                    remaining = max(0, length - st.done)
                    visible = max(0, self.look.shown(j) - st.pos - 1)
                    read = now + (remaining + (length + 1) / 2) / rate
                    unread = read if visible >= remaining else now + (visible + (remaining - visible + 1) / 2) / rate
                    f = flag[objs[none]]
                    e = np.where(f & 2, read, unread)
                    if st.full:
                        e[f == 0] = INF                      # not in this job's dataset
                    eta[none] = e
            np.minimum(best, eta, out=best)
        keys = best.tolist()
        if self.check_rekey:
            assert keys == [self._key(now, o) for o in self.key], "array pass differs from the per-object keys"
        # New keys for all residents, and the heap with exactly these entries. Only entries that match the
        # current key of a resident are ever used (_admit_ranked), so dropping the older ones changes no decision.
        self.key = dict(zip(self.key, keys))
        self.heap = [(-k, o) for o, k in self.key.items()]
        heapq.heapify(self.heap)

    # -- bookkeeping on every access
    def _observe(self, a):
        j, now, global_change = a.job, a.t, False
        st = self.jobs.get(j)
        if st is None:
            st = self.jobs[j] = _Job(a.epoch, a.t)
            self.future[j], self.consumed[j], self.member[j] = {}, set(), set()
            st.full = self.look.mode in ("all", "epoch", "epoch2")
            global_change = True
            if self.dense:
                self._head[j], self._flag[j] = array.array("q", [-1]) * self.dense, bytearray(self.dense)
                self._view[j] = (self._np.frombuffer(self._head[j], self._np.int64),
                                 self._np.frombuffer(self._flag[j], self._np.uint8))
        elif a.epoch != st.epoch:
            st.epoch, st.done, st.full = a.epoch, 0, True
            self.consumed[j].clear()
            global_change = True
            if self.dense:
                self._view[j][1][:] &= 1
        if st.pos >= 0:                                  # running mean of the job's inter-access time
            st.ndt += 1
            dt = a.t - st.t_last
            st.dt = dt if st.dt is None else st.dt + (dt - st.dt) * max(self.alpha, 1.0 / st.ndt)
        st.t_last = a.t
        st.pos += 1
        st.done += 1
        self.consumed[j].add(a.obj)
        self.member[j].add(a.obj)
        head, flag = (self._head[j], self._flag[j]) if self.dense else (None, None)
        if flag is not None:
            flag[a.obj] = 3
        dq = self.future[j].get(a.obj)
        if dq and dq[0] <= st.pos:
            while dq and dq[0] <= st.pos:
                dq.popleft()
                self.nfuture -= 1
            if not dq:
                del self.future[j][a.obj]
            if head is not None:
                head[a.obj] = dq[0] if dq else -1
        new = self.look.reveal(j, st.pos)
        if new:                                          # at a job's first access: its whole announced order
            fut, member_add, deque = self.future[j], self.member[j].add, collections.deque
            self.nfuture += len(new)
            for q, o in new:
                dq = fut.get(o)
                if dq is None:
                    dq = fut[o] = deque()
                    if head is not None:
                        head[o] = q
                dq.append(q)
                member_add(o)
                if flag is not None:
                    flag[o] |= 1
                if not global_change and o in self.resident and o != a.obj:
                    self._set(o, self._key(now, o))
        if self.look.is_last(j, st.pos):
            st.active = False
            global_change = True
        self.since += 1
        if global_change or self.since >= self.refresh:
            self.since = 0
            self._rekey_all(now)

    def on_hit(self, i, a):
        self._observe(a)
        self._set(a.obj, self._key(a.t, a.obj))

    def on_miss(self, i, a):
        self._observe(a)
        k = self._key(a.t, a.obj)
        if k == INF:
            return False
        return self._admit_ranked(a, k)

    def offer(self, now, obj, size):
        """Prefetching: a file that is not resident is offered ahead of its use. It goes through the
        ranked admission of a miss with its current key; no job's position or rate changes. Returns
        True if it was admitted (victims are in self.evicted, as after a miss)."""
        if obj in self.resident:
            return False
        k = self._key(now, obj)
        if k == INF:
            return False
        return self._admit_ranked(Access(now, -1, -1, obj, size), k)

    def next_need(self, now, job, pos):
        """Estimated time of the job's access at announced position pos (for prefetch deadlines)."""
        st = self.jobs[job]
        return now + max(1, pos - st.pos) / self._rate(job)

    def metadata_entries(self):
        return len(self.resident) + self.nfuture + sum(len(s) for s in self.consumed.values())


# --------------------------------------------------------------------------- per-job caches

class PerJob(Policy):
    """Independent per-job caches. The capacity is split equally among the jobs of the trace,
    and a job can only hit what it cached itself."""
    name = "perjob"

    def __init__(self, capacity, info, inner):
        super().__init__(capacity, info)
        share = capacity // max(1, len(info["jobs"]))
        self.subs = {j: inner(share, info) for j in info["jobs"]}

    def contains(self, a):
        return a.obj in self.subs[a.job].resident

    def _sync(self, a):
        sub = self.subs[a.job]
        for obj, size in sub.evicted:
            del self.resident[(a.job, obj)]
            self.evicted.append((obj, size))
        sub.evicted.clear()
        if a.obj in sub.resident and (a.job, a.obj) not in self.resident:
            self.resident[(a.job, a.obj)] = a.size
        self.used = sum(s.used for s in self.subs.values())

    def on_hit(self, i, a):
        self.subs[a.job].on_hit(i, a)
        self._sync(a)

    def on_miss(self, i, a):
        admitted = self.subs[a.job].on_miss(i, a)
        self._sync(a)
        return admitted

    def metadata_entries(self):
        return sum(s.metadata_entries() for s in self.subs.values())


# --------------------------------------------------------------------------- Quiver-inspired replay

def simulate_quiver(accesses, info, capacity, full=False, chunk_frac=0.10, force_after=1.0,
                    name="quiver", hits_out=None):
    """Quiver-inspired coordinated caching. NOT a reproduction of Quiver.

    Taken from the paper: the dataset is cut into chunks of 10% (or half the cache if that is
    smaller); two chunks are resident; a job fills its demand with cached files first and reads
    uncached files of the chunk being loaded from storage, which inserts them; a chunk is evicted
    when all active jobs have finished their pass over it, or by force once the first job that
    finished it has since read force_after chunks' worth of files (the paper gives no value).
    Each job still reads every file of its dataset exactly once per epoch, but in an order decided
    here, so the per-slot file of the trace is ignored: the trace only supplies when each job reads.

    Simplifications: chunks are ranges of the object ids; a job that joins or starts an epoch may
    use every resident chunk; a job that cannot cache reads its next file directly; repeated
    opens in the trace beyond one per file and epoch are replayed as they are.
    full=True is an extension outside the paper: as many chunks as fit stay resident."""
    sizes, first_epoch = info["sizes"], info["first_epoch"]
    job_seq, last_index = info["_job_seq"], info["_last_index"]
    chunk_bytes = min(chunk_frac * info["working_set_bytes"], capacity / 2.0)
    chunks, chunk_of, cur, acc = [], {}, [], 0
    for o in sorted(sizes):
        if cur and acc + sizes[o] > chunk_bytes:
            chunks.append(cur)
            cur, acc = [], 0
        cur.append(o)
        acc += sizes[o]
    if cur:
        chunks.append(cur)
    for c, objs in enumerate(chunks):
        for o in objs:
            chunk_of[o] = c
    n_chunks = len(chunks)
    usable = chunk_bytes >= info["min_size"] and capacity >= 2 * max(sizes.values())
    limit = max(2, int(capacity // chunk_bytes)) if (full and usable) else 2

    epoch_objs = {j: collections.defaultdict(list) for j in job_seq}
    for j, seq in job_seq.items():
        seen = collections.defaultdict(set)
        for o, e in seq:
            if o not in seen[e]:
                seen[e].add(o)
                epoch_objs[j][e].append(o)

    resident, used = {}, 0
    res_chunks = collections.deque()
    todo, todo_cnt, ready, pend, rest = {}, {}, {}, {}, {}
    cur_epoch, active, pos_total, first_done = {}, set(), collections.Counter(), {}
    stats = collections.Counter()
    occupancy = 0

    def consume(j, o):
        todo[j].discard(o)
        c = chunk_of[o]
        todo_cnt[j][c] -= 1
        if todo_cnt[j][c] == 0 and c in res_chunks and c not in first_done:
            first_done[c] = (j, pos_total[j])

    def insert(o, by):
        nonlocal used
        resident[o] = sizes[o]
        used += sizes[o]
        stats["admissions"] += 1
        stats["admission_bytes"] += sizes[o]
        for j2 in active:
            if j2 != by and o in todo[j2]:
                ready[j2].append(o)

    def evict_oldest():
        nonlocal used
        c = res_chunks[0]
        if len(res_chunks) < 2:
            return False
        done = all(todo_cnt[x][c] == 0 for x in active)
        fd = first_done.get(c)
        forced = fd is not None and pos_total[fd[0]] - fd[1] >= force_after * len(chunks[c])
        if not (done or forced):
            return False
        for o in chunks[c]:
            if o in resident:
                used -= resident.pop(o)
                stats["evictions"] += 1
                stats["evicted_bytes"] += sizes[o]
        res_chunks.popleft()
        first_done.pop(c, None)
        return True

    def next_uncached(j, c):
        dq = pend[j][c]
        while dq:
            o = dq[0]
            if o in todo[j]:
                return o
            dq.popleft()
        return None

    def choose(j, a):
        """Return (obj, hit, admitted) for this read of job j."""
        td = todo[j]
        if not td:                                       # the trace repeats a file: replay it as it is
            return a.obj, a.obj in resident, False
        rd = ready[j]
        while rd:
            o = rd.popleft()
            if o in td and o in resident:
                consume(j, o)
                return o, True, False
        if usable:
            if res_chunks:                               # the chunk being loaded
                o = next_uncached(j, res_chunks[-1])
                if o is not None:
                    hit = o in resident
                    if not hit:
                        insert(o, j)
                    consume(j, o)
                    return o, hit, not hit
            start = (res_chunks[-1] + 1) if res_chunks else 0
            nxt = next((c % n_chunks for c in range(start, start + n_chunks)
                        if todo_cnt[j][c % n_chunks] > 0 and (c % n_chunks) not in res_chunks), None)
            if nxt is not None and (len(res_chunks) < limit or evict_oldest()):
                res_chunks.append(nxt)
                o = next_uncached(j, nxt)
                insert(o, j)
                consume(j, o)
                return o, False, True
        dq = rest[j]                                     # cannot cache: read the next file directly
        while dq[0] not in td:
            dq.popleft()
        o = dq[0]
        hit = o in resident
        consume(j, o)
        return o, hit, False

    n = hits = hit_bytes = total_bytes = warm_n = warm_hits = warm_bytes = warm_hit_bytes = 0
    t0 = time.perf_counter()
    for i, a in enumerate(accesses):
        j = a.job
        if cur_epoch.get(j) != a.epoch:
            cur_epoch[j] = a.epoch
            active.add(j)
            order = epoch_objs[j][a.epoch]
            todo[j] = set(order)
            todo_cnt[j] = collections.Counter(chunk_of[o] for o in order)
            pend[j] = collections.defaultdict(collections.deque)
            for o in order:
                pend[j][chunk_of[o]].append(o)
            rest[j] = collections.deque(order)
            ready[j] = collections.deque(o for c in res_chunks for o in chunks[c] if o in resident and o in todo[j])
        pos_total[j] += 1
        o, hit, _ = choose(j, a)
        size = sizes[o]
        warm = a.epoch != first_epoch[j]
        n += 1
        total_bytes += size
        hits += hit
        hit_bytes += size if hit else 0
        if warm:
            warm_n += 1
            warm_bytes += size
            warm_hits += hit
            warm_hit_bytes += size if hit else 0
        if hits_out is not None:
            hits_out.append(bool(hit))
        occupancy += used
        assert used <= capacity, (name, i, used)
        if i == last_index[j]:
            active.discard(j)
    elapsed = time.perf_counter() - t0
    return dict(
        policy=name, capacity_bytes=int(capacity), accesses=n, bytes=total_bytes, hits=hits,
        obj_hit_rate=hits / n if n else 0.0, byte_hit_rate=hit_bytes / total_bytes if total_bytes else 0.0,
        warm_obj_hit_rate=warm_hits / warm_n if warm_n else 0.0,
        warm_byte_hit_rate=warm_hit_bytes / warm_bytes if warm_bytes else 0.0,
        storage_read_bytes=total_bytes - hit_bytes, admission_bytes=stats["admission_bytes"],
        admissions=stats["admissions"], evictions=stats["evictions"], evicted_bytes=stats["evicted_bytes"],
        final_resident_bytes=used,
        peak_metadata_entries=len(resident) + sum(len(t) for t in todo.values()),
        policy_us_per_access=1e6 * elapsed / n if n else 0.0,
        mean_occupancy=occupancy / (n * capacity) if n and capacity else 0.0)


# --------------------------------------------------------------------------- bound

def object_bound(accesses, info, capacity):
    """Upper bound on the object hits of any policy. With every size relaxed to the smallest
    object size, at most capacity // min_size objects fit, and Belady's rule with bypass is
    optimal for equal sizes. Any real schedule is feasible in the relaxed problem."""
    slots = int(capacity // info["min_size"]) if info["min_size"] else 0
    unit = [Access(a.t, a.job, a.epoch, a.obj, 1) for a in accesses]
    r = simulate(unit, Oracle(slots, info), info)
    row = dict.fromkeys(("byte_hit_rate", "warm_byte_hit_rate", "storage_read_bytes", "admission_bytes",
                         "admissions", "evictions", "evicted_bytes", "final_resident_bytes",
                         "peak_metadata_entries", "policy_us_per_access", "mean_occupancy"))
    row.update(policy="bound", capacity_bytes=int(capacity), accesses=r["accesses"],
               bytes=sum(a.size for a in accesses), hits=r["hits"], obj_hit_rate=r["obj_hit_rate"],
               warm_obj_hit_rate=r["warm_obj_hit_rate"])
    return row


# --------------------------------------------------------------------------- dispatch

def build(name, capacity, info):
    """Construct a cross-job policy from its name. Online policies get no offline information."""
    online = online_view(info)
    if name.startswith("perjob-"):
        policy = PerJob(capacity, online, {"static": Static, "lru": LRU}[name.split("-", 1)[1]])
    elif name.startswith("known:"):
        parts = name.split(":")
        mode = parts[1] if parts[1] in ("all", "epoch", "epoch2") else float(parts[1])
        opts = dict(p.split("=", 1) for p in parts[2:])
        bias = {}
        if "rate" in opts:
            factor, job = opts["rate"].split("@")
            bias[int(job)] = float(factor)
        policy = KnownOrder(capacity, online, Lookahead(info["_job_seq"], mode, info["epoch_len"]),
                            rate_bias=bias, stale=int(opts.get("stale", 1)),
                            refresh=int(opts["refresh"]) if "refresh" in opts else None,
                            alpha=float(opts.get("alpha", 0.002)))
    else:
        raise ValueError(f"unknown policy {name}")
    policy.name = name
    return policy


def replay(name, accesses, info, capacity, check=False, hits_out=None):
    if name == "bound":
        return object_bound(accesses, info, capacity)
    if name.startswith("quiver"):
        return simulate_quiver(accesses, info, capacity, full=(name == "quiver-full"), name=name, hits_out=hits_out)
    return simulate(accesses, build(name, capacity, info), info, check=check, hits_out=hits_out)
