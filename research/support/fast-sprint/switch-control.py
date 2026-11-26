"""Replace our coordinator at its idle boundary after the Qwen no-draft reference."""
import os, signal, time, subprocess, sys, json
from pathlib import Path
paths = subprocess.check_output(["ps","-Ao","pid=,args="],text=True).splitlines()
pids=[int(s.split()[0]) for s in paths if s.strip().endswith(" -B .work/fast-sprint/sequence.py") and "python" in s.lower() and " -c " not in s]
if len(pids)!=1:
    raise SystemExit(f"No unique coordinator: {pids}")
for _ in range(180):
    rows=[json.loads(l) for l in Path("research/fast-sprint/results.jsonl").read_text().splitlines()]
    if any(r.get("fixture")=="prose" and r["family"]=="qwen" and r["mode"]=="narrow" for r in rows):
        if list(Path(".work/fast-sprint").glob("qwen-narrow-pair2.log")):
            raise SystemExit("Next arm already started; left alone.")
        try:
            os.kill(pids[0],signal.SIGINT)
        except ProcessLookupError:
            pass
        print("Updated coordinator after reference.",flush=True)
        break
    time.sleep(.25)
else: raise SystemExit("Reference incomplete; left alone.")
