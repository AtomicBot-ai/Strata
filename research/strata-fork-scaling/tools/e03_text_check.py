"""Prepare or run the fixed four-input independent check on the E03 performance binary."""
import argparse
import json
import signal
from pathlib import Path

from tokenizers import Tokenizer

import e02r
import runner
from e03_review_screen import audit
from screen import deadline

LAB = runner.LAB
ROOT = LAB/"runs/E03/text-check"
PANEL = ROOT/"panel.json"


def prepare():
    tokenizer_path = runner.MODEL.parents[1]/"inkling-strata/tokenizer.json"
    tok = Tokenizer.from_file(str(tokenizer_path))
    sources = [LAB.parent/"adaptive-intelligence/context.md", LAB.parent/"adaptive-intelligence/audit.md"]
    cases = []
    for doc in sources:
        ids = tok.encode(doc.read_text(), add_special_tokens=False).ids
        if len(ids) < 576:
            raise ValueError(doc)
        cases.append(dict(name=doc.stem, kind="natural_text", source=str(doc.relative_to(runner.BASE)),
                          root=ids[:512], tails=[ids[512:544], ids[544:576]]))
    logs = LAB.parent/"adaptive-intelligence/runs/rollback-map-01"
    draft_log, branch_log = [logs/name for name in ("drafts.jsonl","branches.jsonl")]
    drafts = {r["task"]:r for r in map(json.loads,draft_log.read_text().splitlines())}
    branches = list(map(json.loads,branch_log.read_text().splitlines()))
    for task in ("test/precalculus/989.json", "abc387_c"):
        draft=drafts[task]
        pair=[next(r for r in branches if r["task"]==task and r["mode"]=="step2" and r["seed"]==seed)
              for seed in (1301,1303)]
        cut=pair[0]["prefix_n"]
        if not (cut == pair[1]["prefix_n"] and all(len(r["tokens"]) >= 32 for r in pair)):
            raise ValueError(task)
        root=draft["input_ids"]+draft["tokens"][:cut]
        cases.append(dict(name=Path(task).stem, kind="recorded_agent_branch", task=task,
                          prefix_n=cut,seeds=[1301,1303],root=root,tails=[r["tokens"][:32] for r in pair]))
    plan=dict(cases=cases, source_sha256={str(p.relative_to(runner.BASE)):e02r.digest(p) for p in sources+[draft_log,branch_log]},
              tokenizer_sha256=e02r.digest(tokenizer_path), upstream="b28ca95e3e6847f2d5e317994f253b66716deeaa",
              acceptance="Both full endpoint arrays per input must exactly match same-shape replay. Report all five metrics against paired native controls; retain any greedy differences. No fitting.",
              slots=2, steps=32, native_reference_width=2)
    if PANEL.exists() and plan!=e02r.read(PANEL):
        raise ValueError("panel already frozen with different inputs")
    ROOT.mkdir(parents=True,exist_ok=True)
    if not PANEL.exists():
        e02r.write(PANEL,plan)
    print(e02r.digest(PANEL),[(r["name"],len(r["root"])) for r in cases])


def evaluate():
    plan=e02r.read(PANEL)
    identity=e02r.read(ROOT/"lock.json")
    if e02r.digest(PANEL)!=identity["panel_sha256"] or e02r.digest(Path(__file__))!=identity["driver_sha256"]:
        raise ValueError("text panel or evaluator changed")
    for name, expected in identity["dependencies"].items():
        if e02r.digest(LAB/name) != expected:
            raise ValueError(f"changed text-check dependency: {name}")
    runner.PATCHED=runner.BUILD/"review-fork-build/strata-inkling"
    if e02r.digest(runner.PATCHED)!=identity["binary_sha256"]:
        raise ValueError("unexpected binary")
    results=[]
    for case in plan["cases"]:
        work=([case["root"]],case["tails"])
        results.append(audit(ROOT/case["name"],work,plan["native_reference_width"]))
    e02r.write(ROOT/"gate.json",dict(status="passed",exact=sum(len(r["branches"]) for r in results),
                                    native_endpoint_agreement=[r["native_candidate_tokens_agree"] for r in results],
                                    panel_sha256=identity["panel_sha256"]))

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["prepare","run"])
    args=parser.parse_args()
    signal.signal(signal.SIGALRM,deadline)
    if args.action=="prepare":
        prepare()
    else:
        evaluate()
