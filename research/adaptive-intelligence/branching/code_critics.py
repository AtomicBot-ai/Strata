"""Two blind code reviewers, one fixed author and paired single-call controls."""

import argparse
import contextlib
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
import numpy as np
from tokenizers import Tokenizer

from blind_critic import (
    ACTIONS,
    BUDGET,
    DATA,
    POST_CAP,
    SEEDS,
    TOKENIZER,
    available,
    drafts,
    locked,
    one,
    sha,
    value,
)
from engine import BIN, MODEL, engine, record
from evidence_critic import prefix
from grade import final_text, run_cases
from prepare import CODE_REV, tests
from rollback_map import decode, load, read_rows, write

QWEN = Path.home() / ".atomic-agent/models/models/qwen-3.8-27b/Qwen3.8-27B-UD-Q4_K_XL.gguf"
SOURCE = DATA / "code5-review-records.jsonl"
POLICIES = ("restart", "static", "inkling", "qwen")
REVIEWERS = ("inkling", "qwen")


def prepare(out):
    excluded = {t["id"] for t in load(DATA / "public.json")}
    for name in ("rollback-map-01", "blind-critic-01", "evidence-critic-01"):
        excluded.update(t["id"] for t in load(out.parent / name / "tasks.json"))
    rows = read_rows(SOURCE)
    tasks = []
    for level, n in (("easy", 2), ("medium", 1), ("hard", 3)):
        pool = [r for r in rows if r["difficulty"] == level and r["question_id"] not in excluded]
        pool.sort(key=lambda r: hashlib.sha256(("code-critics-1/" + r["question_id"]).encode()).digest())
        assert len(pool) >= n
        for r in pool[:n]:
            pub = json.loads(r["public_test_cases"])
            assert (
                r["platform"] == "atcoder"
                and not r["starter_code"]
                and all(x["testtype"] == "stdin" for x in pub)
            )
            tasks.append(
                dict(
                    id=r["question_id"],
                    title=r["question_title"],
                    domain="code",
                    level=level,
                    question=r["question_content"],
                    public=pub,
                )
            )
    out.mkdir()
    write(out / "tasks.json", tasks)
    write(
        out / "protocol.json",
        dict(
            source_revision=CODE_REV,
            source_sha256=sha(SOURCE),
            tasks_sha256=sha(out / "tasks.json"),
            draft_cap=BUDGET,
            draft_seed=1571,
            seeds=SEEDS,
            post_cap=POST_CAP,
            author=MODEL.name,
            critic2=QWEN.name,
            bin_sha256=sha(BIN),
            review="single greedy digit, same body and ordered options, one choice per task, no hidden tests",
            fixed="448 new author tokens per selected repair; fresh root is also a stock short call",
            budget="2048 forwarded tokens after draft, reviewer prompt charged in own tokenizer; infeasible action retains draft",
            stock_long="one author call from root, cap = actual processed draft tokens + 2048; same paired seeds as repairs",
            metric="all hidden stdin cases pass, paired gains/losses by task and seed",
            excluded=sorted(excluded),
        ),
    )


def menus(out):
    data = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
    tasks = load(out / "tasks.json")
    path = out / "menus.jsonl"
    previous = read_rows(path) if path.exists() else []
    assert [r["task"] for r in previous] == [t["id"] for t in tasks[:len(previous)]]
    with path.open("a") as f:
        for t in tasks[len(previous):]:
            k = t["id"]
            d = data[k]
            code = value(d["text"], "code")
            if code:
                try:
                    compile(code, "<draft>", "exec")
                except (SyntaxError, ValueError) as e:
                    checks = "Python syntax error: " + str(e)
                else:
                    checks = "Public stdin examples passed, in order: " + str(run_cases(code, t["public"]))
            else:
                checks = "No Python code block yet."
            options = sorted(available(d), key=lambda a: hashlib.sha256(f"{k}/{a}".encode()).digest())
            menu = "\n".join(f"{i}. {ACTIONS[a]}" for i, a in enumerate(options, 1))
            q = t["question"]
            if "sample input" not in q.lower():
                q += "\n" + "\n".join(
                    f"Sample input: {x['input']}\nSample output: {x['output']}" for x in t["public"]
                )
            status = "Output budget reached." if d["reason"] == "length" else "Author stopped."
            body = (
                f"Problem:\n{q}\nDraft:\n{final_text(d['text'])}\n{status} {checks}\n"
                "Which single action gives this author the best chance of passing all private cases? "
                "Consider the algorithm, its complexity and whether the implementation is complete. "
                "Only the retained prefix goes back to the author, without any feedback. Choose one digit.\n"
                + menu
            )
            record(f, task=k, options=options, body=body, checks=checks)


def inkling(out):
    tok = Tokenizer.from_file(str(TOKENIZER))
    with engine(out / "inkling.log") as s, (out / "inkling.jsonl").open("x") as f:
        for m in read_rows(out / "menus.jsonl"):
            prompt = (
                "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
                "<|message_user|><|content_text|>"
                + m["body"]
                + "<|end_message|><|message_model|><|content_text|>My choice is option "
            )
            ids = tok.encode(prompt, add_special_tokens=False).ids
            start = time.monotonic()
            r = one(s, ids, 1, 1, 0)
            scores = np.frombuffer(bytes.fromhex(s.control("LOGITS", "LOGITS")[0]), dtype="<f4")
            digits = [
                tok.encode(str(i), add_special_tokens=False).ids for i in range(1, len(m["options"]) + 1)
            ]
            assert all(len(x) == 1 for x in digits)
            logits = [float(scores[x[0]]) for x in digits]
            assert np.isfinite(logits).all()
            record(
                f,
                task=m["task"],
                action=m["options"][int(np.argmax(logits))],
                cost=r["processed"],
                elapsed_ms=round(1000 * (time.monotonic() - start)),
                logits=logits,
            )


@contextlib.contextmanager
def server(out):
    with (
        tempfile.TemporaryDirectory(dir="/private/tmp", prefix="strata-review-") as tmp,
        (out / "qwen.log").open("x") as log,
    ):
        sock = tmp + "/llama.sock"
        p = subprocess.Popen(
            [
                "llama-server",
                "--offline",
                "-m",
                str(QWEN),
                "--host",
                sock,
                "-c",
                "4096",
                "-np",
                "1",
                "--no-webui",
                "--no-warmup",
                "--reasoning",
                "off",
                "--cache-ram",
                "0",
            ],
            stdout=log,
            stderr=log,
        )
        try:
            cmd = ["curl", "-fsS", "--max-time", "90", "--unix-socket", sock]
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and p.poll() is None:
                r = subprocess.run(cmd + ["http://localhost/health"], capture_output=True)
                if r.returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("Qwen startup failed; see qwen.log")
            yield cmd
        finally:
            if p.poll() is None:
                p.terminate()
            try:
                p.wait(timeout=12)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def qwen(out):
    with server(out) as cmd, (out / "qwen.jsonl").open("x") as f:
        for m in read_rows(out / "menus.jsonl"):
            # qwen35 non-thinking chat template, with the same answer prefill as Inkling.
            prompt = (
                "<|im_start|>user\n"
                + m["body"]
                + "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\nMy choice is option "
            )
            n = len(m["options"])
            body = dict(
                prompt=prompt,
                n_predict=1,
                temperature=0,
                grammar=f"root ::= [1-{n}]",
                cache_prompt=False,
                seed=1,
            )
            start = time.monotonic()
            reply = subprocess.run(
                cmd
                + [
                    "-H",
                    "Content-Type: application/json",
                    "--data-binary",
                    "@-",
                    "http://localhost/completion",
                ],
                input=json.dumps(body),
                text=True,
                capture_output=True,
                check=True,
            )
            r = json.loads(reply.stdout)
            assert r["content"] in [str(i) for i in range(1, n + 1)] and not r.get("truncated")
            record(
                f,
                task=m["task"],
                action=m["options"][int(r["content"]) - 1],
                digit=r["content"],
                cost=r["tokens_evaluated"],
                elapsed_ms=round(1000 * (time.monotonic() - start)),
                timings=r["timings"],
            )
    names = ["tasks.json", "protocol.json", "drafts.jsonl", "menus.jsonl", "inkling.jsonl", "qwen.jsonl"]
    write(out / "lock.json", {n: sha(out / n) for n in names})


def branches(out):
    locked(out)
    tok = Tokenizer.from_file(str(TOKENIZER))
    reviewers = {p: {r["task"]: r for r in read_rows(out / (p + ".jsonl"))} for p in REVIEWERS}
    with engine(out / "branch.log", checkpoints=False) as s, (out / "answers.jsonl").open("x") as f:
        for d in read_rows(out / "drafts.jsonl"):
            k = d["task"]
            actions = dict(
                restart="RESTART",
                static="CONTINUE" if d["reason"] == "length" else "KEEP",
                **{p: reviewers[p][k]["action"] for p in REVIEWERS},
            )
            # Each unique trajectory is sampled once, then cut at the respective budgets.
            for seed in SEEDS:
                for a in dict.fromkeys(actions.values()):
                    pre = [] if a == "KEEP" else prefix(d, a)
                    ids = d["base"] + pre
                    limits = {}
                    for policy, action in actions.items():
                        if action != a:
                            continue
                        cost = reviewers[policy][k]["cost"] if policy in REVIEWERS else 0
                        if cost > POST_CAP:
                            raise ValueError("review alone exceeds budget")
                        limits["fixed", policy] = 0 if a == "KEEP" else BUDGET
                        limits["budget", policy] = (
                            0 if a == "KEEP" else max(0, POST_CAP - cost - len(ids) + 1)
                        )
                    if a == "RESTART":
                        limits["budget", "stock_long"] = POST_CAP + d["processed"] - len(ids) + 1
                    n = max(limits.values())
                    ts = one(s, ids, n, seed, 1)["tokens"] if n else []
                    for (mode, policy), limit in limits.items():
                        suffix = ts[:limit]
                        text = "Step 1:" + decode(tok, pre + suffix) if limit else d["text"]
                        record(
                            f,
                            task=k,
                            seed=seed,
                            mode=mode,
                            policy=policy,
                            action=a,
                            limit=limit,
                            forwarded_author=len(ids) + max(0, len(suffix) - 1) if limit else 0,
                            text=text,
                        )
            print(k, flush=True)


def grade(out):
    locked(out)
    ts = {t["id"] for t in load(out / "tasks.json")}
    assert sha(SOURCE) == load(out / "protocol.json")["source_sha256"]
    refs = {
        r["question_id"]: tests(r["private_test_cases"])
        for r in read_rows(SOURCE)
        if r["question_id"] in ts
    }
    assert set(refs) == ts and all(cs and all(x["testtype"] == "stdin" for x in cs) for cs in refs.values())
    answers = read_rows(out / "answers.jsonl")
    expected = {
        (k, seed, m, p) for k in ts for seed in SEEDS for m in ("fixed", "budget") for p in POLICIES
    }
    expected.update((k, seed, "budget", "stock_long") for k in ts for seed in SEEDS)
    assert (
        len(answers) == len(expected)
        and {(r["task"], r["seed"], r["mode"], r["policy"]) for r in answers} == expected
    )
    memo = {}

    def passes(k, text):
        v = value(text, "code")
        if (k, v) not in memo:
            cases = refs[k]
            memo[k, v] = (
                bool(v)
                and all(run_cases(v, cases[:3]))
                and (len(cases) <= 3 or all(run_cases(v, cases[3:])))
            )
        return memo[k, v]

    with (out / "scores.jsonl").open("x") as f:
        for d in read_rows(out / "drafts.jsonl"):
            k = d["task"]
            record(f, task=k, mode="draft", passed=passes(k, d["text"]), private_cases=len(refs[k]))
            for r in answers:
                if r["task"] == k:
                    record(
                        f,
                        **{f: r[f] for f in ("task", "seed", "mode", "policy", "action")},
                        passed=passes(k, r["text"]),
                    )
            print("graded", k, flush=True)


if __name__ == "__main__":
    stages = dict(
        prepare=prepare,
        drafts=drafts,
        menus=menus,
        inkling=inkling,
        qwen=qwen,
        branches=branches,
        grade=grade,
    )
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=stages)
    p.add_argument("out", type=Path)
    args = p.parse_args()
    stages[args.stage](args.out)
