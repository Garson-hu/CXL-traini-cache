#!/usr/bin/env python3
"""CosmoFlow training I/O harness: where does the time of a training step go, and how fast can data be supplied?

Modes
  select   choose disjoint random subsets of files that this project has not read before (ledger)
  rawread  read whole files with N threads, no decoding; per-file latency
  stage    copy the files of a list into a directory (for example tmpfs) and write the matching list
  loader   run the real input pipeline without a model and drain it        (data loader only)
  compute  repeat the training step on one batch held in memory            (compute only)
  train    instrumented training: per step, time waiting for data and time computing; optional access trace

Origin: the input pipeline (explicit seeded file order per epoch, interleaved readers, logging of every file pull)
follows train_trace.py of the earlier study (repository ~/CXL, branch explore/reuse-window-prefetch, commit a65c6e3).
parse_data() is copied from data/cosmo.py of the CosmoFlow benchmark, because importing that module pulls in Horovod.
The model is built by the benchmark's own code, imported read-only from --bench.

Differences from the benchmark's train.py, on purpose: a plain loop with one tf.function per step instead of
model.fit (so that waiting and computing can be timed separately), no Horovod, no checkpoints, no learning-rate
schedule, validation only when --valid-list is given. Model, loss (MSE), and optimizer (SGD, momentum 0.9) are the same.

Pipelines: "seq" is the benchmark's sequential reader. "par" is tf.data's parallel interleave with cycle length
--read-par; it reads ahead and has up to three times that many files open at once (measured). "map" reads and
decompresses exactly --read-par files at a time. All but "seq" are asynchronous and end in a prefetch buffer.

With --order list the files are read in list order in every epoch (first read, then re-read of the same sequence);
--start-unix lets jobs on several nodes begin at the same wall-clock time.

File lists hold one "path bytes" pair per line. Nothing is written outside --out, and an existing run label is
never overwritten. The script contains no machine-specific path.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import time


def read_list(path):
    files, sizes = [], []
    for line in open(path):
        if line.strip() and not line.startswith("#"):
            p, s = line.split()[:2]
            files.append(p)
            sizes.append(int(s))
    return files, sizes


def proc_rchar():
    for line in open("/proc/self/io"):
        if line.startswith("rchar:"):
            return int(line.split()[1])
    return 0


def run_info(args, **extra):
    info = dict(mode=args.mode, label=args.label, argv=sys.argv, host=os.uname().nodename,
                cpus=sorted(os.sched_getaffinity(0)), n_cpus=len(os.sched_getaffinity(0)),
                git_commit=os.environ.get("RUN_GIT_COMMIT", ""), start_unix=time.time())
    info.update(extra)
    return info


def out_path(args, kind, ext):
    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, f"{kind}-{args.label}.{ext}")
    if os.path.exists(p):
        sys.exit(f"refusing to overwrite {p}")
    return p


# ---------------------------------------------------------------- select
def mode_select(args):
    import random
    excluded = set()
    for p in args.exclude_names or []:
        for line in open(p):
            for tok in line.split():
                if tok.endswith(".tfrecord"):
                    excluded.add(os.path.basename(tok))
    if os.path.exists(args.ledger):
        excluded.update(line.split()[0] for line in open(args.ledger) if line.strip())
    rows = [line.strip().split(",") for line in open(args.manifest) if not line.startswith("#")]
    pool = [(n, int(s)) for n, s in rows if n not in excluded]
    random.Random(args.seed).shuffle(pool)
    os.makedirs(args.out, exist_ok=True)
    at = 0
    with open(args.ledger, "a") as ledger:
        for spec in args.subsets:
            name, count = spec.split(":")
            target = os.path.join(args.out, name + ".txt")
            if os.path.exists(target):
                sys.exit(f"refusing to overwrite {target}")
            part = pool[at:at + int(count)]
            at += int(count)
            if len(part) < int(count):
                sys.exit("not enough unread files left")
            with open(target, "w") as f:
                for n, s in part:
                    f.write(f"{os.path.join(args.dir, n)} {s}\n")
                    ledger.write(f"{n} {name} {args.tag}\n")
            print(f"{name}: {len(part)} files, {sum(s for _, s in part) / 1e9:.2f} GB")
    print(f"pool after exclusion: {len(pool)} files; used now: {at}")


# ---------------------------------------------------------------- rawread
def mode_rawread(args):
    files, sizes = read_list(args.file_list)
    if args.count:
        files, sizes = files[:args.count], sizes[:args.count]
    csv_path = out_path(args, "reads", "csv")
    json_path = out_path(args, "run", "json")
    info = run_info(args, threads=args.threads, files=len(files), file_list=args.file_list)
    rows, lock, nxt = [], threading.Lock(), [0]

    def worker(tid):
        buf = bytearray(4 << 20)
        while True:
            with lock:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(files):
                return
            t_unix, t0, n = time.time(), time.perf_counter(), 0
            with open(files[i], "rb", buffering=0) as f:
                while True:
                    got = f.readinto(buf)
                    if not got:
                        break
                    n += got
            rows.append((i, tid, n, t_unix, time.perf_counter() - t0))

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(t,)) for t in range(args.threads)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.perf_counter() - t0
    rows.sort()
    with open(csv_path, "w") as f:
        f.write("idx,thread,bytes,t_start_unix,lat_s,name\n")
        for i, tid, n, t_unix, lat in rows:
            f.write(f"{i},{tid},{n},{t_unix:.6f},{lat:.6f},{os.path.basename(files[i])}\n")
    total = sum(r[2] for r in rows)
    lats = sorted(r[4] for r in rows)
    info.update(wall_s=wall, bytes=total, gb_per_s=total / 1e9 / wall, files_per_s=len(rows) / wall,
                lat_p50_ms=1e3 * lats[len(lats) // 2], lat_p90_ms=1e3 * lats[int(0.9 * (len(lats) - 1))],
                end_unix=time.time())
    json.dump(info, open(json_path, "w"), indent=1)
    print(f"rawread {args.label}: {len(rows)} files, {total / 1e9:.2f} GB in {wall:.2f} s = {total / 1e9 / wall:.3f} GB/s, "
          f"p50 {info['lat_p50_ms']:.1f} ms, p90 {info['lat_p90_ms']:.1f} ms")


# ---------------------------------------------------------------- stage
def mode_stage(args):
    files, sizes = read_list(args.file_list)
    os.makedirs(args.to, exist_ok=False)
    lock, nxt = threading.Lock(), [0]

    def worker():
        while True:
            with lock:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(files):
                return
            shutil.copyfile(files[i], os.path.join(args.to, os.path.basename(files[i])))

    t0 = time.time()
    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with open(args.list_out, "w") as f:
        for p, s in zip(files, sizes):
            f.write(f"{os.path.join(args.to, os.path.basename(p))} {s}\n")
    print(f"staged {len(files)} files ({sum(sizes) / 1e9:.2f} GB) to {args.to} in {time.time() - t0:.1f} s")


# ---------------------------------------------------------------- TensorFlow parts
def setup_tf(args, use_gpu):
    if not use_gpu:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import numpy as np
    import tensorflow as tf
    import yaml
    gpus = tf.config.list_physical_devices("GPU")
    for g in gpus:
        tf.config.experimental.set_memory_growth(g, True)
    cfg = yaml.safe_load(open(os.path.join(args.bench, "configs", "cosmo.yaml")))
    return np, tf, cfg, gpus


def make_parse(tf, np, shape, apply_log):
    def parse_data(sample_proto):  # copied from the benchmark's data/cosmo.py (_parse_data)
        feature_spec = dict(x=tf.io.FixedLenFeature([], tf.string), y=tf.io.FixedLenFeature([4], tf.float32))
        parsed_example = tf.io.parse_single_example(sample_proto, features=feature_spec)
        x = tf.io.decode_raw(parsed_example['x'], tf.int16)
        x = tf.cast(tf.reshape(x, shape), tf.float32)
        y = parsed_example['y']
        if apply_log:
            x = tf.math.log(x + tf.constant(1.))
        else:
            x /= (tf.reduce_sum(x) / np.prod(shape))
        return x, y
    return parse_data


class Pipeline:
    """Builds one dataset per epoch from an explicit order; optionally logs every file pull."""

    def __init__(self, args, np, tf, cfg, files, sizes, dataset_name, trace_file=None):
        self.args, self.np, self.tf = args, np, tf
        self.files, self.sizes, self.dataset_name = files, sizes, dataset_name
        self.parse = make_parse(tf, np, cfg["data"]["sample_shape"], cfg["data"].get("apply_log", True))
        self.compression = cfg["data"].get("compression", "GZIP")
        self.trace_file, self.epoch, self.pos = trace_file, 0, 0
        self.names = [os.path.basename(p) for p in files]
        self.cache, self.cache_kinds = None, [0, 0, 0, 0, 0]
        self.cache_announced = set()
        self.cache_requests = [] if getattr(args, "cache_request_log", False) else None
        if args.pipeline == "cache" and dataset_name == "train":   # file bytes come from the cache server
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "system"))
            from cc_client import CacheClient
            ids = {line.split()[0]: n for n, line in enumerate(open(args.cache_catalog)) if line.strip()}
            self.obj_ids = np.array([ids[p] for p in files], dtype=np.int64)   # object identifier = line of the catalog
            self.cache = CacheClient(open(args.cache_addr_file).read().strip(), lib=args.cache_lib or None,
                                     nbuf=max(16, 2 * args.read_par))
            self.cache.register(args.cache_job, args.seed, len(files), len(files) * args.epochs)

    def order(self, epoch, shuffle=True):
        n = len(self.files)
        if not shuffle or self.args.order == "list":   # list order: the same files in the same order in every epoch
            return self.np.arange(n)
        return self.np.random.default_rng(self.args.seed * 1000003 + epoch).permutation(n)

    def _log_pull(self, idx):
        i = int(idx)
        self.trace_file.write(f"{time.time():.6f},{self.args.job},{self.dataset_name},{self.epoch},{self.pos},{i},"
                              f"{self.sizes[i]},{self.names[i]}\n")
        self.pos += 1
        return idx

    def _read_record(self, path):
        """The serialized example of a file that holds one gzip-compressed TFRecord. Same work as TFRecordDataset
        (read, inflate), without its read-ahead of further files and without the CRC check of the record."""
        return self._inflate(self.tf.io.read_file(path))

    def _inflate(self, raw):
        tf = self.tf
        data = tf.io.decode_compressed(raw, compression_type=self.compression)
        return tf.strings.substr(data, 12, tf.strings.length(data) - 16)   # 8-byte length, 4-byte CRC, payload, 4-byte CRC

    def _cache_fetch(self, epoch, pos, obj):
        """The bytes of one file from the cache server. Called by up to read_par threads at once; the request
        itself runs outside the interpreter lock."""
        if self.cache_requests is None:
            data, kind = self.cache.get(self.args.cache_job, int(epoch), int(pos), int(obj))
            self.cache_kinds[kind] += 1
            return data
        import ctypes                        # --cache-request-log: the same call, with its timings kept
        t = time.time()
        p, n, res = self.cache.get_raw(self.args.cache_job, int(epoch), int(pos), int(obj))
        try:
            data = ctypes.string_at(p, n)
        finally:
            self.cache.release(res.buf)
        self.cache_kinds[res.kind] += 1
        self.cache_requests.append((t, int(epoch), int(pos), res.kind, n, res.ns_client, res.ns_srv_total, res.ns_srv_wait,
                                    res.ns_srv_io, res.ns_srv_bulk))
        return data

    def write_cache_requests(self, path):
        """One line per request to the cache server: when it was sent, how it was served (1 hit, 2 miss admitted,
        3 miss bypassed, 4 hit that waited for a running read), and where its time went. All times in ms."""
        with open(path, "w") as f:
            f.write("t_unix,epoch,pos,kind,bytes,client_ms,server_total_ms,server_wait_ms,server_io_ms,server_bulk_ms\n")
            for r in sorted(self.cache_requests):
                f.write(f"{r[0]:.6f},{r[1]},{r[2]},{r[3]},{r[4]}," + ",".join(f"{x / 1e6:.3f}" for x in r[5:]) + "\n")

    def dataset(self, epoch, order):
        tf, a = self.tf, self.args
        self.epoch, self.pos = epoch, 0
        paths = [self.files[i] for i in order]
        ds = tf.data.Dataset.from_tensor_slices((tf.constant(paths), tf.constant(order.astype(self.np.int64))))
        if self.trace_file is not None:
            ds = ds.map(lambda f, i: (f, tf.py_function(self._log_pull, [i], tf.int64)), num_parallel_calls=1)
        reader = lambda f, i: tf.data.TFRecordDataset(f, compression_type=self.compression)
        if a.pipeline == "seq":       # the benchmark's reader: one file at a time, one parse thread, no prefetch
            ds = ds.flat_map(reader).map(self.parse, num_parallel_calls=1)
            return ds.batch(a.batch_size, drop_remainder=True)
        if a.pipeline == "cache" and self.cache is not None:   # as "map", with the file's bytes from the cache server
            # This epoch's order, before its first request. With two-epoch lookahead also the next epoch's order,
            # one epoch early: it is computed from the seed exactly as it will be when that epoch starts.
            if epoch not in self.cache_announced:
                self.cache.announce(a.cache_job, epoch, self.obj_ids[order])
                self.cache_announced.add(epoch)
            if a.cache_lookahead >= 2 and epoch + 1 < a.epochs and epoch + 1 not in self.cache_announced:
                self.cache.announce(a.cache_job, epoch + 1, self.obj_ids[self.order(epoch + 1)])
                self.cache_announced.add(epoch + 1)
            pos = tf.data.Dataset.from_tensor_slices((tf.range(len(order), dtype=tf.int64), tf.constant(self.obj_ids[order])))
            ds = tf.data.Dataset.zip((ds, pos))
            fetch = lambda p, o: tf.numpy_function(self._cache_fetch, [tf.constant(epoch, tf.int64), p, o], tf.string)
            ds = ds.map(lambda fi, po: self._inflate(fetch(po[0], po[1])), num_parallel_calls=a.read_par)
            ds = ds.map(self.parse, num_parallel_calls=a.parse_par)
            return ds.batch(a.batch_size, drop_remainder=True).prefetch(a.prefetch)
        if a.pipeline in ("map", "cache"):   # exactly read_par files are read and decompressed at a time; asynchronous, with prefetch
            ds = ds.map(lambda f, i: self._read_record(f), num_parallel_calls=a.read_par)
            ds = ds.map(self.parse, num_parallel_calls=a.parse_par)
            return ds.batch(a.batch_size, drop_remainder=True).prefetch(a.prefetch)
        ds = ds.interleave(reader, cycle_length=a.read_par, block_length=1, num_parallel_calls=a.read_par)
        ds = ds.map(self.parse, num_parallel_calls=a.parse_par)
        return ds.batch(a.batch_size, drop_remainder=True).prefetch(a.prefetch)


def pipeline_settings(args):
    return dict(pipeline=args.pipeline, read_par=args.read_par, parse_par=args.parse_par, prefetch=args.prefetch,
                batch_size=args.batch_size, seed=args.seed,
                order="numpy.random.default_rng(seed * 1000003 + epoch).permutation(n_files)" if args.order == "seeded"
                else "list order, identical in every epoch")


def list_hash(files):
    return hashlib.sha1("\n".join(os.path.basename(f) for f in files).encode()).hexdigest()


def mode_loader(args):
    np, tf, cfg, _ = setup_tf(args, use_gpu=False)
    files, sizes = read_list(args.file_list)
    epochs_path, json_path = out_path(args, "epochs", "csv"), out_path(args, "run", "json")
    info = run_info(args, files=len(files), bytes=sum(sizes), file_list=args.file_list, names_sha1=list_hash(files),
                    tf=tf.__version__, pace=args.pace, **pipeline_settings(args))
    pipe = Pipeline(args, np, tf, cfg, files, sizes, "train")
    out = open(epochs_path, "w")
    out.write("epoch,samples,bytes,wall_s,samples_per_s,gb_per_s,cpu_s,cpu_s_per_sample,rchar_bytes,blocked_s\n")
    sf = None
    if args.step_log:      # one line per batch, as the training mode writes it (no loss; "compute" is the emulated step)
        sf = open(out_path(args, "steps", "csv"), "w")
        sf.write("epoch,step,t_start_unix,data_wait_s,compute_s\n")
    if args.start_unix:
        time.sleep(max(0.0, args.start_unix - time.time()))
    for e in range(args.epochs):
        order = pipe.order(e)
        it = iter(pipe.dataset(e, order))
        steps = len(files) // args.batch_size
        c0, r0, t0, blocked, done = time.process_time(), proc_rchar(), time.perf_counter(), 0.0, 0
        for step in range(steps):
            tb, tu = time.perf_counter(), time.time()
            next(it)
            w = time.perf_counter() - tb
            blocked += w
            done = step + 1
            c = 0.0
            if args.pace and args.pace_step:   # emulated training step: a fixed time after every batch, never made up
                c = args.batch_size / args.pace
                time.sleep(c)
            elif args.pace:   # emulated consumer: take batches no faster than --pace samples/s
                due = t0 + (step + 1) * args.batch_size / args.pace
                if due > time.perf_counter():
                    c = due - time.perf_counter()
                    time.sleep(c)
            if sf:
                sf.write(f"{e},{step},{tu:.6f},{w:.6f},{c:.6f}\n")
            if args.max_seconds and time.perf_counter() - t0 >= args.max_seconds:
                break
        wall, cpu, rchar = time.perf_counter() - t0, time.process_time() - c0, proc_rchar() - r0
        n = done * args.batch_size
        nbytes = sum(sizes[i] for i in order[:n])
        out.write(f"{e},{n},{nbytes},{wall:.4f},{n / wall:.3f},{nbytes / 1e9 / wall:.4f},{cpu:.3f},{cpu / n:.5f},{rchar},{blocked:.3f}\n")
        out.flush()
        print(f"loader {args.label} epoch {e}: {n} samples in {wall:.2f} s = {n / wall:.2f} samples/s "
              f"({nbytes / 1e9 / wall:.3f} GB/s), cpu {cpu / n * 1e3:.1f} ms/sample, blocked {blocked:.1f} s", flush=True)
        del it
        if args.max_seconds and args.max_seconds_ends_run and wall >= args.max_seconds:
            break                      # the time limit ends the run, not only this epoch
    if pipe.cache_requests is not None:
        pipe.write_cache_requests(out_path(args, "requests", "csv"))
    info["end_unix"] = time.time()
    json.dump(info, open(json_path, "w"), indent=1)


def build_model(args, tf, cfg):
    sys.path.insert(0, args.bench)
    from models import get_model   # the benchmark's model code, unchanged
    model = get_model(**cfg["model"])
    opt = tf.keras.optimizers.SGD(learning_rate=args.lr, momentum=cfg["optimizer"].get("momentum", 0.9))

    @tf.function
    def train_step(x, y):
        with tf.GradientTape() as tape:
            loss = tf.reduce_mean(tf.square(model(x, training=True) - y))
            total = loss + tf.add_n(model.losses) if model.losses else loss
        grads = tape.gradient(total, model.trainable_variables)
        opt.apply_gradients(zip(grads, model.trainable_variables))
        return loss

    @tf.function
    def eval_step(x, y):
        return tf.reduce_mean(tf.square(model(x, training=False) - y))

    return model, train_step, eval_step


def mode_compute(args):
    np, tf, cfg, gpus = setup_tf(args, use_gpu=True)
    steps_path, json_path = out_path(args, "steps", "csv"), out_path(args, "run", "json")
    info = run_info(args, tf=tf.__version__, gpus=[g.name for g in gpus], batch_size=args.batch_size, steps=args.steps)
    shape = cfg["data"]["sample_shape"]
    if args.file_list:   # a real batch: the first batch_size files, parsed by the real pipeline
        files, sizes = read_list(args.file_list)
        args.pipeline, args.seed, args.job = "seq", 0, "compute"
        pipe = Pipeline(args, np, tf, cfg, files[:args.batch_size], sizes[:args.batch_size], "train")
        x, y = next(iter(pipe.dataset(0, np.arange(args.batch_size))))
        info["batch"] = "real"
    else:
        rng = np.random.default_rng(0)
        x = tf.constant(np.log(rng.integers(0, 600, size=[args.batch_size] + shape).astype(np.float32) + 1.0))
        y = tf.constant(rng.uniform(-1, 1, size=[args.batch_size, 4]).astype(np.float32))
        info["batch"] = "synthetic"
    model, train_step, _ = build_model(args, tf, cfg)
    info["parameters"] = int(model.count_params())
    out = open(steps_path, "w")
    out.write("step,compute_s,loss\n")
    times = []
    for step in range(args.steps):
        t0 = time.perf_counter()
        loss = float(train_step(x, y))
        dt = time.perf_counter() - t0
        times.append(dt)
        out.write(f"{step},{dt:.6f},{loss:.6f}\n")
    steady = sorted(times[20:])
    med = steady[len(steady) // 2]
    info.update(step_median_s=med, step_p10_s=steady[int(0.1 * (len(steady) - 1))], step_p90_s=steady[int(0.9 * (len(steady) - 1))],
                samples_per_s=args.batch_size / med, first_step_s=times[0], end_unix=time.time())
    json.dump(info, open(json_path, "w"), indent=1)
    print(f"compute {args.label}: batch {args.batch_size}, median step {med * 1e3:.1f} ms = {args.batch_size / med:.2f} samples/s "
          f"(p10 {info['step_p10_s'] * 1e3:.1f}, p90 {info['step_p90_s'] * 1e3:.1f} ms; first step {times[0]:.1f} s)")


def mode_train(args):
    np, tf, cfg, gpus = setup_tf(args, use_gpu=True)
    files, sizes = read_list(args.file_list)
    steps_path, epochs_path, json_path = out_path(args, "steps", "csv"), out_path(args, "epochs", "csv"), out_path(args, "run", "json")
    trace = open(out_path(args, "reads", "csv"), "w") if args.trace else None
    if trace:
        trace.write("t_unix,job,dataset,epoch,pos,file_id,bytes,name\n")
    info = run_info(args, files=len(files), bytes=sum(sizes), file_list=args.file_list, names_sha1=list_hash(files),
                    tf=tf.__version__, gpus=[g.name for g in gpus], epochs=args.epochs, job=args.job, lr=args.lr,
                    **pipeline_settings(args))
    pipe = Pipeline(args, np, tf, cfg, files, sizes, "train", trace)
    vpipe = None
    if args.valid_list:
        vfiles, vsizes = read_list(args.valid_list)
        vpipe = Pipeline(args, np, tf, cfg, vfiles, vsizes, "valid", trace)
        info.update(valid_files=len(vfiles), valid_bytes=sum(vsizes), valid_order="list order, not shuffled")
    model, train_step, eval_step = build_model(args, tf, cfg)
    steps = len(files) // args.batch_size
    sf = open(steps_path, "w")
    sf.write("epoch,step,t_start_unix,data_wait_s,compute_s,loss\n")
    ef = open(epochs_path, "w")
    ef.write("epoch,samples,bytes,wall_s,samples_per_s,gb_per_s,data_wait_s,compute_s,wait_share,cpu_s,rchar_bytes,"
             "steady_samples_per_s,steady_wait_share,valid_wall_s,loss,cache_hits,cache_misses\n")
    print(f"train {args.label}: {len(files)} files, {sum(sizes) / 1e9:.2f} GB, {steps} steps per epoch at batch {args.batch_size}, "
          f"pipeline {args.pipeline}", flush=True)
    if args.start_unix:   # several jobs on several nodes begin their first epoch at the same wall-clock time
        late = time.time() - args.start_unix
        info["start_late_s"] = max(0.0, late)
        if late < 0:
            time.sleep(-late)
        else:
            print(f"train {args.label}: ready {late:.1f} s after the requested start time", flush=True)
    for e in range(args.epochs):
        order = pipe.order(e)
        c0, r0, te = time.process_time(), proc_rchar(), time.perf_counter()
        k0 = list(pipe.cache_kinds)
        it = iter(pipe.dataset(e, order))
        waits, comps, loss = [], [], float("nan")
        for step in range(steps):
            t_unix, t0 = time.time(), time.perf_counter()
            x, y = next(it)                       # blocks only when no batch is ready
            t1 = time.perf_counter()
            loss = float(train_step(x, y))        # returns when the step has finished on the GPU
            t2 = time.perf_counter()
            waits.append(t1 - t0)
            comps.append(t2 - t1)
            sf.write(f"{e},{step},{t_unix:.6f},{t1 - t0:.6f},{t2 - t1:.6f},{loss:.6f}\n")
        wall, cpu, rchar = time.perf_counter() - te, time.process_time() - c0, proc_rchar() - r0
        del it
        n = steps * args.batch_size
        nbytes = sum(sizes[i] for i in order[:n])
        skip = 20 if steps > 40 else 0            # start-up steps are left out of the steady values
        sw, sc = sum(waits[skip:]), sum(comps[skip:])
        valid_wall = 0.0
        if vpipe:
            tv = time.perf_counter()
            vit = iter(vpipe.dataset(e, vpipe.order(e, shuffle=False)))
            for _ in range(len(vpipe.files) // args.batch_size):
                x, y = next(vit)
                float(eval_step(x, y))
            valid_wall = time.perf_counter() - tv
            del vit
        ef.write(f"{e},{n},{nbytes},{wall:.3f},{n / wall:.3f},{nbytes / 1e9 / wall:.4f},{sum(waits):.3f},{sum(comps):.3f},"
                 f"{sum(waits) / (sum(waits) + sum(comps)):.4f},{cpu:.2f},{rchar},{(steps - skip) * args.batch_size / (sw + sc):.3f},"
                 f"{sw / (sw + sc):.4f},{valid_wall:.2f},{loss:.5f},"
                 f"{pipe.cache_kinds[1] + pipe.cache_kinds[4] - k0[1] - k0[4]},{pipe.cache_kinds[2] + pipe.cache_kinds[3] - k0[2] - k0[3]}\n")
        ef.flush()
        sf.flush()
        if trace:
            trace.flush()
        print(f"train {args.label} epoch {e}: {n} samples in {wall:.1f} s = {n / wall:.2f} samples/s; steady "
              f"{(steps - skip) * args.batch_size / (sw + sc):.2f} samples/s, data wait {100 * sw / (sw + sc):.1f}%, "
              f"cpu {cpu / n * 1e3:.0f} ms/sample, validation {valid_wall:.1f} s", flush=True)
    info["end_unix"] = time.time()
    if pipe.cache is not None:
        info["cache"] = dict(job=args.cache_job, catalog=args.cache_catalog, hits=pipe.cache_kinds[1], hits_waited=pipe.cache_kinds[4],
                             misses_admitted=pipe.cache_kinds[2], misses_bypassed=pipe.cache_kinds[3],
                             accesses_counted_by_server=pipe.cache.end(args.cache_job))
    json.dump(info, open(json_path, "w"), indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["select", "rawread", "stage", "loader", "compute", "train"])
    ap.add_argument("--bench", default=os.environ.get("COSMOFLOW_BENCH", ""), help="CosmoFlow benchmark directory (read-only)")
    ap.add_argument("--file-list")
    ap.add_argument("--out")
    ap.add_argument("--label", default="run")
    ap.add_argument("--pipeline", choices=["seq", "par", "map", "cache"], default="par")
    ap.add_argument("--cache-addr-file", help="cache: file with the cache server's Mercury address")
    ap.add_argument("--cache-catalog", help="cache: the server's catalog (path bytes per line); object identifier = line number")
    ap.add_argument("--cache-job", type=int, default=0, help="cache: numeric job identifier, unique among the server's jobs")
    ap.add_argument("--cache-lib", help="cache: path of libcc_client.so (default: under $CXL_TRAINING_DATA_ROOT/tmp/build/cxlcache)")
    ap.add_argument("--cache-lookahead", type=int, choices=(1, 2), default=1,
                    help="cache: epochs of the file order announced ahead (1: the current epoch at its start; 2: also the next one)")
    ap.add_argument("--read-par", type=int, default=8)
    ap.add_argument("--parse-par", type=int, default=4)
    ap.add_argument("--prefetch", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--order", choices=["seeded", "list"], default="seeded",
                    help="seeded: a new permutation per epoch from --seed; list: the order of the file list in every epoch")
    ap.add_argument("--start-unix", type=float, default=0.0, help="train: wall-clock time at which the first epoch begins")
    ap.add_argument("--lr", type=float, default=0.001)
    ap.add_argument("--steps", type=int, default=300, help="compute: number of steps")
    ap.add_argument("--pace", type=float, default=0.0, help="loader: emulated consumer rate in samples/s (0 = unthrottled)")
    ap.add_argument("--pace-step", action="store_true",
                    help="loader: with --pace, wait batch/pace seconds after every batch, like a training step (time lost waiting for data is not made up)")
    ap.add_argument("--step-log", action="store_true", help="loader: write steps-<label>.csv with the wait of every batch")
    ap.add_argument("--max-seconds", type=float, default=0.0, help="loader: end an epoch after this many seconds")
    ap.add_argument("--max-seconds-ends-run", action="store_true",
                    help="loader: --max-seconds ends the run instead of the epoch (a job with --epochs 2 that announces two "
                         "epochs but is observed for a limited time)")
    ap.add_argument("--cache-request-log", action="store_true",
                    help="loader, pipeline cache: write requests-<label>.csv with the timings of every request to the cache server")
    ap.add_argument("--trace", action="store_true", help="train: log every file pull")
    ap.add_argument("--job", default="job0", help="train: job identity written to the trace")
    ap.add_argument("--valid-list", help="train: files of a validation pass after every epoch, read in list order")
    ap.add_argument("--threads", type=int, default=1, help="rawread: reader threads")
    ap.add_argument("--count", type=int, default=0, help="rawread: use only the first N files")
    ap.add_argument("--to", help="stage: target directory (must not exist)")
    ap.add_argument("--list-out", help="stage: file list to write")
    ap.add_argument("--manifest", help="select: name,bytes file of the directory")
    ap.add_argument("--dir", help="select: directory the names are in")
    ap.add_argument("--exclude-names", nargs="*", help="select: files whose .tfrecord names must not be chosen")
    ap.add_argument("--ledger", help="select: names already used, appended to")
    ap.add_argument("--subsets", nargs="*", help="select: NAME:COUNT ...")
    ap.add_argument("--tag", default="", help="select: note written to the ledger")
    args = ap.parse_args()
    if args.mode in ("loader", "compute", "train") and not args.bench:
        sys.exit("--bench or COSMOFLOW_BENCH is required")
    {"select": mode_select, "rawread": mode_rawread, "stage": mode_stage, "loader": mode_loader,
     "compute": mode_compute, "train": mode_train}[args.mode](args)


if __name__ == "__main__":
    main()
