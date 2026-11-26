"""Inkling/Metal adapters for fixed wide trees. Each suffix ID enters one decode step."""
import contextlib
import ctypes
import hashlib
import json
import os
import random
import subprocess
import time
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
BASE = LAB.parents[1]
BUILD = BASE / ".work/strata-scaling"
STOCK = BUILD / "b3-build/strata-inkling"
PATCHED = BUILD / "lab-build/strata-inkling"
MODEL = BASE.parent / "atomic-turbine/.work/models/Inkling-2-Mini-SQ-10.strata"
RUSAGE = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pid_rusage
CLOCK = time.monotonic_ns


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def memory(pid):
    # Darwin SDK sys/resource.h, struct rusage_info_v4 (uuid occupies two words).
    buf = (ctypes.c_uint64 * 64)()
    if RUSAGE(pid, 4, ctypes.byref(buf)):
        raise OSError("proc_pid_rusage failed")
    return dict(footprint=buf[9], peak_footprint=buf[30], rss=buf[8], pageins=buf[6])


def fixture(p, n, s, seed, shared=True):
    rng = random.Random(seed)
    def ids(length):
        return [rng.randrange(1000, 50000) for _ in range(length)]
    prefixes = [ids(p) for _ in range(1 if shared else n)]
    tails = [ids(s) for _ in range(n)]
    return prefixes, tails


class Wire:
    def __init__(self, proc):
        self.proc = proc

    def send(self, msg):
        self.proc.stdin.write(msg + "\n")
        self.proc.stdin.flush()

    def line(self):
        line = self.proc.stdout.readline()
        if not line:
            raise EOFError(f"engine closed stdout (status={self.proc.poll()})")
        return line.strip()

    def ctrl(self, cmd, tag):
        self.send(cmd)
        words = self.line().split()
        if not words or words[0] != tag:
            raise RuntimeError((cmd, tag, words))
        return words[1:]


@contextlib.contextmanager
def engine(folder, context, stock=False, diag=False):
    cmd = [str(STOCK if stock else PATCHED), "--serve", "--native", str(MODEL),
           "--draft", "off", "--kv", "fp16", "--max-context", str(context),
           "--chunk", "128", "--parallel", "2", "--no-anti-loop"]
    save(folder / "engine.json", dict(command=cmd, lab=not stock, endpoint_logits=diag))
    env = os.environ.copy()
    if not stock:
        env["STRATA_SCALING_LAB"] = "1"
    with (folder / "metal.log").open("x") as err, subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, env=env
    ) as proc:
        wire = Wire(proc)
        try:
            info, ready = wire.line(), wire.line()
            (folder / "startup.txt").write_text(info + "\n" + ready + "\n")
            for flag in ("backend=metal", "drafting=off", "batch_slots=2", "kv_dtype=fp16"):
                if flag not in info.split():
                    raise RuntimeError(info)
            if ready.split()[:2] != ["READY", str(context)]:
                raise RuntimeError(ready)
            if diag:
                wire.ctrl("LABLOGITS", "OK")
            yield wire
        finally:
            if proc.poll() is None:
                try:
                    wire.send("QUIT")
                    proc.wait(timeout=15)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    proc.kill()
            proc.stdin.close()
            proc.stdout.close()


def wave(wire, jobs):
    """Each job is (name, token ids, number of outputs, protocol options)."""
    sent = {name: [] for name, *_ in jobs}
    endpoints = {}
    results = {}
    wire.send("\n".join(f"GENERATE {name} {limit} {opts} " + ",".join(map(str, ids))
                        for name, ids, limit, opts in jobs))
    while len(results) < len(jobs):
        line = wire.line()
        parts = line.split()
        if parts[0] in ("PP", "RESUME"):
            continue
        if parts[0] == "T":
            sent[parts[1]].append(int(parts[2]))
        elif parts[0] == "LOGITS":
            endpoints[parts[1]] = bytes.fromhex(parts[2])
        elif parts[0] == "DONE":
            _, name, count, prompt, pre_ms, dec_ms, reason, _, _, reuse = parts
            if name in results or int(count) != len(sent[name]) or reason not in ("length", "stop"):
                raise ValueError(line)
            results[name] = dict(tokens=sent[name], prompt=int(prompt), reused=int(reuse),
                                 prefill_ms=float(pre_ms), decode_ms=float(dec_ms), reason=reason,
                                 end_ns=CLOCK())
        else:
            raise RuntimeError(line)
    return results, endpoints


def tree(wire, workload, mode, *, native_width=2, teach=True, cache=True):
    roots, tails = workload
    shared = len(roots) == 1
    use_fork = mode == "B4" and shared and len(tails) > 1
    before = memory(wire.proc.pid)
    t0 = CLOCK()
    create = restore = size = root_processed = 0
    if use_fork:
        # Save at P-1, identical to the native prompt-end checkpoint boundary.
        roots_done, _ = wave(wire, [("root", roots[0][:-1], 0, "temperature=0 ckpt=0")])
        root_processed = roots_done["root"]["prompt"] - roots_done["root"]["reused"]
        start = CLOCK()
        count, size = map(int, wire.ctrl("LABSAVE 0", "SAVED"))
        create = CLOCK() - start
        if count != len(roots[0]) - 1:
            raise RuntimeError("snapshot boundary")
    ends, logits = {}, {}
    width = 2 if use_fork else native_width
    for base in range(0, len(tails), width):
        jobs = []
        for slot, tail in enumerate(tails[base:base + width]):
            i = base + slot
            if use_fork and (slot or base):
                start = CLOCK()
                if wire.ctrl(f"LABRESTORE {slot}", "RESTORED") != [str(count)]:
                    raise RuntimeError("restore boundary")
                restore += CLOCK() - start
            opts = f"temperature=0 seed={100+i}"
            # Keep the native checkpoint in any slot which will serve another child.
            if not cache or use_fork or i + width >= len(tails) or not shared:
                opts += " ckpt=0"
            if teach:
                opts += " teacher=" + ",".join(map(str, tail))
            jobs.append((str(i), roots[0 if shared else i], len(tail)+1, opts))
        completed, dist = wave(wire, jobs)
        ends.update(completed)
        logits.update(dist)
    if use_fork:
        wire.ctrl("LABDROP", "DROPPED")
    elapsed = CLOCK() - t0
    for i, tail in enumerate(tails):
        row = ends[str(i)]
        if row["prompt"] != len(roots[0 if shared else i]) or len(row["tokens"]) != len(tail)+1:
            raise ValueError(("unfinished branch", i))
        if teach and row["tokens"][:-1] != tail:
            raise ValueError(("wrong suffix", i))
        row["latency_ns"] = row.pop("end_ns") - t0
    return dict(elapsed_ns=elapsed, create_ns=create, restore_ns=restore, snapshot_bytes=size,
                memory_before=before, memory_after=memory(wire.proc.pid), branches=ends,
                useful_tokens=sum(map(len, tails)), workload_hash=fingerprint(workload),
                prefill_tokens=root_processed + sum(r["prompt"]-r["reused"] for r in ends.values())), logits


def cold(wire):
    for slot in (0, 1):
        wire.ctrl(f"BCO {slot} 1", "BCOK")


def addressed(w, slot, ids, count=3, seed=411, temperature=0):
    w.send(f"BGEN {slot} {count} temperature={temperature} seed={seed} " + ",".join(map(str, ids)))
    tokens = []
    vector = None
    progress = []
    while True:
        parts = w.line().split()
        if parts[0] == "LOGITS":
            vector = bytes.fromhex(parts[-1])
        elif parts[0] in ("T", "BT"):
            tokens.append(int(parts[-1]))
        elif parts[0] in ("DONE", "BADM", "BDONE", "RESUME", "PP"):
            progress.append(parts)
            if parts[0] == "BDONE" or (parts[0] == "BADM" and parts[-1] == "0"):
                if vector is None or len(tokens) != count:
                    raise ValueError(progress)
                return tokens, vector, progress
        else:
            raise RuntimeError(parts)
