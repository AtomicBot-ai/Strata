"""Paired development, screening and independent holdout. Resume completed cases."""
import argparse
import hashlib
import json
import random
import signal
import statistics
import subprocess
from pathlib import Path
from paired_stats import paired_summary
from runner import LAB, PATCHED, STOCK, cold, engine, fingerprint, fixture, save, tree

PREFIXES = (1024, 4096, 16384, 32768)
BRANCHES = (2, 4, 8)
S = 128
BASE_SEED = 1125


def load(path):
    return json.loads(path.read_text())


def deadline(*_):
    raise TimeoutError("600 s per tree")


def system(cmd):
    reply = subprocess.run(cmd, capture_output=True, text=True)
    return (reply.stdout or reply.stderr).strip()


def single(folder, p, n, seed, mode, width, shared=True, stock=False, teach=True, suffix=S):
    path = folder / "metrics.json"
    work = fixture(p, n, suffix, seed, shared)
    key = dict(p=p, n=n, suffix=suffix, c=2, seed=seed, mode=mode, width=width, shared=shared,
               stock=stock, teacher=teach, workload_hash=fingerprint(work),
               binary_sha256=hashlib.sha256((STOCK if stock else PATCHED).read_bytes()).hexdigest())
    if path.exists():
        row = load(path)
        if load(folder / "manifest.json")["case"] != key or row["status"] != "ok":
            raise RuntimeError(f"case differs or failed: {folder}")
        return row
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / "manifest.json", dict(case=key, protocol_sha256=hashlib.sha256(
        (LAB/"PROTOCOL.md").read_bytes()).hexdigest(), cache_mode="warm weights / cold session",
        physical_memory_cap_bytes=None, thermal=system(["pmset", "-g", "therm"]),
        swap=system(["sysctl", "-n", "vm.swapusage"])))
    signal.alarm(600)
    try:
        with engine(folder, max(256, p+suffix+32), stock=stock) as w:
            tree(w, fixture(96, 2, 3, 43), "B3", teach=False)
            cold(w)
            row, _ = tree(w, work, mode, native_width=width, teach=teach)
            row["status"] = "ok"
            save(path, row)
    except Exception as exc:
        save(path, dict(status="timeout" if isinstance(exc,TimeoutError) else "error", detail=str(exc)))
        raise
    finally:
        signal.alarm(0)
    return row


def endpoints(row):
    return {k:r["tokens"] for k,r in row["branches"].items()}


def overhead(out):
    # Unmodified native binary against the patched binary's native path, no forcing.
    ratios = []
    for b in range(5):
        rows = {}
        for stock in ((True,False) if b%2==0 else (False,True)):
            rows[stock] = single(out/f"pair-{b}-{int(stock)}",128,2,541+b,"B3",2,
                                 stock=stock,teach=False,suffix=8)
        equal = endpoints(rows[True]) == endpoints(rows[False])
        if not equal:
            raise RuntimeError(f"unforced native control differs, pair {b}")
        ratios.append(rows[False]["elapsed_ns"]/rows[True]["elapsed_ns"])
    median = statistics.median(ratios)
    save(out/"overhead.json",dict(ratios=ratios,median=median,limit=1.10))
    if median > 1.10:
        raise RuntimeError("instrumentation above 10% development allowance")


def paired(out, p, n, shared, seed, block, width):
    order = ["B3", "B4"] + (["B7"] if width != 2 and n>1 else [])
    random.Random(BASE_SEED+seed+block).shuffle(order)
    rows = {}
    for mode in order:
        rows[mode] = single(out/mode, p, n, seed, mode, width if mode=="B3" else 2, shared=shared)
    if endpoints(rows["B3"]) != endpoints(rows["B4"]):
        save(out/"correctness.json",dict(status="endpoint_disagreement", order=order))
        raise ValueError(f"different native endpoint(s), {out}")
    save(out/"correctness.json",dict(status="pass", order=order,
                                      b7="same as B3" if width==2 or n==1 else "separate fixed-C"))
    return rows["B3"]["elapsed_ns"]/rows["B4"]["elapsed_ns"]


def run(out, gate):
    if load(gate)["status"] != "passed":
        raise RuntimeError(f"state gate required: {gate}")
    if not (out/"overhead/overhead.json").exists():
        overhead(out/"overhead")
    if load(out/"overhead/overhead.json")["median"]>1.10:
        raise RuntimeError("instrumentation gate failed")
    screened = []
    for p in PREFIXES:
        for n,shared in [(2,True),(4,True),(8,True),(1,True),(2,False)]:
            name = f"p{p}-n{n}-{'shared' if shared else 'unrelated'}"
            cell = out/"screen"/name
            # Select native admission on separate inputs before using screening/holdout seeds.
            widths = [1,2] if n>1 else [1]
            dev = {w:single(cell/f"dev-c{w}",p,n,928,"B3",w,shared=shared)["elapsed_ns"] for w in widths}
            width = min(dev,key=dev.get)
            ratios = [paired(cell/f"block-{b}",p,n,shared,1000+b,b,width) for b in range(5)]
            med = statistics.median(ratios)
            screened.append(dict(name=name,p=p,n=n,shared=shared,width=width,median=med,ratios=ratios))
            save(out/"screening.json", screened)
            print(name, width, round(med,3), flush=True)
    eligible = [c for c in screened if c["median"]>=1.3 and c["shared"] and c["n"]>1]
    if eligible:
        c = max(eligible,key=lambda c:(c["median"],-c["p"],-c["n"]))
        save(out/"holdout-class.json",c)
        for i in range(10):
            for b in range(2):
                paired(out/"holdout"/f"tree-{i}-block-{b}",c["p"],c["n"],True,100000+i,b,c["width"])
        save(out/"holdout-summary.json",paired_summary(sorted((out/"holdout").glob("tree-*-block-*"))))
    save(out/"completion.json", dict(status="completed", holdout=bool(eligible)))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("out",type=Path)
    parser.add_argument("gate",type=Path,nargs="?")
    parser.add_argument("--overhead-only",action="store_true")
    args=parser.parse_args()
    signal.signal(signal.SIGALRM,deadline)
    if args.overhead_only:
        overhead(args.out)
    elif args.gate is None:
        parser.error("screening requires a G0 verdict")
    else:
        run(args.out,args.gate)
