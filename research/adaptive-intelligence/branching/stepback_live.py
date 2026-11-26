"""Timed, warm-engine code search. The delivery thread never waits for a GPU tick or a test."""

import ctypes
import hashlib
import queue
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from blind_critic import value
from grade import run_cases
from live_slots import Branch
from rollback_map import decode, prompt

LIMIT = 30.0
CAP = 20 * 2**30
CTX = 4096
MARKS = ("Final:", "```python", "```\n")
clock = time.monotonic


def marker(piece, before, pending):
    """Match a line-initial marker, retaining the token boundary before its first piece."""
    if pending:
        part = pending + piece
    else:
        # A single token can include either end of a newline-delimited marker.
        part = piece.lstrip(" \t\r\n")
        if not part or (
            before.rsplit("\n", 1)[-1].strip()
            and not piece.lstrip(" \t").startswith("\n")
        ):
            return "", False
    if any(part.startswith(m) for m in MARKS):
        return part, True
    return (
        (part, False)
        if part and any(m.startswith(part) for m in MARKS)
        else ("", False)
    )


def peak_footprint(pid):
    buf = (ctypes.c_uint64 * 64)()
    rc = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pid_rusage(
        pid, 4, ctypes.byref(buf)
    )
    if rc:
        raise RuntimeError("cannot measure process footprint")
    return buf[30]


class Delivery:
    def __init__(self, start, seconds, public):
        self.start = start
        self.deadline = start + seconds
        self.public = public
        self.results = {}
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.measured = []

    def submit(self, pool, code):
        if not code or code in self.results:
            return
        self.results[code] = True
        pool.submit(self._check, code)

    def _check(self, code):
        begin = clock()
        try:
            passed = sum(run_cases(code, self.public))
            self.events.put(("checked", (clock(), code, passed, begin)))
        except Exception as exc:
            self.events.put(("error", exc))

    def select(self):
        best = None
        pending = None
        # Reserve time to publish the chosen response and signal cancellation. All modes use it.
        cutoff = self.deadline - 0.020
        while clock() < cutoff:
            try:
                kind, item = self.events.get(timeout=max(0, cutoff - clock()))
            except queue.Empty:
                break
            if kind == "error":
                raise item
            if kind == "complete":
                pending = item
            else:
                end, code, passed, begin = item
                if end <= cutoff:
                    self.measured.append(
                        dict(
                            code_sha=hashlib.sha256(code.encode()).hexdigest(),
                            completed_ms=(end - self.start) * 1000,
                            elapsed_ms=(end - begin) * 1000,
                            passed=passed,
                        )
                    )
                    if best is None or (passed, -end) > (best[0], -best[1]):
                        best = (passed, end, code)
                if best and best[0] == len(self.public):
                    break
            if pending is not None and len(self.measured) >= pending:
                break
        delivered = clock()
        self.stop.set()
        return dict(
            code=best[2] if best and delivered <= self.deadline else None,
            delivered_ms=(delivered - self.start) * 1000,
            deadline_missed=delivered > self.deadline,
        )


class Search:
    def __init__(self, mode, live, tok, task, seed, delivery):
        self.mode, self.live, self.tok = mode, live, tok
        self.task, self.seed, self.delivery = task, seed, delivery
        self.branches, self.active = {}, {}
        self.ready = deque()
        self.held = set()
        self.max_payload = self.opportunities = self.pruned = self.divergent_ticks = 0
        self.paired_decode_ticks = 0
        self.max_footprint = 0
        self.ticks = 0
        self.errors = []
        self.seen_pairs = set()

    def elapsed(self):
        return clock() - self.delivery.start

    def release(self, b):
        if b.name in self.held:
            self.live.drop(b.name)
            self.held.remove(b.name)

    def start_ready(self, ids):
        while (
            self.ready
            and len(self.active) < self.slots
            and not self.delivery.stop.is_set()
        ):
            name, parent, ready = self.ready.popleft()
            slot = next(i for i in range(self.slots) if i not in self.active.values())
            b = Branch(name, slot, self.seed + int(name), parent, ready, self.elapsed())
            self.branches[name] = b
            self.active[name] = slot
            if parent is None:
                self.live.fresh(name, ids, b.seed, CTX - len(ids), free_slot=slot)
            else:
                root = self.branches[parent]
                b.tokens = root.tokens[: root.point]
                b.suffix_start = len(b.tokens)
                first = self.live.fork(parent, name, slot, b.seed)
                b.tokens.append(first)
                self.release(root)
                # EOS from the first resampled token can finish the child before the next tick.
                self.live.s.send("ALLOC")
                line = self.live.s.line().split()
                if line[0] == "DONE":
                    self.finish(line)
                    line = self.live.s.line().split()
                if line[0] != "ALLOC":
                    raise RuntimeError(f"unconsumed fork event {line}")

    def inspect_root(self, b):
        if b.confirmed or b.name not in ("0", "1") or self.mode not in ("C", "D"):
            return
        piece = self.tok.decode([b.tokens[-1]], skip_special_tokens=False)
        # Only decode the prefix when this token might begin a marker.
        if not b.marker and not piece.lstrip().startswith(("F", "`")):
            return
        before = decode(self.tok, b.tokens[:-1]) if not b.marker else ""
        candidate, complete = marker(piece, before, b.marker)
        if b.marker and not candidate:
            self.release(b)
            b.marker = ""
            b.point = None
            # A mismatching token may itself start the next line's marker.
            self.inspect_root(b)
            return
        if not candidate:
            return
        if not b.marker:
            n, payload, pending = self.live.snapshot(b.name)
            if n != self.base_len + len(b.tokens) - 1 or pending != b.tokens[-1]:
                raise RuntimeError("checkpoint token boundary mismatch")
            b.point, b.payload = len(b.tokens) - 1, payload
            self.held.add(b.name)
            self.max_payload = max(
                self.max_payload, sum(self.branches[k].payload for k in self.held)
            )
            if self.max_payload + self.live.allocated > CAP:
                raise MemoryError("Metal allocation plus snapshot ceiling exceeded")
        b.marker = candidate
        if complete:
            b.confirmed = True
            self.ready.append((str(int(b.name) + 2), b.name, self.elapsed()))

    def finish(self, row):
        _, name = row[:2]
        b = self.branches[name]
        b.stopped, b.reason = self.elapsed(), row[-1]
        b.decode_ms = float(row[5])
        del self.active[name]
        if b.reason == "nonfinite":
            raise RuntimeError("non-finite model output")
        if b.reason in ("stop", "length") and not self.delivery.stop.is_set():
            b.code = value("Step 1:" + decode(self.tok, b.tokens), "code")
            self.delivery.submit(self.pool, b.code)
            if self.mode in ("C", "D") and name in ("0", "1") and not b.confirmed:
                self.release(b)
                self.ready.append((str(int(name) + 2), None, self.elapsed()))

    def observe_pair(self, stepped):
        if len(stepped) == 2:
            self.paired_decode_ticks += 1
        for name, slot in list(self.active.items()):
            child = self.branches[name]
            if child.parent not in self.active:
                continue
            root = self.branches[child.parent]
            left = root.tokens[root.point :]
            right = child.tokens[child.suffix_start :]
            common = min(len(left), len(right))
            if (
                name in stepped
                and root.name in stepped
                and left[:common] != right[:common]
            ):
                self.divergent_ticks += 1
            if (
                self.ready
                and common >= 32
                and left[:common] == right[:common]
                and name not in self.seen_pairs
            ):
                self.opportunities += 1
                self.seen_pairs.add(name)
                if self.mode == "D":
                    self.finish(self.live.cancel(name))
                    self.pruned += 1

    def generate(self, pool):
        self.pool = pool
        try:
            ids = prompt(self.tok, self.task)
            self.base_len = len(ids)
            if self.base_len >= CTX - 1:
                raise ValueError("input exceeds context limit")
            self.slots = 1 if self.mode == "A" else 2
            count = {"A": 1, "B": 4, "C": 2, "D": 2}[self.mode]
            self.ready.extend((str(i), None, 0.0) for i in range(count))
            while not self.delivery.stop.is_set() and (self.active or self.ready):
                self.start_ready(ids)
                if not self.active or self.delivery.stop.is_set():
                    break
                events = self.live.tick()
                stepped = set()
                for row in events:
                    if row[0] == "T":
                        b = self.branches[row[1]]
                        if b.tokens:
                            stepped.add(b.name)
                        b.tokens.append(int(row[2]))
                        self.inspect_root(b)
                    elif row[0] == "DONE":
                        self.finish(row)
                    elif row[0] == "PREFILL":
                        b = self.branches[row[1]]
                        b.prompt_tokens += int(row[2])
                        b.prefill_ms += float(row[3])
                    elif row[0] not in ("PP", "RESUME"):
                        raise RuntimeError(f"unexpected tick event {row}")
                self.observe_pair(stepped)
                self.ticks += 1
                if self.ticks % 32 == 1:
                    self.check_memory()
            self.delivery.events.put(("complete", len(self.delivery.results)))
        except BaseException as exc:
            self.errors.append(exc)
            self.delivery.events.put(("error", exc))
        finally:
            try:
                for name in list(self.active):
                    self.finish(self.live.cancel(name))
                for name in list(self.held):
                    self.release(self.branches[name])
                self.check_memory()
            except BaseException as exc:
                self.errors.append(exc)
                self.delivery.events.put(("error", exc))

    def check_memory(self):
        self.max_footprint = max(
            self.max_footprint, peak_footprint(self.live.s.proc.pid)
        )
        if self.max_footprint > CAP:
            raise MemoryError("process footprint ceiling exceeded")


def run_task(live, tok, task, mode, seed, emit):
    delivery = Delivery(clock(), LIMIT, task["public"])
    search = Search(mode, live, tok, task, seed, delivery)
    with ThreadPoolExecutor(2) as pool:
        runner = threading.Thread(target=search.generate, args=(pool,))
        runner.start()
        try:
            selected = delivery.select()
            # Publish to the benchmark client before waiting for GPU/worker cleanup.
            emit(dict(task=task["id"], mode=mode, seed=seed, **selected))
            selected["published_ms"] = (clock() - delivery.start) * 1000
            if selected["published_ms"] > LIMIT * 1000:
                selected["code"] = None
                selected["deadline_missed"] = True
        finally:
            delivery.stop.set()
            runner.join()
    if search.errors:
        raise search.errors[0]
    # A failed sandbox invocation is infrastructure failure even if another candidate won first.
    while not delivery.events.empty():
        kind, item = delivery.events.get_nowait()
        if kind == "error":
            raise item
    branches = [asdict(b) for b in search.branches.values()]
    selected["branch"] = next(
        (
            b["name"]
            for b in branches
            if selected["code"] and b["code"] == selected["code"]
        ),
        None,
    )
    return dict(
        task=task["id"],
        seed=seed,
        mode=mode,
        selected=selected,
        public_checks=delivery.measured,
        branches=branches,
        gpu_ticks=search.ticks,
        two_slot_decode_ticks=search.paired_decode_ticks,
        divergent_sibling_ticks=search.divergent_ticks,
        prune_opportunities=search.opportunities,
        pruned=search.pruned,
        peak_footprint=search.max_footprint,
        metal_bytes=live.allocated,
        peak_snapshot_bytes=search.max_payload,
    )
