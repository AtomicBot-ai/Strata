"""Targeted release checks for native state, cancellation, lifecycle and memory bounds."""
import argparse
import contextlib
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys

S=Path(__file__).resolve().parents[1]
ROOT=S.parents[1]
sys.path.insert(0,str(S.parent/"strata-fork-scaling/tools"))
from runner import MODEL,Wire,addressed,cold,memory
from marginal_run import save

@contextlib.contextmanager
def engine(binpath,budget,log,diag):
    with log.open("a") as err,subprocess.Popen([str(binpath),"--serve","--native",str(MODEL),"--draft","off","--kv","fp16","--parallel","2","--chunk","128","--max-context","768","--no-anti-loop"],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,
            env=dict(os.environ,TURBINE_SNAPSHOT_MIB=str(budget),**({"TURBINE_TEST_LOGITS":"1"} if diag else {}))) as proc:
        try:
            w=Wire(proc);info,ready=w.line(),w.line()
            assert f"native_fork={int(bool(budget))}" in info.split() and ready.split()[:2]==["READY","768"]
            yield w
        finally:
            if proc.poll() is None:
                try:proc.stdin.write("QUIT\n");proc.stdin.flush();proc.wait(timeout=10)
                except (BrokenPipeError,subprocess.TimeoutExpired):proc.kill();proc.wait()

def prefill(w,slot,ids):
    w.send(f"BGEN {slot} 0 ckpt=0 "+",".join(map(str,ids)))
    while True:
        l=w.line()
        if l==f"BADM {slot} 0": return
        if not l.startswith(("DONE ","PP ","RESUME ")):raise ValueError(l[:75])

def main():
    p=argparse.ArgumentParser();p.add_argument("--binary",type=Path,required=True);p.add_argument("--diag",action="store_true")
    a=p.parse_args()
    folder=S/"runs/engineering"/("diagnostic" if a.diag else "release")
    folder.mkdir(parents=True,exist_ok=True)
    log=folder/"engine.log"
    signal.alarm(240)
    parent=[178+i%137 for i in range(191)]
    other=[566-i%31 for i in range(100)]
    result=dict(binary_sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest())
    with engine(a.binary,1,log,a.diag) as w:
        prefill(w,0,parent)
        result["budget_refusal"]=w.ctrl("STATE_SAVE 0","ERR")
        assert "budget" in result["budget_refusal"]
    with engine(a.binary,32,log,a.diag) as w:
        result["empty_refusal"]=w.ctrl("STATE_SAVE 0","ERR")
        prefill(w,0,parent)
        result["long_parent_over_32mib"]=w.ctrl("STATE_SAVE 0","ERR")
        assert "budget" in result["long_parent_over_32mib"]
        cold(w)
        parent=parent[:63]
        prefill(w,0,parent)
        handle,count,size=w.ctrl("STATE_SAVE 0","SAVED")
        assert int(count)==len(parent) and 0<int(size)<=32*2**20
        result["permitted_payload_bytes"]=int(size)
        result["replacement_refused"]=w.ctrl("STATE_SAVE 0","ERR")
        result["stale_refused"]=w.ctrl(f"STATE_RESTORE 1 {int(handle)^1}","ERR")
        assert result["stale_refused"]==["invalid","snapshot","handle"]
        assert w.ctrl(f"STATE_RESTORE 1 {handle}","RESTORED")==[count]
        if a.diag:
            toks,v,log1=addressed(w,1,parent+[811],count=6)
            cold(w);prefill(w,1,parent)
            rt,rv,_=addressed(w,1,parent+[811],count=6)
            assert v==rv and len(v)==200058*4 and toks==rt
            result["same_shape_exact"]=True
            cold(w)
            prefill(w,0,other)
            w.ctrl(f"STATE_RESTORE 1 {handle}","RESTORED")
            t0,v0,_=addressed(w,0,other+[601],count=6)
            cold(w)
            prefill(w,0,other)
            tr,vr,_=addressed(w,0,other+[601],count=6)
            assert v0==vr and t0==tr
            result["unrelated_resident_slot_exact"]=True
        w.ctrl(f"STATE_RESTORE 1 {handle}","RESTORED")
        w.send("BGEN 1 400 temperature=0 "+",".join(map(str,parent+[711])))
        while True:
            l=w.line()
            if l=="BADM 1 1":break
            if l.startswith(("ERR","BDONE")):raise ValueError(l)
        w.send(f"STATE_RESTORE 1 {handle}\nSTATE_DROP {handle}\nBSTOP 1")
        saw=set()
        while len(saw)<3:
            l=w.line()
            if l.startswith("ERR invalid command or busy slot"):saw.add("busy_refused")
            elif l=="DROPPED":saw.add("dropped")
            elif l.startswith("BDONE 1 ") and "cancel" in l:saw.add("cancelled")
            elif l.startswith(("BDONE ","ERR ")) and "cancel" not in l:raise ValueError(l)
        result["abort"]=sorted(saw)
        w.ctrl(f"STATE_RESTORE 1 {handle}","ERR")
        if a.diag:
            t,v,events=addressed(w,1,other,count=6)
            cold(w)
            rt,rv,_=addressed(w,1,other,count=6)
            assert v==rv and t==rt and not any(e[0]=="RESUME" for e in events)
            result["post_cancel_unrelated_exact"]=True
        cold(w);prefill(w,0,parent)
        samples=[]
        for i in range(110):
            new,_,_=w.ctrl("STATE_SAVE 0","SAVED")
            w.ctrl(f"STATE_RESTORE 1 {new}","RESTORED")
            w.ctrl(f"STATE_DROP {new}","DROPPED")
            if i in (9,109):samples.append(memory(w.proc.pid))
        retained=samples[-1]["footprint"]-samples[0]["footprint"]
        assert retained<=16*2**20
        result.update(lifecycle_cycles=110,retained_bytes=retained,samples=samples)
    with engine(a.binary,0,log,a.diag) as w:
        result["disabled_refusal"]=w.ctrl("STATE_SAVE 0","ERR")
        assert result["disabled_refusal"]==["native","fork","disabled"]
    result["status"]="passed";save(folder/"result.json",result)
    signal.alarm(0)
    print("native state checks passed",folder.name,flush=True)
if __name__=="__main__":
    def timeout(*_):raise TimeoutError("state check stalled")
    signal.signal(signal.SIGALRM,timeout)
    main()
