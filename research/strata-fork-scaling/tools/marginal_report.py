"""Aggregate complete within-tree blocks. Preserve samples and uncertainty per contrast."""
import collections
import statistics as st
from pathlib import Path

import numpy as np

from marginal_study import ALL, CORE, EXTRA, OUT, SEEDS, cell, read, save
from runner import LAB

MIB=2**20
REPORT=LAB/"reports/E03-M.md"


def intervals(data, calculator):
    sample=np.asarray(data,dtype=float)
    value=float(calculator(sample))
    if len(sample)<3:
        return dict(value=value,trees=len(sample),ci95=None,ci_family=None)
    random=np.random.default_rng(38019)
    draws=sample[random.integers(0,len(sample),size=(10000,len(sample)))]
    vals=calculator(draws)
    q=np.percentile(vals,[0.625,2.5,97.5,99.375]).tolist()
    return dict(value=value,trees=len(sample),ci95=q[1:3],ci_family=[q[0],q[3]])


def phases(row):
    waves=row["waves"]
    base=row["parent_prefill_ns"] if row["initial_parent_in_elapsed"] else 0
    parts=dict(cold_explicit_parent=base,create=row["snapshot_create_ns"],restore=row["restore_ns"],
               wave_until_first=sum(x["dispatch_to_first_ns"] for x in waves),
               wave_mixed=sum(x["mixed_ns"] for x in waves),
               wave_decode_tail=sum(x["last_first_to_done_ns"] for x in waves),drop=row["drop_ns"])
    parts["host_residual"]=row["elapsed_ns"]-sum(parts.values())
    if parts["host_residual"]<0: raise ValueError("overlapping wave phases")
    m=row["memory"]
    return dict(seconds=row["elapsed_ns"]/1e9,phases_s={k:v/1e9 for k,v in parts.items()},
                parent_prepare_s=row["parent_prefill_ns"]/1e9,slot_clear_s=row["postrun_slot_clear_ns"]/1e9,
                median_queue_s=st.median(b["dispatch_ns"] for b in row["branches"])/1e9,
                branch_engine_prefill_sum_s=sum(b["engine_prefill_ms"] for b in row["branches"])/1000,
                branch_engine_decode_sum_s=sum(b["engine_decode_ms"] for b in row["branches"])/1000,
                first_wave_engine_prefill_ms=[b["engine_prefill_ms"] for b in row["branches"][:row["key"]["width"]]],
                peak_mib=m["end"]["peak_footprint"]/MIB,peak_above_parent_mib=(m["end"]["peak_footprint"]-m["parent"]["footprint"])/MIB,
                after_create_delta_mib=(m["after_create"]["footprint"]-m["parent"]["footprint"])/MIB,
                rss_end_mib=m["end"]["rss"]/MIB,payload_mib=row["snapshot_bytes"]/MIB,
                branch_prompt_tokens_reused=sum(b["reused"] for b in row["branches"]))


def present(x):
    return f"{x:.3f}".replace(".",",")


def main():
    raw={}
    cells=[]
    phase_rows=[]
    for c in ALL:
        folder=cell(c)
        allrows=[]
        for path in sorted(folder.glob("tree-*/block-*/pair.json")):
            pair=read(path)
            seed,b=pair["seed"],pair["block"]
            pair["mode_obs"]={m:phases(read(path.parent/f"{m}-w{w}/result.json")) for m,w in pair["best"].items()}
            raw[c,seed,b]=pair
            allrows.append(pair)
        if not allrows: continue
        relevant=SEEDS if c in CORE else EXTRA
        bytree=[]
        for seed in relevant:
            blocks=[r for r in allrows if r["seed"]==seed]
            if len(blocks)!=(2 if c in CORE else 1): continue
            bytree.append([st.mean(r["elapsed_ns"][m]/1e9 for r in blocks) for m in ("native","fork")])
        result=dict(config=c,complete_pairs=len(allrows),complete_trees=len(bytree))
        if bytree:
            arr=np.asarray(bytree)
            result["median_tree_speedup"]=float(np.median(arr[:,0]/arr[:,1]))
            result["ratio_totals"]=float(arr[:,0].sum()/arr[:,1].sum())
        result["fixed_width_samples"]=[dict(seed=r["seed"],block=r["block"],ratios=r["fixed_width"])
                                         for r in allrows if r["fixed_width"]]
        cells.append(result)
        for r in allrows:
            phase_rows.append(dict(config=c,seed=r["seed"],block=r["block"],width=r["best"],modes=r["mode_obs"]))
    contrasts=[]
    def marginal(p,s,resident,lo,hi,seeds,blocks,group):
        low=(p,lo,s,resident,2)
        high=(p,hi,s,resident,2)
        trees=[]
        for seed in seeds:
            if any((c,seed,b) not in raw for c in (low,high) for b in range(blocks)): continue
            points={}
            for mode in ("native","fork"):
                def delta(b,key):
                    return raw[high,seed,b]["mode_obs"][mode][key]-raw[low,seed,b]["mode_obs"][mode][key]
                points[mode]=st.mean(delta(b,"seconds") for b in range(blocks))
                points[mode+"_peak_MiB"]=st.mean(delta(b,"peak_mib") for b in range(blocks))
            trees.append(dict(seed=seed,**points))
        if not trees: return
        d=np.array([[t["native"],t["fork"]] for t in trees])
        avg=d.mean(axis=0)
        contrasts.append(dict(group=group,p=p,s=s,resident=resident,lo=lo,hi=hi,trees=trees,
            native_extra_s=avg[0],fork_extra_s=avg[1],native_s_per_branch=avg[0]/(hi-lo),fork_s_per_branch=avg[1]/(hi-lo),
            native_peak_MiB_per_branch=st.mean(t["native_peak_MiB"] for t in trees)/(hi-lo),
            fork_peak_MiB_per_branch=st.mean(t["fork_peak_MiB"] for t in trees)/(hi-lo),
            saving_s=intervals(d,lambda a:(a[...,0]-a[...,1]).mean(axis=-1)),
            saving_percent=intervals(d,lambda a:100*(1-a[...,1].mean(axis=-1)/a[...,0].mean(axis=-1))) if all(d[:,0]>0) else None))
    for p in (4096,16384):
        for resident in (False,True):
            marginal(p,128,resident,2,8,SEEDS,2,"primary")
        for lo,hi in ((2,4),(4,8),(8,16),(2,16)):
            marginal(p,128,True,lo,hi,EXTRA,1,"extension")
    for s in (512,1024):
        marginal(4096,s,True,2,8,EXTRA,1,"extension")
    first_blocks=[]
    for p in (4096,16384):
        for resident in (False,True):
            pair=[raw.get(((p,n,128,resident,2),SEEDS[0],0)) for n in (2,8)]
            if all(pair):
                first_blocks.append(dict(p=p,resident=resident,seed=SEEDS[0],
                    **{m:(pair[1]["elapsed_ns"][m]-pair[0]["elapsed_ns"][m])/1e9 for m in ("native","fork")}))
    proof_files=list(OUT.glob("*/audit-*/gate.json"))
    exact=total=0
    for path in proof_files:
        for r in read(path)["branches"]:
            exact+=r["exact"];total+=1
    stats=dict(cells=cells,contrasts=contrasts,first_blocks=first_blocks,complete_pairs=len(raw),endpoint_pairs=total,same_shape_exact=exact,
               completed=(OUT/"complete.json").exists() and (OUT/"neighbors-complete.json").exists())
    save(OUT/"analysis.json",stats)
    save(OUT/"phase-memory.json",phase_rows)
    lines=["# E03-M · добавочная стоимость веток","",
           f"Завершённых пар времени {len(raw)}. В завершённых численных проверках побайтно совпали {exact}/{total} пар конечных векторов.","",
           "Каждая строка использует одни и те же деревья и блоки для обоих концов контраста. Основные строки включают только деревья с обоими повторами. Положительная экономия означает меньшее добавочное время со снимком.",""]
    for x in contrasts:
        ci=x["saving_s"]["ci95"]
        interval="" if ci is None else f" Интервал 95% для экономии от {present(ci[0])} до {present(ci[1])} с."
        lines.append(f"- {'Резидентный' if x['resident'] else 'Холодный'} родитель, P={x['p']}, S={x['s']}, {x['lo']}→{x['hi']} веток, деревьев {len(x['trees'])}. Штатно добавилось {present(x['native_extra_s'])} с, со снимком {present(x['fork_extra_s'])} с.{interval}")
    if not stats["completed"] and first_blocks:
        lines+=["", "## Первый временной блок на дереве 72401", "",
                "Это отдельное наблюдение до завершения основных повторов. Для перехода с 2 на 8 веток получены следующие дополнительные времена.", ""]
        for r in first_blocks:
            lines.append(f"- {'Готовый' if r['resident'] else 'Холодный'} родитель P={r['p']}: штатно {present(r['native'])} с, со снимком {present(r['fork'])} с.")
    lines+=["","[Протокол](../E03-M.md) · [Парные оценки, интервалы и стоимость на ветку](../runs/E03-M/analysis.json) · [Разбивка времени и физической памяти](../runs/E03-M/phase-memory.json) · [Первичные данные](../runs/E03-M/)"]
    REPORT.write_text("\n".join(lines)+"\n")
    print(len(raw),exact,total,len(contrasts))

if __name__=="__main__":
    main()
