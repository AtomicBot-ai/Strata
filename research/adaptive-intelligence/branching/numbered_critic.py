"""Secondary blinded selector. Restrict the first model token to the numbered menu."""

import argparse
import hashlib
import re
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

from blind_critic import ACTIONS, POST_CAP, SEEDS, available, critique_prompt, locked, one, sha, value
from engine import TOKENIZER, engine, record
from grade import run_cases
from prepare import DATA
from rollback_map import decode, load, read_rows, write


def decide(out):
    locked(out)
    tok = Tokenizer.from_file(str(TOKENIZER))
    drafts = {d["task"]: d for d in read_rows(out / "drafts.jsonl")}
    public = load(out / "public-checks.json")
    with engine(out / "numbered.log") as s, (out / "numbered.jsonl").open("x") as f:
        for t in load(out / "tasks.json"):
            k = t["id"]
            d = drafts[k]
            choices = sorted(available(d), key=lambda a: hashlib.sha256(f"{k}/{a}".encode()).digest())
            stem = decode(tok, critique_prompt(tok, t, d, public.get(k))).rsplit("Available actions:", 1)[0]
            menu = "\n".join(f"{i}. {ACTIONS[a]}" for i, a in enumerate(choices, 1))
            prompt = (
                stem + "Choose one numbered option:\n" + menu + "\nReturn the digit only."
                "<|end_message|><|message_model|><|content_text|>My choice is option "
            )
            ids = tok.encode(prompt, add_special_tokens=False).ids
            raw = one(s, ids, 1, 1, 0)
            logits = np.frombuffer(bytes.fromhex(s.control("LOGITS", "LOGITS")[0]), dtype="<f4")
            scores = {}
            for i, action in enumerate(choices, 1):
                number = str(i)
                candidate = tok.encode(number, add_special_tokens=False).ids
                assert len(candidate) == 1 and decode(tok, ids + candidate) == prompt + number
                scores[action] = float(logits[candidate[0]])
            assert np.isfinite(list(scores.values())).all()
            record(
                f,
                task=k,
                action=max(scores, key=scores.get),
                menu=choices,
                logits=scores,
                input_ids=ids,
                processed=raw["processed"],
            )
    write(
        out / "numbered-lock.json",
        {name: sha(out / name) for name in ("numbered-protocol.md", "numbered.jsonl", "lock.json")},
    )


def choices_and_drafts(out):
    locked(out)
    assert all(sha(out / name) == h for name, h in load(out / "numbered-lock.json").items())
    return (read_rows(out / "numbered.jsonl"), {d["task"]: d for d in read_rows(out / "drafts.jsonl")})


def project(out):
    choices, drafts = choices_and_drafts(out)
    indexed = {(r["task"], r["action"], r["seed"]): r for r in read_rows(out / "arms.jsonl")}
    tok = Tokenizer.from_file(str(TOKENIZER))
    with (
        engine(out / "numbered-branches.log", checkpoints=False) as s,
        (out / "numbered-branches.jsonl").open("x") as f,
    ):
        for c in choices:
            k, a = c["task"], c["action"]
            d = drafts[k]
            for seed in SEEDS:
                spent = c["processed"]
                text = d["text"]
                extended = False
                if a != "KEEP":
                    r = indexed[k, a, seed]
                    prefix = d["tokens"][: r["prefix_n"]]
                    ids = d["base"] + prefix
                    n = max(0, POST_CAP - spent - len(ids) + 1)
                    tokens = r["tokens"]
                    if n > len(tokens) and r["reason"] == "length":
                        fresh = one(s, ids, n, seed, 1)
                        if fresh["tokens"][: len(tokens)] != tokens:
                            raise ValueError("generation prefix differs")
                        tokens = fresh["tokens"]
                        extended = True
                    if n:
                        tokens = tokens[:n]
                        spent += len(ids) + max(0, len(tokens) - 1)
                        text = "Step 1:" + decode(tok, prefix + tokens)
                assert spent <= POST_CAP
                record(f, task=k, seed=seed, decision=a, text=text, processed=spent, extended=extended)


def grade(out):
    choices_and_drafts(out)
    refs = load(DATA / ("labels-" + out.name + ".json"))
    previous = {(r["task"], r["seed"]): r for r in read_rows(out / "scores.jsonl")}
    arms = read_rows(out / "arms.jsonl")
    memo = {}
    for r in arms:
        k = r["task"]
        old = previous[k, r["seed"]]
        for field, ok in (
            ("fixed_text", old["alternatives_fixed"][r["action"]]),
            ("chosen_text", old["critic"]),
            ("root_text", old["restart"]),
        ):
            if r[field] is not None:
                memo[k, value(r[field], old["domain"])] = ok
    with (out / "numbered-scores.jsonl").open("x") as f:
        for r in read_rows(out / "numbered-branches.jsonl"):
            k = r["task"]
            old = previous[k, r["seed"]]
            a = r["decision"]
            v = value(r["text"], old["domain"])
            if a == "KEEP":
                ok = old["draft"]
            elif (k, v) in memo:
                ok = memo[k, v]
            elif old["domain"] == "math":
                ok = v == refs[k]
            else:
                cases = refs[k]
                ok = (
                    bool(v)
                    and all(run_cases(v, cases[:3]))
                    and (len(cases) <= 3 or all(run_cases(v, cases[3:])))
                )
            memo[k, v] = ok
            record(
                f,
                **{
                    **old,
                    "decision": a,
                    "critic": ok,
                    "critic_forwarded": r["processed"],
                    "critic_fixed": old["alternatives_fixed"][a],
                },
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["decide", "project", "grade"])
    p.add_argument("out", type=Path)
    args = p.parse_args()
    {"decide": decide, "project": project, "grade": grade}[args.stage](args.out)
