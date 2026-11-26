import sys, time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'research/spec-policy-fast'))
from run_policy import run_arm, previous
for family,mode,label in [
    ("qwen","stock","p01-a1"),("qwen","eight","p01-b1"),
    ("ink","plain","p04-reference"),("ink","stock","p04-reference"),
    ("ink","adaptive","p04-a1"),("ink","dynamic","p04-b1"),
    ("ink","fixed-trace","p04-diag"),("ink","dynamic-trace","p04-diag"),
    ("qwen","without-lookup","p03-dflash"),("qwen","lookup-only","p03-lookup")]:
    for attempt in range(3):
        limit=time.monotonic()+300
        while previous.others() and time.monotonic()<limit: time.sleep(3)
        if previous.others(): sys.exit("machine remains busy")
        try:
            run_arm(family,mode,label+(f"-retry{attempt}" if attempt else ""))
            break
        except (RuntimeError,SystemExit) as e:
            if "workload" in str(e) or "busy" in str(e):
                continue
            print(family,mode,repr(e),flush=True)
            break
