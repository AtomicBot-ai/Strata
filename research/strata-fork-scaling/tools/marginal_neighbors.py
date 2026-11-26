"""Complete adjacent warm fan-out contrasts on the already assigned extension tree seeds."""
import fcntl
import json
import signal
from pathlib import Path

from marginal_study import CORE, EXTRA, OUT, paired_block, read, save, sha, shuffled


def main():
    plan=OUT/"neighbors-plan.json"
    cells=[c for c in CORE if c[3]]
    spec=dict(freeze=sha(OUT/"freeze.json"),cells=cells,seeds=EXTRA,source=sha(Path(__file__)),
              purpose="Pair warm N=2,4,8,16 and physical C=1,2 on identical extension trees.",
              rule="All fixed widths for first tree, selected widths on other two. No change to primary estimates.")
    if not plan.exists(): save(plan,spec)
    if read(plan)!=json.loads(json.dumps(spec)): raise ValueError("plan changed")
    if not (OUT/"complete.json").exists(): return
    with (OUT/"study.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for i,seed in enumerate(EXTRA):
            for c in shuffled(cells,seed,"adjacent"):
                paired_block(c,seed,0,i==0)
        save(OUT/"neighbors-complete.json",dict(additional_pairs=len(cells)*len(EXTRA)))

if __name__=="__main__":
    def timeout(*_): raise TimeoutError("arm exceeded 1800 seconds")
    signal.signal(signal.SIGALRM,timeout)
    main()
