"""Calibrate on old tasks, seal a balanced schedule, run a resumable pilot, then unblind."""

import argparse
import hashlib
import fcntl
import itertools
import json
import os
from pathlib import Path
import random
import statistics
import threading
import time

import numpy as np
from tokenizers import Tokenizer
from blind_critic import DATA
from engine import BIN, MODEL, TOKENIZER, engine, record
from grade import run_cases
from live_slots import LiveSlots
from stepback_data import RUNS, SEEDS
from stepback_live import Delivery, run_task

HERE = Path(__file__).resolve().parent
MODES = "ABCD"
CALIBRATION = ["abc374_b", "abc374_c", "abc374_f"]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text())


def save(path, data):
    # A finished job is an atomic file. A crash before replace leaves the job eligible for retry.
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def deadline_gate():
    public = [{}]
    for label, offset, expected in [
        ("timely", 0.010, "program"),
        ("late", 0.140, None),
        ("none", None, None),
    ]:
        start = time.monotonic()
        d = Delivery(start, 0.100, public)
        if offset is not None:

            def completed(d=d, start=start):
                d.events.put(("checked", (time.monotonic(), "program", 1, start)))

            threading.Timer(offset, completed).start()
        result = d.select()
        if result["code"] != expected or result["deadline_missed"]:
            raise RuntimeError(f"deadline gate failed: {label}")
    return ["timely", "late", "none"]


def hashes():
    scripts = [
        "live_slots.py",
        "stepback_live.py",
        "live_trial.py",
        "stepback_data.py",
        "live_gate.py",
        "rollback_map.py",
        "blind_critic.py",
        "grade.py",
        "engine.py",
        "prepare.py",
    ]
    return {s: sha(HERE / s) for s in scripts}


def public_tasks(out, calibration):
    path = RUNS / "code-critics-01/tasks.json" if calibration else out / "tasks.json"
    return {t["id"]: t for t in load(path)}


def run(out, jobs, calibration=False):
    sub = out / ("calibration" if calibration else "jobs")
    sub.mkdir(exist_ok=True)
    tasks = public_tasks(out, calibration)
    tok = Tokenizer.from_file(str(TOKENIZER))
    pending = [
        (k, s, m) for k, s, m in jobs if not (sub / f"{k}-{s}-{m}.json").is_file()
    ]
    if not pending:
        return
    log = sub / f"engine-{time.time_ns()}.log"
    with (
        engine(log, slots=2) as session,
        (sub / "deliveries.jsonl").open("a") as responses,
    ):
        live = LiveSlots(session)
        # Warm kernels and both slots outside request timing; fresh() clears slot state per admission.
        for slot in range(2):
            live.fresh(f"warm{slot}", [100, 200, 300], 41, 2, 0, free_slot=slot)
        finished = set()
        while len(finished) < 2:
            finished.update(r[1] for r in live.tick() if r[0] == "DONE")
        for k, s, m in pending:
            print("starting", k, s, m, flush=True)
            row = run_task(
                live, tok, tasks[k], m, s, lambda data: record(responses, **data)
            )
            save(sub / f"{k}-{s}-{m}.json", row)
            print(
                "delivered",
                k,
                s,
                m,
                round(row["selected"]["published_ms"]),
                row["selected"]["branch"],
                flush=True,
            )


def files_for_gate(out):
    data = load(out / "protocol.json")
    if sha(out / "tasks.json") != data["tasks_sha256"]:
        raise RuntimeError("public task list changed")
    gate = load(RUNS / "live-fork-gate-01/gate.json")
    if gate["binary_sha256"] != sha(BIN) or len(gate["matched"]) != 2:
        raise RuntimeError("missing numerical gate for current engine")
    return data


def calibrate(out):
    files_for_gate(out)
    gatefile = out / "deadline-gate.json"
    if not gatefile.exists():
        save(gatefile, deadline_gate())
    jobs = [
        (k, 3001, m)
        for i, k in enumerate(CALIBRATION)
        for m in ("AB" if i % 2 == 0 else "BA")
    ]
    run(out, jobs, True)
    # Old calibration IDs and their existing closed labels only.
    from diverse_plans import source_rows
    from prepare import tests

    labels = {
        r["question_id"]: tests(r["private_test_cases"])
        for r in source_rows(DATA / "code5-review-records.jsonl")
        if r["question_id"] in CALIBRATION
    }
    results = {m: [] for m in "AB"}
    for k, s, m in jobs:
        chosen = load(out / "calibration" / f"{k}-{s}-{m}.json")["selected"]
        correct = bool(chosen["code"]) and all(run_cases(chosen["code"], labels[k]))
        results[m].append(dict(task=k, correct=correct, ms=chosen["published_ms"]))

    def rank(m):
        return (
            -sum(r["correct"] for r in results[m]),
            statistics.median(r["ms"] for r in results[m]),
            m,
        )

    tasks = list(public_tasks(out, False))
    schedule = []
    perms = list(itertools.permutations(MODES))
    for i, seed in enumerate(SEEDS):
        order = tasks.copy()
        random.Random(seed).shuffle(order)
        for j, k in enumerate(order):
            # All 24 permutations occur in each seed block.
            schedule.extend((k, seed, m) for m in perms[(j + i * 7) % 24])
    lock = dict(
        control=min("AB", key=rank),
        calibration=results,
        schedule=schedule,
        protocol=sha(out / "protocol.json"),
        scripts=hashes(),
        engine=sha(BIN),
        tokenizer=sha(TOKENIZER),
        model=MODEL.name,
        model_sha256=sha(MODEL),
        hidden_sha256=sha(DATA / (out.name + "-private.json")),
        deadline_gate=sha(gatefile),
        state_gate=sha(RUNS / "live-fork-gate-01/gate.json"),
    )
    if (out / "lock.json").exists() and load(out / "lock.json") != json.loads(
        json.dumps(lock)
    ):
        raise RuntimeError("refusing to replace a frozen protocol")
    save(out / "lock.json", lock)


def frozen(out):
    files_for_gate(out)
    lock = load(out / "lock.json")
    if (
        lock["protocol"] != sha(out / "protocol.json")
        or lock["scripts"] != hashes()
        or lock["engine"] != sha(BIN)
        or lock["model_sha256"] != sha(MODEL)
        or lock["tokenizer"] != sha(TOKENIZER)
    ):
        raise RuntimeError("frozen pilot inputs changed")
    return lock


def grade(out):
    lock = frozen(out)
    rows = []
    for k, s, m in lock["schedule"]:
        row = load(out / "jobs" / f"{k}-{s}-{m}.json")
        assert (row["task"], row["seed"], row["mode"]) == (k, s, m)
        rows.append(row)
    path = DATA / (out.name + "-private.json")
    if sha(path) != lock["hidden_sha256"]:
        raise RuntimeError("hidden fixtures changed")
    refs = load(path)
    cache_dir = out / "hidden-cache"
    cache_dir.mkdir(exist_ok=True)

    def correct(k, code):
        if not code:
            return False
        key = hashlib.sha256((k + "\0" + code).encode()).hexdigest()
        cache = cache_dir / (key + ".json")
        if not cache.exists():
            cases = refs[k]
            ok = all(run_cases(code, cases[:3])) and (
                len(cases) <= 3 or all(run_cases(code, cases[3:]))
            )
            save(cache, ok)
        return load(cache)

    scores = []
    for r in rows:
        k = r["task"]
        sel = r["selected"]
        right = correct(k, sel["code"])
        candidates = {
            b["code"]
            for b in r["branches"]
            if b["code"] and b["stopped"] * 1000 <= min(30000, sel["published_ms"])
        }
        scores.append(
            dict(
                task=k,
                seed=r["seed"],
                mode=r["mode"],
                correct=right,
                oracle=right or any(correct(k, c) for c in sorted(candidates)),
                ms=sel["published_ms"],
                divergent=r["divergent_sibling_ticks"] > 0,
                opportunities=r["prune_opportunities"],
                pruned=r["pruned"],
                memory=r["metal_bytes"] + r["peak_snapshot_bytes"],
                footprint=r["peak_footprint"],
                missed=sel["deadline_missed"],
                forwarded=sum(
                    b["prompt_tokens"]
                    + max(0, len(b["tokens"]) - b["suffix_start"] - 1)
                    for b in r["branches"]
                ),
            )
        )
    save(out / "scores.json", scores)
    tasks = sorted(refs)
    idx = {(r["task"], r["seed"], r["mode"]): r for r in scores}
    totals = {}
    for m in MODES:
        rr = [r for r in scores if r["mode"] == m]
        totals[m] = {
            key: sum(r[key] for r in rr)
            for key in (
                "correct",
                "oracle",
                "divergent",
                "opportunities",
                "pruned",
                "missed",
                "forwarded",
            )
        }
        totals[m].update(
            p50_ms=float(np.median([r["ms"] for r in rr])),
            p95_ms=float(np.percentile([r["ms"] for r in rr], 95)),
            peak_alloc=max(r["memory"] for r in rr),
            peak_footprint=max(r["footprint"] for r in rr),
        )
    pairs = {}
    for m, n in (
        ("D", lock["control"]),
        ("C", "B"),
        ("D", "C"),
        ("D", "A"),
        ("D", "B"),
    ):
        outcomes = {
            k: [
                int(idx[k, s, m]["correct"]) - int(idx[k, s, n]["correct"])
                for s in SEEDS
            ]
            for k in tasks
        }
        deltas = np.array([np.mean(v) for v in outcomes.values()])
        dist = (
            np.random.default_rng(91371)
            .choice(deltas, (20000, len(tasks)))
            .mean(axis=1)
            * 100
        )
        pairs[m + "-" + n] = dict(
            pp=float(100 * deltas.mean()),
            ci=np.percentile(dist, [2.5, 97.5]).tolist(),
            wins=sum(a.count(1) for a in outcomes.values()),
            losses=sum(a.count(-1) for a in outcomes.values()),
            by_task=outcomes,
        )
    primary = pairs["D-" + lock["control"]]
    save(
        out / "summary.json",
        dict(
            n=len(scores),
            control=lock["control"],
            totals=totals,
            pairs=pairs,
            confirm=primary["pp"] >= 5 and primary["ci"][0] > 0,
        ),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["calibrate", "pilot", "grade"])
    p.add_argument("out", type=Path)
    a = p.parse_args()
    with (a.out / ".writer").open("a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if a.stage == "calibrate":
            calibrate(a.out)
        elif a.stage == "pilot":
            run(a.out, frozen(a.out)["schedule"])
        else:
            grade(a.out)
