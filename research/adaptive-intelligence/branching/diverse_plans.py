"""Three paired three-attempt policies; the author sees only its own plan."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from tokenizers import Tokenizer
from blind_critic import DATA, TOKENIZER, one, sha, value
from engine import BIN, MODEL, engine, record
from grade import final_text, run_cases
from prepare import CODE_REV, tests
from rollback_map import decode, load, read_rows, write

PLAN_SEEDS = (2111, 2113, 2129)
CODE_SEEDS = (2203, 2207, 2213)
MODES = ("direct", "independent_plans", "diverse_plans")
PLAN_CAP = 80
EXTRA = 1024
FENCE = "```python\n"


def source_rows(path):
    with path.open("rb") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # incomplete records at range boundaries
            yield row


def prepare(out):
    excluded = {t["id"] for t in load(DATA / "public.json")}
    for name in ("code-critics-01", "evidence-critic-01", "blind-critic-01", "rollback-map-01"):
        excluded.update(t["id"] for t in load(out.parent / name / "tasks.json"))
    fresh = sorted(DATA.glob("diverse-*.jsonl"))
    old = [*sorted(DATA.glob("code6-*.jsonl")), DATA / "code5-review-records.jsonl"]
    pools = []
    source_index = {}
    for files in (fresh, old):
        pool = {}
        for path in files:
            for r in source_rows(path):
                k = r["question_id"]
                if k in excluded or r["platform"] != "atcoder" or r["starter_code"]:
                    continue
                public = json.loads(r["public_test_cases"])
                if not public or not all(t["testtype"] == "stdin" for t in public):
                    continue
                pool[k] = dict(
                    id=k,
                    level=r["difficulty"],
                    title=r["question_title"],
                    question=r["question_content"],
                    public=public,
                )
                source_index[k] = path.name
        pools.append(pool)
        excluded.update(pool)
    supplemental = sorted(
        pools[1], key=lambda k: hashlib.sha256(("diverse-plan-v1/" + k).encode()).digest()
    )[:2]
    tasks = [pools[0][k] for k in sorted(pools[0])] + [pools[1][k] for k in supplemental]
    assert len(tasks) == 8
    out.mkdir(exist_ok=False)
    write(out / "tasks.json", tasks)
    sources = {t["id"]: source_index[t["id"]] for t in tasks}
    write(
        out / "protocol.json",
        dict(
            author=MODEL.name,
            binary_sha256=sha(BIN),
            tokenizer_sha256=sha(TOKENIZER),
            revision=CODE_REV,
            sources=sources,
            source_hashes={name: sha(DATA / name) for name in set(sources.values())},
            tasks_sha256=sha(out / "tasks.json"),
            driver_sha256=sha(Path(__file__)),
            methods=MODES,
            seeds=dict(plans=PLAN_SEEDS, code=CODE_SEEDS),
            plan_cap=PLAN_CAP,
            budget_extra=EXTRA,
            budget="Each branch may process twice the number of tokens in its ordinary input plus 1024. Includes prompts, plan generation and replay. No pooling after EOS. Same per-task cap for each trio.",
            endpoint="At least one program passes all hidden cases. Net newly covered minus newly lost tasks. No selector or test feedback. Inspect implemented algorithm families separately.",
            sampling="Temperature 1, top_k 32, top_p .95, clean Strata slot on each call.",
        ),
    )


def message(tok, body, prefill):
    text = (
        "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
        "<|message_user|><|content_text|>"
        + body
        + "<|end_message|><|message_model|><|content_text|>"
        + prefill
    )
    return tok.encode(text, add_special_tokens=False).ids


def statement(task):
    q = task["question"]
    if "sample input" not in q.lower():
        q += "\n" + "\n".join(f"Input:\n{x['input']}Output:\n{x['output']}" for x in task["public"])
    return q


def branch(session, tok, task, idx, mode, prior):
    q = statement(task)
    implement = "Return a complete Python 3 stdin/stdout solution in one fenced python block."
    root = message(tok, q + "\n" + implement, FENCE)
    cap = 2 * len(root) + EXTRA
    plan = None
    plan_cost = 0
    ids = root
    if mode != "direct":
        ask = "Give a concise algorithm for the problem: state the representation, main operation and time complexity. Two short sentences, no code."
        if prior:
            ask += "\nEarlier plans:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(prior, 1))
            ask += (
                "\nName one assumption or limitation in those plans that could cause failure. "
                "Propose a viable algorithm that avoids it using a different representation or main operation. "
                "Rewording or changing only the implementation does not count. End with the new plan. No code."
            )
        prompt = message(tok, q + "\n" + ask, "")
        result = one(session, prompt, PLAN_CAP, PLAN_SEEDS[idx], 1)
        raw = decode(tok, result["tokens"])
        plan = final_text(raw).split("```")[0].strip()
        plan_cost = result["processed"]
        ids = message(
            tok,
            q + "\nYour proposed approach:\n" + plan + "\nImplement your proposed approach. " + implement,
            FENCE,
        )
    limit = cap - plan_cost - len(ids) + 1
    if limit < 1:
        raise ValueError("insufficient budget for author")
    r = one(session, ids, limit, CODE_SEEDS[idx], 1)
    spent = plan_cost + r["processed"]
    assert spent <= cap
    return dict(
        task=task["id"],
        mode=mode,
        idx=idx,
        plan=plan,
        plan_processed=plan_cost,
        plan_stop=result["reason"] if plan is not None else None,
        text=FENCE + decode(tok, r["tokens"]),
        processed=spent,
        cap=cap,
        code_limit=limit,
        stop=r["reason"],
    )


def generate(out):
    protocol = load(out / "protocol.json")
    assert (
        sha(out / "tasks.json") == protocol["tasks_sha256"]
        and sha(Path(__file__)) == protocol["driver_sha256"]
    )
    tok = Tokenizer.from_file(str(TOKENIZER))
    path = out / "branches.jsonl"
    cached = {(r["task"], r["mode"], r["idx"]): r for r in read_rows(path)} if path.exists() else {}
    with path.open("a") as f, engine(out / f"metal-{len(cached)}.log", checkpoints=False) as s:
        for t in load(out / "tasks.json"):
            for mode in MODES:
                prior = []
                for idx in range(3):
                    key = (t["id"], mode, idx)
                    if key not in cached:
                        if mode == "diverse_plans" and idx == 0:
                            row = {**cached[t["id"], "independent_plans", 0], "mode": mode}
                        else:
                            row = branch(s, tok, t, idx, mode, prior if mode == "diverse_plans" else [])
                        record(f, **row)
                        cached[key] = row
                    prior.append(cached[key]["plan"])
            print(t["id"], flush=True)
    write(out / "lock.json", {p: sha(out / p) for p in ("tasks.json", "protocol.json", "branches.jsonl")})


def grade(out):
    assert all(sha(out / name) == h for name, h in load(out / "lock.json").items())
    p = load(out / "protocol.json")
    tasks = load(out / "tasks.json")
    refs = {}
    for name, h in p["source_hashes"].items():
        assert sha(DATA / name) == h
        for r in source_rows(DATA / name):
            if p["sources"].get(r["question_id"]) == name:
                refs[r["question_id"]] = tests(r["private_test_cases"])
    assert all(refs[t["id"]] and all(c["testtype"] == "stdin" for c in refs[t["id"]]) for t in tasks)
    rows = read_rows(out / "branches.jsonl")
    expected = {(t["id"], m, i) for t in tasks for m in MODES for i in range(3)}
    assert len(rows) == len(expected) and {(r["task"], r["mode"], r["idx"]) for r in rows} == expected
    path = out / "scores.jsonl"
    prior = read_rows(path) if path.exists() else []
    assert [(r["task"], r["mode"], r["idx"]) for r in prior] == [
        (r["task"], r["mode"], r["idx"]) for r in rows[: len(prior)]
    ]
    memo = {(r["task"], r["digest"]): r["correct"] for r in prior}
    with path.open("a") as f:
        for r in rows[len(prior) :]:
            k = r["task"]
            code = value(r["text"], "code")
            digest = hashlib.sha256((code or "").encode()).hexdigest()
            if (k, digest) not in memo:
                cs = refs[k]
                memo[k, digest] = (
                    bool(code)
                    and all(run_cases(code, cs[:3]))
                    and (len(cs) <= 3 or all(run_cases(code, cs[3:])))
                )
            record(
                f,
                task=k,
                mode=r["mode"],
                idx=r["idx"],
                digest=digest,
                correct=memo[k, digest],
                private_cases=len(refs[k]),
            )
            if r["mode"] == MODES[-1] and r["idx"] == 2:
                print(k, flush=True)
    counts = defaultdict(dict)
    scores = read_rows(path)
    for t in tasks:
        for m in MODES:
            counts[t["id"]][m] = sum(
                r["correct"] for r in scores if r["task"] == t["id"] and r["mode"] == m
            )
    paired = {}
    for m in MODES[:-1]:
        paired[m] = dict(
            gained=[k for k, c in counts.items() if c[MODES[-1]] and not c[m]],
            lost=[k for k, c in counts.items() if c[m] and not c[MODES[-1]]],
        )
    write(
        out / "summary.json",
        dict(
            counts=counts,
            paired=paired,
            coverage={m: sum(c[m] > 0 for c in counts.values()) for m in MODES},
            correct_programs={m: sum(c[m] for c in counts.values()) for m in MODES},
            processed={m: sum(r["processed"] for r in rows if r["mode"] == m) for m in MODES},
            max_processed=sum(3 * r["cap"] for r in rows if r["mode"] == "direct" and r["idx"] == 0),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "generate", "grade"))
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "generate": generate, "grade": grade}[args.stage](args.out)
