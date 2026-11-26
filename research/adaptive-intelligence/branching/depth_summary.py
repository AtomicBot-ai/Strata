"""Summarize matched R04 rollouts from output files. No inference or tests."""

from collections import Counter
from statistics import median
from depth_map import OUT, STAGES, read, save


def outcomes(checks):
    return dict(
        public=all(checks["public"]),
        small=all(v for k, v in checks["diagnostic"].items() if k != "scale"),
        combined=all(checks["public"]) and all(checks["diagnostic"].values()),
        scale=checks["diagnostic"].get("scale"),
    )


def summarize():
    protocol = read(OUT / "protocol.json")
    rows = []
    parents = {}
    for t in protocol["tasks"]:
        task = t["id"]
        parents[task] = outcomes(read(OUT / task / "parent-checks.json"))
        for seed in protocol["seeds"]:
            for stage in STAGES:
                p = OUT / task / str(seed) / stage
                gen = read(p / "generation.json")
                assert (gen["task"], gen["seed"], gen["stage"], gen["offset"]) == (
                    task,
                    seed,
                    stage,
                    t["offsets"][stage],
                )
                rows.append(
                    dict(
                        task=task,
                        seed=seed,
                        stage=stage,
                        child_s=gen["child_s"],
                        replay_s=gen["prepare_s"],
                        new_tokens=len(gen["tokens"]),
                        reason=gen["reason"],
                        has_code=gen["code_sha"] is not None,
                        **outcomes(read(p / "checks.json")),
                    )
                )
    tasks = list(parents)
    by_stage = {}
    for stage in STAGES:
        rr = [r for r in rows if r["stage"] == stage]
        by_stage[stage] = dict(
            n=len(rr),
            public=sum(r["public"] for r in rr),
            combined=sum(r["combined"] for r in rr),
            small_and_public=sum(r["public"] and r["small"] for r in rr),
            scale=sum(r["scale"] is True for r in rr),
            scale_n=sum(r["scale"] is not None for r in rr),
            median_child_s=median(r["child_s"] for r in rr),
            median_replay_s=median(r["replay_s"] for r in rr),
            median_new_tokens=median(r["new_tokens"] for r in rr),
            reasons=dict(Counter(r["reason"] for r in rr)),
            recovered=sum(
                r["combined"] and not parents[r["task"]]["combined"] for r in rr
            ),
            regressed=sum(
                not r["combined"] and parents[r["task"]]["combined"] for r in rr
            ),
            tasks={k: sum(r["combined"] for r in rr if r["task"] == k) for k in tasks},
        )
    ix = {(r["task"], r["seed"], r["stage"]): r for r in rows}
    pairs = {}
    for a, b in [("approach", "middle"), ("approach", "code"), ("middle", "code")]:
        vals = [
            int(ix[k, s, a]["combined"]) - int(ix[k, s, b]["combined"])
            for k in tasks
            for s in protocol["seeds"]
        ]
        pairs[a + "-" + b] = {
            "wins": vals.count(1),
            "losses": vals.count(-1),
            "ties": vals.count(0),
        }
    save(
        OUT / "summary.json",
        dict(by_stage=by_stage, paired_combined=pairs, parents=parents, rows=rows),
    )


if __name__ == "__main__":
    summarize()
