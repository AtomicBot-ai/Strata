"""Independent replay at exactly the B4 prefill and decode shapes; diagnose frozen G0."""
import argparse
from pathlib import Path
from runner import cold, engine, fixture, save, tree, wave
from gates import score


def replay(w, roots, tails):
    # Recompute each slot's P-1 in isolation with no explicit checkpoint.
    # Admit both leaves together, exactly as B4 does after its restore calls.
    out = {}
    for start in range(0, len(tails), 2):
        cold(w)
        prompt = ",".join(map(str, roots[0][:-1]))
        for slot in (0,1):
            w.send(f"BGEN {slot} 0 temperature=0 ckpt=0 " + prompt)
            while True:
                line = w.line()
                if line.startswith("BADM"):
                    if line != f"BADM {slot} 0":
                        raise ValueError(line)
                    break
                if not line.startswith(("PP ", "DONE ")):
                    raise ValueError(line)
        jobs = []
        for i in (start,start+1):
            opts = f"temperature=0 seed={100+i} ckpt=0 teacher=" + ",".join(map(str,tails[i]))
            jobs.append((str(i),roots[0],len(tails[i])+1,opts))
        _, logits = wave(w,jobs)
        out.update(logits)
    return out


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    rows = []
    with engine(out,2304,diag=True) as w:
        for boundary in (1023,1024,1025,2049):
            work = fixture(boundary+1,4,6,boundary)
            reference = replay(w,*work)
            cold(w)
            _, got = tree(w,work,"B4")
            rows.append(dict(boundary=boundary,errors=[score(reference[k],got[k]) for k in sorted(got)]))
            save(out/"matched.json",rows)
            print(boundary, [r["exact"] for r in rows[-1]["errors"]],flush=True)

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    main(p.parse_args().out)
