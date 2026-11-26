"""Calculate sprint decisions from complete paired blocks, retaining raw failure evidence."""
import json
import statistics as st
from pathlib import Path

import numpy as np

S=Path(__file__).resolve().parents[1]
OUT=S/"runs"
def read(p):return json.loads(p.read_text())
def save(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+"\n")
def med(xs):return float(st.median(xs))

def s01():
    summ=[]
    for folder in sorted((OUT/"S01").glob("p*-n*")):
        bs=[read(p) for p in sorted(folder.glob("block-*/pair.json"))]
        if len(bs)!=3:continue
        modes={m:{k:med([b["modes"][m][k] for b in bs]) for k in ("wall_s","parent_s","create_ms","restore_ms","cleanup_ms","marginal_s","peak_gib")} for m in bs[0]["modes"]}
        baseline=min(("native-1","native-2"),key=lambda m:modes[m]["wall_s"])
        rows=[b["modes"] for b in bs]
        gate=read(folder/"gate.json")
        summ.append(dict(cell=folder.name,modes=modes,baseline=baseline,
             speed=med([r[baseline]["wall_s"]/r["fork-2"]["wall_s"] for r in rows]),
             marginal_saved_pct=med([100*(1-r["fork-2"]["marginal_s"]/r[baseline]["marginal_s"]) for r in rows]),
             exact=sum(r["exact"] for r in gate["branches"]),endpoints_equal=all(b["endpoints_agree"] for b in bs)))
    return summ

def ssd(study):
    rows=[]
    counts=[2,4] if study=="S02" else [8]
    for n in counts:
        folders=sorted((OUT/study).glob(f"n{n}-block*"))
        if len(folders)!=3 or not all((p/"comparison.json").exists() for p in folders):continue
        base="C" if study=="S02" else "FIFO"
        chosen="D" if study=="S02" else "family"
        modes=read(folders[0]/"comparison.json")["order"]
        data={m:[read(p/m/"result.json") for p in folders] for m in modes}
        def ratios(a,b,key):return [r[key]/u[key] for r,u in zip(data[a],data[b])]
        biggest_seq_ratio=max(med([a["end_to_end_latency_s"][str(i)]/b["end_to_end_latency_s"][str(i)]
                          for a,b in zip(data[chosen],data[base])]) for i in range(n))
        p95=lambda r:float(np.percentile(list(r["end_to_end_latency_s"].values()),95))
        p95_ratio=med([p95(a)/p95(b) for a,b in zip(data[chosen],data[base])])
        native_works=[len({sum(sum(map(len,r["tokens"].values())) for r in [data[m][i]]) for m in modes})==1 for i in range(3)]
        token_match=all(data[chosen][i]["tokens"]==data[base][i]["tokens"] for i in range(3))
        control_matches={m:all(data[m][i]["tokens"]==data[base][i]["tokens"] for i in range(3)) for m in modes}
        total_prompt_reuse={m:[sum(r["reused"].values()) for r in data[m]] for m in modes}
        same_prompt_work=all(len({total_prompt_reuse[m][i] for m in modes})==1 for i in range(3))
        stats={m:{} for m in modes}
        for m,observations in data.items():
            for k in ("wall_s","device_read","process_read","peak_footprint","routed_expert_read_bytes"):
                stats[m][k]=med([r[k] for r in observations])
            hs=[r["hit_rate"] for r in observations if r["hit_rate"] is not None]
            stats[m].update(hit_rate=med(hs) if hs else None,
                useful_tps=med([sum(map(len,r["tokens"].values()))/r["wall_s"] for r in observations]),
                p95_latency_s=med([p95(r) for r in observations]))
        speed=med(ratios(base,chosen,"wall_s"))
        readable_baseline=all(r["device_read"]>0 for r in data[base])
        io=1-med(ratios(chosen,base,"device_read")) if readable_baseline else None
        ok=all(native_works) and token_match
        if study=="S03":
            ok=ok and same_prompt_work and all(control_matches.values()) and (speed>=1.10 or (io is not None and io>=0.15)) and biggest_seq_ratio<=1.10 and p95_ratio<=1.10
        else:
            ok=ok and all(a["tokens"]==b["tokens"] for a,b in zip(data["A"],data["B"])) and speed>1 and all(v>1 for v in ratios(base,chosen,"wall_s"))
        rows.append(dict(n=n,stats=stats,decision_supported=ok,median_speed=speed,physical_read_saving_pct=100*io if io is not None else None,
                         token_identity_vs_baseline=control_matches,same_decode_work=all(native_works),
                         prompt_reuse=total_prompt_reuse,same_prompt_work=same_prompt_work,p95_ratio=p95_ratio,
                         worst_sequence_median_latency_ratio=biggest_seq_ratio))
    return rows
def main():
    save(OUT/"sprint-summary.json",dict(S01=s01(),S02=ssd("S02"),S03=ssd("S03")))
if __name__=="__main__":main()
