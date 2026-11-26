"""Exercise the packaged Qwen main/parent copy with two real requests and cancellation."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

SPRINT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SPRINT.parent / "strata-fork-scaling/tools"))
from runner import Wire, memory


def run(binary):
    source = SPRINT / "runs/S02/n2-block0/D"
    config = json.loads((source / "input.json").read_text())
    expected = json.loads((source / "result.json").read_text())["tokens"]
    out = SPRINT / "runs/engineering/qwen"
    out.mkdir(exist_ok=True,parents=True)
    args = [str(binary), *config["cmd"][1:]]
    env = dict(os.environ)
    env.update({k:v for k,v in config["env"].items() if k.startswith("STRATA_METAL_") and
                k not in ("STRATA_METAL_KERNELS","STRATA_METAL_ENGINE_KERNELS","STRATA_METAL_DATA")})
    env["TURBINE_QWEN_FORK"] = "1"
    parent = config["jobs"]["0"]["ids"][:-1]
    ids = lambda x: ",".join(map(str,x))
    with (out / "metal.log").open("a") as log, subprocess.Popen(args,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=log,text=True,env=env) as proc:
        try:
            wire = Wire(proc)
            info=[]
            while True:
                line=wire.line()
                if line.startswith("INFO "):info.extend(line.split())
                if line.startswith("READY"):break
            assert {"batch_slots=2","native_parent_fork=1"}.issubset(info),info
            assert wire.ctrl("BGEN 2 2 178,179","ERR")
            assert wire.ctrl("STATE_RESTORE MAIN 7","ERR")==["invalid","snapshot","handle"]
            wire.send("GEN 1 temperature=0 "+ids(parent))
            while not wire.line().startswith("DONE "):pass
            handle,n=wire.ctrl("STATE_SAVE MAIN","SAVED")
            assert int(n)==len(parent)
            assert wire.ctrl("STATE_SAVE MAIN","ERR")
            assert wire.ctrl(f"STATE_RESTORE MAIN {int(handle)^1}","ERR")==["invalid","snapshot","handle"]
            # A targeted co-read into the reserved row must be ignored just like any out-of-range row.
            wire.send("BCO 2 101,102,103")
            tokens={str(i):[] for i in range(2)}
            for slot in range(2):
                wire.send(f"STATE_RESTORE MAIN {handle}\nBGEN {slot} 16 temperature=0 "+ids(config["jobs"][str(slot)]["ids"]))
            completed=set()
            admitting=0
            restores=0
            while len(completed)<2:
                f=wire.line().split()
                if f[0]=="RESTORED":
                    assert f[1:]==[n];restores+=1
                elif f[0]=="T":tokens[str(admitting)].append(int(f[1]))
                elif f[0]=="BADM":
                    assert int(f[1])==admitting;admitting+=1
                elif f[0]=="BT":tokens[f[1]].append(int(f[2]))
                elif f[0]=="BDONE":completed.add(f[1])
                elif f[0] in ("ERR","FATAL"):raise ValueError(f)
            assert tokens==expected and restores==2
            wire.ctrl(f"STATE_RESTORE MAIN {handle}","RESTORED")
            wire.send("BGEN 1 128 temperature=0 "+ids(parent+[343]))
            while not wire.line().startswith("BADM 1 "):pass
            wire.send(f"BSTOP 1\nSTATE_DROP {handle}")
            dropped=False
            cancelled=False
            while not (dropped and cancelled):
                line=wire.line()
                if line=="DROPPED":dropped=True
                if line.startswith("BDONE 1 "):
                    if "cancel" not in line:raise ValueError(line)
                    cancelled=True
            assert wire.ctrl(f"STATE_RESTORE MAIN {handle}","ERR")==["invalid","snapshot","handle"]
            wire.send("GEN 1 temperature=0 "+ids(parent))
            while not wire.line().startswith("DONE "):pass
            samples=[]
            for i in range(26):
                h,n=wire.ctrl("STATE_SAVE MAIN","SAVED")
                wire.ctrl(f"STATE_RESTORE MAIN {h}","RESTORED")
                wire.ctrl(f"STATE_DROP {h}","DROPPED")
                if i in (5,25):samples.append(memory(proc.pid))
            growth=samples[-1]["footprint"]-samples[0]["footprint"]
            peak=memory(proc.pid)["peak_footprint"]
            assert growth<=16*2**20 and peak<=32*2**30,(growth,peak)
            wire.send("QUIT")
            assert proc.wait(timeout=15)==0
            report=dict(matched_tokens=sum(map(len,tokens.values())),peak_bytes=peak,
                        reserved_slot_inaccessible=True,stale_handle_rejected=True,cancelled=cancelled,
                        drop_acknowledged=dropped,cycles=26,retained_bytes=growth,samples=samples)
            (out/"result.json").write_text(json.dumps(report,indent=2)+"\n")
            print(report)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("binary",type=Path)
    a=p.parse_args()
    def timeout(*args):raise TimeoutError("Qwen state lifecycle check stalled")
    signal.signal(signal.SIGALRM,timeout);signal.alarm(240)
    run(a.binary.resolve())
