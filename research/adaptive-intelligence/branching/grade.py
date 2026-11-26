"""Select using public examples only, then evaluate every candidate for oracle diagnostics."""

import argparse
import collections
import hashlib
import json
import os
import signal
import re
import subprocess
import time
from pathlib import Path

from engine import ROOT, record
from prepare import DATA

IMAGE = "python@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89"
# The container receives inputs, never expected outputs. Each case gets a new isolated
# Python process. Temp files bound output size, and there are no network or host mounts.
RUNNER = """
import json, os, resource, subprocess, sys, tempfile
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576,1048576))
    resource.setrlimit(resource.RLIMIT_CPU, (2,2))
d=json.load(sys.stdin)
path='/tmp/candidate.py'
open(path,'w').write(d['code'])
results=[]
for value in d['inputs']:
    with tempfile.TemporaryFile() as out:
        try:
            r=subprocess.run([sys.executable,'-I','-B',path],input=value.encode(),
                stdout=out,stderr=subprocess.DEVNULL,timeout=3,preexec_fn=limits)
            out.seek(0)
            results.append(out.read(1048576).decode('utf8','replace') if r.returncode==0 else None)
        except subprocess.TimeoutExpired:
            results.append(None)
print(json.dumps(results))
"""


def final_text(generated):
    # Inkling can emit a thinking channel followed by the visible text channel.
    if (
        "<|content_thinking|>" in generated
        and "<|content_text|>" not in generated.rsplit("<|content_thinking|>", 1)[-1]
    ):
        return ""
    return (
        generated.rsplit("<|content_text|>", 1)[-1]
        .split("<|end_message|>")[0]
        .split("<|content_model_end_sampling|>")[0]
    )


def extract(text, domain):
    text = final_text(text)
    if domain == "code":
        blocks = re.findall(r"```(?:python3?|py)?[ \t]*\n(.*?)```", text, re.I | re.S)
        return blocks[-1].strip() if blocks else None
    vals = re.findall(r"\\boxed\s*\{\s*([-+]?\d[\d,]*)\s*\}", text)
    if not vals:
        match = re.fullmatch(r"\s*([-+]?\d[\d,]*)[.!]?\s*", text)
        vals = [match[1]] if match else []
    return str(int(vals[-1].replace(",", ""))) if vals else None


def run_cases(code, cases):
    if not code:
        return [False] * len(cases)
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=16",
        "--memory=192m",
        "--cpus=1",
        "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=8m,mode=1777",
        IMAGE,
        "python",
        "-I",
        "-B",
        "-c",
        RUNNER,
    ]
    r = subprocess.run(
        command,
        input=json.dumps(dict(code=code, inputs=[t["input"] for t in cases])),
        text=True,
        capture_output=True,
        timeout=15 + 4 * len(cases),
    )
    if r.returncode:
        raise RuntimeError("Docker evaluator failed: " + r.stderr[:500])
    actual = json.loads(r.stdout)
    if not isinstance(actual, list) or len(actual) != len(cases):
        raise ValueError("incomplete evaluator")
    return [v is not None and v.split() == t["output"].split() for v, t in zip(actual, cases)]


def choose(domain, answers, scores):
    if not answers:
        return None
    if domain == "math":
        votes = collections.Counter(a for a in answers if a is not None)
        return max(range(len(answers)), key=lambda i: votes.get(answers[i], 0))
    return max(range(len(answers)), key=lambda i: scores[i])


def evaluate(directory, output):
    tasks = {r["id"]: r for r in json.loads((DATA / "public.json").read_text())}
    rows = [json.loads(l) for l in (directory / "raw.jsonl").open()]
    labels = json.loads((DATA / "labels.json").read_text())
    # Memoize deterministic grading across modes. Charge standalone public check time
    # even on a cache hit for another arm; within a request identical programs can reuse it.
    cache = {}

    def grade_program(key, code, cases):
        if key not in cache:
            begin = time.monotonic()
            passed = run_cases(code, cases)
            cache[key] = (passed, 1000 * (time.monotonic() - begin))
        return cache[key]

    with output.open("x") as f:
        for r in rows:
            task = tasks[r["task_id"]]
            domain = r["domain"]
            answers = []
            scores = []
            completion_ms = []
            seen = set()
            verify_ms = 0
            for c in r["candidates"]:
                begin = time.monotonic()
                a = extract(c["text"], domain)
                extract_ms = 1000 * (time.monotonic() - begin)
                answers.append(a)
                public_score = 0
                if domain == "code" and a:
                    key = (task["id"], "public", a)
                    passed, ms = grade_program(key, a, task["public"])
                    if key not in seen:
                        verify_ms += ms
                    seen.add(key)
                    public_score = sum(passed)
                verify_ms += extract_ms
                scores.append(public_score)
                completion_ms.append(c["at_ms"] + verify_ms)
            selected = choose(domain, answers, scores)
            correct = []
            for a in answers:
                if domain == "math":
                    correct.append(a == labels[task["id"]])
                else:
                    key = (task["id"], "private", a)
                    passed, _ = grade_program(key, a, labels[task["id"]])
                    correct.append(bool(passed) and all(passed))
            record(
                f,
                task_id=task["id"],
                mode=r["mode"],
                seed=r["seed"],
                domain=domain,
                selected=selected,
                correct=bool(selected is not None and correct[selected]),
                oracle=any(correct),
                answer_values=answers
                if domain == "math"
                else [hashlib.sha256(a.encode()).hexdigest() if a else None for a in answers],
                public_scores=scores,
                correct_candidates=correct,
                completion_ms=completion_ms,
                wall_ms=r["wall_ms"] + verify_ms,
                verify_ms=verify_ms,
                processed=r["processed"],
                budget=r["budget"],
                peak_process_footprint=r["peak_process_footprint"],
            )
            print(r["mode"], task["id"], correct, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = os.environ.get("STRATA_PILOT_STARTED")
    if started:
        remaining = int(Path(started).stat().st_mtime + 7200 - time.time())
        if remaining <= 0:
            raise TimeoutError("two-hour pilot allocation exhausted")

        def stop(*_):
            raise TimeoutError("two-hour pilot allocation exhausted")

        signal.signal(signal.SIGALRM, stop)
        signal.alarm(remaining)
    evaluate(args.directory, args.output)
