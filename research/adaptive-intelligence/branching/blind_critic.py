"""Prospective, blinded action selection. Stages intentionally separate planning from scoring."""

import argparse
import collections
import hashlib
import json
import re
import signal
import time
from pathlib import Path

from tokenizers import Tokenizer
from engine import BIN, TOKENIZER, engine, record
from grade import extract, final_text, run_cases
from prepare import CODE_REV, DATA, MATH_REV, tests
from rollback_map import BUDGET, CONTEXT, boundaries, decode, load, prompt, read_rows, write
from search import reset

SEEDS = (1601, 1607, 1609)
DRAFT_SEED = 1571
POST_CAP = 2048
CRITIC_CAP = 80
ACTIONS = {
    "KEEP": "submit the existing answer as it is",
    "RESTART": "discard the entire draft and solve afresh",
    "STEP2": "keep step 1 and rewrite from step 2",
    "STEP3": "keep steps 1 and 2 and rewrite from step 3",
    "CONTINUE": "append tokens exactly where the truncated draft ends",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out):
    excluded = {t["id"] for t in load(DATA / "public.json")}
    excluded.update(t["id"] for t in load(out.parent / "rollback-map-01" / "tasks.json"))
    pools = collections.defaultdict(dict)
    for row in read_rows(DATA / "math.jsonl"):
        k = row["unique_id"]
        if k not in excluded and re.fullmatch(r"-?\d+", row["answer"]):
            pools["math", row["level"]][k] = (row["problem"], [], row["answer"])
    for file in sorted(DATA.glob("code6-*.jsonl")):
        with file.open("rb") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                k = r["question_id"]
                if k in excluded or r["platform"] != "atcoder" or r["starter_code"]:
                    continue
                public = json.loads(r["public_test_cases"])
                if public and all(t["testtype"] == "stdin" for t in public):
                    pools["code", r["difficulty"]][k] = (
                        r["question_content"],
                        public,
                        r["private_test_cases"],
                    )
    tasks = []
    labels = {}
    for d, level, n in [
        ("math", 4, 3),
        ("math", 5, 3),
        ("code", "easy", 1),
        ("code", "medium", 1),
        ("code", "hard", 2),
    ]:
        pool = pools[d, level]
        ids = sorted(pool, key=lambda k: hashlib.sha256(("blind-critic-v1/" + k).encode()).digest())[:n]
        if len(ids) != n:
            raise ValueError(f"missing stratum {level}")
        for k in ids:
            q, p, ref = pool[k]
            tasks.append(dict(id=k, domain=d, level=level, question=q, public=p))
            labels[k] = tests(ref) if d == "code" else ref
            if d == "code" and not all(t["testtype"] == "stdin" for t in labels[k]):
                raise ValueError(k)
            if not labels[k]:
                raise ValueError(k)
    out.mkdir(parents=True, exist_ok=False)
    write(out / "tasks.json", tasks)
    write(DATA / ("labels-" + out.name + ".json"), labels)
    write(
        out / "protocol.json",
        dict(
            seeds=SEEDS,
            draft_seed=DRAFT_SEED,
            draft_cap=BUDGET,
            critic_cap=CRITIC_CAP,
            post_draft_processed_cap=POST_CAP,
            excluded_ids=sorted(excluded),
            math_revision=MATH_REV,
            code_revision=CODE_REV,
            binary_sha256=sha(BIN),
            tokenizer_sha256=sha(TOKENIZER),
            tasks_sha256=sha(out / "tasks.json"),
            invalid_action="RESTART, critic cost charged",
            critic_temperature=0,
            continuation_temperature=1,
        ),
    )
    print([(t["id"], t["level"]) for t in tasks], flush=True)


def value(text, domain):
    if domain == "math":
        return extract(text, domain)
    # A complete program can be truncated immediately before the closing fence.
    # The evaluator decides whether the unmodified contents actually run and pass.
    blocks = re.findall(r"```(?:python3?|py)?[ \t]*\n(.*?)(?:```|\Z)", final_text(text), re.I | re.S)
    return blocks[-1].strip() if blocks else None


def one(session, ids, n, seed, temp):
    if n < 1 or len(ids) + n >= CONTEXT:
        raise ValueError("request exceeds context")
    reset(session)
    r = session.gen(ids, n, seed, temp)
    if r["reused"]:
        raise ValueError("unexpected cross-request cache reuse")
    return r


def drafts(out):
    tok = Tokenizer.from_file(str(TOKENIZER))
    with (out / "drafts.jsonl").open("x") as f, engine(out / "drafts.log", checkpoints=False) as s:
        for task in load(out / "tasks.json"):
            ids = prompt(tok, task)
            r = one(s, ids, BUDGET, DRAFT_SEED, 1)
            record(
                f,
                task=task["id"],
                base=ids,
                text="Step 1:" + decode(tok, r["tokens"]),
                points=boundaries(tok, r["tokens"]),
                **r,
            )


def public_checks(out):
    initial = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
    result = {}
    for t in load(out / "tasks.json"):
        if t["domain"] == "code":
            program = value(initial[t["id"]]["text"], "code")
            begin = time.monotonic()
            flags = run_cases(program, t["public"]) if program else None
            result[t["id"]] = dict(passed=flags, wall_ms=(time.monotonic() - begin) * 1000)
    write(out / "public-checks.json", result)


def available(r):
    return [
        "KEEP",
        "RESTART",
        *(k.upper() for k in r["points"]),
        *(["CONTINUE"] if r["reason"] == "length" else []),
    ]


def critique_prompt(tok, t, draft, public):
    actions = available(draft)
    status = (
        "The author stopped." if draft["reason"] == "stop" else "The draft was cut off by its output limit."
    )
    checks = ""
    if public is not None:
        flags = public["passed"]
        checks = (
            "Public examples in order: "
            + (str(flags) if flags is not None else "no extractable Python yet")
            + "."
        )
    examples = "".join(f"\nSample input: {x['input']}\nSample output: {x['output']}" for x in t["public"])
    body = (
        f"Problem:\n{t['question']}{examples}\nDraft:\n{final_text(draft['text'])}\n{status} {checks}\n"
        "Inspect the reasoning, arithmetic or code. Preserve correct work. For a truncated answer with a sound approach, "
        "prefer continuing. For a substantive error, preserve only steps before the earliest error. "
        "Choose the action most likely to yield a correct submitted answer. Available actions:\n"
        + "\n".join(k + " = " + ACTIONS[k] for k in actions)
        + "\nWrite one of those exact action labels first, then a short reason. Do not supply a replacement solution."
    )
    text = (
        "<|message_system|><|content_text|>You are reviewing a proposed solution. Thinking effort level: 0"
        "<|end_message|><|message_user|><|content_text|>"
        + body
        + "<|end_message|><|message_model|><|content_text|>Action: "
    )
    return tok.encode(text, add_special_tokens=False).ids


def decide(out):
    tok = Tokenizer.from_file(str(TOKENIZER))
    initial = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
    checks = load(out / "public-checks.json")
    with (out / "decisions.jsonl").open("x") as f, engine(out / "critic.log", checkpoints=False) as s:
        for t in load(out / "tasks.json"):
            d = initial[t["id"]]
            ids = critique_prompt(tok, t, d, checks.get(t["id"]))
            r = one(s, ids, CRITIC_CAP, 1, 0)
            answer = decode(tok, r["tokens"])
            m = re.match(r"^[\s*`]*(KEEP|RESTART|STEP2|STEP3|CONTINUE)\b", answer, re.I)
            raw = m[1].upper() if m else None
            valid = raw in available(d)
            record(
                f,
                task=t["id"],
                available=available(d),
                action=raw if valid else "RESTART",
                valid=valid,
                text=answer,
                input_ids=ids,
                **r,
            )
    write(
        out / "lock.json",
        {
            p: sha(out / p)
            for p in (
                "protocol.json",
                "tasks.json",
                "drafts.jsonl",
                "public-checks.json",
                "decisions.jsonl",
            )
        },
    )


def locked(out):
    for name, hash_value in load(out / "lock.json").items():
        if sha(out / name) != hash_value:
            raise ValueError("sealed artifact changed: " + name)


def arms(out):
    locked(out)
    tok = Tokenizer.from_file(str(TOKENIZER))
    initial = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
    decisions = {r["task"]: r for r in read_rows(out / "decisions.jsonl")}
    with (out / "arms.jsonl").open("x") as f, engine(out / "arms.log", checkpoints=False) as s:
        for t in load(out / "tasks.json"):
            k = t["id"]
            d = initial[k]
            c = decisions[k]
            base = d["base"]
            for action in available(d):
                if action == "KEEP":
                    continue
                prefix = (
                    []
                    if action == "RESTART"
                    else d["tokens"]
                    if action == "CONTINUE"
                    else d["tokens"][: d["points"][action.lower()]]
                )
                root_n = POST_CAP - len(base) + 1 if action == "RESTART" else 0
                chosen_n = (
                    max(0, POST_CAP - c["processed"] - len(base) - len(prefix) + 1)
                    if action == c["action"]
                    else 0
                )
                n = max(BUDGET, root_n, chosen_n)
                for seed in SEEDS:
                    r = one(s, base + prefix, n, seed, 1)

                    def project(limit):
                        if limit == 0:
                            return d["text"]
                        return "Step 1:" + decode(tok, prefix + r["tokens"][:limit])

                    record(
                        f,
                        task=k,
                        action=action,
                        seed=seed,
                        prefix_n=len(prefix),
                        base_n=len(base),
                        requested=n,
                        root_n=root_n,
                        chosen_n=chosen_n,
                        fixed_text=project(BUDGET),
                        root_text=project(root_n) if action == "RESTART" else None,
                        chosen_text=project(chosen_n) if action == c["action"] else None,
                        **r,
                    )
            print(k, c["action"], flush=True)


def grade(out):
    locked(out)
    refs = load(DATA / ("labels-" + out.name + ".json"))
    tasks = {t["id"]: t for t in load(out / "tasks.json")}
    initial = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
    decisions = {r["task"]: r for r in read_rows(out / "decisions.jsonl")}
    records = read_rows(out / "arms.jsonl")
    rows = {(r["task"], r["action"], r["seed"]): r for r in records}
    expected = {
        (k, a, seed) for k, d in initial.items() for a in available(d) if a != "KEEP" for seed in SEEDS
    }
    if set(rows) != expected or len(records) != len(expected):
        raise ValueError("incomplete counterfactuals")
    memo = {}

    def passes(k, text):
        v = value(text, tasks[k]["domain"])
        if (k, v) not in memo:
            if v is None:
                ok = False
            elif tasks[k]["domain"] == "math":
                ok = v == refs[k]
            else:
                cases = refs[k]
                ok = all(run_cases(v, cases[:3])) and (len(cases) <= 3 or all(run_cases(v, cases[3:])))
            memo[k, v] = bool(ok)
        return memo[k, v]

    with (out / "scores.jsonl").open("x") as f:
        for k, d in initial.items():
            c = decisions[k]
            action = c["action"]
            draft_ok = passes(k, d["text"])
            for seed in SEEDS:
                arm = {a: rows[k, a, seed] for a in available(d) if a != "KEEP"}
                fixed = {"KEEP": draft_ok, **{a: passes(k, r["fixed_text"]) for a, r in arm.items()}}
                chosen = None if action == "KEEP" else arm[action]
                actual_charge = (
                    lambda r, n: 0
                    if n == 0
                    else r["base_n"] + r["prefix_n"] + max(0, min(len(r["tokens"]), n) - 1)
                )
                critic_tokens = c["processed"] + (
                    actual_charge(chosen, chosen["chosen_n"]) if chosen else 0
                )
                root = arm["RESTART"]
                root_tokens = actual_charge(root, root["root_n"])
                if max(critic_tokens, root_tokens) > POST_CAP:
                    raise ValueError("budget overrun")
                record(
                    f,
                    task=k,
                    domain=tasks[k]["domain"],
                    seed=seed,
                    decision=action,
                    draft=draft_ok,
                    critic=draft_ok if chosen is None else passes(k, chosen["chosen_text"]),
                    restart=passes(k, root["root_text"]),
                    critic_forwarded=critic_tokens,
                    restart_forwarded=root_tokens,
                    critic_fixed=fixed[action],
                    alternatives_fixed=fixed,
                    static_fixed=fixed["CONTINUE"] if "CONTINUE" in fixed else draft_ok,
                )
            print("graded", k, flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    stages = dict(
        prepare=prepare, drafts=drafts, public=public_checks, decide=decide, arms=arms, grade=grade
    )
    cli.add_argument("stage", choices=list(stages))
    cli.add_argument("out", type=Path)
    args = cli.parse_args()

    def expired(*_):
        raise TimeoutError("two-hour pilot cap")

    signal.signal(signal.SIGALRM, expired)
    manifest = args.out / "protocol.json"
    remaining = int(manifest.stat().st_mtime + 7200 - time.time()) if manifest.exists() else 7200
    if remaining <= 0:
        raise TimeoutError("two-hour pilot cap")
    signal.alarm(remaining)
    stages[args.stage](args.out)
