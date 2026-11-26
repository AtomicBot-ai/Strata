"""Synchronous protocol for explicit GPU ticks; the caller owns the deadline."""

from dataclasses import dataclass, field


class LiveSlots:
    def __init__(self, session):
        self.s = session
        self.s.control("MANUAL", "MANUALOK")
        self.allocated = int(self.s.control("ALLOC", "ALLOC")[0])

    def fresh(self, rid, ids, seed, limit, temperature=1, *, reuse=False, free_slot=0):
        if not reuse:
            self.s.control(f"BCO {free_slot} 1", "BCOK")
        tokens = ",".join(map(str, ids))
        self.s.send(
            f"GENERATE {rid} {limit} temperature={temperature} top_k=32 top_p=0.95 seed={seed} {tokens}"
        )
        _, admitted, slot = self.s.line().split()
        if admitted != rid or int(slot) != free_slot:
            raise RuntimeError("request admitted in unexpected slot")
        # RESUME, if present, is consumed with the next tick.

    def tick(self):
        self.s.send("TICK")
        events = []
        while True:
            line = self.s.line()
            if line == "TICKED":
                return events
            events.append(line.split())

    def drop(self, key):
        self.s.control("LIVEDROP " + key, "DROPPED")

    def snapshot(self, rid):
        return tuple(map(int, self.s.control("LIVESAVE " + rid, "SAVED")))

    def fork(self, parent, rid, slot, seed):
        self.s.control(f"LIVEFORK {parent} {slot} {rid} {seed}", "FORKED")
        tag, name, token = self.s.line().split()
        if (tag, name) != ("T", rid):
            raise RuntimeError("missing first fork token")
        return int(token)

    def cancel(self, rid):
        # Engine processes cancellations before the next step.
        self.s.send("CANCEL " + rid)
        fields = self.s.line().split()
        if fields[:2] != ["DONE", rid] or fields[-1] != "cancel":
            raise RuntimeError(f"unexpected cancellation: {fields}")
        return fields


@dataclass
class Branch:
    name: str
    slot: int
    seed: int
    parent: str | None
    ready: float
    started: float
    tokens: list = field(default_factory=list)
    suffix_start: int = 0
    prompt_tokens: int = 0
    prefill_ms: float = 0
    decode_ms: float = 0
    stopped: float | None = None
    reason: str = ""
    point: int | None = None
    marker: str = ""
    confirmed: bool = False
    payload: int = 0
    code: str | None = None
