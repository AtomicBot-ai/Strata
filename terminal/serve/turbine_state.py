"""One process-local native parent. All wire exchanges use StrataEngine's admission lock."""
import json
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field


class CheckpointError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def event(name, **values):
    print(json.dumps({"turbine": name, **values}, separators=(",", ":")), flush=True)


@dataclass
class Parent:
    ids: tuple
    owner: object
    identity: tuple
    born: int
    id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    handle: int = 0
    leases: int = 0
    closed: bool = False
    timer: object = None


class Checkpoints:
    ttl = 300

    def __init__(self, engine, family):
        self.engine = engine
        self.family = family
        self.born = engine.gen
        self.lock = threading.RLock()
        self.parent = None

    def alive(self):
        return self.engine.gen == self.born and self.engine.alive()

    def exchange(self, command, reply, progress=()):
        engine = self.engine
        lines = engine.lines
        if not self.alive():
            raise CheckpointError(404, "checkpoint engine ended")
        engine._send_for(self.born, command)
        while True:
            try:
                line = lines.get(timeout=120)
            except queue.Empty:
                engine._end_out_of_step(self.born, "native checkpoint command timed out")
                raise CheckpointError(503, "checkpoint command timed out") from None
            if line is None:
                raise CheckpointError(503, "checkpoint engine ended")
            fields = line.split()
            if fields and fields[0] == reply:
                return fields[1:]
            if fields and fields[0] == "ERR":
                raise CheckpointError(409, " ".join(fields[1:]))
            if not fields or fields[0] not in progress:
                engine._end_out_of_step(self.born, "unexpected checkpoint reply")
                raise CheckpointError(503, f"unexpected checkpoint frame {fields[0][:24] if fields else 'empty'}")

    def create(self, ids, owner, identity):
        e = self.engine
        with self.lock:
            if self.parent:
                raise CheckpointError(409, "a checkpoint is already active")
            p = Parent(tuple(ids), owner, identity, self.born)
            self.parent = p
        try:
            with e._exclusive_control():
                tokens = ",".join(map(str, ids))
                if self.family == "inkling":
                    with e.slot_cv:
                        slot = e.pick_slot(ids)
                        if slot is None:
                            raise CheckpointError(409, "no free slot to prepare the parent")
                        e.slot_busy[slot] = True
                        e.slot_claims.add(slot)
                        busy, claims = e.slot_busy, e.slot_claims
                    try:
                        e.slot_held[slot] = []
                        e.slot_prompt[slot] = []
                        result = self.exchange(f"BGEN {slot} 0 ckpt=0 {tokens}", "BADM", ("PP", "DONE", "RESUME", "REUSED"))
                        if result != [str(slot), "0"]:
                            e._end_out_of_step(self.born, "unexpected parent admission")
                            raise CheckpointError(503, "invalid parent admission")
                        saved = self.exchange(f"STATE_SAVE {slot}", "SAVED")
                    finally:
                        with e.slot_cv:
                            claims.discard(slot)
                            busy[slot] = False
                            e.slot_cv.notify_all()
                else:
                    self.exchange(f"GEN 1 temperature=0 {tokens}", "DONE", ("PP", "T", "RESUME", "REUSED"))
                    saved = self.exchange("STATE_SAVE MAIN", "SAVED")
                p.handle, count = map(int, saved[:2])
                if count != len(ids):
                    self.exchange(f"STATE_DROP {p.handle}", "DROPPED")
                    raise CheckpointError(409, "engine saved a different prefix length")
            with self.lock:
                p.timer = threading.Timer(self.ttl, self.expire, args=(p,))
                p.timer.daemon = True
                p.timer.start()
            event("checkpoint_created", tokens=count, snapshot_bytes=int(saved[2]) if len(saved) > 2 else None)
            return {"id": p.id, "tokens": count, "ttl_seconds": self.ttl}
        except BaseException:
            with self.lock:
                self.parent = None
            raise

    def lookup(self, ident, owner):
        p = self.parent
        if not self.alive() or not p or p.id != ident or p.owner != owner or p.closed:
            raise CheckpointError(404, "unknown checkpoint")
        return p

    def acquire(self, ident, owner, identity, ids):
        with self.lock:
            p = self.lookup(ident, owner)
            if identity != p.identity or tuple(ids[:len(p.ids)]) != p.ids:
                raise CheckpointError(409, "checkpoint prefix or model configuration differs")
            p.leases += 1
            return p

    def restore(self, p, slot, prompt):
        if tuple(prompt[:len(p.ids)]) != p.ids:
            raise CheckpointError(409, "generation changed the checkpoint prefix")
        location = slot if self.family == "inkling" else "MAIN"
        result = self.exchange(f"STATE_RESTORE {location} {p.handle}", "RESTORED")
        if result != [str(len(p.ids))]:
            raise CheckpointError(503, "restore length differs from saved prefix")

    def finish(self, p, assignment):
        # A disconnected stream can hand its slot to the background BSTOP/BDONE drain.
        e = self.engine
        if assignment and self.alive():
            born, slot = assignment
            def wait():
                with e.slot_cv:
                    while self.alive() and e.gen == born and e.slot_busy[slot]:
                        e.slot_cv.wait(timeout=1)
                self.release(p)
            with e.slot_cv:
                if e.gen == born and e.slot_busy[slot]:
                    threading.Thread(target=wait, daemon=True).start()
                    return
        self.release(p)

    def release(self, p):
        with self.lock:
            p.leases -= 1
            if p.closed and not p.leases:
                self.drop(p)

    def drop(self, p):
        if self.alive():
            with self.engine._exclusive_control():
                self.exchange(f"STATE_DROP {p.handle}", "DROPPED")
        self.parent = None
        event("checkpoint_dropped")

    def expire(self, p):
        with self.lock:
            if self.parent is p:
                p.closed = True
                if not p.leases:
                    self.drop(p)

    def delete(self, ident, owner):
        with self.lock:
            p = self.lookup(ident, owner)
            p.timer.cancel()
            self.expire(p)
            return 202 if p.leases else 204
