"""Trace the first parity failure without changing the engine or thresholds."""
import argparse
from pathlib import Path
from runner import addressed, engine, cold, save, wave
from gates import score

def trace(out):
    root = [31+i%401 for i in range(78)]
    job = [(f"r{i}", root, 1, "temperature=0") for i in (0,1)]
    tails = [(f"r{i}", root+[123+i], 3, "temperature=0") for i in (0,1)]
    with engine(out, 2304, diag=True) as w:
        cold(w)
        first, a = wave(w, job)
        w.ctrl("LABSAVE 1", "SAVED")
        cold(w)
        for slot in (0,1):
            w.ctrl(f"LABRESTORE {slot}", "RESTORED")
        got, b = wave(w, tails)
        cold(w)
        second, c = wave(w, job)
        ref, d = wave(w, tails)
        result = dict(native_same_prompt_slots=score(a["r0"], a["r1"]),
                      native_repeat=[score(a[k], c[k]) for k in sorted(a)],
                      after_restore=[score(d[k], b[k]) for k in sorted(d)], got=got, reference=ref)
        save(out/"diagnostic.json", result)
        iso = []
        for src in (1,0):
            cold(w)
            addressed(w,src,root,1)
            w.ctrl(f"LABSAVE {src}","SAVED")
            for dst in (src,1-src):
                tail = root+[123+dst]
                cold(w)
                w.ctrl(f"LABRESTORE {dst}","RESTORED")
                got, actual, _ = addressed(w,dst,tail)
                cold(w)
                addressed(w,src,root,1)
                ref, expected, _ = addressed(w,src,tail)
                iso.append(dict(src=src,dst=dst,error=score(expected,actual),got=got,reference=ref))
        save(out/"isolated.json",iso)

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    out=p.parse_args().out
    out.mkdir(parents=True,exist_ok=False)
    trace(out)
