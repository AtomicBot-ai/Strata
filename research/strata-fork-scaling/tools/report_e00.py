"""Summarize the original paired four-tree workload and plot measured block variation."""
import argparse
import json
from pathlib import Path
import numpy as np
from runner import LAB, save


def summarize(out):
    raw = LAB/"runs/E00/reproduction"
    modes = ["replay","batch","checkpoint"]
    times = []
    tasks = None
    counts = {}
    for p in sorted(raw.glob("paired-*/cost.jsonl")):
        rows = [json.loads(l) for l in p.read_text().splitlines()]
        names = [r["task"] for r in rows if r["mode"]=="replay"]
        if tasks is not None and names!=tasks:
            raise ValueError("tree set changed")
        tasks = names
        by_key = {(r["task"],r["mode"]):r for r in rows}
        times.append([[by_key[t,m]["wall_ms"]/1000 for m in modes] for t in tasks])
        for m in modes:
            total=sum(by_key[t,m]["processed"] for t in tasks)
            if m in counts and counts[m]!=total:
                raise ValueError("work changed")
            counts[m]=total
    a=np.asarray(times)
    assert a.shape==(10,4,3)
    total=a.sum(axis=1)
    ratios=total[:,:2]/total[:,2:3]
    # Historical claims concern this specific set of four trees. Interval below
    # resamples complete paired blocks, conditional on those fixtures.
    rng=np.random.default_rng(1125)
    boot=np.median(ratios[rng.integers(0,len(total),(10000,len(total)))],axis=1)
    summary=dict(tasks=tasks, modes=modes,blocks=len(a),tokens=counts,
                 median_s=np.median(total,axis=0).tolist(), min_s=total.min(axis=0).tolist(),
                 max_s=total.max(axis=0).tolist(), p95_s=np.percentile(total,95,axis=0).tolist(),
                 paired_speedup=np.median(ratios,axis=0).tolist(),
                 paired_block_ci95=np.percentile(boot,[2.5,97.5],axis=0).tolist(),
                 ratio_of_totals=(total.sum(axis=0)[:2]/total[:,2].sum()).tolist())
    save(out/"E00.json",summary)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(8,3.5),layout="constrained")
    labels=["Последовательно","Пакетом","Снимок"]
    for i,r in enumerate(total):
        axes[0].plot(range(3),r,color="#506579",alpha=.45,lw=.8)
    axes[0].plot(range(3),np.median(total,axis=0),color="#035e67",marker="o",lw=2)
    axes[0].set(ylabel="Время четырёх деревьев, с",xticks=range(3),xticklabels=labels,ylim=(0,None))
    bars=axes[1].bar(labels,[counts[m] for m in modes],color=["#82919c","#64788d","#147b78"])
    axes[1].bar_label(bars,padding=3)
    axes[1].set(ylabel="Обработанные токены",ylim=(0,2050))
    for ax in axes:
        ax.tick_params(axis="x",labelsize=8)
        ax.spines[["top","right"]].set_visible(False)
    fig.savefig(out/"E00.png",dpi=150)
    plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("out",type=Path)
    summarize(parser.parse_args().out)
