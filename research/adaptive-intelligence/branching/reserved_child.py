"""R03: one live parent, one reserved child slot, public checks cannot stop decoding."""

import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tokenizers import Tokenizer

from blind_critic import value
from engine import BIN, TOKENIZER, engine
from grade import run_cases
from live_slots import LiveSlots
from rollback_map import decode, prompt
from stepback_live import CAP, CTX, Delivery, Search

RUNS = Path(__file__).resolve().parents[1] / "runs"
OLD = RUNS / "stepback-live-01"
OUT = RUNS / "stepback-r03"
PLAN = OUT / "protocol.json"


def read(path):
    return json.loads(path.read_text())


def save(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def plan(tasks):
    records = [
        json.loads(line)
        for line in (RUNS / "stepback-r02/branches.jsonl").read_text().splitlines()
    ]
    winners = {
        (r["task"], r["seed"], r["branch"])
        for r in records
        if r["mode"] == "C" and r["selected"]
    }
    chosen = {}
    counts = Counter()
    for row in records:
        task, seed, parent = row["task"], row["seed"], row["parent"]
        level = tasks[task]["level"]
        if (
            row["mode"] != "C"
            or row["kind"] != "child"
            or row["state"] != "started"
            or row["inferred_end"] != "public_pass"
        ):
            continue
        if (task, seed, parent) not in winners or task in chosen or counts[level] >= 2:
            continue
        chosen[task] = dict(
            task=task,
            level=level,
            seed=seed,
            old_parent=parent,
            old_child=row["branch"],
        )
        counts[level] += 1
    assert sorted(counts.values()) == [2, 2, 2]
    return dict(
        selection="First two distinct tasks per difficulty in R02 schedule order; mode C child cancelled upon public success of its own parent.",
        model="Inkling-2-Mini SQ-10",
        binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(),
        context=CTX,
        seed_rule="reuse both archived seeds; regenerate live parent from original task",
        termination="EOS or context limit for both; no fallback, timer, pruning, or early exit on checks",
        tasks=list(chosen.values()),
    )


def check_program(code, public, start):
    passed = run_cases(code, public)
    return dict(passed=passed, completed_s=time.monotonic() - start)


class ReservedPair(Search):
    def __init__(self, live, tok, task, spec, pool):
        # The marker and snapshot primitives use the same request-relative clock as R01.
        start = time.monotonic()
        super().__init__(
            "C",
            live,
            tok,
            task,
            spec["seed"] + int(spec["old_parent"]),
            Delivery(start, 30, task["public"]),
        )
        self.pool = pool
        self.checks = {}

    def finish(self, row):
        b = self.branches[row[1]]
        if row[-1] not in ("stop", "length"):
            raise RuntimeError(row)
        b.stopped, b.reason = self.elapsed(), row[-1]
        del self.active[b.name]
        b.code = value("Step 1:" + decode(self.tok, b.tokens), "code")
        self.checks[b.name] = self.pool.submit(
            check_program, b.code, self.task["public"], self.delivery.start
        )

    def run(self):
        ids = prompt(self.tok, self.task)
        self.base_len = len(ids)
        assert self.base_len < CTX - 1
        self.slots = 2
        self.ready.append(("0", None, 0.0))
        while self.ready or self.active:
            self.start_ready(ids)
            if "2" in self.branches and self.branches["2"].slot != 1:
                raise RuntimeError("child did not enter the reserved slot")
            if not self.active:
                break
            for row in self.live.tick():
                if row[0] == "T":
                    b = self.branches[row[1]]
                    b.tokens.append(int(row[2]))
                    self.inspect_root(b)
                elif row[0] == "DONE":
                    self.finish(row)
                elif row[0] not in ("PREFILL", "PP", "RESUME"):
                    raise RuntimeError(row)
            self.ticks += 1
            if self.ticks % 32 == 1:
                self.check_memory()
        for key in list(self.held):
            self.release(self.branches[key])
        self.check_memory()


def main():
    OUT.mkdir(exist_ok=True)
    tasks = {t["id"]: t for t in read(OLD / "tasks.json")}
    protocol = plan(tasks)
    if PLAN.exists() and protocol != read(PLAN):
        raise RuntimeError("R03 inputs changed")
    save(PLAN, protocol)
    remaining = [
        s for s in protocol["tasks"] if not (OUT / s["task"] / "result.json").exists()
    ]
    if not remaining:
        return
    tok = Tokenizer.from_file(str(TOKENIZER))
    with (
        engine(OUT / f"metal-{time.time_ns()}.log", slots=2) as session,
        ThreadPoolExecutor(2) as pool,
    ):
        live = LiveSlots(session)
        for spec in remaining:
            task = tasks[spec["task"]]
            old = read(OLD / "jobs" / f"{task['id']}-{spec['seed']}-C.json")
            archived = {b["name"]: b for b in old["branches"]}
            folder = OUT / task["id"]
            folder.mkdir(exist_ok=True)
            pair = ReservedPair(live, tok, task, spec, pool)
            pair.run()
            out = {}
            for name, b in pair.branches.items():
                label = "parent" if b.parent is None else "child"
                prior = archived[spec["old_" + label]]
                if b.seed != prior["seed"]:
                    raise RuntimeError("inconsistent seed")
                if b.code:
                    (folder / f"{label}.py").write_text(b.code + "\n")
                check = pair.checks[name].result()
                out[label] = dict(
                    slot=b.slot,
                    seed=b.seed,
                    reason=b.reason,
                    ready_s=b.ready,
                    started_s=b.started,
                    stopped_s=b.stopped,
                    point=b.point,
                    suffix_start=b.suffix_start,
                    token_ids=b.tokens,
                    generated_tokens=len(b.tokens) - b.suffix_start,
                    has_code=bool(b.code),
                    public=check,
                    matches_old_recorded_tokens=b.tokens[: len(prior["tokens"])]
                    == prior["tokens"],
                )
            root = pair.branches["0"]
            oldroot = archived[spec["old_parent"]]
            same_boundary = (
                root.confirmed
                and root.point == oldroot["point"]
                and root.tokens[: root.point] == oldroot["tokens"][: oldroot["point"]]
            )
            result = dict(
                task=task["id"],
                branches=out,
                old_fork_prefix_identical=same_boundary,
                peak_snapshot_bytes=pair.max_payload,
                peak_engine_footprint=pair.max_footprint,
            )
            save(folder / "result.json", result)
            print(
                task["id"],
                [
                    (
                        k,
                        b["reason"],
                        sum(b["public"]["passed"]),
                        len(b["public"]["passed"]),
                        round(b["stopped_s"], 1),
                    )
                    for k, b in out.items()
                ],
                flush=True,
            )


if __name__ == "__main__":
    main()
