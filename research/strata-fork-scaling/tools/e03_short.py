"""One exploratory long-tree pair, reusing E03's baseline selection and timings."""
import signal
from screen import deadline, load, paired, single
from runner import LAB, save

if __name__=="__main__":
    signal.signal(signal.SIGALRM,deadline)
    gate=LAB/"runs/E02-R/gate.json"
    if load(gate)["status"]!="passed":
        raise RuntimeError("E02-R gate required")
    run=LAB/"runs/E03/after-E02-R"
    cell=run/"screen/p16384-n8-shared"
    dev={w:single(cell/f"dev-c{w}",16384,8,928,"B3",w)["elapsed_ns"] for w in (1,2)}
    width=min(dev,key=dev.get)
    ratio=paired(cell/"block-0",16384,8,True,1000,0,width)
    save(run/"short-long-tree.json",dict(p=16384,n=8,s=128,slot_limit=2,paired_blocks=1,
         baseline_width=width,dev_elapsed_ns=dev,paired_speedup=ratio,phase="exploratory"))
    print("One exploratory pair complete",width,ratio,flush=True)
