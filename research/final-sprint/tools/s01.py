"""Three short paired blocks, including native serial and two-slot prompt-cache baselines."""
import hashlib
import json
import random
import signal
import sys
from pathlib import Path
import numpy as np

SPRINT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SPRINT.parent/"strata-fork-scaling/tools"))
from marginal_run import arm, save, read, BIN, metrics

OUT=SPRINT/"runs/S01"
def timeout(*args):
    raise TimeoutError("warm branch arm exceeded 30 min")

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plan=dict(cells=[[16384,4],[32768,8]],suffix=128,seeds=[83101,83102,83103],audit_seed=83901,
              slots=2,model="Inkling-2-Mini SQ-10",base="b28ca95",binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(),
              native_selection="faster median of three for 1/2 admissions; report both",
              marginal="(time through slot cleanup - completion time of first two children)/(N-2); complementary first-two boundary inside same tree",
              memory_budget_bytes=32*2**30)
    if (OUT/"plan.json").exists() and read(OUT/"plan.json")!=plan: raise RuntimeError("plan changed")
    save(OUT/"plan.json",plan)
    signal.signal(signal.SIGALRM,timeout)
    def measure(folder,c,seed,mode,w,diag=False):
        signal.alarm(1800)
        try:
            r=arm(folder,c,seed,mode,2,w,diag)
            if r["memory"]["cleared"]["peak_footprint"]>plan["memory_budget_bytes"]: raise ValueError("arm exceeded memory budget")
            return r
        finally:
            signal.alarm(0)
    for p,n in plan["cells"]:
        c=(p,n,128,True)
        cell=OUT/f"p{p}-n{n}"
        g=cell/"gate.json"
        if not g.exists():
            rows={}
            for m,w in (("native",1),("native",2),("fork",2),("replay",2)):
                folder=cell/"audit"/f"{m}-{w}"
                measure(folder,c,plan["audit_seed"],m,w,True)
                rows[m,w]=np.load(folder/"endpoints.npy",mmap_mode="r")
            checked=[]
            for i in range(n):
                ref,f=[rows[m,2][i] for m in ("replay","fork")]
                controls={}
                for w in (1,2):
                    baseline=rows["native",w][i]
                    controls[str(w)]={"replay":metrics(baseline,ref),"fork":metrics(baseline,f)}
                checked.append(dict(exact=f.tobytes()==ref.tobytes(),controls=controls))
            save(g,dict(passed=all(r["exact"] for r in checked),branches=checked))
        if not read(g)["passed"]: raise ValueError("same-shape mismatch")
        for i,seed in enumerate(plan["seeds"]):
            order=[("native",1),("native",2),("fork",2)]
            random.Random(seed+p).shuffle(order)
            block=cell/f"block-{i}"
            rows={}
            for m,w in order:
                r=measure(block/f"{m}-{w}",c,seed,m,w)
                ends=[b["endpoint"] for b in r["branches"]]
                rows[f"{m}-{w}"]=dict(wall_s=r["through_cleanup_ns"]/1e9,parent_s=r["parent_prefill_ns"]/1e9,
                    marginal_s=(r["through_cleanup_ns"]-max(b["done_ns"] for b in r["branches"][:2]))/(n-2)/1e9,
                    create_ms=r["snapshot_create_ns"]/1e6,restore_ms=r["restore_ns"]/1e6,
                    cleanup_ms=(r["drop_ns"]+r["postrun_slot_clear_ns"])/1e6,
                    peak_gib=r["memory"]["cleared"]["peak_footprint"]/2**30,tokens=ends,work=r["key"]["work"])
            if len({r["work"] for r in rows.values()})!=1: raise ValueError("unmatched work")
            equal=len({tuple(r["tokens"]) for r in rows.values()})==1
            save(block/"pair.json",dict(order=order,seed=seed,modes=rows,endpoints_agree=equal))
            if not equal: raise ValueError("endpoint disagreement; needs matched replay on this tree")
            print(p,n,seed,flush=True)
if __name__=="__main__":
    main()
