"""Audit decode windows and derive paired marginal costs from completed jobs."""

import json
from pathlib import Path
from statistics import median

OUT = Path(__file__).resolve().parents[1] / "runs/ssd-branch-01"


def load(tag):
    return json.loads((OUT / (tag + ".json")).read_text())


def block(tag):
    rows = {m: load(f"{tag}-{m}") for m in ("A", "B", "joint", "serial")}
    expected = [rows["A"]["tokens"][0], rows["B"]["tokens"][1]]
    if any("window" not in r for r in rows.values()):
        raise ValueError(f"{tag}: incomplete decode")
    keys = ("disk", "process", "ms")
    measured = {m: r["window"] for m, r in rows.items()}
    a, b, j, s = (measured[m] for m in ("A", "B", "joint", "serial"))
    return {
        "same_token_ids": {
            m: r["tokens"] == expected
            for m, r in rows.items()
            if m in ("joint", "serial")
        },
        "same_prompts": all(
            r["input_ids"] == rows["A"]["input_ids"] for r in rows.values()
        ),
        "observed": measured,
        "idle_device_MB_s": {
            m: (r["idle"][1][1] - r["idle"][0][1])
            * 1e3
            / (r["idle"][1][0] - r["idle"][0][0])
            for m, r in rows.items()
        },
        "second_branch": {k: j[k] - a[k] for k in keys},
        "fraction_of_solo_B": {k: (j[k] - a[k]) / b[k] for k in keys},
        "saved_vs_two_solos": {k: 1 - j[k] / (a[k] + b[k]) for k in keys},
        "saved_vs_serial": {k: 1 - j[k] / s[k] for k in keys},
    }


def trace(tag, reference):
    job = load(tag)
    lines = [
        line.split()
        for line in (OUT / (tag + ".log")).read_text().splitlines()
        if line.startswith("SSD_ROUTE ")
    ]
    assert len(job["tokens"][0]) == len(job["tokens"][1]) and len(job["tokens"][0]) > 0
    top_k = (len(lines[0]) - 8) // 2
    width = 48
    assert len(lines) == len(job["tokens"][0]) * width
    groups = [lines[k : k + width] for k in range(0, len(lines), width)]
    hits = misses = reads = overlap = demand = wait = weighted_overlap = (
        weighted_demand
    ) = 0
    for group in groups[6 : 6 + job["count"]]:
        assert [int(row[1]) for row in group] == list(range(width))
        for row in group:
            layer, n, per_expert, h, m, b = map(int, row[1:7])
            del layer
            assert n == 2 and len(row) == 8 + 2 * top_k
            ids = list(map(int, row[8:]))
            left, right = set(ids[:top_k]), set(ids[top_k:])
            assert len(right) == len(left) == top_k and h + m == len(left | right)
            same = len(left & right)
            hits += h
            misses += m
            reads += b
            wait += float(row[7])
            overlap += same
            demand += len(right)
            weighted_overlap += same * per_expert
            weighted_demand += len(right) * per_expert
    return dict(
        same_release_tokens=job["tokens"] == load(reference)["tokens"],
        layers_per_step=width,
        experts_per_row_per_layer=top_k,
        fraction_second_experts_also_in_first=overlap / demand,
        fraction_second_expert_bytes_also_in_first=weighted_overlap / weighted_demand,
        overlap_count=overlap,
        second_branch_expert_choices=demand,
        hit_count=hits,
        miss_count=misses,
        hit_fraction=hits / (hits + misses),
        logical_expert_read_bytes=reads,
        host_wait_ms=wait,
    )


def main():
    blocks = {tag: block(tag) for tag in ("r1", "r2", "r3", "default", "different")}
    pilot = [blocks[tag] for tag in ("r1", "r2", "r3")]
    stats = {}
    for metric in (
        "second_branch",
        "fraction_of_solo_B",
        "saved_vs_two_solos",
        "saved_vs_serial",
    ):
        stats[metric] = {}
        for k in ("disk", "process", "ms"):
            values = [r[metric][k] for r in pilot]
            stats[metric][k] = dict(
                median=median(values), min=min(values), max=max(values)
            )
    summary = dict(blocks=blocks, three_paired_repeats=stats)
    if (OUT / "trace-related.json").exists() and (
        OUT / "trace-different.json"
    ).exists():
        summary["routes"] = {
            tag: trace("trace-" + tag, baseline)
            for tag, baseline in [
                ("related", "r1-joint"),
                ("different", "different-joint"),
            ]
        }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
