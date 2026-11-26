"""Run one arm of the speculative-policy sprint using the original two fixtures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / ".work/spec-policy-fast"
RC = WORK / "Atomic-Turbine-0.1.0-e9559eaa"
sys.path.insert(0, str(HERE.parent / "fast-sprint"))
import run as previous

PROFILE = previous.profile
FIXTURES = previous.prompts
PACKAGE_SHA = "e9559eaac6e6a787a4b7853d554ee2c6cfb37c83"
HEAD = "1ca3ddef163053df8c882f2f83e8f88470831aac"
MODES = {"qwen": {"stock","eight","without-lookup","lookup-only","overlap"},
         "ink": {"plain","stock","adaptive","fixed-trace","dynamic","dynamic-trace","existing-probes"}}


def profile(family, mode, chat):
    original = {"plain":"off", "adaptive":"adapt", "fixed-trace":"adapt", "dynamic":"adapt",
                "dynamic-trace":"adapt", "existing-probes":"adapt", "lookup-only":"off"}.get(mode, "stock")
    args, env = PROFILE(family, original, chat)
    if family == "qwen":
        if "--draft-model" in args:
            args[args.index("--draft-model")+1] = str(ROOT / ".work/fast-sprint/qwen-dflash2.pack")
        args[args.index("--spec")+1] = "8" if mode == "eight" else "6"
        args[args.index("--suffix-draft")+1] = "0" if mode == "without-lookup" else "3"
        if mode == "overlap":
            env["STRATA_ADAPT_OVERLAP"] = "1"
    elif mode in {"dynamic","dynamic-trace","fixed-trace","existing-probes"}:
        args[0] = str(WORK / "build/strata-inkling")
        if mode == "existing-probes":
            args[0] = str(WORK / "existing-probes/strata-inkling")
        if mode != "fixed-trace":
            env["TURBINE_ADAPTIVE_PLAIN_COST"] = "1"
        if mode.endswith("trace"):
            env["TURBINE_POLICY_TRACE"] = "1"
    return args, env


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def append(path, record):
    with path.open("a") as f:
        print(json.dumps(record, ensure_ascii=False), file=f)


def run_arm(family, mode, label, mixed=False):
    if mode not in MODES[family] or not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
        raise ValueError("unknown profile or label")
    ledger = HERE / "processes.jsonl"
    entries = [json.loads(s) for s in ledger.read_text().splitlines()] if ledger.exists() else []
    if sum(e["event"]=="start" for e in entries) >= 28 or sum(e.get("seconds",0) for e in entries) > 45*60-250:
        raise SystemExit("sprint process/time limit")
    previous.PACKAGE = RC
    previous.WORK = WORK
    previous.profile = profile
    previous.prompts = FIXTURES
    if mixed:
        def mixed_fixture(family, chat):
            prompts = FIXTURES(family, chat)
            return {"warm":prompts["warm"], "mixed":prompts["code"][:140]+prompts["prose"][-128:]}
        previous.prompts = mixed_fixture
    args, env = profile(family, mode, family == "qwen")
    if args[0].startswith(str(RC)):
        manifest = json.loads((RC/"manifest.json").read_text())
        assert hashlib.sha256(Path(args[0]).read_bytes()).hexdigest() == manifest["files"][str(Path(args[0]).relative_to(RC))]
    for var in os.environ:
        if var.startswith(("STRATA_","TURBINE_","INK_METAL_")):
            raise SystemExit(f"unset inherited engine override {var}")
    log = WORK / f"{family}-{mode}-{label}.log"
    if log.exists(): raise SystemExit("label already used")
    if previous.others(): raise SystemExit("machine busy")
    started = utc()
    t0 = time.monotonic()
    rows = []
    previous.write = lambda row: rows.append(dict(row, recorded_utc=utc()))
    meta = dict(family=family, mode=mode, label=label, start_utc=started)
    append(ledger,dict(meta,event="start"))
    exclusion = None
    try:
        previous.run(family, mode, label, chat=family=="qwen")
    except BaseException as exc:
        exclusion = repr(exc)
        raise
    finally:
        stopped = utc()
        append(ledger,dict(meta,event="stop",stop_utc=stopped,seconds=time.monotonic()-t0,exclusion=exclusion))
        dest = HERE / "logs" / log.name
        dest.parent.mkdir(exist_ok=True)
        lines = []
        if log.exists():
            shutil.copyfile(log,dest)
            lines = dest.read_text().splitlines()
        chunks = re.split(r"(?=^strata draft: request \d+ )","\n".join(lines), flags=re.M)[1:]
        # For lookup-only there is no DFlash2 round log; use native prompt summaries to split requests.
        if not chunks:
            chunks = re.split(r"(?=^strata serve: prompt \d+ tokens = )","\n".join(lines),flags=re.M)[1:]
        pos = 0
        for index,r in enumerate(rows):
            r.update(source=PACKAGE_SHA if args[0].startswith(str(RC)) else HEAD,
                     log=str(dest.relative_to(ROOT)),start_utc=started,stop_utc=stopped,exclusion=exclusion,
                     effective_window=None, lookup_accepted=None,lookup_offered=None, lookup_rounds=None,
                     dflash_accepted=None, dflash_offered=None, emitted_per_round=None,tree_sizes=None)
            r["host_file_read_mb"] = float(r["done"][13]) if family == "qwen" and "done" in r else None
            if r.get("fixture") and family=="qwen" and index<len(chunks):
                chunk=chunks[index]
                w=re.search(r"window<=(\d+)",chunk)
                r["effective_window"]=int(w[1]) if w else None
                l=re.search(r"suffix drafts: (\d+) windows, (\d+) of (\d+) drafts accepted",chunk)
                # Native prints the suffix summary only when at least one such window fired.
                lr,la,lo=map(int,l.groups()) if l else (0,0,0)
                r.update(lookup_rounds=lr,lookup_accepted=la,lookup_offered=lo,
                         dflash_accepted=r["accepted"]-la if mode!="lookup-only" else None,
                         dflash_offered=r["offered"]-lo if mode!="lookup-only" else None)
                if r.get("draft_rounds"):
                    r["emitted_per_round"]=len(r["output_ids"])/r["draft_rounds"]
            if family=="ink" and mode.endswith("trace") and "input_ids" in r:
                # Anchor positions restart at the prompt length for each request.
                if index==0:
                    events=[{k:float(v) for k,v in re.findall(r"(\w+)=([\d.]+)",s)} for s in lines if s.startswith("policy ")]
                end=len(r["input_ids"])+len(r["output_ids"])
                group=[]
                while pos<len(events) and len(r["input_ids"])<=events[pos]["pos"]<end:
                    group.append(events[pos]); pos+=1
                r["round_trace"]=group
                r["tree_sizes"]=[int(e["nodes"]) for e in group]
                r["verify_gpu_ms"]=sum(e["verify_gpu_ms"] for e in group)
                r["plain_steps"]=len(r["output_ids"])-1-sum(int(e["emit"]) for e in group)
                # A gap between speculative intervals denotes one or more true plain steps.
                mask=[False]*(len(r["output_ids"])-1)
                for e in group:
                    i=int(e["pos"])-len(r["input_ids"])
                    for j in range(i,min(i+int(e["emit"]),len(mask))): mask[j]=True
                r["mode_switches"]=sum(a!=b for a,b in zip(mask,mask[1:]))
            append(HERE/"results.jsonl",r)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("family",choices=MODES)
    p.add_argument("mode")
    p.add_argument("label")
    p.add_argument("--mixed",action="store_true")
    a=p.parse_args()
    run_arm(a.family,a.mode,a.label,a.mixed)
