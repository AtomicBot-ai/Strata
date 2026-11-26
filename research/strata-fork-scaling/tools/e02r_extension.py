"""Prospective replication cohorts of four with the initial frozen E02-R thresholds."""
import argparse
import shutil
import signal
import time
from pathlib import Path

import numpy as np

import e02r as study

INITIAL = study.OUT
ROOT = INITIAL / "extension"
FIRST_SEED = 49101


def verdict(panel, bounds):
    failures = []
    means = {}
    for group in ("native","candidate"):
        means[group] = {}
        for d in study.DEPTHS:
            means[group][str(d)] = {}
            for m in study.KEYS:
                value = float(np.mean([tree[group][str(d)][m] for tree in panel]))
                means[group][str(d)][m] = value
                limit = bounds[str(d)][m]
                if value > limit:
                    failures.append(dict(group=group,depth=d,metric=m,value=value,limit=limit))
    exact = all(tree["exact"] for tree in panel)
    if not exact:
        status = "exact_mismatch"
    elif any(f["group"]=="native" for f in failures):
        status = "native_out_of_envelope"
    elif failures:
        status = "candidate_out_of_envelope"
    else:
        status = "passed"
    return dict(status=status, exact=exact, failures=failures, means=means)


def run():
    original = INITIAL/"freeze.json"
    lock = study.read(original)
    if lock["provenance"] != study.provenance():
        raise RuntimeError("original E02-R source or executable changed")
    initial_gate = study.read(INITIAL/"gate.json")
    baseline = verdict(study.read(INITIAL/"hold-panel.json"), lock["bounds"])
    if baseline["status"] != initial_gate["status"] or baseline["failures"] != initial_gate["failures"]:
        raise RuntimeError("replication scoring differs from the initial gate")
    study.OUT = ROOT
    study.RAW = study.RAW/"extension"
    ROOT.mkdir(exist_ok=True)
    plan = ROOT/"protocol.json"
    design = dict(first_seed=FIRST_SEED, cohort_size=4, seed_spacing=4, boundaries=study.LENGTHS,
                  original_freeze_sha256=study.digest(original),source_sha256=study.digest(Path(__file__)),
                  method="Same twelve arms per new tree; independent four-tree panels. Report every panel, no refitting or retrospective exclusion. Repeated panels are exploratory external replication, not additional primary holdout.")
    if not plan.exists():
        study.write(plan,design)
    if study.read(plan)["original_freeze_sha256"] != study.digest(original) or study.read(plan)["source_sha256"] != design["source_sha256"]:
        raise RuntimeError("replication lock changed")
    i = 0
    while True:
        panel_dir = ROOT/f"cohort-{i+1:03}"
        decision = panel_dir/"gate.json"
        if decision.exists():
            if study.read(decision)["status"] == "exact_mismatch":
                raise RuntimeError("pending same-path divergence requires localization")
            i+=1
            continue
        panel_dir.mkdir(exist_ok=True)
        seeds = list(range(FIRST_SEED+4*i,FIRST_SEED+4*i+4))
        manifest = panel_dir/"manifest.json"
        if not manifest.exists():
            study.write(manifest,dict(seeds=seeds,freeze_sha256=study.digest(original),start_ns=time.time_ns()))
        panel=[]
        for seed in seeds:
            row_path=panel_dir/f"tree-{seed}.json"
            if row_path.exists():
                row=study.read(row_path)
            else:
                study.RAW.mkdir(parents=True,exist_ok=True)
                # Each independent 12-arm tree stores ~105 MiB of full-vocabulary arrays.
                if shutil.disk_usage(study.RAW).free < 2*1024**3:
                    raise OSError("insufficient remaining local space for sustained raw logits")
                row=study.collect("hold",seed)
                study.write(row_path,row)
                print(f"cohort {i+1} tree {seed} matched={row['exact']}",flush=True)
            panel.append(row)
            if not row["exact"]:
                study.write(decision,dict(status="exact_mismatch",seed=seed,complete_trees=len(panel)))
                raise RuntimeError(f"same-path divergence at seed {seed}; localize before continuing")
        result=verdict(panel,lock["bounds"])
        study.write(decision,result)
        print(f"cohort {i+1} {result['status']} failures={len(result['failures'])}",flush=True)
        i+=1


if __name__=="__main__":
    signal.signal(signal.SIGALRM,study.timeout)
    run()
