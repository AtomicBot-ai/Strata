"""Local stdin protocol used for both paths; weights live outside this project."""

import contextlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT.parent / "atomic-turbine/.work"
MODEL = WORK / "models/Inkling-2-Mini-SQ-10.strata"
TOKENIZER = WORK / "inkling-strata/tokenizer.json"
BIN = ROOT / ".work/strata-build/strata-inkling"


class Session:
    def __init__(self, proc):
        self.proc = proc

    def send(self, msg):
        self.proc.stdin.write(msg + "\n")
        self.proc.stdin.flush()

    def line(self):
        value = self.proc.stdout.readline().strip()
        if not value or value.startswith("ERR"):
            raise RuntimeError(value or "unexpected EOF from Strata")
        return value

    def control(self, cmd, expected):
        self.send(cmd)
        reply = self.line().split()
        if reply[0] != expected:
            raise RuntimeError(reply)
        return reply[1:]

    def gen(self, ids, n, seed=42, temp=0):
        start = time.monotonic()
        self.send(f"GEN {n} temperature={temp} top_k=32 top_p=0.95 seed={seed} " + ",".join(map(str, ids)))
        tokens = []
        reused = 0
        while True:
            parts = self.line().split()
            if parts[0] == "RESUME":
                reused = int(parts[1])
            elif parts[0] == "T":
                tokens.append(int(parts[1]))
            elif parts[0] == "DONE":
                if (
                    int(parts[1]) != len(tokens)
                    or int(parts[2]) != len(ids)
                    or parts[-1] not in ("stop", "length")
                ):
                    raise RuntimeError(parts)
                # Final sampled token has not been fed into the model.
                return dict(
                    tokens=tokens,
                    processed=len(ids) - reused + max(0, len(tokens) - 1),
                    reused=reused,
                    wall_ms=1000 * (time.monotonic() - start),
                    reason=parts[-1],
                )
            elif parts[0] != "PP":
                raise RuntimeError(parts)


@contextlib.contextmanager
def engine(log, *, slots=1, checkpoints=True, context=4096):
    cmd = [
        str(BIN),
        "--serve",
        "--native",
        str(MODEL),
        "--draft",
        "off",
        "--kv",
        "fp16",
        "--max-context",
        str(context),
        "--chunk",
        "128",
        "--parallel",
        str(slots),
        "--no-anti-loop",
    ]
    if checkpoints:
        cmd.append("--research-checkpoint")
    with log.open("x") as err:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1
        )
        try:
            session = Session(proc)
            info, ready = session.line(), session.line()
            if (
                "backend=metal" not in info
                or "drafter=none" not in info
                or not ready.startswith(f"READY {context} ")
            ):
                raise RuntimeError((info, ready))
            yield session
        finally:
            if proc.poll() is None:
                try:
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                    proc.wait(timeout=5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait()
            proc.stdin.close()
            proc.stdout.close()


def record(stream, **data):
    stream.write(json.dumps(data, ensure_ascii=False) + "\n")
    stream.flush()


def batch(session, jobs, temperature=1):
    """Issue two native GENERATE requests together and demultiplex the responses by ID.

    The caller accounts for any known first-slot RESUME and forwards per-request events.
    """
    messages = []
    tokens = {}
    results = {}
    for i, (ids, n, seed) in enumerate(jobs):
        ident = str(i)
        tokens[ident] = []
        messages.append(
            f"GENERATE {ident} {n} temperature={temperature} top_k=32 top_p=0.95 seed={seed} "
            + ",".join(map(str, ids))
        )
    session.send("\n".join(messages))
    while len(results) < len(jobs):
        parts = session.line().split()
        if parts[0] == "T":
            tokens[parts[1]].append(int(parts[2]))
        elif parts[0] == "DONE":
            ident = parts[1]
            if (
                ident in results
                or int(parts[2]) != len(tokens[ident])
                or parts[-1] not in ("length", "stop")
            ):
                raise ValueError(parts)
            results[ident] = dict(
                tokens=tokens[ident], reason=parts[-1], processed=int(parts[3]) + max(0, int(parts[2]) - 1)
            )
        elif parts[0] != "PP":
            raise ValueError(parts)
    return [results[str(i)] for i in range(len(jobs))]
