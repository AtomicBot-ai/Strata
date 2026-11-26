"""Offline counterfactual map on new debug IDs. Run prepare, drafts, label-drafts, branches, grade."""

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
from grade import extract, run_cases
from prepare import CODE_REV, DATA, MATH_REV, tests
from search import reset

DRAFT_SEED = 719
PAIR_SEEDS = (1301, 1303, 1307)
BUDGET = 448
CONTEXT = 4096
MARKER = re.compile(r"(?im)^\s*(?:\*\*)?Step[ \t]+([23])[ \t]*[:.)]")
FINAL = re.compile(r"(?im)^\s*(?:\*\*)?Final(?: answer)?[ \t]*:")


def read_rows(path):
    with path.open() as f:
        return [json.loads(line) for line in f]


def load(path):
    return json.loads(path.read_text())


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def prepare(out):
    excluded = {t["id"] for t in load(DATA / "public.json")}
    groups = collections.defaultdict(dict)
    for r in read_rows(DATA / "math.jsonl"):
        if r["unique_id"] not in excluded and re.fullmatch(r"-?\d+", r["answer"]) and r["level"] in (4, 5):
            groups["math", r["level"]][r["unique_id"]] = (r["problem"], [], r["answer"])
    for path in sorted(DATA.glob("code6-*.jsonl")):
        with path.open("rb") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (
                    r["question_id"] in excluded
                    or r["platform"] != "atcoder"
                    or r["starter_code"]
                    or r["difficulty"] not in ("medium", "hard")
                ):
                    continue
                public = json.loads(r["public_test_cases"])
                if not public or not all(t["testtype"] == "stdin" for t in public):
                    continue
                groups["code", r["difficulty"]][r["question_id"]] = (r["question_content"], public, r)
    tasks = []
    gold = {}
    for domain, level, count in (
        ("math", 4, 3),
        ("math", 5, 3),
        ("code", "medium", 2),
        ("code", "hard", 2),
    ):
        group = groups[domain, level]
        ids = sorted(group, key=lambda k: hashlib.sha256(("rollback-map-v1/" + k).encode()).digest())[
            :count
        ]
        if len(ids) != count:
            raise ValueError("missing stratum")
        for k in ids:
            q, public, ref = group[k]
            tasks.append(dict(id=k, domain=domain, level=level, question=q, public=public))
            gold[k] = ref if domain == "math" else tests(ref["private_test_cases"])
    out.mkdir(parents=True, exist_ok=False)
    write(out / "tasks.json", tasks)
    # Reference data stays outside the deliverable and the inference path.
    private = DATA / ("labels-" + out.name + ".json")
    write(private, gold)
    write(
        out / "protocol.json",
        dict(
            math_revision=MATH_REV,
            code_revision=CODE_REV,
            excluded=sorted(excluded),
            seeds=PAIR_SEEDS,
            draft_seed=DRAFT_SEED,
            cap=BUDGET,
            context=CONTEXT,
            first_step="Step 1:",
            binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(),
            tokenizer_sha256=hashlib.sha256(TOKENIZER.read_bytes()).hexdigest(),
        ),
    )
    print([(r["id"], r["level"]) for r in tasks])


def prompt(tok, task):
    suffix = (
        "Then write Final: followed by one fenced python program reading stdin and writing stdout."
        if task["domain"] == "code"
        else r"Then write Final: followed by the integer in \boxed{}."
    )
    parts = [task["question"]]
    for ex in task["public"]:
        parts.append(f"Example input:\n{ex['input']}\nExample output:\n{ex['output']}")
    parts.append(
        "Use three short lines labeled Step 1:, Step 2:, Step 3: for your approach. "
        "Start each label on a new line. " + suffix
    )
    text = (
        "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
        "<|message_user|><|content_text|>"
        + "\n".join(parts)
        + "<|end_message|><|message_model|><|content_text|>Step 1:"
    )
    return tok.encode(text, add_special_tokens=False).ids


def decode(tok, ids):
    return tok.decode(ids, skip_special_tokens=False)


def boundaries(tok, ids):
    # A split must be a genuine token boundary. Keep the next fixed label, never its content.
    text = decode(tok, ids)
    final = FINAL.search(text)
    end = final.start() if final else len(text)
    for delimiter in ("```", r"\boxed{", "<|end_message|>", "<|content_model_end_sampling|>"):
        i = text.find(delimiter)
        if i >= 0:
            end = min(end, i)
    labels = {}
    for m in MARKER.finditer(text, 0, end):
        name = "step" + m[1]
        if name in labels or (name == "step3" and "step2" not in labels):
            continue
        # Decoder may produce UTF-8 fragments at arbitrary boundaries, hence verify literal prefix.
        for n in range(1, len(ids) + 1):
            if decode(tok, ids[:n]) == text[: m.end()]:
                labels[name] = n
                break
    return labels


def generate(session, tok, task, base, prefix, mode, seed):
    if len(base) + len(prefix) + BUDGET >= CONTEXT:
        raise ValueError("continuation does not fit context")
    reset(session)
    result = session.gen(base + prefix, BUDGET, seed, 1)
    if result["reused"]:
        raise ValueError("unexpected cache reuse after reset")
    full = prefix + result["tokens"]
    return dict(
        task=task["id"],
        mode=mode,
        seed=seed,
        prefix_n=len(prefix),
        base_n=len(base),
        text="Step 1:" + decode(tok, full),
        equal_length_text="Step 1:" + decode(tok, full[:BUDGET]),
        **result,
    )


def inference(out, draft):
    tok = Tokenizer.from_file(str(TOKENIZER))
    tasks = load(out / "tasks.json")
    if not draft:
        drafts = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
        failed = set(load(out / "failed-ids.json"))
    stage = "drafts" if draft else "branches"
    with (
        (out / (stage + ".jsonl")).open("x") as stream,
        engine(out / (stage + ".log"), checkpoints=False) as session,
    ):
        for task in tasks:
            base = prompt(tok, task)
            if draft:
                r = generate(session, tok, task, base, [], "draft", DRAFT_SEED)
                record(stream, **r, points=boundaries(tok, r["tokens"]), input_ids=base)
                print(task["id"], r["reason"], flush=True)
                continue
            if task["id"] not in failed:
                continue
            original = drafts[task["id"]]
            if original["input_ids"] != base:
                raise ValueError("prompt drift")
            prefixes = {"restart": []}
            for point, n in original["points"].items():
                prefixes[point] = original["tokens"][:n]
            if original["reason"] == "length":
                prefixes["continue"] = original["tokens"]
            for seed in PAIR_SEEDS:
                for name, ids in prefixes.items():
                    record(stream, **generate(session, tok, task, base, ids, name, seed))
            # Equal number of fresh alternatives versus searching over multiple rollback points.
            for i in range(len(PAIR_SEEDS) * max(0, len(original["points"]) - 1)):
                record(stream, **generate(session, tok, task, base, [], "extra_restart", 2300 + i))
            print(task["id"], list(prefixes), flush=True)


def score(out, draft):
    tasks = {t["id"]: t for t in load(out / "tasks.json")}
    refs = load(DATA / ("labels-" + out.name + ".json"))
    stage = "drafts" if draft else "branches"
    failed = []
    memo = {}

    def assess(task_id, text):
        domain = tasks[task_id]["domain"]
        value = extract(text, domain)
        if (task_id, value) not in memo:
            if value is None:
                verdict = (False, "no_final")
            elif domain == "math":
                verdict = (value == refs[task_id], "graded")
            else:
                cases = refs[task_id]
                # Cheap first batch can disqualify a candidate without running all remaining cases.
                first = run_cases(value, cases[:3])
                passed = all(first) and (len(cases) <= 3 or all(run_cases(value, cases[3:])))
                verdict = (passed, "graded")
            memo[task_id, value] = verdict
        return memo[task_id, value]

    with (out / (stage + "-scores.jsonl")).open("x") as f:
        for r in read_rows(out / (stage + ".jsonl")):
            ok, status = assess(r["task"], r["text"])
            same, same_status = assess(r["task"], r["equal_length_text"])
            record(
                f,
                task=r["task"],
                mode=r["mode"],
                seed=r["seed"],
                correct=ok,
                status=status,
                equal_length_correct=same,
                equal_length_status=same_status,
            )
            if draft and not ok:
                failed.append(r["task"])
    if draft:
        write(out / "failed-ids.json", failed)
        print("failed drafts:", failed)


def summarize(out):
    """Build paired results and verify every planned counterfactual is present exactly once."""
    drafts = read_rows(out / "drafts.jsonl")
    original = {r["task"]: r for r in read_rows(out / "drafts-scores.jsonl")}
    rows = read_rows(out / "branches.jsonl")
    grades = read_rows(out / "branches-scores.jsonl")
    key = lambda r: (r["task"], r["mode"], r["seed"])
    scores = {key(r): r for r in grades}
    if len(scores) != len(rows) or len(scores) != len(grades) or set(scores) != {key(r) for r in rows}:
        raise ValueError("missing or duplicate counterfactual grade")
    used = set()
    result = []
    for draft in drafts:
        task = draft["task"]
        if original[task]["correct"]:
            continue
        modes = {"restart": PAIR_SEEDS, **{name: PAIR_SEEDS for name in draft["points"]}}
        if draft["reason"] == "length":
            modes["continue"] = PAIR_SEEDS
        extra = len(PAIR_SEEDS) * max(0, len(draft["points"]) - 1)
        if extra:
            modes["extra_restart"] = range(2300, 2300 + extra)
        arms = {}
        for mode, seeds in modes.items():
            keys = [(task, mode, s) for s in seeds]
            used.update(keys)
            rs = [scores[k] for k in keys]
            arms[mode] = dict(
                n=len(rs),
                correct_seeds=[r["seed"] for r in rs if r["correct"]],
                equal_length_seeds=[r["seed"] for r in rs if r["equal_length_correct"]],
                no_final=sum(r["status"] == "no_final" for r in rs),
            )
        paired = []
        for point in draft["points"]:
            for seed in PAIR_SEEDS:
                r = scores[task, point, seed]
                root = scores[task, "restart", seed]
                if r["correct"] and not root["correct"]:
                    paired.append(dict(seed=seed, point=point, equal_length=r["equal_length_correct"]))
        all_restart = arms["restart"]["correct_seeds"] + arms.get("extra_restart", {}).get(
            "correct_seeds", []
        )
        result.append(
            dict(
                task=task,
                draft_status=original[task]["status"],
                draft_stop=draft["reason"],
                points=draft["points"],
                arms=arms,
                paired_wins=paired,
                only_rollback_in_sample=bool(paired) and not all_restart,
                only_rollback_equal_length=any(r["equal_length"] for r in paired) and not all_restart,
            )
        )
    if used != set(scores):
        raise ValueError("unplanned trajectories")
    write(out / "map.json", dict(drafts=len(drafts), failed=len(result), branches=len(rows), tasks=result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=["prepare", "drafts", "label-drafts", "branches", "grade", "summary"]
    )
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    def expired(*_):
        raise TimeoutError("rollback map time budget exhausted")

    signal.signal(signal.SIGALRM, expired)
    t0 = (
        (args.out / "protocol.json").stat().st_mtime
        if (args.out / "protocol.json").exists()
        else time.time()
    )
    secs = int(t0 + 7200 - time.time())
    if args.stage == "summary":
        summarize(args.out)
        raise SystemExit(0)
    if secs <= 0:
        raise TimeoutError("rollback map time budget exhausted")
    signal.alarm(secs)
    if args.stage == "prepare":
        prepare(args.out)
    elif args.stage in ("drafts", "branches"):
        inference(args.out, args.stage == "drafts")
    else:
        score(args.out, args.stage == "label-drafts")
