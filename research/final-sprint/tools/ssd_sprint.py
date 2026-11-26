"""Bounded S02/S03 on Qwen Metal. Physical disk, process IO, routed decode cache and all completions."""
import argparse
import collections
import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

from tokenizers import Tokenizer
from tokenizers.models import BPE
from tokenizers.pre_tokenizers import ByteLevel

SPRINT=Path(__file__).resolve().parents[1]
ROOT=SPRINT.parents[1]
sys.path.insert(0,str(SPRINT.parent/"strata-fork-scaling/tools"))
from runner import memory
from marginal_run import read,save

MODEL=Path.home()/"code/models/qwen38-iq3"
PACK=ROOT/".work/ssd-qwen-pack"
ENGINE=ROOT/".work/final-sprint/qwen-build/strata"
METAL=ROOT/"Atomic-Turbine/engine/metal"
CAP=16
SEEDS=[84201,84202,84203]


def inputs(study,n):
    tok=Tokenizer(BPE.from_file(str(PACK/"tokenizer/vocab.json"),str(PACK/"tokenizer/merges.txt")))
    tok.pre_tokenizer=ByteLevel(add_prefix_space=False)
    stems=["Write a long numbered guide to sorting a list. Include at least 100 detailed entries. Begin by writing a paragraph about",
           "Write a long numbered guide to growing an orchard. Include at least 100 detailed entries. Begin by writing a paragraph about"]
    tails=[[" selecting"," comparing"," counting"," splitting"],[" watering"," pruning"," fencing"," planting"]]
    jobs={}
    for i in range(n):
        family=i//4 if study=="S03" else 0
        # Unique initial request marker removes cross-request prompt reuse from the S03 order comparison.
        prefix=([1000+i] if study=="S03" else [])+tok.encode(stems[family]).ids[:22]
        ids=prefix+tok.encode(tails[family][i%4]).ids
        jobs[i]={"family":family,"ids":ids}
    if len({len(j["ids"]) for j in jobs.values()})!=1: raise ValueError("unequal input length")
    return jobs


def probe_disk():
    lib=ctypes.CDLL(str(ROOT/".work/ssd-counters.dylib"))
    lib.disk_read.restype=lib.process_read.restype=ctypes.c_int64
    if not lib.open_disk(b"disk0"): raise ValueError("disk0 unavailable")
    def sample(pid):
        d,p=lib.disk_read(),lib.process_read(pid)
        if min(d,p)<0: raise ValueError("invalid disk counter")
        return [time.monotonic_ns(),d,p]
    return sample


def one(folder,jobs,order,width,study,mode,probe=False,verify_copy=False):
    if (folder/"result.json").exists(): return read(folder/"result.json")
    if folder.exists(): folder.rename(folder.with_name(folder.name+f"-interrupted-{time.time_ns()}"))
    folder.mkdir(parents=True)
    args=[str(ENGINE),"--serve","--pack",str(PACK),"--native",str(next(MODEL.glob("*-00001-of-00002.gguf"))),
          "--ple-gguf",str(next(MODEL.glob("*-00002-of-00002.gguf"))),"--expert-profile",str(MODEL/"profile.bin"),
          "--max-context","512","--expert-cache","64","--batch","3" if study=="S02" else "2","--prefill","auto","--spec","2","--suffix-draft","0","--mmap-experts"]
    env=dict(STRATA_METAL_STREAM="1",STRATA_METAL_ARENA_GB="6",STRATA_METAL_STREAM_FAKE="0",
             STRATA_METAL_BATCH_ROWS="1",STRATA_METAL_PREFETCH="0",STRATA_METAL_PREFETCH2="0",
             STRATA_SSD_TRACE_ROWS="1",STRATA_METAL_KERNELS=str(METAL/"kernels"),
             STRATA_METAL_ENGINE_KERNELS=str(METAL/"src/engine/msl"),
             STRATA_METAL_DATA="/Applications/Strata.app/Contents/Resources/engine-bundle/0.1.65-macos-arm64-metal/metal/data")
    if study=="S02":
        env["TURBINE_S02_PROBE"]="1"
    if verify_copy:
        env["TURBINE_S02_VERIFY_COPY"]="1"
    save(folder/"input.json",dict(cmd=args,env=env,order=order,jobs=jobs,width=width))
    sample=probe_disk()
    with (folder/"metal.log").open("x") as log, subprocess.Popen(args,env=dict(os.environ,**env),text=True,
             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log) as proc:
        def line():
            l=proc.stdout.readline()
            if not l: raise RuntimeError(f"engine exited {proc.poll()}; see {folder}")
            return l.strip()
        def send(s):
            proc.stdin.write(s+"\n")
            proc.stdin.flush()
        try:
            while not line().startswith("READY"): pass
            if probe:
                # Actual documented file path interface. Batching must explicitly refuse before any write.
                send("SAVE "+str(folder/"capability-probe.state"))
                reply=line()
                while reply.startswith(("SESSION ","SWAIT ")): reply=line()
                save(folder/"capability.json",dict(reply=reply,shared_batch_capture_supported=not reply.startswith("SERR")))
                if not reply.startswith("SERR"): raise ValueError("unexpected batch snapshot capability; investigate")
            idle=sample(proc.pid)
            time.sleep(0.5)
            start=sample(proc.pid)
            fork=mode in ("B","D")
            common_length=len(jobs[0]["ids"])-1
            if study=="S02":
                # Same priming work, counted on the clock for all four modes. Native cache stays on.
                # GEN 1 consumes the shared prompt and emits one unconsumed prediction.
                # Stock Strata rejects its prefill-only GEN 0 when --batch is enabled.
                send("GEN 1 temperature=0 "+",".join(map(str,jobs[0]["ids"][:common_length])))
                priming=[]
                while True:
                    l=line();priming.append(l)
                    if l.startswith(("ERR","FATAL")):raise RuntimeError(l)
                    if l.startswith("DONE "):break
                if fork:
                    send("SPRINT_SAVE");reply=line()
                    if reply!=f"SSAVED {common_length}":raise ValueError(("Qwen snapshot capture",reply,common_length))
            else:
                priming=[]
            restores=0
            active={}
            remaining=collections.deque(order)
            tokens={i:[] for i in order}
            latency={}
            commands=collections.deque()
            events=[]
            admission_tokens=[]
            admission_count=None
            reuse={}
            def admit(slot):
                i=remaining.popleft()
                active[slot]=i
                commands.append(slot)
                if fork:send("SPRINT_RESTORE")
                send(f"BGEN {slot} {CAP} temperature=0 "+",".join(map(str,jobs[i]["ids"])))
            for slot in range(width): admit(slot)
            while active:
                l=line()
                fields=l.split()
                events.append([time.monotonic_ns()-start[0],l])
                if not fields:continue
                if fields[0]=="SRESTORED":
                    if int(fields[1])!=common_length:raise ValueError(l)
                    restores+=1
                if fields[0] in ("ERR","FATAL","SREFUSED"): raise RuntimeError(l)
                if fields[0]=="T": admission_tokens.append(int(fields[-1]))
                elif fields[0]=="DONE" and commands:
                    admission_count=int(fields[1])
                    # The first DONE (admission) prints a native reused-token counter after the draft counters.
                    if len(fields)>=9: reuse[active[commands[0]]]=int(fields[8])
                elif fields[0]=="BADM":
                    slot=int(fields[1])
                    if (commands.popleft()!=slot or int(fields[2])!=1 or admission_count not in (0,1)
                            or len(admission_tokens)!=admission_count):
                        raise ValueError(("bad admission",l,admission_tokens))
                    tokens[active[slot]].extend(admission_tokens)
                    admission_tokens.clear()
                    admission_count=None
                elif fields[0]=="BT":
                    tokens[active[int(fields[1])]].append(int(fields[2]))
                elif fields[0]=="BDONE":
                    slot=int(fields[1]);i=active.pop(slot)
                    if len(tokens[i])!=CAP:raise ValueError(("unexpected length",i,len(tokens[i]),l))
                    latency[i]=(time.monotonic_ns()-start[0])/1e9
                    if remaining: admit(slot)
            if fork:
                if restores!=len(jobs):raise ValueError("missing Qwen restore")
                send("SPRINT_DROP")
                if line()!="SDROPPED":raise ValueError("snapshot cleanup")
            end=sample(proc.pid)
            footprint=memory(proc.pid)
            send("QUIT")
            proc.wait(timeout=20)
            if proc.returncode: raise RuntimeError(f"engine quit {proc.returncode}")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    native_log=(folder/"metal.log").read_text().splitlines()
    checked=[l for l in native_log if l.startswith("S02_COPY ") and l.split()[2]=="2"]
    if verify_copy and (len(checked)!=len(jobs)+1 or any(not l.endswith("exact=1") for l in checked)):
        raise ValueError(("incomplete same-state copy proof",checked))
    counts=[list(map(int,l.split()[4:7])) for l in (folder/"metal.log").read_text().splitlines() if l.startswith("SSD_ROUTE ")]
    hits=sum(r[0] for r in counts); misses=sum(r[1] for r in counts)
    result=dict(wall_s=(end[0]-start[0])/1e9,device_read=end[1]-start[1],process_read=end[2]-start[2],
                idle_counter=idle,begin=start,end=end,cache_hits=hits,cache_misses=misses,
                routed_expert_read_bytes=sum(r[2] for r in counts),routed_cut_count=len(counts),
                hit_rate=hits/(hits+misses) if hits+misses else None,peak_footprint=footprint["peak_footprint"],
                tokens=tokens,end_to_end_latency_s=latency,reused=reuse,events=events,priming=priming,reserved_row_restores=restores,verified_copies=checked)
    if result["peak_footprint"]>32*2**30:raise ValueError("32 GiB measured process budget exceeded")
    save(folder/"result.json",result)
    return result


def main(study):
    out=SPRINT/"runs"/study
    out.mkdir(parents=True,exist_ok=True)
    plan=dict(study=study,counts=[2,4] if study=="S02" else [8],seeds=SEEDS,tokens=CAP,active_slots=2,allocated_slots=3 if study=="S02" else 2,arena_gib=6,
              engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(),qwen_revision="b28ca95",
              admission="FIFO to next free slot; all sequences available at time zero",
              s03_rule="median paired speedup >=1.10 OR median physical device reads reduction >=15%; median paired p95 latency ratio <=1.10 and each request median latency ratio <=1.10, equal work and stable outputs",
              capture="SSD_ROUTE counts cover routed decode rows exposed by the diagnostic hook; device IO covers the whole timed workload")
    if (out/"plan.json").exists() and read(out/"plan.json")!=plan: raise RuntimeError("plan differs")
    save(out/"plan.json",plan)
    for n in plan["counts"]:
        jobs=inputs(study,n)
        if study=="S02":
            for candidate,w in (("B",1),("D",2)):
                signal.alarm(600)
                try:one(out/f"n{n}-audit"/candidate,jobs,list(range(n)),w,study,candidate,verify_copy=True)
                finally:signal.alarm(0)
        for block,seed in enumerate(SEEDS):
            if study=="S02":
                candidates={m:(list(range(n)),1 if m in ("A","B") else 2) for m in ("A","B","C","D")}
            else:
                arrival=list(jobs)
                random.Random(seed).shuffle(arrival)
                mixed=arrival.copy()
                random.Random(seed+51).shuffle(mixed)
                candidates={"FIFO":(arrival,2),"shuffled":(mixed,2),
                            "family":(sorted(arrival,key=lambda i:jobs[i]["family"]),2)}
            modes=list(candidates)
            random.Random(seed+n).shuffle(modes)
            folder=out/f"n{n}-block{block}"
            results={}
            for mode in modes:
                signal.alarm(600)
                try: results[mode]=one(folder/mode,jobs,*candidates[mode],study,mode,probe=study=="S02" and n==2 and block==0 and mode=="C")
                finally: signal.alarm(0)
            baseline="A" if study=="S02" else "FIFO"
            # JSON keys can be strings when resuming a cached arm.
            canonical=lambda r: {str(k):v for k,v in r["tokens"].items()}
            tokens_ok={m:canonical(r)==canonical(results[baseline]) for m,r in results.items()}
            save(folder/"comparison.json",dict(seed=seed,order=modes,token_identity=tokens_ok))
            print(study,n,block,tokens_ok,flush=True)
if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("study",choices=["S02","S03"]);a=cli.parse_args()
    def timeout(*_):raise TimeoutError("engine trial exceeded ten minutes")
    signal.signal(signal.SIGALRM,timeout)
    main(a.study)
