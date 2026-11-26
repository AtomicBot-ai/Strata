"""Finite diagnostic slice. Each published cell has its own paired endpoint-logit audit."""
import hashlib
import json
import random
import signal
from pathlib import Path
import numpy as np

import e02r
import runner
import screen
from runner import LAB, cold, engine, fixture, fingerprint, save, tree
from screen import deadline, endpoints, load, overhead, single
from shape_diagnostic import replay

RUN = LAB / "runs/E03/after-E02-R"
OUT = LAB / "runs/E03/review-b28ca95"
CELLS = [(4096, n) for n in (2, 4, 8)] + [(16384, n) for n in (2, 4, 8)]
SEED = 1000


def audit(cell, work, width):
    root, tails = work
    p = len(root[0])
    result = cell / "audit.json"
    if result.exists():
        data = load(result)
        if data["work"] != fingerprint(work) or data["width"] != width or data["status"] != "passed":
            raise ValueError(result)
        return data
    cell.mkdir(parents=True, exist_ok=True)
    signal.alarm(900)
    try:
        with engine(cell, p + 160, diag=True) as wire:
            cold(wire)
            reference = replay(wire, root, tails)
            cold(wire)
            fork, restored = tree(wire, work, "B4")
            cold(wire)
            baseline, native = tree(wire, work, "B3", native_width=width)
    finally:
        signal.alarm(0)
    expected = {str(i) for i in range(len(tails))}
    if any(set(x) != expected for x in (reference, restored, native)):
        raise ValueError("incomplete endpoint logits")
    rows = []
    for i in range(len(tails)):
        k = str(i)
        raw = [x[k] for x in (reference, restored, native)]
        vectors = [np.frombuffer(v, dtype="<f4") for v in raw]
        if any(v.shape != (200058,) or not np.isfinite(v).all() for v in vectors):
            raise ValueError("invalid logit vector")
        r, f, b = vectors
        rows.append(dict(branch=i, same_shape_exact=raw[0] == raw[1],
                         sha256=[hashlib.sha256(v).hexdigest() for v in raw],
                         native_batching=e02r.metrics(b, r), candidate=e02r.metrics(b, f)))
    ok = all(row["same_shape_exact"] for row in rows)
    data = dict(status="passed" if ok else "exact_mismatch", work=fingerprint(work),
                width=width, hash_order=["replay", "snapshot", "native"], branches=rows,
                native_candidate_tokens_agree=endpoints(baseline)==endpoints(fork))
    save(result, data)
    if not ok:
        raise ValueError(f"same-shape mismatch: {result}")
    return data


def main():
    OUT.mkdir(exist_ok=True)
    if load(LAB/"runs/E02-R/gate.json")["status"] != "passed" or load(LAB/"runs/E02-R/extension/closure.json")["status"] != "closed":
        raise RuntimeError("missing original gate or replication closure")
    runner.PATCHED = screen.PATCHED = runner.BUILD/"review-fork-build/strata-inkling"
    runner.STOCK = screen.STOCK = runner.BUILD/"review-stock-build/strata-inkling"
    plan = dict(cells=CELLS, diagnostic_only=True, timing_seed=SEED, dev_seed=928,
                upstream="b28ca95e3e6847f2d5e317994f253b66716deeaa",
                stock_sha256=e02r.digest(runner.STOCK), candidate_sha256=e02r.digest(runner.PATCHED),
                fixed_suffix=128, slots=2, paired_blocks=1, strict_gate="all branches, full endpoint FP32",
                native_width="Use the faster policy measured on separate seed 928 in the previous upstream revision; if missing measure both widths on this revision before the timed pair.",
                control="native baseline vs matched solo-prefill replay and snapshot; identical inputs for all three")
    manifest = OUT / "protocol.json"
    if manifest.exists() and load(manifest) != json.loads(json.dumps(plan)):
        raise ValueError("different diagnostic protocol")
    save(manifest, plan)
    if not (OUT/"overhead/overhead.json").exists():
        overhead(OUT/"overhead")
    if load(OUT/"overhead/overhead.json")["median"] > 1.10:
        raise ValueError("native overhead control failed")
    summary=[]
    for p,n in CELLS:
        name=f"p{p}-n{n}-shared"
        base=OUT/name
        previous=RUN/"screen"/name
        if all((previous/f"dev-c{w}/metrics.json").exists() for w in (1,2)):
            times={w:load(previous/f"dev-c{w}/metrics.json")["elapsed_ns"] for w in (1,2)}
            selected_on="2af30cc"
        else:
            times={w:single(base/f"dev-c{w}",p,n,928,"B3",w)["elapsed_ns"] for w in (1,2)}
            selected_on="b28ca95"
        width=min(times,key=times.get)
        work=fixture(p,n,128,SEED)
        proof=audit(base/"same-shape",work,width)
        block=base/"block-0"
        if not proof["native_candidate_tokens_agree"]:
            save(OUT/name/"endpoint-disagreement.json",dict(status="endpoint_disagreement"))
            raise ValueError("native endpoints disagree; inspect paired control")
        order=["B3","B4"]
        random.Random(screen.BASE_SEED+SEED).shuffle(order)
        for mode in order:
            single(block/mode,p,n,SEED,mode,width if mode=="B3" else 2)

        native,fork=[load(block/m/"metrics.json") for m in ("B3","B4")]
        if any(x["workload_hash"]!=proof["work"] for x in (native,fork)):
            raise ValueError("timing inputs differ from audit")
        if endpoints(native)!=endpoints(fork):
            raise ValueError("timed endpoints disagree")
        ratio=native["elapsed_ns"]/fork["elapsed_ns"]
        summary.append(dict(p=p,n=n,width=width,width_selected_on=selected_on,baseline_s=native["elapsed_ns"]/1e9,
                            fork_s=fork["elapsed_ns"]/1e9, speedup=ratio, exact_branches=n,
                            audit=f"{name}/same-shape/audit.json"))
        save(OUT/"results.json",summary)
        print(name, n, "exact;",round(ratio,4),"x",flush=True)

if __name__=="__main__":
    signal.signal(signal.SIGALRM,deadline)
    main()
