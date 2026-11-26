"""Measure cold or resident fan-out with the existing Strata 0.1.69 lab protocol."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from e02r import metrics
from runner import BUILD, LAB, MODEL, Wire, fingerprint, fixture, memory, wave

BIN = BUILD / "review-fork-build/strata-inkling"
OUT = LAB / "runs/E03-M"
CLOCK = time.monotonic_ns


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def workload(p, n, s, seed, resident):
    # All N and S cuts share exactly the same first k continuations.
    roots, tails = fixture(p, 16, 1024, seed)
    parent = roots[0] if resident else roots[0][:-1]
    # Warm children append a distinct ingress token to the very same resident parent.
    prompts = [parent + [60000+i] for i in range(n)] if resident else [roots[0]]*n
    return parent, prompts, [tail[:s] for tail in tails[:n]]


class TimedWire(Wire):
    def line(self):
        line = super().line()
        if line.startswith("T "):
            _, name, _ = line.split()
            self.first_token.setdefault(name, CLOCK())
        return line


@contextlib.contextmanager
def engine(folder, context, slots, diagnostics):
    cmd = [str(BIN), "--serve", "--native", str(MODEL), "--draft", "off", "--kv", "fp16",
           "--max-context", str(context), "--chunk", "128", "--parallel", str(slots), "--no-anti-loop"]
    with (folder/"metal.log").open("x") as log, subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=log, text=True, env=dict(os.environ, STRATA_SCALING_LAB="1")) as proc:
        w = TimedWire(proc)
        w.first_token = {}
        try:
            info, ready = w.line(), w.line()
            save(folder/"engine.json",dict(cmd=cmd,info=info,ready=ready))
            flags = {"engine=strata-inkling-0.1.69","backend=metal","drafting=off","kv_dtype=fp16",
                     "ckpt_key=1","shared_prefix=0",f"batch_slots={slots}"}
            if not flags.issubset(info.split()) or ready.split()[:2]!=["READY",str(context)]:
                raise ValueError((info,ready))
            if diagnostics:
                w.ctrl("LABLOGITS","OK")
            yield w
        finally:
            if proc.poll() is None:
                try:
                    w.send("QUIT")
                    proc.wait(timeout=12)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait()


def clear(w, slots):
    for slot in range(slots):
        w.ctrl(f"BCO {slot} 1","BCOK")


def prime(w, slot, ids, checkpoint):
    opts = "" if checkpoint else "ckpt=0 "
    w.send(f"BGEN {slot} 0 temperature=0 {opts}" + ",".join(map(str,ids)))
    reused = None
    while True:
        parts = w.line().split()
        if parts[0]=="DONE":
            if int(parts[2])!=len(ids):
                raise ValueError(parts)
            reused=int(parts[-1])
        elif parts[0]=="BADM":
            if parts[1:]!=[str(slot),"0"] or reused!=0:
                raise ValueError(("cold prime",parts,reused))
            return
        elif parts[0]!="PP":
            raise ValueError(parts[:6])


def arm(folder, config, seed, mode, slots, width, diag=False):
    p,n,s,resident=config
    parent,prompts,tails=workload(*config[:3],seed,resident)
    key=dict(config=list(config),seed=seed,mode=mode,slots=slots,width=width,diag=diag,
             work=fingerprint([parent,prompts,tails]))
    result=folder/"result.json"
    if result.exists():
        row=read(result)
        if row["key"]!=key: raise ValueError(result)
        if diag:
            raw=folder/"endpoints.npy"
            if hashlib.sha256(raw.read_bytes()).hexdigest()!=row["raw_sha256"]: raise ValueError(raw)
        return row
    folder.mkdir(parents=True,exist_ok=False)
    save(folder/"input.json",key)
    try:
        with engine(folder,p+s+32,slots,diag) as w:
            # Same warm-up and idle/cold slot policy on every fresh process.
            wave(w,[("warmup",[41,57,73],2,"temperature=0 ckpt=0")])
            clear(w,slots)
            mem=lambda: memory(w.proc.pid)
            mems={"before":mem()}
            parent_ns=create_ns=restore_ns=drop_ns=0
            payload=0
            initial=CLOCK()
            if resident or mode=="fork":
                prime(w,0,parent,checkpoint=resident)
                parent_ns=CLOCK()-initial
            mems["parent"]=mem()
            start=CLOCK() if resident else initial
            if mode=="fork":
                mark=CLOCK()
                count,payload=map(int,w.ctrl("LABSAVE 0","SAVED"))
                create_ns=CLOCK()-mark
                if count!=len(parent) or payload<=0: raise ValueError(("snapshot",count,payload))
            mems["after_create"]=mem()
            rows=[]
            vectors=[]
            waves=[]
            for base in range(0,n,width):
                size=min(width,n-base)
                if mode=="replay":
                    clear(w,slots)
                    for slot in range(size): prime(w,slot,parent,checkpoint=resident)
                if mode=="fork":
                    for slot in range(size):
                        if base or slot:
                            mark=CLOCK()
                            if w.ctrl(f"LABRESTORE {slot}","RESTORED")!=[str(len(parent))]:
                                raise ValueError("restore boundary")
                            restore_ns+=CLOCK()-mark
                jobs=[]
                for i in range(base,base+size):
                    # Native engine keeps its own prompt-end checkpoint for subsequent children.
                    ckpt="" if mode=="native" and i+width<n else " ckpt=0"
                    opts=f"temperature=0 seed={100+i}{ckpt} teacher="+",".join(map(str,tails[i]))
                    jobs.append((str(i),prompts[i],s+1,opts))
                dispatch=CLOCK()
                done,dist=wave(w,jobs)
                for i in range(base,base+size):
                    k=str(i)
                    row=done[k]
                    if row["tokens"][:-1]!=tails[i] or row["prompt"]!=len(prompts[i]):
                        raise ValueError(("unfinished work",i))
                    if (mode in ("fork","replay") or (resident and i==0)) and row["reused"]!=len(parent):
                        raise ValueError(("reuse",mode,i,row["reused"],len(parent)))
                    first=w.first_token[k]
                    rows.append(dict(branch=i,dispatch_ns=dispatch-start,first_ns=first-start,
                                     done_ns=row["end_ns"]-start, reused=row["reused"],
                                     engine_prefill_ms=row["prefill_ms"],engine_decode_ms=row["decode_ms"],
                                     endpoint=row["tokens"][-1]))
                    if diag:
                        vec=np.frombuffer(dist[k],dtype="<f4")
                        if vec.shape!=(200058,) or not np.isfinite(vec).all() or int(vec.argmax())!=row["tokens"][-1]:
                            raise ValueError("invalid endpoint")
                        vectors.append(vec)
                firsts=[w.first_token[str(i)] for i in range(base,base+size)]
                last=max(row["end_ns"] for row in done.values())
                waves.append(dict(first_branch=base,size=size,queue_ns=dispatch-start,
                                  dispatch_to_first_ns=min(firsts)-dispatch,
                                  mixed_ns=max(firsts)-min(firsts),last_first_to_done_ns=last-max(firsts),
                                  physical=mem()))
            children_done=CLOCK()
            if mode=="fork":
                mark=CLOCK()
                w.ctrl("LABDROP","DROPPED")
                drop_ns=CLOCK()-mark
            end=CLOCK()
            mems["end"]=mem()
            mark=CLOCK()
            clear(w,slots)
            clear_ns=CLOCK()-mark
            mems["cleared"]=mem()
        record=dict(key=key,elapsed_ns=end-start,through_cleanup_ns=end-start+clear_ns,
                    parent_prefill_ns=parent_ns,initial_parent_in_elapsed=not resident and mode=="fork",
                    snapshot_create_ns=create_ns,restore_ns=restore_ns,drop_ns=drop_ns,
                    postrun_slot_clear_ns=clear_ns,children_done_ns=children_done-start,
                    snapshot_bytes=payload,memory=mems,branches=rows,waves=waves)
        if diag:
            raw=folder/"endpoints.npy"
            np.save(raw,np.stack(vectors),allow_pickle=False)
            record["raw_sha256"]=hashlib.sha256(raw.read_bytes()).hexdigest()
        save(result,record)
        return record
    except BaseException as exc:
        save(folder/"failure.json",dict(error=repr(exc)))
        raise
