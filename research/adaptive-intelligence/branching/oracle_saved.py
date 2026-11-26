"""R05: offline oracle on the six matched R03/R04 families, without generation."""

import hashlib
import json
from pathlib import Path

from depth_cases import cases
from grade import run_cases
from prepare import DATA

RUNS = Path(__file__).resolve().parents[1] / "runs"
PILOT = RUNS / "stepback-live-01"
R03 = RUNS / "stepback-r03"
R04 = RUNS / "stepback-r04"
OUT = RUNS / "stepback-r05"


def read(path):
    return json.loads(path.read_text())


def save(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inventory():
    protocol = read(R04 / "protocol.json")
    rows = []
    for spec in protocol["tasks"]:
        k = spec["id"]
        old = R03 / k
        assert sha((old / "result.json").read_bytes()) == spec["source_sha"]
        assert sha(json.dumps(cases(k), sort_keys=True).encode()) == spec["checks_sha"]
        for role in ("parent", "child"):
            path = old / (role + ".py")
            pub = read(old / "result.json")["branches"][role]["public"]["passed"]
            assert len(pub) == len(spec["public"])
            diag = read(R04 / k / "parent-checks.json")["diagnostic"] if role == "parent" else None
            rows.append((k, role, path, all(pub), diag))
        for seed in protocol["seeds"]:
            for stage in spec["offsets"]:
                folder = R04 / k / str(seed) / stage
                path = folder / "candidate.py"
                code_sha = sha(path.read_text().removesuffix("\n").encode()) if path.exists() else None
                assert code_sha == read(folder / "generation.json")["code_sha"]
                checks = read(folder / "checks.json")
                assert len(checks["public"]) == len(spec["public"])
                rows.append((k, f"{seed}/{stage}", path, all(checks["public"]), checks["diagnostic"]))
    return rows


def pilot_public():
    """Actual selector vs eligible alternatives, using only archived public scores."""
    tasks = {t["id"]: len(t["public"]) for t in read(PILOT / "tasks.json")}
    jobs = {(r["task"], r["seed"], r["mode"]): r
            for path in (PILOT / "jobs").glob("*.json") for r in [read(path)]}
    checks = {}
    for (task, _, _), job in jobs.items():
        for c in job["public_checks"]:
            key = (task, c["code_sha"])
            ok = c["passed"] == tasks[task]
            if checks.setdefault(key, ok) != ok:
                raise ValueError("inconsistent archived public checks")
    results = []
    for (task, seed, mode), job in sorted(jobs.items()):
        if any((task, seed, m) not in jobs for m in "ABCD"):
            continue
        sel = job["selected"]
        chosen = bool(sel["code"]) and checks[task, sha(sel["code"].encode())]
        ready = {sha(b["code"].encode()) for b in job["branches"] if b["code"]
                 and b["stopped"] * 1000 <= min(30000, sel["published_ms"])}
        values = [checks.get((task, key)) for key in ready]
        oracle = chosen or any(values)
        if not oracle and None in values:
            raise ValueError("ungraded alternative could change the oracle")
        results.append(dict(task=task, seed=seed, mode=mode, chosen=chosen, oracle=oracle))
    return results


def main():
    rows = inventory()
    private = DATA / "stepback-live-01-private.json"
    fixture_sha = sha(private.read_bytes())
    assert fixture_sha == read(PILOT / "lock.json")["hidden_sha256"]
    refs = read(private)
    OUT.mkdir(exist_ok=True)
    cache = OUT / "scores"
    cache.mkdir(exist_ok=True)
    manifest = {
        "fixture_sha": fixture_sha,
        "candidates": [
            dict(task=k, branch=b, path=str(p.relative_to(RUNS)) if p.exists() else None,
                 sha=sha(p.read_bytes()) if p.exists() else None)
            for k, b, p, _, _ in rows
        ],
    }
    lock = OUT / "inventory.json"
    if lock.exists() and read(lock) != manifest:
        raise ValueError("frozen candidates or evaluation data changed")
    if not lock.exists():
        save(lock, manifest)
    scores = []
    for k, branch, path, public, diag in rows:
        hidden = refs[k]
        assert hidden
        code = path.read_text() if path.exists() else ""
        key = sha((k + "\0" + code).encode())
        result = cache / (key + ".json")
        if not result.exists():
            # A single failure settles the all-cases metric; test the rest only if needed.
            split = min(3, len(hidden))
            passed = run_cases(code, hidden[:split])
            if all(passed) and split < len(hidden):
                passed += run_cases(code, hidden[split:])
            save(result, dict(task=k, passed=passed, n=len(hidden)))
        passed = read(result)["passed"]
        private_ok = len(passed) == len(hidden) and all(passed)
        # Only R03 children lack recorded diagnostic checks. Run these only when
        # they can affect the conjunction of public, private and diagnostic passes.
        if diag is None and public and private_ok:
            extra = cases(k)
            diagfile = cache / (key + "-diagnostic.json")
            if not diagfile.exists():
                save(diagfile, dict(zip([c["label"] for c in extra], run_cases(code, extra))))
            diag = read(diagfile)
        if diag is not None:
            assert set(diag) == {c["label"] for c in cases(k)}
        scores.append(dict(task=k, branch=branch, has_code=bool(code), public=public,
                           hidden=private_ok, combined=bool(public and private_ok and all(diag.values()))))
        print(k, branch, private_ok, flush=True)
    pools = {}
    for label in ("parent", "r03_pair", "approach", "middle", "code", "r04_pool", "all"):
        by_task = {}
        for k in sorted({r["task"] for r in scores}):
            subset = [r for r in scores if r["task"] == k and (
                r["branch"] == "parent" or label == "all"
                or (label == "r03_pair" and r["branch"] == "child")
                or (label == "r04_pool" and "/" in r["branch"])
                or r["branch"].endswith("/" + label))]
            by_task[k] = {m: any(r[m] for r in subset) for m in ("public", "hidden", "combined")}
        pools[label] = by_task
    save(OUT / "summary.json", dict(hidden_counts={k: len(refs[k]) for k in pools["all"]},
                                     pools=pools, rows=scores))
    save(OUT / "pilot-public.json", pilot_public())


if __name__ == "__main__":
    main()
