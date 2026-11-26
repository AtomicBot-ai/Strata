"""Select native admission on a development tree class; no speculative fork timings."""
import argparse
import signal
import statistics
from pathlib import Path
from runner import save
from screen import deadline, endpoints, single

p = argparse.ArgumentParser()
p.add_argument("out",type=Path)
out = p.parse_args().out
signal.signal(signal.SIGALRM, deadline)
pairs=[]
for b in range(3):
    rows={}
    for width in ((1,2) if b%2==0 else (2,1)):
        rows[width]=single(out/f"pair-{b}-width-{width}",1024,4,700+b,"B3",width)
    pairs.append(dict(seed=700+b,times_s=[rows[w]["elapsed_ns"]/1e9 for w in (1,2)],
                      reuse=[sum(r["reused"] for r in rows[w]["branches"].values()) for w in (1,2)],
                      endpoint_tokens_equal=endpoints(rows[1])==endpoints(rows[2])))
    save(out/"pairs.json",pairs)
medians=[statistics.median(p["times_s"][j] for p in pairs) for j in (0,1)]
save(out/"selection.json",dict(p=1024,n=4,s=128,slot_limit=2, widths=[1,2],
                               medians_s=medians,fastest_width=medians.index(min(medians))+1))
