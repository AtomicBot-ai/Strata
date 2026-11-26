"""Replay the original four trees with the historical binary; preserve every block."""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

lab = Path(__file__).resolve().parents[2] / "adaptive-intelligence"
parser = argparse.ArgumentParser()
parser.add_argument("out", type=Path)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
order = ["batch", "replay", "checkpoint"]
rng = random.Random(1125)
for block in range(13):
    rng.shuffle(order)
    folder = args.out / f"{'warmup' if block < 3 else 'paired'}-{block:02}"
    subprocess.run([sys.executable, "-B", str(lab / "branching/fixed_cost.py"),
                    str(lab / "runs/branch-debug/raw.jsonl"), str(folder),
                    "--modes", *order], check=True, timeout=180)
    rows = [json.loads(line) for line in (folder / "cost.jsonl").read_text().splitlines()]
    for mode, expected in (("batch", 1728), ("replay", 1728), ("checkpoint", 932)):
        group = [row for row in rows if row["mode"] == mode]
        if len(group) != 4 or sum(row["processed"] for row in group) != expected:
            raise ValueError((block, mode, "historical work changed"))
    print(folder.name, order, flush=True)
