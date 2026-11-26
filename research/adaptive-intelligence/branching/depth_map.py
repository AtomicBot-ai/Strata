"""R04 matched child rollouts at three exact token boundaries of archived R03 parents."""

import hashlib
import json
import sys
import time
from pathlib import Path

from tokenizers import Tokenizer
from blind_critic import value
from depth_cases import cases
from engine import BIN, MODEL, TOKENIZER, engine
from grade import run_cases
from live_slots import LiveSlots
from reserved_child import OLD, RUNS, read, save
from rollback_map import prompt, decode, boundaries
from stepback_live import CTX, CAP, peak_footprint

OUT = RUNS / "stepback-r04"
PREV = RUNS / "stepback-r03"
STAGES = ("approach", "middle", "code")
SEEDS = (4201, 4217, 4243)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare():
    tok = Tokenizer.from_file(str(TOKENIZER))
    tasks = {t["id"]: t for t in read(OLD / "tasks.json")}
    out = dict(
        seeds=SEEDS,
        context=CTX,
        binary=digest(BIN.read_bytes()),
        tokenizer=digest(TOKENIZER.read_bytes()),
        model=MODEL.name,
        points="start after Step 1:; after Step 2: before its content; immediately before R03 Final: marker",
        stop="EOS or context limit, no public early exit",
        tasks=[],
    )
    for i, spec in enumerate(read(PREV / "protocol.json")["tasks"]):
        k = spec["task"]
        src = PREV / k / "result.json"
        root = read(src)["branches"]["parent"]
        offsets = dict(
            approach=0,
            middle=boundaries(tok, root["token_ids"])["step2"],
            code=root["point"],
        )
        assert 0 < offsets["middle"] < offsets["code"] and decode(
            tok, root["token_ids"][offsets["code"] :]
        ).startswith("Final:")
        probes = cases(k)
        out["tasks"].append(
            dict(
                id=k,
                source_sha=digest(src.read_bytes()),
                offsets=offsets,
                checks_sha=digest(json.dumps(probes, sort_keys=True).encode()),
                public=tasks[k]["public"],
            )
        )
    return tok, tasks, out


def sample(live, ids, seed):
    # Recreate the archived prefix in slot 0, then sample from its distribution in slot 1.
    start = time.monotonic()
    live.fresh("root", ids, seed, 1)
    done = False
    while not done:
        done = any(r[0] == "DONE" for r in live.tick())
    processed, size, _ = live.snapshot("root")
    if processed != len(ids) or live.allocated + size > CAP:
        raise RuntimeError("snapshot boundary or allocation")
    begin = time.monotonic()
    output = [live.fork("root", "child", 1, seed)]
    live.s.send("ALLOC")
    line = live.s.line().split()
    reason = None
    if line[0] == "DONE":
        reason = line[-1]
        line = live.s.line().split()
    if line[0] != "ALLOC":
        raise RuntimeError(line)
    live.drop("root")
    while reason is None:
        for r in live.tick():
            if r[0] == "T" and r[1] == "child":
                output.append(int(r[2]))
            elif r[0] == "DONE" and r[1] == "child":
                reason = r[-1]
            else:
                raise RuntimeError(r)
    end = time.monotonic()
    if reason not in ("stop", "length") or peak_footprint(live.s.proc.pid) > CAP:
        raise RuntimeError("termination or memory limit")
    return output, dict(reason=reason, prepare_s=begin - start, child_s=end - begin)


def generate(tok, tasks, protocol):
    schedule = []
    for i, t in enumerate(protocol["tasks"]):
        for j, seed in enumerate(SEEDS):
            for z in range(3):
                stage = STAGES[(i + j + z) % 3]
                folder = OUT / t["id"] / str(seed) / stage
                if not (folder / "generation.json").exists():
                    schedule.append((t, seed, stage, folder))
    if not schedule:
        return
    with engine(OUT / f"metal-{time.time_ns()}.log", slots=2) as session:
        live = LiveSlots(session)
        for task, seed, stage, folder in schedule:
            k = task["id"]
            root = read(PREV / k / "result.json")["branches"]["parent"]["token_ids"]
            offset = task["offsets"][stage]
            suffix, stats = sample(live, prompt(tok, tasks[k]) + root[:offset], seed)
            text = decode(tok, root[:offset] + suffix)
            code = value("Step 1:" + text, "code")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "response.txt").write_text("Step 1:" + text)
            if code:
                (folder / "candidate.py").write_text(code + "\n")
            save(
                folder / "generation.json",
                dict(
                    **stats,
                    task=k,
                    seed=seed,
                    stage=stage,
                    offset=offset,
                    tokens=suffix,
                    code_sha=digest(code.encode()) if code else None,
                ),
            )
            print(k, seed, stage, len(suffix), stats["reason"], flush=True)


def grade(tasks, protocol):
    # All branches finish before evaluation; fixtures and outputs never feed generation.
    paths = sorted(OUT.glob("*/*/*/generation.json"))
    if len(paths) != len(protocol["tasks"]) * len(STAGES) * len(SEEDS):
        raise RuntimeError("incomplete generations")
    for task in protocol["tasks"]:
        k = task["id"]
        paths_for_task = [p.parent for p in paths if p.parents[2].name == k]
        memo = {}
        for folder in [PREV / k, *paths_for_task]:
            parent = folder == PREV / k
            out = OUT / k / "parent-checks.json" if parent else folder / "checks.json"
            cp = folder / ("parent.py" if parent else "candidate.py")
            code = cp.read_text().strip() if cp.exists() else None
            if out.exists():
                memo[code] = read(out)
                continue
            if code not in memo:
                pub = tasks[k]["public"]
                probes = cases(k)
                scores = run_cases(code, pub + probes)
                memo[code] = dict(
                    public=scores[: len(pub)],
                    diagnostic={
                        c["label"]: v for c, v in zip(probes, scores[len(pub) :])
                    },
                )
            save(out, memo[code])
        print("checked", k, flush=True)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    tok, tasks, spec = prepare()
    spec = json.loads(json.dumps(spec))
    protocol_file = OUT / "protocol.json"
    if protocol_file.exists() and read(protocol_file) != spec:
        raise RuntimeError("frozen R04 inputs changed")
    if not protocol_file.exists():
        save(protocol_file, spec)
    if sys.argv[1] == "generate":
        generate(tok, tasks, spec)
    elif sys.argv[1] == "grade":
        grade(tasks, spec)
    else:
        raise ValueError("use generate or grade")
