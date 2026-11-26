"""Local OpenCode client against the real Strata HTTP server, isolated three-task fixture."""
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

S=Path(__file__).resolve().parents[1]
ROOT=S.parents[1]
TERMINAL=ROOT/"Atomic-Turbine/terminal"
SCRATCH=ROOT/".work/final-sprint"
OUT=S/"runs/S04"
CLI=Path("/Applications/OpenCode.app/Contents/Resources/opencode-cli")
sys.path.insert(0,str(S.parent/"strata-fork-scaling/tools"))
from runner import MODEL, memory
from marginal_run import save,read

TASKS=[
("inspect","Inspect this Strata repository. Use grep and read. Where does shape_engine_fetch install the Inkling engine, and where does it obtain the update feed? Cite the exact files and function names. Keep the answer short."),
("repair","Fix Strata issue 7119 in terminal/setup.py (function shape_engine_fetch). If shape_engine.ensure emits a concrete failure reason and returns None, the GUI sees only fail()'s message and hint. The current hint refers to an invisible line above. Include the actual emitted reason in that hint, preserve the command-line progress messages and STRATA_ALLOW_NO_ENGINE behavior. Use tools to inspect and edit the actual file."),
("parallel","Use two explore subagents concurrently (two task calls in one message). Ask one to trace engine selection in terminal/strata_control/shape_engine.py and one to trace manifest validation in terminal/strata_control/engine_component.py. Wait for both and report one finding per file.")]



def main():
    OUT.mkdir(parents=True,exist_ok=True)
    project=SCRATCH/"s04-fixture"
    project.mkdir(exist_ok=True)
    setup_file=project/"terminal/setup.py"
    if not setup_file.is_file():
        raise ValueError("prepare the isolated upstream Strata fixture at e83de74 before S04")
    cfg=SCRATCH/"s04-api.json"
    with socket.socket() as so:
        so.bind(("127.0.0.1",0))
        port=so.getsockname()[1]
    url=f"http://127.0.0.1:{port}"
    events=OUT/"wire.jsonl"
    events.touch(exist_ok=True)
    save(SCRATCH/"s04-wire-config.json",dict(binary=str(ROOT/".work/strata-scaling/review-fork-build/strata-inkling"),events=str(events)))
    save(cfg,dict(exe=str(S/"tools/strata-inkling-observer"),arch="inkling2_loop",tokenizer=str(SCRATCH/"ink-tokenizer"),
         model_name="inkling",args=["--serve","--native",str(MODEL),"--draft","off","--kv","fp16","--max-context","24576","--chunk","128","--parallel","2","--no-anti-loop"],
         host="127.0.0.1",port=port,open_browser=False))
    config=SCRATCH/"opencode-client.json"
    acl={"*":"deny","read":"allow","glob":"allow","grep":"allow","list":"allow","edit":"allow","apply_patch":"allow",
         "task":{"*":"deny","explore":"allow"},"subagent":"allow","external_directory":"deny"}
    save(config,dict(provider={"turbine":{"npm":"@ai-sdk/openai-compatible","name":"Atomic Turbine","options":{"baseURL":url+"/v1","apiKey":"local-smoke"},
                     "models":{"inkling":{"name":"Inkling","limit":{"context":24576,"output":1024}}}}},
                     enabled_providers=["turbine"],model="turbine/inkling",small_model="turbine/inkling",permission=acl,
                     share="disabled",autoupdate=False))
    env=dict(os.environ,PWD=str(project),PYTHONPATH=str(TERMINAL),STRATA_DATA_DIR=str(SCRATCH/"s04-server-state"),
             OPENCODE_CONFIG=str(config),OPENCODE_DISABLE_MODELS_FETCH="1",OPENCODE_DISABLE_AUTOUPDATE="1",
             OPENCODE_DISABLE_LSP_DOWNLOAD="1",OPENCODE_DISABLE_DEFAULT_PLUGINS="1",NO_COLOR="1",
             DO_NOT_TRACK="1",OTEL_SDK_DISABLED="true",
             NO_PROXY="localhost,127.0.0.1")
    for var,sub in [("XDG_DATA_HOME","data"),("XDG_CONFIG_HOME","config"),("XDG_STATE_HOME","state"),("XDG_CACHE_HOME","cache")]:
        env[var]=str(SCRATCH/"opencode"/sub)
    args=[sys.executable,"-B",str(TERMINAL/"serve/server.py"),"--engine","strata","--config",str(cfg),"--host","127.0.0.1",
          "--port",str(port),"--no-api-key","--offline","--parallel","2","--batch-telemetry"]
    log=OUT/f"server-{time.time_ns()}.log"
    with log.open("w") as stream,subprocess.Popen(args,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True) as server:
        try:
            for _ in range(180):
                if server.poll() is not None: raise RuntimeError(f"server exit {server.returncode}, see {log}")
                try:
                    with urllib.request.urlopen(url+"/v1/models",timeout=2) as reply:
                        models=json.load(reply)
                    break
                except OSError:time.sleep(1)
            else:raise TimeoutError("server startup")
            save(OUT/"instance.json",dict(models=models,argv=args,cli=subprocess.check_output([CLI,"--version"],env=env,text=True).strip()))
            for name,prompt in TASKS:
                folder=OUT/name
                if (folder/"result.json").exists():continue
                folder.mkdir(exist_ok=True)
                before=events.stat().st_size if events.exists() else 0
                t=time.monotonic()
                peaks=[]
                with (folder/"client.jsonl").open("w") as out,(folder/"client.log").open("w") as err:
                    cmd=[str(CLI),"run","--standalone","--format","json","-m","turbine/inkling",prompt]
                    with subprocess.Popen(cmd,env=env,stdout=out,stderr=err,cwd=project,start_new_session=True) as proc:
                        timed_out=False
                        while proc.poll() is None:
                            if events.exists():
                                latest=events.read_text().splitlines()[-1:]
                                if latest:
                                    try:peaks.append(memory(json.loads(latest[0])[1])["peak_footprint"])
                                    except (OSError,ValueError):pass
                            if (peaks and max(peaks)>32*2**30) or time.monotonic()-t>420:
                                os.killpg(proc.pid,signal.SIGTERM);timed_out=True
                                try:proc.wait(timeout=8)
                                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
                                break
                            time.sleep(1)
                with events.open("rb") as f:
                    f.seek(before); trace=[json.loads(l) for l in f if l.strip()]
                save(folder/"wire.json",trace)
                tools=[];text=[];errors=[]
                for l in (folder/"client.jsonl").read_text().splitlines():
                    try:d=json.loads(l)
                    except ValueError:continue
                    part=d.get("part") or {}
                    if part.get("tool"):tools.append(dict(name=part["tool"],state=part.get("state",{}).get("status")))
                    if part.get("type")=="text":text.append(part.get("text","")[:2000])
                    if d.get("type")=="error":errors.append(d.get("error"))
                active_slots=set()
                max_slots=0
                for _,_,_,tag,counts in trace:
                    if tag=="BADM" and len(counts)>1 and counts[1]:
                        active_slots.add(counts[0])
                        max_slots=max(max_slots,len(active_slots))
                    if tag=="BDONE" and counts:active_slots.discard(counts[0])
                save(folder/"result.json",dict(argv=cmd,seconds=time.monotonic()-t,exit=proc.returncode,timed_out=timed_out,
                     tools=tools,text=text,errors=errors,saves=sum(l[3]=="SAVED" for l in trace),restores=sum(l[3]=="RESTORED" for l in trace),
                     reuse_events=sum(l[3] in ("RESUME","REUSED") and l[4] and l[4][0]>0 for l in trace if l[4]),
                     simultaneous_decode_slots=max_slots,
                     engine_peak_bytes=max(peaks,default=None),fixture_base="e83de74",diff=subprocess.check_output(["git","diff","--stat"],cwd=project,text=True)))
                print(name,proc.returncode,len(tools),flush=True)
        finally:
            if server.poll() is None:
                os.killpg(server.pid,signal.SIGTERM)
                try:server.wait(timeout=12)
                except subprocess.TimeoutExpired:os.killpg(server.pid,signal.SIGKILL)
if __name__=="__main__":main()
