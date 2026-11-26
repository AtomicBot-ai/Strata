"""Two bounded native Strata requests. Run on an Apple Silicon Mac with Metal."""
import argparse
import ctypes
import hashlib
import json
import signal
import subprocess
import time
from pathlib import Path

from tokenizers import Tokenizer, __version__ as tokenizer_version

HERE = Path(__file__).resolve().parent
CACHE = HERE.parents[2] / "atomic-turbine/.work"
PROMPT = "The first ten positive integers are 1, 2,"
COMMIT = "26350e4387b8019b0f6825ba78b87eb6360159e7"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(8 << 20), b""):
            result.update(data)
    return result.hexdigest()


def memory(pid):
    # Darwin sys/resource.h, rusage_info_v4, including its 16-byte UUID.
    values = (ctypes.c_uint64 * 64)()
    if ctypes.CDLL("/usr/lib/libproc.dylib").proc_pid_rusage(pid, 4, ctypes.byref(values)):
        return None
    return dict(process_disk_read_bytes=values[18], peak_footprint_bytes=values[30])


def timeout(*_):
    raise TimeoutError("Strata exceeded its 90 second launch/request deadline")


def measure(command, ids, stem):
    start = time.perf_counter()
    with stem.with_suffix(".stderr").open("x") as err, stem.with_suffix(".protocol").open("x") as log:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                text=True, bufsize=1)
        def receive():
            line = proc.stdout.readline()
            if not line or line.startswith("ERR"):
                raise RuntimeError(f"Strata protocol error: {line.strip()!r}. See {err.name}")
            log.write(line)
            log.flush()
            return line.strip()
        def send(line):
            log.write("> " + line + "\n")
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
        try:
            signal.alarm(90)
            info = receive()
            if not all(tag in info.split() for tag in ("backend=metal", "drafter=none", "batch_slots=1", "kv_dtype=fp16")):
                raise ValueError(info)
            ready = receive()
            if ready.split()[:2] != ["READY", "512"]:
                raise ValueError(ready)
            startup_ms = 1000 * (time.perf_counter() - start)
            send("STATS")
            stats = receive()
            if not stats.startswith("STATS "):
                raise ValueError(stats)
            before = memory(proc.pid)
            start = time.perf_counter()
            send("GEN 16 temperature=0 seed=42 " + ",".join(map(str, ids)))
            tokens = []
            first = None
            while True:
                event = receive().split()
                if event[0] == "T":
                    if first is None:
                        first = time.perf_counter()
                    tokens.append(int(event[1]))
                elif event[0] == "DONE":
                    break
            end = time.perf_counter()
            if (first is None or not 0 < len(tokens) <= 16 or len(tokens) != int(event[1])
                    or len(ids) != int(event[2]) or event[5] not in ("stop", "length")
                    or (event[5] == "length" and len(tokens) != 16)):
                raise ValueError(f"Invalid completion: {event}")
            after = memory(proc.pid)
            return dict(engine_info=info, expert_stats=stats, startup_ms=startup_ms,
                        wall_ms=1000 * (end-start), ttft_ms=1000 * (first-start), prefill_ms=float(event[3]),
                        decode_ms=float(event[4]), tokens=tokens, stop_reason=event[5],
                        memory_ready=before, memory_done=after,
                        process_disk_read_bytes=after["process_disk_read_bytes"]-before["process_disk_read_bytes"]
                        if before and after else None, ssd_physical_bytes=None, expert_misses=None,
                        ssd_logical_bytes=None, energy_j=None, correct=None)
        finally:
            signal.alarm(0)
            if proc.poll() is None:
                try:
                    send("QUIT")
                    proc.wait(timeout=5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    proc.kill()
                    proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="new directory for raw traces and JSONL")
    parser.add_argument("--component", type=Path, default=CACHE / "inkling-strata/engine")
    parser.add_argument("--model", type=Path, default=CACHE / "models/Inkling-2-Mini-SQ-10.strata")
    parser.add_argument("--tokenizer", type=Path, default=CACHE / "inkling-strata/tokenizer.json")
    args = parser.parse_args()
    binary = args.component / "strata-inkling"
    build = json.loads((args.component / "BUILD.json").read_text())
    binary_hash = digest(binary)
    model_hash = digest(args.model)
    if (binary_hash != "9bd678185e41526eb3796220c3dc7723bb2d13b60e585241ee4f05e7c492f27b"
            or build["commit"] != COMMIT or model_hash != "ac4d452ad03e4930abd9d46f9c5eec22b2f75a1da45a1e49bd24ccd58b065934"):
        raise ValueError("Engine build or model differs from the E00 baseline")
    tokenizer = Tokenizer.from_file(str(args.tokenizer))
    ids = tokenizer.encode(PROMPT, add_special_tokens=False).ids
    command = list(map(str, [binary, "--serve", "--native", args.model, "--max-context", 512, "--parallel", 1,
                             "--draft", "off", "--kv", "fp16", "--chunk", 128, "--no-anti-loop"]))
    meta = dict(command=command, build=build, model_sha256=model_hash, binary_sha256=binary_hash,
                tokenizer_sha256=digest(args.tokenizer), tokenizer_version=tokenizer_version, prompt=PROMPT, input_ids=ids)
    args.out.mkdir(parents=True, exist_ok=False)
    signal.signal(signal.SIGALRM, timeout)
    reference = None
    with (args.out / "baseline.jsonl").open("x") as output:
        for number in (1, 2):
            row = dict(**meta, run_id=f"strata-{number}")
            try:
                row.update(measure(command, ids, args.out / row["run_id"]))
                row["text"] = tokenizer.decode(row["tokens"], skip_special_tokens=False)
                result = (row["tokens"], row["stop_reason"])
                if reference is not None and result != reference:
                    raise ValueError("Independent greedy replay differs")
                reference = result
                row["status"] = "ok"
            except Exception as error:
                row.update(status="failed", error=str(error))
                raise
            finally:
                output.write(json.dumps(row) + "\n")
                output.flush()


if __name__ == "__main__":
    main()
