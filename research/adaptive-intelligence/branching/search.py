"""One bounded tree, multiple execution controls; no access to held-out answers."""

import ctypes
import re
import os
import argparse
import hashlib
import json
import signal
import time
from pathlib import Path
from tokenizers import Tokenizer
from engine import BIN, MODEL, ROOT, TOKENIZER, batch, engine, record

DATA = ROOT / ".work/pilot-data"
MAX_NEW = 320
ANCHOR = 24


def prompt(tok, task):
    ask = (
        "Return a Python 3 stdin/stdout solution in a single fenced python block."
        if task["domain"] == "code"
        else "Give the final integer in \\boxed{}."
    )
    q = task["question"]
    for case in task.get("public", []):
        q += f"\nExample input:\n{case['input']}\nExample output:\n{case['output']}"
    text = (
        "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
        "<|message_user|><|content_text|>" + q + "\n" + ask + "<|end_message|><|message_model|>"
    )
    return tok.encode(text, add_special_tokens=False).ids


def reset(session, slot=0):
    session.control(f"BCO {slot} 1", "BCOK")


def run_tree(session, tok, task, mode, seed):
    base = prompt(tok, task)
    # Both controls can afford two full independent attempts. A hard cap of four avoids
    # spending the entire pilot on trivial answers. All forwarded model tokens are billed.
    budget = 2 * (len(base) + MAX_NEW) + ANCHOR
    # Slot cleanup is part of the task's wall cost. Models are already loaded.
    start = time.monotonic()
    used = 0
    candidates = []
    prefixes = []
    controls = []
    anchor = []
    snapshot = 0
    if mode == "batch":
        reset(session, 1)
    reset(session)
    if mode != "independent":
        initial = session.gen(base, ANCHOR, seed, 1)
        used += initial["processed"]
        anchor = initial["tokens"]
        if initial["reason"] == "stop":
            candidates.append(
                dict(ids=anchor, seed=seed, reason="stop", at_ms=1000 * (time.monotonic() - start))
            )
        elif mode == "checkpoint":
            saved = session.control("SAVE", "SAVED")
            if int(saved[0]) != len(base) + len(anchor) - 1:
                raise ValueError("anchor position")
            snapshot = int(saved[1])
    pref = base + anchor
    index = 0
    while index < 4:
        if anchor and initial["reason"] == "stop":
            break
        if mode == "batch" and index == 0:
            # RESUME has no ID in this protocol; issue requests together in known slot order.
            n = min(MAX_NEW, (budget - used - len(pref) - 1) // 2 + 1)
            if n <= 0:
                break
            jobs = [(pref, n, seed + 1), (pref, n, seed + 2)]
            outputs = batch_with_first_resume(session, jobs, len(pref) - 1)
            index = 2
            for j, out in enumerate(outputs):
                used += out["processed"]
                candidates.append(
                    dict(
                        ids=anchor + out["tokens"],
                        seed=jobs[j][2],
                        reason=out["reason"],
                        at_ms=1000 * (time.monotonic() - start),
                    )
                )
            continue
        reuse = 0
        if mode == "checkpoint" or (mode == "replay" and index == 0):
            reuse = len(pref) - 1
        if mode == "checkpoint" and index:
            t = time.monotonic()
            session.control("RESTORE", "RESTORED")
            controls.append(1000 * (time.monotonic() - t))
        target = pref if mode != "independent" else base
        # Ordinary one-slot replay can occasionally reuse a finished sibling prefix;
        # conservative admission never relies on such a hit.
        new = min(MAX_NEW, (budget - used) - (len(target) - reuse) + 1)
        if new <= 0:
            break
        branch_seed = seed + index + 1
        out = session.gen(target, new, branch_seed, 1)
        used += out["processed"]
        if used > budget:
            raise ValueError("token budget overrun")
        prefixes.append(out["reused"])
        candidates.append(
            dict(
                ids=anchor + out["tokens"],
                seed=branch_seed,
                reason=out["reason"],
                at_ms=1000 * (time.monotonic() - start),
            )
        )
        index += 1
    if snapshot:
        session.control("DROP", "DROPPED")
    elapsed = 1000 * (time.monotonic() - start)
    for cand in candidates:
        cand["text"] = tok.decode(cand["ids"], skip_special_tokens=False)
    return dict(
        mode=mode,
        seed=seed,
        task_id=task["id"],
        domain=task["domain"],
        input_ids=base,
        anchor=anchor,
        processed=used,
        budget=budget,
        wall_ms=elapsed,
        reuse=prefixes,
        restore_ms=controls,
        snapshot_bytes=snapshot,
        candidates=candidates,
    )


def batch_with_first_resume(session, jobs, expected, temperature=1):
    # SUBMIT in one write so both slots participate in the scheduler. In this
    # first wave only slot 0 has state, and that entire prefix is a known hit.
    class FirstResume:
        saw = False

        def send(self, msg):
            session.send(msg)

        def line(self):
            line = session.line()
            if line.startswith("RESUME "):
                if self.saw or int(line.split()[1]) != expected:
                    raise ValueError(line)
                self.saw = True
                line = session.line()
            return line

    reader = FirstResume()
    result = batch(reader, jobs, temperature)
    if not reader.saw:
        raise RuntimeError("first slot did not reuse native prefix")
    result[0]["processed"] -= expected
    return result


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("out", type=Path)
    cli.add_argument("--split", choices=["debug", "pilot"], required=True)
    cli.add_argument("--modes", nargs="+", default=["replay", "checkpoint", "batch", "independent"])
    args = cli.parse_args()
    tasks = [t for t in json.loads((DATA / "public.json").read_text()) if t["split"] == args.split]
    if not tasks:
        raise ValueError("empty split")
    args.out.mkdir(parents=True, exist_ok=False)
    tok = Tokenizer.from_file(str(TOKENIZER))
    (args.out / "manifest.json").write_text(
        json.dumps(
            dict(
                binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(),
                model=str(MODEL),
                input_sha256=hashlib.sha256((DATA / "public.json").read_bytes()).hexdigest(),
                modes=args.modes,
                tasks=[t["id"] for t in tasks],
                anchor=ANCHOR,
                max_new=MAX_NEW,
            ),
            indent=2,
        )
    )
    seeds = [101] if args.split == "debug" else [101, 211, 307]
    with (args.out / "raw.jsonl").open("x") as rows:
        for i, seed in enumerate(seeds):
            modes = args.modes[i:] + args.modes[:i]
            for mode in modes:
                with engine(
                    args.out / f"{seed}-{mode}.log",
                    slots=2 if mode == "batch" else 1,
                    checkpoints=mode == "checkpoint",
                ) as session:
                    for t in tasks:
                        row = run_tree(session, tok, t, mode, seed)
                        buf = (ctypes.c_uint64 * 64)()
                        rc = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pid_rusage(
                            session.proc.pid, 4, ctypes.byref(buf)
                        )
                        row["peak_process_footprint"] = None if rc else buf[30]
                        log = (args.out / f"{seed}-{mode}.log").read_text()
                        total = re.search(r"TotalAlloc=([0-9.]+) GiB", log)
                        row["metal_allocation_gib"] = float(total[1]) if total else None
                        record(rows, **row)
                        if (
                            not total
                            or rc
                            or buf[30] > 20 * 2**30
                            or row["metal_allocation_gib"] + row["snapshot_bytes"] / 2**30 > 20
                            or row["processed"] > row["budget"]
                        ):
                            raise RuntimeError("pilot resource ceiling or accounting failure")
                        print(
                            seed, mode, t["id"], len(row["candidates"]), round(row["wall_ms"]), flush=True
                        )


if __name__ == "__main__":

    def limit(*_):
        raise TimeoutError("inference pilot time expired")

    signal.signal(signal.SIGALRM, limit)
    if os.environ.get("STRATA_PILOT_STARTED"):
        first_manifest = Path(os.environ["STRATA_PILOT_STARTED"])
        remaining_seconds = int(first_manifest.stat().st_mtime + 7200 - time.time())
        if remaining_seconds <= 0:
            raise TimeoutError("two-hour pilot allocation exhausted")
        signal.alarm(min(6000, remaining_seconds))
    else:
        signal.alarm(6000)
    main()
