"""R02: reconstruct branch lifetimes from the sealed public job logs only."""

import json
from collections import Counter
from pathlib import Path
from statistics import median

RUNS = Path(__file__).resolve().parents[1] / "runs"
PILOT = RUNS / "stepback-live-01"
OUT = RUNS / "stepback-r02"


def load(path):
    return json.loads(path.read_text())


def rows_for(job, examples):
    mode = job["mode"]
    selected = job["selected"]
    delivery = selected["delivered_ms"] / 1000
    public_success = any(c["passed"] == examples for c in job["public_checks"])
    branches = job["branches"]
    by_name = {b["name"]: b for b in branches}
    early_cancels = {
        b["name"]
        for b in branches
        if b["parent"] is not None
        and b["reason"] == "cancel"
        and b["stopped"] < delivery
    }
    # Only pruning calls cancel on a live child independently of request termination.
    # A pre-delivery record plus the request's exact prune count gives an unambiguous attribution here.
    assert len(early_cancels) == job["pruned"]
    assert not early_cancels or mode == "D"
    end = (
        "public_pass"
        if public_success
        else "deadline"
        if delivery >= 29.980
        else "exhausted"
    )
    common = dict(
        task=job["task"],
        seed=job["seed"],
        mode=mode,
        request_end=end,
        delivery_s=delivery,
    )
    for b in branches:
        ready, started, stopped = b["ready"], b["started"], b["stopped"]
        assert 0 <= ready <= started <= stopped
        cause = b["reason"]
        if cause == "cancel":
            cause = "duplicate_prune" if b["name"] in early_cancels else end
            assert cause != "exhausted"
        yield dict(
            common,
            branch=b["name"],
            parent=b["parent"],
            state="started",
            kind="child" if b["parent"] is not None else "fresh",
            ready_s=ready,
            started_s=started,
            stopped_s=stopped,
            queue_s=started - ready,
            active_s=stopped - started,
            pre_delivery_active_s=max(0, min(delivery, stopped) - started),
            generated_tokens=len(b["tokens"]) - b["suffix_start"],
            engine_reason=b["reason"],
            inferred_end=cause,
            has_code=bool(b["code"]),
            selected=selected["branch"] == b["name"],
        )
    # Initial attempts all enter the queue at offset zero. A confirmed marker
    # queues a child, but the timestamp survives only when the child starts.
    pending = []
    if mode == "B":
        pending.extend((str(i), None, 0.0) for i in range(4) if str(i) not in by_name)
    if mode in "CD":
        for parent in ("0", "1"):
            b = by_name[parent]
            name = str(int(parent) + 2)
            if b["confirmed"] and name not in by_name:
                pending.append((name, parent, None))
            elif not b["confirmed"] and name not in by_name:
                # On this dataset every such parent was still running at cutoff.
                assert b["reason"] == "cancel" and b["stopped"] >= delivery
    for name, parent, ready in pending:
        yield dict(
            common,
            branch=name,
            parent=parent,
            state="never_started",
            kind="child" if parent is not None else "fresh",
            ready_s=ready,
            started_s=None,
            stopped_s=None,
            queue_s=delivery - ready if ready is not None else None,
            active_s=0.0,
            pre_delivery_active_s=0.0,
            generated_tokens=0,
            engine_reason=None,
            inferred_end=end,
            has_code=False,
            selected=False,
        )


def main():
    lock = load(PILOT / "lock.json")
    schedule = [tuple(k) for k in lock["schedule"]]
    tasks = {r["id"]: len(r["public"]) for r in load(PILOT / "tasks.json")}
    jobs = [load(p) for p in (PILOT / "jobs").glob("*.json")]
    index = {(j["task"], j["seed"], j["mode"]): j for j in jobs}
    assert len(index) == len(jobs) == 210 and set(index) == set(schedule[:210])
    assert len(schedule) == 288
    paired = {(t, s) for t, s, _ in index if all((t, s, m) in index for m in "ABCD")}
    assert len(paired) == 52
    records = []
    for key in schedule[:210]:
        for row in rows_for(index[key], tasks[key[0]]):
            row["complete_quartet"] = key[:2] in paired
            records.append(row)
    assert len(records) == len(
        {(r["task"], r["seed"], r["mode"], r["branch"]) for r in records}
    )
    OUT.mkdir(exist_ok=True)
    (OUT / "branches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    summary = {}
    for m in "ABCD":
        for kind in ("fresh", "child"):
            group = [r for r in records if r["mode"] == m and r["kind"] == kind]
            started = [r for r in group if r["state"] == "started"]
            if not started:
                continue
            summary[f"{m}_{kind}"] = {
                "started": len(started),
                "waiting_at_end": len(group) - len(started),
                "median_queue_s": median(r["queue_s"] for r in started),
                "median_active_s": median(r["active_s"] for r in started),
                "median_generated_tokens": median(
                    r["generated_tokens"] for r in started
                ),
                "end_counts": dict(Counter(r["inferred_end"] for r in started)),
                "extracted_programs": sum(r["has_code"] for r in started),
                "selected": sum(r["selected"] for r in started),
            }
    result = dict(
        completed_jobs=len(jobs),
        planned=len(schedule),
        paired_quartets=len(paired),
        by_mode=dict(Counter(j["mode"] for j in jobs)),
        groups=summary,
    )
    (OUT / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
