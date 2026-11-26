"""Summarize paired blind-critic outcomes; keep the three continuations of a task together."""

import argparse
from collections import Counter
from pathlib import Path

from blind_critic import POST_CAP, SEEDS, locked
from rollback_map import load, read_rows, write


def cluster_interval(deltas):
    # Exact percentile bootstrap: draw len(deltas) tasks with replacement.
    single = Counter(deltas)
    total = Counter({0: 1})
    for _ in deltas:
        nxt = Counter()
        for a, count in total.items():
            for b, multiplicity in single.items():
                nxt[a + b] += count * multiplicity
        total = nxt
    bounds = []
    for per_mille in (25, 975):
        accumulated = 0
        for value, count in sorted(total.items()):
            accumulated += count
            if accumulated * 1000 >= per_mille * total.total():
                bounds.append(round(100 * value / (len(deltas) * len(SEEDS)), 2))
                break
    return bounds


def main(out, numbered):
    locked(out)
    prefix = "numbered-" if numbered else ""
    scores = read_rows(out / (prefix + "scores.jsonl"))
    decisions = read_rows(out / ("numbered.jsonl" if numbered else "decisions.jsonl"))
    ids = [t["id"] for t in load(out / "tasks.json")]
    expected = {(k, seed) for k in ids for seed in SEEDS}
    assert len(scores) == len(expected) and {(r["task"], r["seed"]) for r in scores} == expected
    assert all(0 <= r[f] <= POST_CAP for r in scores for f in ("critic_forwarded", "restart_forwarded"))
    tasks = []
    for k in ids:
        group = [r for r in scores if r["task"] == k]
        first = group[0]
        fixed = {a: sum(r["alternatives_fixed"][a] for r in group) for a in first["alternatives_fixed"]}
        tasks.append(
            dict(
                task=k,
                domain=first["domain"],
                draft=first["draft"],
                decision=first["decision"],
                critic=sum(r["critic"] for r in group),
                restart=sum(r["restart"] for r in group),
                only_critic=sum(r["critic"] and not r["restart"] for r in group),
                only_restart=sum(r["restart"] and not r["critic"] for r in group),
                critic_fixed=fixed[first["decision"]],
                static_fixed=sum(r["static_fixed"] for r in group),
                alternatives_fixed=fixed,
                best_task_fixed=max(fixed.values()),
                best_seed_fixed=sum(any(r["alternatives_fixed"].values()) for r in group),
            )
        )
    totals = {
        f: sum(t[f] for t in tasks)
        for f in (
            "critic",
            "restart",
            "only_critic",
            "only_restart",
            "critic_fixed",
            "static_fixed",
            "best_task_fixed",
            "best_seed_fixed",
        )
    }
    totals["restart_fixed"] = sum(t["alternatives_fixed"]["RESTART"] for t in tasks)
    write(
        out / (prefix + "comparison.json"),
        dict(
            pairs=len(scores),
            valid_decisions=sum(c["action"] in c["menu"] if numbered else c["valid"] for c in decisions),
            correct_drafts=sum(t["draft"] for t in tasks),
            cluster_bootstrap_95pp=cluster_interval([t["critic"] - t["restart"] for t in tasks]),
            actions=dict(Counter(c["action"] for c in decisions)),
            totals=totals,
            tasks=tasks,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--numbered", action="store_true")
    args = parser.parse_args()
    main(args.out, args.numbered)
