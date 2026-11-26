import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "research/fast-sprint"))
from run import HERE, others, run

deadline = time.monotonic()+75*60

def once(fam, mode, key):
    attempt=0
    while time.monotonic()<deadline:
        if others():
            time.sleep(8)
            continue
        time.sleep(4)
        if others():
            continue
        attempt+=1
        label="chat-"+(key if attempt==1 else f"{key}-retry{attempt}")
        try:
            run(fam, mode, label, chat=True)
        except (RuntimeError, SystemExit) as exc:
            if "external workload" in str(exc) or "Machine busy" in str(exc):
                print("giving way to another job",flush=True)
                continue
            print(fam,mode,label,str(exc),flush=True)
            return {}
        return {r["fixture"]:r for l in (HERE/"results.jsonl").read_text().splitlines()
                if (r:=json.loads(l))["family"]==fam and r["mode"]==mode and r["label"]==label and "fixture" in r}
    raise SystemExit("elapsed-time limit")

def equivalent(ref, candidate):
    return all(key in ref and key in candidate and ref[key]["output_ids"]==candidate[key]["output_ids"] for key in ("code","prose"))

def pairs(fam,ref):
    mode="tree" if fam=="ink" else "stock"
    a=once(fam,mode,"pair1")
    if not a: return
    b=once(fam,"narrow","pair1")
    if not equivalent(ref,b) or not equivalent(a,b):
        print(fam,"greedy parity gate did not pass: remaining performance repeats skipped",flush=True)
        return
    for other,key in [("narrow","pair2"),(mode,"pair2"),(mode,"pair3"),("narrow","pair3")]:
        row=once(fam,other,key)
        if not equivalent(ref,row): return


qref=once("qwen","off","reference")
if qref: pairs("qwen",qref)
