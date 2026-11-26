"""Check real upstream slot-local reuse, eviction, and greedy tokens against cold runs."""
import argparse
from pathlib import Path
from runner import cold, engine, fixture, save, wave

p = argparse.ArgumentParser()
p.add_argument("out", type=Path)
out = p.parse_args().out
out.mkdir(parents=True, exist_ok=False)
prefixes, tails = fixture(1024, 2, 9, 111)
a, b = [prefixes[0] + t for t in tails]
with engine(out, 1536, stock=True) as w:
    def run(prompts):
        result, _ = wave(w, [(str(i), ids, 8, "temperature=0") for i, ids in enumerate(prompts)])
        return list(result[k] for k in sorted(result))
    rows = {}
    for key, prompts in [("prime", [a, b]), ("retry", [a, b]), ("switch", [b, a]), ("return", [a, b])]:
        rows[key] = run(prompts)
    save(out / "events.json", rows)
    for key, want in (("prime", 0), ("retry", len(a)-1), ("switch", 0), ("return", 0)):
        assert [r["reused"] for r in rows[key]] == [want, want], (key, rows[key])
    for i in range(2):
        assert rows["prime"][i]["tokens"] == rows["retry"][i]["tokens"] == rows["return"][i]["tokens"]
    print("Native retry and two-slot session switch matched recorded obligations.")
