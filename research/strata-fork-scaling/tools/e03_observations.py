"""Report only complete paired measurements; keep unfinished E03 cells visible."""
import argparse
import json
import statistics
from pathlib import Path
import numpy as np

from runner import LAB
from screen import PREFIXES


def read(path):
    return json.loads(path.read_text())


def summarize_cell(folder):
    groups=[]
    fixed_width=[]
    fixed_matches=0
    for b in range(5):
        block=folder/f"block-{b}"
        proof=block/"correctness.json"
        if proof.exists() and read(proof)["status"]=="pass":
            base,fork=[read(block/m/"metrics.json") for m in ("B3","B4")]
            groups.append((base,fork))
            fixed_path=block/"B7/metrics.json"
            native=read(fixed_path) if fixed_path.is_file() else base
            if {k:r["tokens"] for k,r in native["branches"].items()} == {k:r["tokens"] for k,r in fork["branches"].items()}:
                fixed_matches+=1
                fixed_width.append(native["elapsed_ns"]/fork["elapsed_ns"])
    row={"complete_pairs":len(groups)}
    if groups:
        row["median_paired_speedup"]=statistics.median(a["elapsed_ns"]/b["elapsed_ns"] for a,b in groups)
        row["ratio_of_totals"]=sum(a["elapsed_ns"] for a,b in groups)/sum(b["elapsed_ns"] for a,b in groups)
        for i,mode in enumerate(("B3","B4")):
            obs=[pair[i] for pair in groups]
            latency=[branch["latency_ns"]/1e9 for meas in obs for branch in meas["branches"].values()]
            row[mode]=dict(
                median_s=statistics.median(o["elapsed_ns"]/1e9 for o in obs),
                p95_branch_s=float(np.percentile(latency,95)),
                peak_footprint_gib=max(o["memory_after"]["peak_footprint"] for o in obs)/2**30,
                median_total_restore_ms=statistics.median(o["restore_ns"]/1e6 for o in obs),
                median_total_create_ms=statistics.median(o["create_ns"]/1e6 for o in obs),
                median_prefill_tokens=statistics.median(o["prefill_tokens"] for o in obs),
                useful_tps=sum(o["useful_tokens"] for o in obs)*1e9/sum(o["elapsed_ns"] for o in obs),
                snapshot_payload_bytes=max(o["snapshot_bytes"] for o in obs))
        row["fixed_width_matching_pairs"]=fixed_matches
        row["fixed_width_median_speedup"]=statistics.median(fixed_width) if fixed_matches==len(groups) else None
        row["peak_ratio"]=row["B4"]["peak_footprint_gib"]/row["B3"]["peak_footprint_gib"]
    return row


def main(run):
    rows=[]
    for p in PREFIXES:
        for n,share in ((2,True),(4,True),(8,True),(1,True),(2,False)):
            folder=run/"screen"/f"p{p}-n{n}-{'shared' if share else 'unrelated'}"
            row=summarize_cell(folder)
            row.update(p=p,n=n,shared=share)
            if row["complete_pairs"]==5:
                row["status"]="complete"
            else:
                failures=[(path,read(path)) for pattern in ("**/correctness.json","**/metrics.json")
                          for path in folder.glob(pattern) if read(path).get("status") not in ("pass","ok")]
                row.update(status="failed" if failures else "partial" if folder.exists() else "not_run",
                           failures=[dict(path=str(path),status=data.get("status"),detail=data.get("detail"))
                                     for path,data in failures])
            rows.append(row)
    report={"source":str(run),"cells":rows}
    if (run/"holdout-summary.json").exists():
        report["holdout"]=read(run/"holdout-summary.json")
    (run/"observations.json").write_text(json.dumps(report,indent=2)+"\n")
    print(len([r for r in rows if r["status"]=="complete"]), "complete cells")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("run",type=Path)
    main(p.parse_args().run)
