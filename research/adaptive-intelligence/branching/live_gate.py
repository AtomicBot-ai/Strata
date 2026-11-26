"""Targeted GPU gate: same-shape replay, cross-slot restore, cancellation and ring wrap."""

import argparse
import hashlib
import json
import signal
from pathlib import Path

from engine import BIN, engine
from live_slots import LiveSlots


def expect(x, msg):
    if not x:
        raise RuntimeError(msg)


def digest(live, rid):
    import numpy as np

    data = bytes.fromhex(live.s.control("LIVELOGITS " + rid, "LOGITS")[0])
    logits = np.frombuffer(data, dtype="<f4")
    expect(len(logits) == 200058 and np.isfinite(logits).all(), "invalid logits")
    return hashlib.sha256(data).hexdigest()


def until(live, tag, ids):
    found = {}
    while set(found) != set(ids):
        for row in live.tick():
            if row[0] == tag:
                expect(row[1] in ids and row[1] not in found, "unexpected event")
                found[row[1]] = row
    return found


def pair(live, ids, limit, reuse=False):
    for slot, seq in enumerate(ids):
        # Read RESUME immediately; fresh() otherwise leaves it for tick().
        live.fresh(str(slot), seq, 43, limit, 0, reuse=reuse, free_slot=slot)
        if reuse:
            expect(live.s.line().startswith("RESUME "), "expected restored prefix")


def gate(out):
    out.mkdir(exist_ok=False, parents=True)
    audit = []
    keys = ["0", "1"]
    prefix = [100 + i % 730 for i in range(1103)]
    tails = [[270 + i for i in range(29)], [510 - i for i in range(29)]]
    with engine(out / "metal.log", slots=2, context=1536) as session:
        live = LiveSlots(session)
        expect(live.allocated < 20 * 2**30, "allocation cap")
        for src in (0, 1):
            dest = 1 - src
            variants = [prefix + tail for tail in tails]
            # Reference: both slots processed the same long prefix in the same batched shape.
            pair(live, [prefix, prefix], 1)
            until(live, "DONE", keys)
            last = int(live.snapshot(keys[src])[2])
            pair(live, variants, 1, reuse=True)
            events = until(live, "DONE", keys)
            hashes = [digest(live, k) for k in keys]
            # Perturb both physical rings, then restore the source snapshot into both slots.
            pair(live, [[700 + slot] * 1400 for slot in range(2)], 1)
            until(live, "DONE", keys)
            for slot in range(2):
                session.control(f"LIVERESTORE {src} {slot}", "RESTORED")
            pair(live, variants, 1, reuse=True)
            until(live, "DONE", keys)
            expect(
                [digest(live, k) for k in keys] == hashes,
                "cross-slot forced logits mismatch",
            )
            live.drop(str(src))

            pair(live, [prefix, prefix], 5)
            roots = until(live, "T", keys)
            ref_tokens = [int(roots[k][2]) for k in keys]
            reference = []
            for _ in range(4):
                t = until(live, "T", keys)
                reference.append([int(t[k][2]) for k in keys])
            final_logits = [digest(live, k) for k in keys]
            pair(live, [prefix, prefix], 5)
            until(live, "T", keys)
            n, size, pending = live.snapshot(str(src))
            expect(
                n == len(prefix) and pending == last == ref_tokens[src],
                "pending token mismatch",
            )
            live.cancel(str(dest))
            child = "child"
            expect(
                live.fork(str(src), child, dest, 71) == ref_tokens[dest],
                "first child token mismatch",
            )
            names = keys.copy()
            names[dest] = child
            for expected in reference:
                got = until(live, "T", names)
                expect(
                    [int(got[k][2]) for k in names] == expected,
                    "live sibling token mismatch",
                )
            expect(
                [digest(live, k) for k in names] == final_logits, "fork logits mismatch"
            )
            live.cancel(child)
            live.drop(str(src))
            expect(size + live.allocated <= 20 * 2**30, "snapshot allocation cap")
            audit.append(
                dict(
                    source=src,
                    destination=dest,
                    processed=n,
                    pending=pending,
                    bytes=size,
                    tails_logits_sha256=hashes,
                    live_logits_sha256=final_logits,
                )
            )
    (out / "gate.json").write_text(
        json.dumps(
            dict(
                binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(),
                metal_bytes=live.allocated,
                matched=audit,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    signal.alarm(150)
    gate(p.parse_args().out)
