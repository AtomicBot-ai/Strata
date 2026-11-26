"""Finite, restartable experiment for paired marginal cost. One process owns the GPU."""
import argparse
import fcntl
import hashlib
import itertools
import random
import signal
import time
from pathlib import Path

import numpy as np

from marginal_run import BIN, LAB, OUT, arm, metrics, read, save

DEV = 70281
AUDIT = 71381
SEEDS = list(range(72401,72409))
EXTRA = list(range(73501,73504))
MODES = ("native","fork")
CORE = [(p,n,128,warm,2) for warm in (True,False) for p in (4096,16384) for n in ((2,8) if warm else (2,4,8))]
MORE = ([(p,n,128,True,2) for p,n in itertools.product((4096,16384),(4,16))] +
        [(4096,n,s,True,2) for s,n in itertools.product((512,1024),(2,8))]+[(4096,8,128,True,1)])
ALL = CORE+MORE


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def shuffled(items,*key):
    items=list(items)
    random.Random('/'.join(map(str,key))).shuffle(items)
    return items


def cell(c):
    p,n,s,warm,slots=c
    return OUT/f"{'warm' if warm else 'cold'}-p{p}-n{n}-s{s}-c{slots}"


def run_arm(c, seed, parent, mode, width, diag=False):
    folder=parent/f"{mode}-w{width}"
    # A killed process can leave a verified partial attempt. Never overwrite it.
    if folder.exists() and not (folder/"result.json").exists():
        folder.rename(folder.with_name(f"{folder.name}-interrupted-{time.time_ns()}"))
    signal.alarm(1800)
    try:
        return arm(folder,c[:4],seed,mode,c[4],width,diag)
    finally:
        signal.alarm(0)


def selection(c):
    folder=cell(c)
    path=folder/"selection.json"
    if path.exists(): return read(path)
    times={mode:{} for mode in MODES}
    for mode,width in shuffled(itertools.product(MODES,range(1,c[4]+1)),DEV,c):
        row=run_arm(c,DEV,folder/"dev",mode,width)
        times[mode][width]=row["elapsed_ns"]
    best={mode:min(items,key=items.get) for mode,items in times.items()}
    save(path,dict(seed=DEV,elapsed_ns=times,best=best))
    return read(path)


def audit(c,seed):
    folder=cell(c)/f"audit-{seed}"
    proof=folder/"gate.json"
    if proof.exists():
        gate=read(proof)
        if gate["status"]!="passed": raise ValueError(proof)
        return gate
    outputs={}
    for mode,width in shuffled(itertools.product((*MODES,"replay"),range(1,c[4]+1)),seed,c,"audit"):
        run_arm(c,seed,folder,mode,width,diag=True)
        outputs[mode,width]=np.load(folder/f"{mode}-w{width}/endpoints.npy",mmap_mode="r")
    rows=[]
    exact=True
    for w in range(1,c[4]+1):
        for i in range(c[1]):
            fork=outputs["fork",w][i]
            ref=outputs["replay",w][i]
            match=fork.tobytes()==ref.tobytes()
            exact=exact and match
            controls={}
            for v in range(1,c[4]+1):
                native=outputs["native",v][i]
                ctrl=metrics(native,ref)
                controls[str(v)]=dict(replay=ctrl,candidate=ctrl if match else metrics(native,fork))
            rows.append(dict(width=w,branch=i,exact=match,native_controls=controls))
    save(proof,dict(status="passed" if exact else "exact_mismatch",seed=seed,branches=rows))
    if not exact: raise ValueError(proof)
    return read(proof)


def paired_block(c,seed,block,all_widths):
    base=cell(c)/f"tree-{seed}/block-{block}"
    if (base/"pair.json").exists(): return
    best=selection(c)["best"]
    audit(c,AUDIT)
    choices=shuffled(itertools.product(MODES,range(1,c[4]+1)),seed,c,"paired")
    if block%2: choices.reverse()
    results={}
    for mode,w in choices:
        if all_widths or best[mode]==w:
            results[mode,w]=run_arm(c,seed,base,mode,w)
    n,f=[results[m,best[m]] for m in MODES]
    if n["key"]["work"]!=f["key"]["work"]: raise ValueError("unpaired tree")
    endpoints={key:tuple(b["endpoint"] for b in row["branches"]) for key,row in results.items()}
    if len(set(endpoints.values()))>1:
        g=audit(c,seed)
        for (mode,w),actual in endpoints.items():
            replay=read(cell(c)/f"audit-{seed}/{mode}-w{w}/result.json")
            if actual!=tuple(b["endpoint"] for b in replay["branches"]):
                raise ValueError(("timed endpoint could not be reproduced",base,mode,w))
    all_fixed={str(w):results["native",w]["elapsed_ns"]/results["fork",w]["elapsed_ns"]
               for w in range(1,c[4]+1) if ("native",w) in results and ("fork",w) in results}
    save(base/"pair.json",dict(seed=seed,block=block,best=best,order=[[m,w] for m,w in results],
         config=c,work=n["key"]["work"],elapsed_ns={m:results[m,best[m]]["elapsed_ns"] for m in MODES},
         ratio=n["elapsed_ns"]/f["elapsed_ns"],fixed_width=all_fixed,endpoints_equal=len(set(endpoints.values()))==1))
    print(cell(c).name,seed,block,round(n["elapsed_ns"]/f["elapsed_ns"],4),flush=True)


def run():
    files=[LAB/"E03-M.md",Path(__file__),LAB/"tools/marginal_run.py",LAB/"tools/runner.py",LAB/"tools/e02r.py"]
    metadata=dict(provenance={p.name:sha(p) for p in files},binary_sha256=sha(BIN),
                  development=DEV,audit=AUDIT,core_seeds=SEEDS,extension_seeds=EXTRA,core=CORE,extra=MORE)
    import json
    path=OUT/"freeze.json"
    if sha(BIN)!=read(LAB/"runs/E03/review-b28ca95/protocol.json")["candidate_sha256"]:
        raise ValueError("different Strata build")
    if not path.exists(): save(path,metadata)
    if read(path)!=json.loads(json.dumps(metadata)): raise ValueError("frozen design differs")
    # Publish an early paired 2-to-8 observation before the remaining randomized blocks.
    for c in shuffled([x for x in CORE if x[0]==4096 and x[3]],SEEDS[0],"first"):
        paired_block(c,SEEDS[0],0,True)
    for i,seed in enumerate(SEEDS):
        for b in range(2):
            for c in shuffled(CORE,seed,b,"cells"):
                paired_block(c,seed,b,i==0 and b==0)
        if i<len(EXTRA):
            for c in shuffled(MORE,EXTRA[i],"extensions"):
                paired_block(c,EXTRA[i],0,i==0)
    save(OUT/"complete.json",dict(status="completed",expected_core_pairs=len(CORE)*len(SEEDS)*2,
                                   expected_extra_pairs=len(MORE)*len(EXTRA)))


if __name__=="__main__":
    OUT.mkdir(parents=True,exist_ok=True)
    def timeout(*_): raise TimeoutError("one measured arm exceeded 1800 seconds")
    signal.signal(signal.SIGALRM,timeout)
    with (OUT/"study.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run()
