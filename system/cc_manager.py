#!/usr/bin/env python3
"""Control plane of the minimal CXL training cache: all metadata and every decision.

The manager owns the object table, the slot table, the reference counts of running transfers,
the job table, and the statistics. It is driven by one thread. For every access it calls a
replacement policy of the simulator (simulator/cachesim.py, simulator/crossjob.py), unchanged:
'static', 'lru', 'reuse-epoch' (progress-aware), 'known:epoch' (known order). The policies see
every object as one unit and the capacity as a number of slots.

What a job tells the cache, and nothing more: at registration its seed, its epoch length, and
the total number of accesses it will make; before each epoch the order of that epoch; with every
request the epoch and the position. That is the 'known:epoch' lookahead of the simulator. With
'known:epoch2' (two-epoch lookahead) a job announces the next epoch as well, one epoch early.

Prefetching (optional, known-order policies only): for every job the announced accesses of the
next `lead` seconds are candidates, soonest first across jobs. A candidate that is not resident
is offered to the policy (KnownOrder.offer: the ranked admission of a miss, no other rule); if
it is admitted the backend reads it into a slot in the background. At most `par` such reads run
at once and at most `unused` prefetched files wait for their first use. Every prefetched file
ends as used in time, late (requested while its read was running), evicted unused, or unused.

The manager does no I/O. It tells a backend what to do (hit, miss, fail, reply) and is told
when a transfer or an admission copy has finished. The backend is the data plane
(system/cc_server.c, through cc_server.py) or, in tests, a stub.
"""
import collections
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "simulator"))
from cachesim import LRU, Access, ReuseEpoch, Static  # noqa: E402
from crossjob import KnownOrder  # noqa: E402

KIND_HIT, KIND_MISS_ADMIT, KIND_MISS_BYPASS, KIND_HIT_WAITED = 1, 2, 3, 4
KIND_HIT_PREFETCHED, KIND_HIT_PREFETCH_LATE = 5, 6      # in the manager's log only; clients see 1 and 4
POLICIES = ("static", "lru", "reuse-epoch", "known:epoch", "known:epoch2")


class OnlineLookahead:
    """What crossjob.Lookahead is for a recorded trace, for running jobs: the part of each job's
    order that the job has announced. Mode 'epoch': a job's order is visible up to the end of
    the epoch it is in. Mode 'epoch2': up to the end of the epoch after it, as far as the job
    has announced that one. Filled by add_job and add_epoch; the policy only reads it."""

    def __init__(self, mode="epoch"):
        self.mode = mode
        self._seq, self._epoch_end, self._shown, self._total = {}, {}, {}, {}

    def add_job(self, job, total):
        self._seq[job], self._epoch_end[job], self._shown[job], self._total[job] = [], [], 0, total

    def add_epoch(self, job, epoch, objs):
        end = len(self._seq[job]) + len(objs)
        self._seq[job].extend((o, epoch) for o in objs)
        self._epoch_end[job].extend([end] * len(objs))

    def reveal(self, job, pos):
        """Job is at position pos of its own sequence. Return newly visible [(position, obj)]."""
        seq, h = self._seq[job], self._epoch_end[job][pos]
        if self.mode == "epoch2" and h < len(seq):
            h = self._epoch_end[job][h]
        start = max(self._shown[job], pos + 1)
        self._shown[job] = max(self._shown[job], h)
        return [(q, seq[q][0]) for q in range(start, h)]

    def shown(self, job):
        return self._shown[job]

    def is_last(self, job, pos):
        return pos == self._total[job] - 1

    def complete(self, job):
        return self._shown[job] >= self._total[job]

    def ahead(self, job, pos, n):
        """The next visible accesses after position pos, at most n: [(position, obj)]."""
        seq = self._seq[job]
        return [(q, seq[q][0]) for q in range(pos + 1, min(self._shown[job], pos + 1 + n))]


class _JobState:
    __slots__ = ("seed", "epoch_len", "total", "epochs", "lengths", "orders", "pending", "k", "next_pos",
                 "held", "done", "ended", "held_since", "mismatches")

    def __init__(self, seed, epoch_len, total):
        self.seed, self.epoch_len, self.total = seed, epoch_len, total
        self.epochs, self.lengths, self.orders = [], [], []   # announced epochs, in order
        self.pending = {}          # epoch -> [length, list being filled]
        self.k, self.next_pos = 0, 0   # index of the current epoch, next position in it
        self.held = {}             # (epoch, pos) -> request that arrived before its predecessors
        self.done, self.ended, self.held_since, self.mismatches = 0, False, None, 0


class CacheManager:
    """policy: one of POLICIES. capacity: slots the policy may fill. nslots: slots of the store
    (capacity plus spare slots for objects in transit). catalog: list of (path, size)."""

    def __init__(self, policy, capacity, nslots, catalog, backend, objects=None, log_accesses=True,
                 hold_timeout=0.5, clock=time.monotonic, prefetch=None):
        assert policy in POLICIES, policy
        assert 0 < capacity <= nslots
        self.policy_name, self.capacity, self.nslots, self.catalog, self.backend = policy, capacity, nslots, catalog, backend
        self.clock, self.hold_timeout = clock, hold_timeout
        self.info = dict(epoch_len={}, objects=objects or len(catalog), jobs=[], first_epoch={},
                         working_set_bytes=objects or len(catalog), mean_size=1, min_size=1, sizes={})
        self.look = OnlineLookahead("epoch2" if policy == "known:epoch2" else "epoch")
        if policy == "static":
            self.policy = Static(capacity, self.info)
        elif policy == "lru":
            self.policy = LRU(capacity, self.info)
        elif policy == "reuse-epoch":
            self.policy = ReuseEpoch(capacity, self.info)
        else:
            self.policy = KnownOrder(capacity, self.info, self.look, dense=len(catalog))   # objects are catalog lines
        self.jobs = {}
        self.slot_of = {}                   # object -> slot that holds its bytes
        self.loading = {}                   # resident object -> slot its admission copy is going into
        self.orphan = {}                    # slot -> object: a copy still running for an object evicted meanwhile
        self.waiters = collections.defaultdict(list)   # slot -> requests waiting for the copy into it
        self.pins = [0] * nslots            # transfers reading the slot
        self.free = list(range(nslots - 1, -1, -1))
        self.draining = set()               # slots given up by the policy that are still being read
        self.n = 0                          # accesses processed
        self.log = [] if log_accesses else None
        self.stat = collections.Counter()
        self.t0 = clock()
        # prefetching: dict(par=reads in flight, lead=seconds of a job's accesses, unused=files waiting for first use)
        self.prefetch = prefetch if prefetch and prefetch.get("par", 0) > 0 and policy.startswith("known") else None
        self.pf = {}                        # prefetched object not yet requested -> [state "flying" or "ready", time issued]
        self.pf_todo = {}                   # job -> deque of (position, object) waiting to be offered
        self.pf_enq = {}                    # job -> last position put on its deque
        self.pf_inflight = 0

    # ------------------------------------------------------------------ jobs
    def register(self, job, seed, epoch_len, total):
        if job in self.jobs:
            return -17                       # EEXIST
        self.jobs[job] = _JobState(seed, epoch_len, total)
        self.info["epoch_len"][job] = epoch_len
        self.info["jobs"].append(job)
        self.look.add_job(job, total)
        return 0

    def announce(self, job, epoch, offset, length, ids):
        """One piece of the order of an epoch: `ids` are the objects at positions offset.. of an
        epoch of `length` accesses. The epoch is usable once all pieces have arrived."""
        st = self.jobs.get(job)
        if st is None:
            return -2                        # ENOENT
        cur = st.pending.setdefault(epoch, [length, []])
        if offset != len(cur[1]) or cur[0] != length or any(not 0 <= o < len(self.catalog) for o in ids):
            return -22                       # EINVAL
        cur[1].extend(ids)
        if len(cur[1]) == length:
            del st.pending[epoch]
            st.epochs.append(epoch)
            st.lengths.append(length)
            st.orders.append(cur[1])
            self.look.add_epoch(job, epoch, cur[1])
            self.info["first_epoch"].setdefault(job, epoch)
            self._drain(job)
        return len(cur[1]) if epoch in st.pending else length

    def end(self, job):
        st = self.jobs.get(job)
        if st is None:
            return -2
        st.ended = True
        return st.done

    # ------------------------------------------------------------------ requests
    def get(self, req, job, epoch, pos, obj):
        """A GET arrived. It is processed when all earlier positions of its job have been."""
        st = self.jobs.get(job)
        if st is None or not 0 <= obj < len(self.catalog):
            self.stat["rejected"] += 1
            self.backend.fail(req, -22)
            return
        st.held[(epoch, pos)] = (req, obj)
        if st.held_since is None:
            st.held_since = self.clock()
        self._drain(job)

    def _drain(self, job):
        st = self.jobs[job]
        while st.k < len(st.epochs):
            key = (st.epochs[st.k], st.next_pos)
            item = st.held.pop(key, None)
            if item is None:
                break
            self._process(job, st, key[0], key[1], *item)
            st.next_pos += 1
            if st.next_pos == st.lengths[st.k]:
                st.k, st.next_pos = st.k + 1, 0
        st.held_since = self.clock() if st.held else None

    def tick(self):
        """Called regularly. A request that has waited longer than hold_timeout for a predecessor
        that never came is processed out of order, and counted: the announced order was not kept."""
        now = self.clock()
        for job, st in self.jobs.items():
            if st.held and st.held_since is not None and now - st.held_since > self.hold_timeout and st.k < len(st.epochs):
                same = sorted(p for (e, p) in st.held if e == st.epochs[st.k])
                if not same:
                    continue
                self.stat["order_gaps"] += same[0] - st.next_pos
                st.next_pos = same[0]
                self._drain(job)

    def _process(self, job, st, epoch, pos, req, obj):
        # The time the policy sees is the time that is logged: seconds since the manager started, to the
        # microsecond. The simulator on the recorded trace then works with exactly the same numbers.
        now = float(f"{self.clock() - self.t0:.6f}")
        order = st.orders[st.k]
        if order[pos] != obj:               # the job did not read what it announced
            st.mismatches += 1
            self.stat["order_mismatches"] += 1
        st.done += 1
        a = Access(now, job, epoch, obj, 1)
        i, self.n = self.n, self.n + 1
        size = self.catalog[obj][1]
        pol = self.policy
        self.stat["accesses"] += 1
        self.stat["bytes"] += size
        hit = pol.contains(a)
        admitted, nevict, kind = False, 0, 0
        if hit:
            pol.on_hit(i, a)
            self.stat["hits"] += 1
            self.stat["hit_bytes"] += size
            was_pf = self.pf.pop(obj, None)
            if obj in self.slot_of:
                slot = self.slot_of[obj]
                self.pins[slot] += 1
                kind = KIND_HIT
                if was_pf is not None:
                    kind = KIND_HIT_PREFETCHED
                    self.stat["prefetch_in_time"] += 1
                    self.stat["prefetch_in_time_bytes"] += size
                self.backend.hit(req, slot, size, KIND_HIT)
            elif obj in self.loading:        # its admission copy is still running: wait for it
                kind = KIND_HIT_WAITED
                self.stat["hit_waits"] += 1
                if was_pf is not None:
                    kind = KIND_HIT_PREFETCH_LATE
                    self.stat["prefetch_late"] += 1
                self.waiters[self.loading[obj]].append((req, size))
            else:                            # resident for the policy, but the bytes never arrived
                kind = KIND_MISS_BYPASS
                self.stat["hits_without_data"] += 1
                self.backend.miss(req, self.catalog[obj][0], size, -1)
        else:
            admitted = bool(pol.on_miss(i, a))
            if pol.evicted:
                nevict = len(pol.evicted)
                for victim, _ in pol.evicted:
                    self._evict_physical(victim)
                self.stat["evictions"] += nevict
                pol.evicted.clear()
            if admitted and not self.free:   # every spare slot is still being read
                self.stat["admissions_without_slot"] += 1
                admitted = False             # the policy keeps the object as resident; later hits read storage
                self.backend.miss(req, self.catalog[obj][0], size, -1)
                kind = KIND_MISS_BYPASS
            elif admitted:
                slot = self.free.pop()
                assert self.pins[slot] == 0 and slot not in self.draining and slot not in self.orphan, slot
                self.loading[obj] = slot
                self.stat["admissions"] += 1
                self.stat["admission_bytes"] += size
                kind = KIND_MISS_ADMIT
                self.backend.miss(req, self.catalog[obj][0], size, slot)
            else:
                self.stat["bypasses"] += 1
                kind = KIND_MISS_BYPASS
                self.backend.miss(req, self.catalog[obj][0], size, -1)
        assert len(pol.resident) <= self.capacity, (len(pol.resident), self.capacity)
        if self.log is not None:
            self.log.append((now, job, epoch, pos, obj, size, int(hit), int(admitted), nevict, kind))
        if self.prefetch:
            self._pf_window(job)
            self._pf_pump(now)

    # ------------------------------------------------------------------ prefetching
    def _pf_window(self, job):
        """Put the announced accesses that entered the job's window on its deque."""
        st = self.policy.jobs[job]
        depth = max(4, int(self.prefetch["lead"] * self.policy._rate(job)))
        last = self.pf_enq.get(job, -1)
        todo = self.pf_todo.setdefault(job, collections.deque())
        for q, o in self.look.ahead(job, st.pos, depth):
            if q > last:
                todo.append((q, o))
                last = q
        self.pf_enq[job] = last
        if self.look.shown(job) - st.pos - 1 < depth and not self.look.complete(job):
            self.stat["prefetch_window_cut"] += 1     # the announced order ends inside the window

    def _pf_pump(self, now):
        """Offer candidates, soonest need first, while the limits allow."""
        pol, limit = self.policy, self.prefetch["unused"]
        while self.pf_inflight < self.prefetch["par"] and len(self.pf) < limit and self.free:
            best = None
            for job, todo in self.pf_todo.items():
                pos = pol.jobs[job].pos
                while todo and todo[0][0] <= pos:
                    todo.popleft()
                    self.stat["prefetch_passed"] += 1
                # Only what lies inside the job's window at the rate measured now. The window was sized when the
                # candidate was queued; a job with several read streams sends its first requests at once, the rate
                # measured then is far too high, and without this check the prefetcher runs ahead until `unused`
                # stops it (seen on 2026-11-24: 5,897 prefetches for 1,352 requests of two jobs).
                if todo and todo[0][0] - pos <= max(4, int(self.prefetch["lead"] * pol._rate(job))):
                    eta = pol.next_need(now, job, todo[0][0])
                    if best is None or eta < best[0]:
                        best = (eta, job)
            if best is None:
                return
            q, obj = self.pf_todo[best[1]].popleft()
            if obj in pol.resident:
                continue
            if not pol.offer(now, obj, 1):
                self.stat["prefetch_declined"] += 1
                continue
            if pol.evicted:
                self.stat["evictions"] += len(pol.evicted)
                for victim, _ in pol.evicted:
                    self._evict_physical(victim)
                pol.evicted.clear()
            size = self.catalog[obj][1]
            if not self.free:                # every spare slot is being read: resident without data, as for a miss
                self.stat["admissions_without_slot"] += 1
                return
            slot = self.free.pop()
            assert self.pins[slot] == 0 and slot not in self.draining and slot not in self.orphan, slot
            self.loading[obj] = slot
            self.pf[obj] = ["flying", now]
            self.pf_inflight += 1
            self.stat["prefetch_issued"] += 1
            self.stat["prefetch_bytes"] += size
            self.backend.prefetch(obj, self.catalog[obj][0], size, slot)

    def prefetched(self, obj, slot, ok, io_s=0.0):
        """The background read of obj into slot has finished."""
        self.pf_inflight -= 1
        self.stat["prefetch_done"] += 1
        self.stat["prefetch_io_us"] += int(io_s * 1e6)
        if not ok:
            self.stat["prefetch_failures"] += 1
        state = self.pf.get(obj)
        if state is not None and self.loading.get(obj) == slot:
            if ok:
                state[0] = "ready"
            else:
                del self.pf[obj]
        self.admitted(obj, slot, ok)
        if self.prefetch:
            self._pf_pump(float(f"{self.clock() - self.t0:.6f}"))

    def _evict_physical(self, victim):
        if self.pf.pop(victim, None) is not None:
            self.stat["prefetch_evicted_unused"] += 1
            self.stat["prefetch_evicted_unused_bytes"] += self.catalog[victim][1]
        slot = self.slot_of.pop(victim, None)
        if slot is not None:
            if self.pins[slot]:
                self.draining.add(slot)      # a transfer still reads it; freed in hit_done
            else:
                self.free.append(slot)
        elif victim in self.loading:         # its copy is still running: the slot is released in admitted()
            self.orphan[self.loading.pop(victim)] = victim

    # ------------------------------------------------------------------ completions
    def hit_done(self, slot):
        self.pins[slot] -= 1
        assert self.pins[slot] >= 0, slot
        if self.pins[slot] == 0 and slot in self.draining:
            self.draining.remove(slot)
            self.free.append(slot)

    def admitted(self, obj, slot, ok):
        """The admission copy of obj into slot has finished (ok) or did not happen."""
        if self.loading.get(obj) == slot:
            del self.loading[obj]
            keep = ok
        else:                                # evicted while the copy was running (and possibly admitted again elsewhere)
            assert self.orphan.pop(slot) == obj, (obj, slot)
            keep = False
        waiting = self.waiters.pop(slot, [])
        if not ok:
            self.stat["admission_failures"] += 1
        if keep:
            self.slot_of[obj] = slot
        for req, size in waiting:
            if ok:                           # the slot holds the bytes, resident or not
                self.pins[slot] += 1
                self.backend.hit(req, slot, size, KIND_HIT_WAITED)
            else:
                self.backend.miss(req, self.catalog[obj][0], size, -1)
        if not keep:
            if self.pins[slot]:
                self.draining.add(slot)
            else:
                self.free.append(slot)

    # ------------------------------------------------------------------ checks and reports
    def check(self):
        """Invariants of the metadata. Cheap enough to run after every event in tests."""
        pol = self.policy
        assert len(pol.resident) <= self.capacity
        used = set(self.slot_of.values()) | set(self.loading.values()) | set(self.orphan)
        assert len(used) == len(self.slot_of) + len(self.loading) + len(self.orphan), "a slot holds two objects"
        assert not used & set(self.free), "a slot in use is on the free list"
        assert not used & self.draining and not self.draining & set(self.free)
        assert len(used) + len(self.free) + len(self.draining) == self.nslots, "a slot was lost"
        assert all(self.pins[s] == 0 for s in self.free), "a free slot is being read"
        for obj in list(self.slot_of) + list(self.loading):
            assert obj in pol.resident, obj
        assert all(s in self.loading.values() or s in self.orphan for s in self.waiters), "a request waits for nothing"
        assert all(o in pol.resident for o in self.pf), "a prefetched object is tracked after its eviction"
        assert 0 <= self.pf_inflight <= (self.prefetch["par"] if self.prefetch else 0)
        return True

    def summary(self):
        s = dict(self.stat)
        s.update(policy=self.policy_name, capacity_slots=self.capacity, store_slots=self.nslots,
                 resident=len(self.policy.resident), in_store=len(self.slot_of), loading=len(self.loading) + len(self.orphan),
                 free_slots=len(self.free), draining_slots=len(self.draining), jobs=len(self.jobs),
                 objects=len(self.catalog))
        n, b = s.get("accesses", 0), s.get("bytes", 0)
        s["obj_hit_rate"] = s.get("hits", 0) / n if n else 0.0
        s["byte_hit_rate"] = s.get("hit_bytes", 0) / b if b else 0.0
        s["storage_read_bytes"] = b - s.get("hit_bytes", 0)     # read from storage for requests (demand)
        if self.prefetch:
            s["prefetch_config"] = dict(self.prefetch)
            s["prefetch_unused_now"] = len(self.pf)
            issued = s.get("prefetch_issued", 0)
            s["prefetch_in_time_share"] = s.get("prefetch_in_time", 0) / issued if issued else 0.0
            s["demand_storage_read_bytes"] = s["storage_read_bytes"] - s.get("prefetch_in_time_bytes", 0)
        return s

    def write_log(self, path):
        """The accesses in the order the manager processed them, with its decisions. The first five
        columns are a trace in the simulator's format (sizes are the files' real sizes)."""
        with open(path, "w") as f:
            pf = f"; prefetch par={self.prefetch['par']} lead={self.prefetch['lead']} unused={self.prefetch['unused']}" if self.prefetch else ""
            f.write(f"# kind=real; accesses as processed by the cache manager, policy {self.policy_name}, "
                    f"capacity {self.capacity} slots, catalog {self.info['objects']} objects; decision columns after the trace columns{pf}\n")
            f.write("t,job,epoch,obj,size,pos,hit,admitted,evicted,kind\n")
            for t, job, epoch, pos, obj, size, hit, adm, nev, kind in self.log:
                f.write(f"{t:.6f},{job},{epoch},{obj},{size},{pos},{hit},{adm},{nev},{kind}\n")


def load_catalog(path):
    """Lines 'path bytes'. The object identifier is the line number, from 0."""
    out = []
    for line in open(path):
        p = line.split()
        if p:
            out.append((p[0], int(p[1])))
    return out
