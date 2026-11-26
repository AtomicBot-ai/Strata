"""Gate on fixed forced trajectories. One short branch, one crossing the 1024-row SWA ring."""

import argparse
import hashlib
import signal
import time
import numpy as np
from engine import BIN, engine, record


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    prefix = [100 + i % 730 for i in range(192)]
    paths = {"A": [271 + i % 511 for i in range(1041)], "B": [513, 41, 97]}
    with engine(out / "metal.log", context=1536) as session, (out / "gate.jsonl").open("x") as rows:
        record(rows, binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(), prefix=prefix, paths=paths)

        def evaluate(label):
            # Teacher-force the trajectory, then compare every vocabulary logit at its endpoint.
            ids = prefix + paths[label]
            result = session.gen(ids, 1)
            raw = bytes.fromhex(session.control("LOGITS", "LOGITS")[0])
            logits = np.frombuffer(raw, dtype="<f4")
            if len(logits) != 200058 or not np.isfinite(logits).all():
                raise ValueError("invalid logits")
            return result, logits

        reference = {}
        noise = {}
        for label in paths:
            for repeat in (1, 2):
                session.gen(prefix, 0)  # Match segmentation of the saved path.
                result, logits = evaluate(label)
                if repeat == 1:
                    reference[label] = (logits, result["tokens"])
                else:
                    noise[label] = float(np.max(np.abs(reference[label][0] - logits)))
                    if reference[label][1] != result["tokens"]:
                        raise ValueError("greedy replay unstable")
                record(
                    rows,
                    path=label,
                    mode="replay",
                    repeat=repeat,
                    **result,
                    hash=hashlib.sha256(logits).hexdigest(),
                    max_repeat_error=noise.get(label),
                )
        session.gen(prefix, 0)
        begin = time.monotonic()
        saved = session.control("SAVE", "SAVED")
        record(
            rows,
            saved_tokens=int(saved[0]),
            payload_bytes=int(saved[1]),
            save_ms=1000 * (time.monotonic() - begin),
        )
        for label in ("A", "B", "B", "A"):
            begin = time.monotonic()
            restored = session.control("RESTORE", "RESTORED")
            restore_ms = 1000 * (time.monotonic() - begin)
            result, logits = evaluate(label)
            diff = float(np.max(np.abs(reference[label][0] - logits)))
            matched = (
                int(restored[0]) == result["reused"] == len(prefix)
                and diff <= noise[label]
                and result["tokens"] == reference[label][1]
            )
            record(
                rows,
                mode="checkpoint",
                path=label,
                restore_ms=restore_ms,
                max_error=diff,
                hash=hashlib.sha256(logits).hexdigest(),
                matched=matched,
                **result,
            )
            if not matched:
                raise RuntimeError(f"replay mismatch on {label}: {diff} vs noise {noise[label]}")
        session.control("DROP", "DROPPED")
        session.send("RESTORE")
        if session.proc.stdout.readline().strip() != "ERR no saved prefix":
            raise RuntimeError("released checkpoint still usable")


if __name__ == "__main__":
    from pathlib import Path

    args = argparse.ArgumentParser()
    args.add_argument("out", type=Path)

    def deadline(*_):
        raise TimeoutError("checkpoint gate exceeded 120 seconds")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(120)
    run(args.parse_args().out)
