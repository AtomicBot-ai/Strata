"""Check the behavior of the single repair requested from the OpenCode client."""
import argparse
import ast
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

SPRINT = Path(__file__).resolve().parents[1]
FIXTURE = SPRINT.parents[1] / ".work/final-sprint/s04-fixture"
OUT = SPRINT / "runs/S04"


def check_repair():
    source = (FIXTURE / "terminal/setup.py").read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if getattr(n, "name", None) == "shape_engine_fetch")
    shape = types.SimpleNamespace(shown=lambda *args: "Inkling", WORDS={
        "setup_failed": "{model} failed", "setup_failed_hint": "See the line above. Nothing was downloaded for the model. Run this again when the update feed has it.",
        "setup_skip": "skip {model}", "setup_ok": "ok {model}: {version}, {folder}"})
    messages, failures, warnings = [], [], []
    reason = "server returned an invalid component digest"

    def ensure(shape_id, feed, *, emit, title):
        emit("reading manifest")
        emit(reason)
        return None

    shape.ensure = ensure
    class Failed(Exception):
        pass

    def fail(*args):
        failures.append(" ".join(map(str, args)))
        raise Failed()

    control = types.ModuleType("strata_control")
    control.shape_engine = shape
    control.engine_component = types.SimpleNamespace(components_dir=lambda: FIXTURE)
    cli = types.ModuleType("strata_cli")
    cli.update_cmd = types.SimpleNamespace(_feed_source=lambda *args: "fixture-feed")
    namespace = dict(os=os, argparse=argparse, SHAPE_ENGINE={"shape":"inkling2","title":"Inkling"},
                     say=messages.append, warn=warnings.append, fail=fail)
    with mock.patch.dict(sys.modules, {"strata_control": control, "strata_cli": cli}):
        isolated = ast.Module(body=[fn], type_ignores=[])
        exec(compile(isolated, str(FIXTURE / "terminal/setup.py"), "exec"), namespace)
        with mock.patch.dict(os.environ, {"STRATA_ALLOW_NO_ENGINE":"0"}):
            try:
                namespace["shape_engine_fetch"](argparse.Namespace())
            except Failed:
                pass
        standard_messages = list(messages)
        with mock.patch.dict(os.environ, {"STRATA_ALLOW_NO_ENGINE":"1"}):
            skipped = namespace["shape_engine_fetch"](argparse.Namespace()) is None
    return dict(reason_visible=bool(failures and reason in failures[0]),
                dangling_reference_removed=bool(failures and "line above" not in failures[0]),
                terminal_progress=any(reason in m for m in standard_messages),
                allow_no_engine_preserved=skipped and len(failures)==1 and bool(warnings))


def verify_parallel():
    rows = [json.loads(line) for line in (OUT / "parallel/client.jsonl").read_text().splitlines() if line.strip()]
    parent = next((row.get("sessionID") for row in rows if row.get("sessionID")), None)
    tools = []
    for row in rows:
        part = row.get("part", {})
        if part.get("tool") in ("subagent", "task"):
            state = part.get("state", {})
            tools.append({"status": state.get("status"), "time": state.get("time"), "agent": state.get("input", {}).get("agent")})
    database = FIXTURE.parent / "opencode/data/opencode/opencode.db"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as conn:
        children = [dict(id=ident, start=start, end=end, outcome=outcome, directory=directory)
                    for ident,start,end,outcome,directory in conn.execute(
                        "select id,time_created,time_idle,idle_outcome,directory from session_v2 where parent_id=? order by time_created", (parent,))]
    complete = [c for c in children if c["end"] and c["outcome"]=="succeeded"]
    overlap = max((min(a["end"],b["end"])-max(a["start"],b["start"])
                   for i,a in enumerate(complete) for b in complete[i+1:]), default=0)
    return dict(client_calls=tools, children=children, successful_child_overlap_ms=max(0,overlap))


if __name__ == "__main__":
    report = dict(repair=check_repair(), parallel=verify_parallel())
    (OUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    diff = subprocess.check_output(["git", "diff", "--", "terminal/setup.py"], cwd=FIXTURE, text=True)
    (OUT / "repair/fixture.patch").write_text(diff)
    print(report)
