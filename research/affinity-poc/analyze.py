"""Apply the frozen two-workload comparison and retain paired results by seed."""
import json
import statistics
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
OUT=HERE/"runs"
PLAN=json.loads((HERE/"plan.json").read_text())
median=statistics.median


def read(path):
    return json.loads(path.read_text())


def summarize(load):
    blocks=[]
    totals={arm:[] for arm in PLAN["arms"]}
    for seed in PLAN["seeds"]:
        base=OUT/load/str(seed)
        rows={arm:read(base/arm/"result.json") for arm in totals}
        inputs={arm:read(base/arm/"input.json") for arm in totals}
        fifo=rows["fifo"]
        for arm,r in rows.items():
            same_inputs=all(inputs[arm][key]==inputs["fifo"][key] for key in ("parents","prompts","arrival_order","cap","first_turn"))
            equal_work=same_inputs and all(r[k]==fifo[k] for k in ("tokens","reused","first_turn","read_prompt_tokens"))
            assert len(r["restored"])==8
            lat=r["latency_s"]
            ref_lat=fifo["latency_s"]
            p95=lambda d:float(np.percentile(list(d.values()),95))
            totals[arm].append(dict(seed=seed,wall_s=r["wall_s"],device_gb=r["disk0_bytes"]/1e9,
                process_gb=r["process_read"]/1e9,peak_gib=r["peak_bytes"]/2**30,p95_s=p95(lat),
                speed=fifo["wall_s"]/r["wall_s"],saved=1-r["disk0_bytes"]/fifo["disk0_bytes"] if fifo["disk0_bytes"] else None,
                p95_ratio=p95(lat)/p95(ref_lat),per_id={i:lat[i]/ref_lat[i] for i in lat},
                equal_work=equal_work,read_prompt=r["read_prompt_tokens"],output_tokens=sum(map(len,r["tokens"].values())),
                decisions=[d["id"] for d in r["decisions"]],moved=sum(d["id"]!=d["ready"][0] for d in r["decisions"]),
                guard=sum(d["reason"]=="age-bound" for d in r["decisions"])))
        blocks.append(str(base.relative_to(HERE)))
    summary={}
    for arm,records in totals.items():
        row={key:median(x[key] for x in records) for key in ("wall_s","device_gb","process_gb","peak_gib","p95_s","speed","p95_ratio")}
        row["saved"]=median(x["saved"] for x in records) if all(x["saved"] is not None for x in records) else None
        row["per_id_median_ratio"]={i:median(x["per_id"][i] for x in records) for i in records[0]["per_id"]}
        row["worst_id"]=max(row["per_id_median_ratio"],key=row["per_id_median_ratio"].get)
        row["worst_ratio"]=row["per_id_median_ratio"][row["worst_id"]]
        row["equal_work"]=all(x["equal_work"] for x in records)
        row["reordered"]=sum(x["moved"] for x in records)
        row["guard"]=sum(x["guard"] for x in records)
        row["passes"]=row["equal_work"] and (row["speed"]>=1.10 or (row["saved"] is not None and row["saved"]>=.15)) and row["p95_ratio"]<=1.10 and row["worst_ratio"]<=1.10
        summary[arm]=row
    return dict(summary=summary,pairs=totals,raw=blocks)


if __name__=="__main__":
    data={load:summarize(load) for load in PLAN["loads"]}
    decisions={arm:("INTEGRATE" if all(load["summary"][arm]["passes"] for load in data.values()) else "DROP") for arm in ("parent","cache")}
    (HERE/"results.json").write_text(json.dumps(dict(loads=data,decisions=decisions),indent=2)+"\n")
    for load,value in data.items():
        for arm,s in value["summary"].items():
            print(load,arm,{k:s[k] for k in ("wall_s","device_gb","speed","saved","p95_ratio","worst_ratio","reordered","equal_work")})
    print(decisions)
