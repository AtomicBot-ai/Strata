"""Correctness and state-lifetime gates on the matched upstream Metal build."""
import argparse
import numpy as np
from pathlib import Path
from runner import addressed, cold, engine, fixture, memory, save, tree


def score(ref, got):
    a = np.frombuffer(ref, dtype="<f4")
    b = np.frombuffer(got, dtype="<f4")
    if a.size != 200058 or b.size != a.size or not (np.isfinite(a).all() and np.isfinite(b).all()):
        raise ValueError("invalid logits")
    delta = a.astype(float) - b
    return dict(maxabs=float(np.abs(delta).max()), rms=float(np.mean(delta**2)**0.5),
                same_argmax=bool(a.argmax() == b.argmax()), exact=ref == got)


def hist_boundaries(out, w):
    rows = []
    for boundary in (1023, 1024, 1025, 2049):
        # A slightly longer prompt leaves exactly 'boundary' committed tokens in the snapshot.
        task = fixture(boundary+1, 4, 6, boundary)
        reference = None
        stats = []
        for mode, width, cache in (("B3", 2, True), ("B3", 2, True), ("B3", 1, True),
                                   ("B3", 2, False), ("B4", 2, True)):
            cold(w)
            row, logits = tree(w, task, mode, native_width=width, cache=cache)
            if reference is None:
                reference = logits
            stats.append([score(reference[k], logits[k]) for k in sorted(reference)])
        failures = []
        for i, candidate in enumerate(stats[-1]):
            baseline = [item[i] for item in stats[:-1]]
            if (any(candidate[key] > max(r[key] for r in baseline) + 1e-6 for key in ("maxabs", "rms"))
                    or (all(r["same_argmax"] for r in baseline) and not candidate["same_argmax"])):
                failures.append(i)
        rows.append(dict(boundary=boundary, shape_errors=stats, failing_branches=failures))
        save(out / "boundaries.json", rows)
        if failures:
            raise ValueError(("native numeric envelope exceeded", boundary, failures))
        print("boundary", boundary, flush=True)


def lifecycle(out, w):
    cold(w)
    root = [31 + i % 401 for i in range(78)]
    checks = []
    for src in (1, 0):
        dst = 1-src
        cold(w)
        addressed(w, src, root, 1)
        w.ctrl(f"LABSAVE {src}", "SAVED")
        # Advance the parent independently, then return to the earlier immutable point.
        addressed(w, src, root+[731, 912], 3)
        w.ctrl(f"LABRESTORE {dst}", "RESTORED")
        tokens, actual, _ = addressed(w, dst, root+[123], 3, seed=411, temperature=0.7)
        # A nested snapshot can replace the parent after the child becomes independent.
        w.ctrl(f"LABSAVE {dst}", "SAVED")
        w.ctrl(f"LABRESTORE {src}", "RESTORED")
        nested = root + [123] + tokens + [651]
        nt, nv, _ = addressed(w, src, nested)
        cold(w)
        addressed(w, src, root, 1)
        expected, reference, _ = addressed(w, src, root+[123], 3, seed=411, temperature=0.7)
        nref, nvec, _ = addressed(w, src, nested)
        checks.append(dict(source=src, destination=dst, endpoint=score(reference, actual),
                           nested=score(nvec, nv), rng_equal=tokens==expected,
                           nested_tokens_equal=nt==nref))
        save(out / "addressed.json", checks)
        if reference != actual or nvec != nv or tokens != expected or nt != nref:
            raise ValueError(("same-shape restore", src, dst))
        w.ctrl("LABDROP", "DROPPED")
        w.ctrl(f"LABRESTORE {src}", "ERR")
    # Keep one model loaded and stress actual copy/free, with capped retained footprint
    # relative to the allocator's warm plateau after the first ten cycles.
    samples = []
    for i in range(110):
        w.ctrl("LABSAVE 0", "SAVED")
        w.ctrl("LABRESTORE 1", "RESTORED")
        w.ctrl("LABDROP", "DROPPED")
        if i in (9, 29, 59, 109):
            samples.append(memory(w.proc.pid))
    retained = samples[-1]["footprint"] - samples[0]["footprint"]
    save(out / "lifecycle.json", dict(cross_slot=checks, samples=samples, retained=retained,
                                      tolerance_bytes=16*2**20))
    if retained > 16*2**20:
        raise ValueError("retained footprint above 16 MiB after warm plateau")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("out", type=Path)
    out = cli.parse_args().out
    out.mkdir(parents=True, exist_ok=False)
    try:
        with engine(out, 2304, diag=True) as w:
            lifecycle(out, w)
            hist_boundaries(out, w)
    except Exception as exc:
        save(out / "gate.json", dict(status="failed", error=str(exc)))
        raise
    save(out / "gate.json", dict(status="passed"))
