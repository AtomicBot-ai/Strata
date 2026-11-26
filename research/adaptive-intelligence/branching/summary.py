"""Paired quality comparisons. Only debugging outcomes select the external control."""

from itertools import product
import json
from pathlib import Path
from statistics import mean, median
import numpy as np
from grade import choose

WRAPPERS = ("batch", "independent", "replay")


def read(path):
    return [json.loads(line) for line in path.open()]


def controls(debug):
    result = {}
    for d in ("code", "math"):

        def score(mode):
            rows = [r for r in debug if r["domain"] == d and r["mode"] == mode]
            if len(rows) != 2:
                raise ValueError(f"incomplete debug arm {mode} {d}")
            return (-mean(r["correct"] for r in rows), mean(r["wall_ms"] for r in rows), mode)

        result[d] = min(WRAPPERS, key=score)
    return result


def matched_time(r, cutoff):
    n = sum(t <= cutoff for t in r["completion_ms"])
    i = choose(r["domain"], r["answer_values"][:n], r["public_scores"][:n])
    return i is not None and r["correct_candidates"][i]


def summarize(debug_path, pilot_path):
    pilot = read(pilot_path)
    selected = controls(read(debug_path))
    raw = {(r["mode"], r["task_id"], r["seed"]): r for r in read(pilot_path.with_name("raw.jsonl"))}
    indexed = {(r["mode"], r["task_id"], r["seed"]): r for r in pilot}
    if len(indexed) != len(pilot):
        raise ValueError("duplicate pilot row")
    result = {}
    for domain, wrapper in selected.items():
        rows = [r for r in pilot if r["domain"] == domain and r["mode"] == "checkpoint"]
        ids = sorted({r["task_id"] for r in rows})
        seeds = (101, 211, 307)
        if len(ids) != 4 or any(
            (m, k, s) not in indexed for k in ids for s in seeds for m in (*WRAPPERS, "checkpoint")
        ):
            raise ValueError("Incomplete task/seed/mode matrix")
        pairs = []
        for r in rows:
            control = indexed[wrapper, r["task_id"], r["seed"]]
            cutoff = min(r["wall_ms"], control["wall_ms"])
            c = r["selected"]
            shared = min(len(r["answer_values"]), len(control["answer_values"]))
            short_choice = choose(domain, r["answer_values"][:shared], r["public_scores"][:shared])
            internal_short = short_choice is not None and r["correct_candidates"][short_choice]
            internal_raw = raw["checkpoint", r["task_id"], r["seed"]]["candidates"]
            external_raw = raw[wrapper, r["task_id"], r["seed"]]["candidates"]
            identical = sum(
                a["seed"] == b["seed"] and a["ids"] == b["ids"] for a, b in zip(internal_raw, external_raw)
            )
            pairs.append(
                dict(
                    task=r["task_id"],
                    seed=r["seed"],
                    internal=r["correct"],
                    external=control["correct"],
                    internal_time=matched_time(r, cutoff),
                    external_time=matched_time(control, cutoff),
                    internal_oracle=r["oracle"],
                    external_oracle=control["oracle"],
                    internal_n=len(r["answer_values"]),
                    external_n=len(control["answer_values"]),
                    internal_at_external_count=internal_short,
                    identical_common_candidates=identical,
                    common_candidates=shared,
                    extra_selected=c is not None and c >= len(control["answer_values"]),
                    wall_limit_ms=cutoff,
                )
            )
        task_deltas = [
            mean(int(p["internal"]) - int(p["external"]) for p in pairs if p["task"] == k) for k in ids
        ]
        # Exact empirical task bootstrap distribution at this pilot size (4**4).
        boot = [mean(sample) for sample in product(task_deltas, repeat=len(ids))]
        result[domain] = dict(
            wrapper=wrapper,
            n_pairs=len(pairs),
            tasks=len(ids),
            wins=sum(p["internal"] and not p["external"] for p in pairs),
            losses=sum(p["external"] and not p["internal"] for p in pairs),
            delta_pp=100 * mean(task_deltas),
            ci95_pp=list(100 * np.percentile(boot, [2.5, 97.5])),
            matched_time_counts=[sum(p[k] for p in pairs) for k in ("internal_time", "external_time")],
            arms={
                m: dict(
                    selected=sum(r["correct"] for r in pilot if r["mode"] == m and r["domain"] == domain),
                    oracle=sum(r["oracle"] for r in pilot if r["mode"] == m and r["domain"] == domain),
                    median_processed=median(
                        r["processed"] for r in pilot if r["mode"] == m and r["domain"] == domain
                    ),
                    median_ms=median(
                        r["wall_ms"] for r in pilot if r["mode"] == m and r["domain"] == domain
                    ),
                )
                for m in (*WRAPPERS, "checkpoint")
            },
            pairs=pairs,
        )
    return result


if __name__ == "__main__":
    import sys

    result = summarize(Path(sys.argv[1]), Path(sys.argv[2]))
    with Path(sys.argv[3]).open("x") as out:
        json.dump(result, out, indent=2)
