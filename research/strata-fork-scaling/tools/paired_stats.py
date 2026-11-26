"""Summaries of completed matched tree pairs. Never impute failed or blocked cells."""
import json
from pathlib import Path

import numpy as np


def paired_summary(folders):
    groups = {}
    pairs = []
    for folder in folders:
        data = [json.loads((folder / mode / "metrics.json").read_text()) for mode in ("B3", "B4")]
        if any(row["status"] != "ok" for row in data):
            raise ValueError(f"incomplete pair {folder}")
        left, right = data
        if left["workload_hash"] != right["workload_hash"] or left["useful_tokens"] != right["useful_tokens"]:
            raise ValueError(f"unequal work {folder}")
        ratio = left["elapsed_ns"] / right["elapsed_ns"]
        groups.setdefault(left["workload_hash"], []).append(ratio)
        pairs.append(data)
    if not pairs:
        raise ValueError("no completed pairs")
    samples = list(groups.values())
    rng = np.random.default_rng(1125)
    boot = []
    for indices in rng.integers(0,len(samples),(10000,len(samples))):
        drawn = [rng.choice(samples[i],size=len(samples[i]),replace=True) for i in indices]
        boot.append(np.median(np.concatenate(drawn)))
    elapsed = np.asarray([[r["elapsed_ns"] for r in pair] for pair in pairs])
    summary = dict(independent_trees=len(groups), paired_blocks=len(pairs),
                   median_paired=float(np.median(elapsed[:,0]/elapsed[:,1])),
                   ratio_of_total_times=float(elapsed[:,0].sum()/elapsed[:,1].sum()),
                   cluster_ci95=np.percentile(boot,[2.5,97.5]).tolist())
    for index,mode in enumerate(("B3","B4")):
        rows=[pair[index] for pair in pairs]
        summary[mode]=dict(median_s=float(np.median(elapsed[:,index])/1e9),
                           useful_tps=sum(r["useful_tokens"] for r in rows)/(elapsed[:,index].sum()/1e9),
                           p95_branch_s=float(np.percentile([b["latency_ns"]/1e9 for r in rows
                                                            for b in r["branches"].values()],95)),
                           peak_footprint_bytes=max(r["memory_after"]["peak_footprint"] for r in rows),
                           median_restore_ms=float(np.median([r["restore_ns"] for r in rows])/1e6),
                           median_create_ms=float(np.median([r["create_ns"] for r in rows])/1e6))
    return summary
