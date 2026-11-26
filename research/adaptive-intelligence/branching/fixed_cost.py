"""Cost of an identical teacher-forced two-leaf tree from each debugging task."""

import json
import time
import argparse
from pathlib import Path
from engine import engine, record
from search import batch_with_first_resume, reset


def main(raw, out, modes):
    trees = [json.loads(l) for l in raw.open() if json.loads(l)["mode"] == "replay"]
    out.mkdir(parents=True, exist_ok=False)
    with (out / "cost.jsonl").open("x") as rows:
        for mode in modes:
            with engine(
                out / f"{mode}.log", slots=2 if mode == "batch" else 1, checkpoints=mode == "checkpoint"
            ) as s:
                for row in trees:
                    common = row["input_ids"] + row["anchor"][:-1]
                    suffixes = [
                        c["ids"][len(row["anchor"]) - 1 : len(row["anchor"]) + 16]
                        for c in row["candidates"][:2]
                    ]
                    assert len(suffixes) == 2 and all(suffixes)
                    reset(s)
                    if mode == "batch":
                        reset(s, 1)
                    start = time.monotonic()
                    setup = s.gen(common, 0)
                    used = setup["processed"]
                    payload = 0
                    if mode == "checkpoint":
                        payload = int(s.control("SAVE", "SAVED")[1])
                    if mode == "batch":
                        outputs = batch_with_first_resume(
                            s, [(common + tail, 1, 42) for tail in suffixes], len(common), temperature=0
                        )
                    else:
                        outputs = [s.gen(common + suffixes[0], 1)]
                        if mode == "checkpoint":
                            s.control("RESTORE", "RESTORED")
                        outputs.append(s.gen(common + suffixes[1], 1))
                    if mode == "checkpoint":
                        s.control("DROP", "DROPPED")
                    used += sum(r["processed"] for r in outputs)
                    record(
                        rows,
                        task=row["task_id"],
                        mode=mode,
                        prefix_tokens=len(common),
                        suffixes=suffixes,
                        processed=used,
                        wall_ms=1000 * (time.monotonic() - start),
                        payload_bytes=payload,
                    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("raw", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument(
        "--modes",
        choices=["replay", "checkpoint", "batch"],
        nargs="+",
        default=["replay", "checkpoint", "batch"],
    )
    args = p.parse_args()
    main(args.raw, args.out, args.modes)
