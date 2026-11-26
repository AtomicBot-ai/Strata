"""Fetch bounded byte ranges of pinned LiveCodeBench and freeze a disjoint stratified sample."""

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

from diverse_plans import source_rows
from prepare import CODE_REV, DATA, tests
from engine import ROOT

RUNS = ROOT / "research/adaptive-intelligence/runs"
LEVELS = ("easy", "medium", "hard")
SEEDS = (3203, 3251, 3299)
CHUNK = 8 * 2**20


def source_pool():
    excluded = {t["id"] for t in json.loads((DATA / "public.json").read_text())}
    for path in RUNS.glob("*/tasks.json"):
        excluded.update(t["id"] for t in json.loads(path.read_text()))
    pool = {}
    for path in sorted(DATA.glob("*.jsonl")):
        if path.name == "math.jsonl":
            continue
        for r in source_rows(path):
            k = r["question_id"]
            if (
                k in excluded
                or r["platform"] != "atcoder"
                or r["starter_code"]
                or not k.startswith("abc")
            ):
                continue
            public = json.loads(r["public_test_cases"])
            if (
                public
                and all(t["testtype"] == "stdin" for t in public)
                and r["private_test_cases"]
            ):
                pool[k] = (r, path)
    return pool


def eligible(pool):
    count = Counter(r["difficulty"] for r, _ in pool.values())
    return (
        all(count[level] >= 8 for level in LEVELS)
        and len({k.split("_")[0] for k in pool}) >= 4
    )


def fetch():
    if eligible(source_pool()):
        return
    files = json.loads((DATA / "lcb-files.json").read_text())
    for fraction in (0.5, 0.25, 0.75, 0.1, 0.9, 0.4, 0.6, 0.33, 0.66):
        for name in ("test6", "test3", "test2", "test4", "test5", "test"):
            size = next(r["size"] for r in files if r["path"] == name + ".jsonl")
            start = int(size * fraction)
            path = DATA / f"stepback-{name}-{start}.jsonl"
            if not path.exists():
                url = f"https://huggingface.co/datasets/livecodebench/code_generation_lite/resolve/{CODE_REV}/{name}.jsonl?stepback={start}"
                req = Request(
                    url, headers={"Range": f"bytes={start}-{start + CHUNK - 1}"}
                )
                with urlopen(req, timeout=50) as response:
                    if (
                        response.status != 206
                        or response.headers["Content-Range"]
                        != f"bytes {start}-{start + CHUNK - 1}/{size}"
                    ):
                        raise RuntimeError("unexpected remote byte range")
                    data = response.read(CHUNK + 1)
                if len(data) != CHUNK:
                    raise RuntimeError("incomplete byte range")
                tmp = path.with_suffix(".part")
                tmp.write_bytes(data)
                os.replace(tmp, path)
            pool = source_pool()
            print(
                path.name,
                Counter(r["difficulty"] for r, _ in pool.values()),
                flush=True,
            )
            if eligible(pool):
                return
    raise RuntimeError("insufficient fresh IDs")


def prepare(out):
    pool = source_pool()
    if not eligible(pool):
        raise ValueError("fetch fresh tasks first")
    ids = sorted(
        pool,
        key=lambda k: hashlib.sha256(("stepback-primary-v1/" + k).encode()).digest(),
    )
    keys = [
        k
        for level in LEVELS
        for k in [k for k in ids if pool[k][0]["difficulty"] == level][:8]
    ]
    assert len({k.split("_")[0] for k in keys}) >= 4
    public, labels, sources = [], {}, {}
    for k in keys:
        r, path = pool[k]
        public.append(
            dict(
                id=k,
                domain="code",
                level=r["difficulty"],
                question=r["question_content"],
                public=json.loads(r["public_test_cases"]),
            )
        )
        labels[k] = tests(r["private_test_cases"])
        assert labels[k] and all(t["testtype"] == "stdin" for t in labels[k])
        if path.name not in sources:
            sources[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    out.mkdir(exist_ok=False)
    (out / "tasks.json").write_text(json.dumps(public, ensure_ascii=False, indent=2))
    (DATA / (out.name + "-private.json")).write_text(json.dumps(labels))
    (out / "protocol.json").write_text(
        json.dumps(
            dict(
                revision=CODE_REV,
                sources=sources,
                seeds=SEEDS,
                tasks_sha256=hashlib.sha256(
                    (out / "tasks.json").read_bytes()
                ).hexdigest(),
                deadline_seconds=30,
                cap_gib=20,
                max_slots=2,
                max_attempts=4,
                primary="D vs frozen calibration winner",
                gate="+5pp and lower bound of paired task bootstrap above zero",
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["fetch", "prepare"])
    p.add_argument("out", type=Path, nargs="?")
    a = p.parse_args()
    fetch() if a.stage == "fetch" else prepare(a.out)
