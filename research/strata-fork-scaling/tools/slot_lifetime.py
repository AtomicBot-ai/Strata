"""Verify cancellation, checkpoint lifetime and incompatible-history fallback."""
import argparse
from pathlib import Path
from runner import addressed, cold, engine, save
from gates import score


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    with engine(out,768,diag=True) as w:
        # A checkpoint handle is scoped to one engine process. Another model/backend
        # cannot import a handle. A fresh process has none.
        missing = w.ctrl("LABRESTORE 1","ERR")
        parent = [178+i%137 for i in range(191)]
        addressed(w,0,parent,1)
        w.ctrl("LABSAVE 0","SAVED")
        w.ctrl("LABRESTORE 1","RESTORED")
        # Address the child directly. Drop the checkpoint after its first token,
        # while the child owns its state. CANCEL must release its active slot.
        w.send("BGEN 1 400 temperature=0 seed=71 " + ",".join(map(str,parent+[611])))
        while True:
            msg = w.line()
            if msg == "BADM 1 1":
                break
            if not msg.startswith(("PP ","RESUME ","DONE ","T ")):
                raise ValueError(msg)
        w.send("LABDROP\nBSTOP 1")
        events=[]
        while True:
            msg=w.line()
            events.append(msg)
            if msg.startswith("BDONE"):
                break
        if not any(s=="DROPPED" for s in events) or "cancel" not in events[-1].split():
            raise ValueError(events)
        if w.ctrl("LABRESTORE 1","ERR")!=missing:
            raise RuntimeError("drop did not invalidate the handle")
        # Reuse the released physical slot with a different history. Native replay
        # must match a cold read and must not report a stale prefix.
        other=[566-i%31 for i in range(100)]
        actual, dist, log=addressed(w,1,other)
        cold(w)
        ref, oracle, _=addressed(w,1,other)
        verdict=score(oracle,dist)
        save(out/"cancel.json",dict(events=events, missing=missing, parity=verdict,
                                    tokens_equal=actual==ref, slot_reuse=log))
        if not verdict["exact"] or actual!=ref or any(x[0]=="RESUME" for x in log):
            raise ValueError("cancelled slot contaminated the next history")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    run(p.parse_args().out)
