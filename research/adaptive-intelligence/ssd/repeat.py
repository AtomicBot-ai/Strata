"""Counterbalance the initial block, then check ordinary read-ahead and an unrelated pair."""

from measure import OUT, measure

for prefix, modes, prefetch, unrelated in [
    ("r2", ["serial", "joint", "B", "A"], 0, False),
    ("r3", ["B", "serial", "A", "joint"], 0, False),
    ("default", ["B", "joint", "A", "serial"], 6, False),
    ("different", ["A", "joint", "B", "serial"], 0, True),
]:
    for mode in modes:
        tag = f"{prefix}-{mode}"
        if not (OUT / (tag + ".json")).exists():
            measure(tag, mode, 64, prefetch, unrelated)
