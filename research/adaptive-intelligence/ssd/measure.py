"""Measure 64 decode steps in the packaged Qwen Metal engine. Run from the workspace root."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path.cwd()
BUNDLE = Path(
    "/Applications/Strata.app/Contents/Resources/engine-bundle/0.1.65-macos-arm64-metal"
)
MODEL = Path.home() / "code/models/qwen38-iq3"
PACK = ROOT / ".work/ssd-qwen-pack"
OUT = ROOT / "research/adaptive-intelligence/runs/ssd-branch-01"


def prompts(unrelated=False):
    from tokenizers import Tokenizer
    from tokenizers.models import BPE
    from tokenizers.pre_tokenizers import ByteLevel

    tok = Tokenizer(
        BPE.from_file(
            str(PACK / "tokenizer/vocab.json"), str(PACK / "tokenizer/merges.txt")
        )
    )
    tok.pre_tokenizer = ByteLevel(add_prefix_space=False)
    # A plain-text continuation with one different final token; no chat template or special IDs.
    stem = "Write a long numbered guide to sorting a list. Include at least 100 detailed entries.\n1. Start by"
    ids = [tok.encode(stem + tip).ids for tip in (" selecting", " comparing")]
    if unrelated:
        other = "Explain the anatomy and history of the pipe organ, describing every component in detail and including many musical examples. Begin with the wind supply and the bellows."
        ids[1] = tok.encode(other).ids[: len(ids[0])]
        assert len(ids[1]) == len(ids[0])
    return ids


def measure(tag, mode, count, ahead, unrelated=False, trace_engine=None):
    path = OUT / (tag + ".json")
    if path.exists():
        raise FileExistsError(path)
    exe = Path(trace_engine).resolve() if trace_engine else BUNDLE / "strata"
    args = [
        str(exe),
        "--serve",
        "--pack",
        str(PACK),
        "--native",
        str(next(MODEL.glob("*-00001-of-00002.gguf"))),
        "--ple-gguf",
        str(next(MODEL.glob("*-00002-of-00002.gguf"))),
        "--expert-profile",
        str(MODEL / "profile.bin"),
        "--max-context",
        "512",
        "--expert-cache",
        "64",
        "--batch",
        "2",
        "--prefill",
        "auto",
        "--spec",
        "2",
        "--suffix-draft",
        "0",
        "--mmap-experts",
    ]
    env = dict(
        os.environ,
        STRATA_METAL_STREAM="1",
        STRATA_METAL_ARENA_GB="6",
        STRATA_METAL_STREAM_FAKE="0",
        STRATA_METAL_BATCH_ROWS="0" if mode == "serial" else "1",
        STRATA_METAL_PREFETCH=str(ahead),
        STRATA_METAL_PREFETCH2="0",
    )
    if trace_engine:
        env.update(
            STRATA_SSD_TRACE_ROWS="1",
            STRATA_METAL_KERNELS=str(BUNDLE / "metal/kernels"),
            STRATA_METAL_ENGINE_KERNELS=str(BUNDLE / "metal/engine-msl"),
            STRATA_METAL_DATA=str(BUNDLE / "metal/data"),
        )
    counter = ctypes.CDLL(str(ROOT / ".work/ssd-counters.dylib"))
    counter.disk_read.restype = counter.process_read.restype = ctypes.c_int64
    if not counter.open_disk(b"disk0"):
        raise RuntimeError("disk0 storage driver unavailable")
    ids = prompts(unrelated)

    def read(pid):
        d, p = counter.disk_read(), counter.process_read(pid)
        if min(p, d) < 0:
            raise RuntimeError("read counter unavailable")
        return (time.monotonic_ns(), d, p)

    with (OUT / (tag + ".log")).open("w") as log:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            env=env,
            bufsize=1,
        )
        try:
            for line in proc.stdout:
                if line.startswith("READY"):
                    break
            else:
                raise RuntimeError("no READY: " + str(log.name))
            idle0 = read(proc.pid)
            time.sleep(1)
            idle1 = read(proc.pid)
            cut = 6
            # Each arm admits both prefixes in the same order. Inactive slots stop at the admission token.
            active = [0] if mode == "A" else [1] if mode == "B" else [0, 1]
            cap = count + cut + 2
            proc.stdin.write(
                "".join(
                    "BGEN %d %d temperature=0 %s\n"
                    % (i, cap if i in active else 1, ",".join(map(str, row)))
                    for i, row in enumerate(ids)
                )
            )
            proc.stdin.flush()
            events = []
            admitted = set()
            done = set()
            tokens = [[], []]
            first = {}
            last = {}
            for line in proc.stdout:
                fields = line.split()
                if not fields:
                    continue
                kind = fields[0]
                now = read(proc.pid)
                events.append([line.strip(), *now])
                if kind == "ERR":
                    raise RuntimeError(line)
                if kind == "BADM":
                    slot = int(fields[1])
                    admitted.add(slot)
                    if int(fields[2]) == 0:
                        done.add(slot)
                if kind == "BT":
                    slot = int(fields[1])
                    tokens[slot].append(int(fields[2]))
                    n = len(tokens[slot])
                    if n == cut:
                        first[slot] = now
                    if n == cut + count:
                        last[slot] = now
                if kind == "BDONE":
                    done.add(int(fields[1]))
                if len(admitted) == 2 and len(done) == 2:
                    break
            proc.stdin.write("QUIT\n")
            proc.stdin.flush()
            if proc.wait(timeout=45):
                raise RuntimeError("engine failed: " + str(log.name))
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=30)
    result = dict(
        mode=mode,
        tag=tag,
        count=count,
        prefetch=ahead,
        unrelated=unrelated,
        input_ids=ids,
        tokens=tokens,
        events=events,
        idle=[idle0, idle1],
        binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
    )
    if all(s in first and s in last for s in active):
        start = max(first.values())
        end = max(last.values())
        result["window"] = dict(
            ms=(end[0] - start[0]) / 1e6,
            disk=end[1] - start[1],
            process=end[2] - start[2],
        )
    path.write_text(json.dumps(result, indent=1))
    print(tag, result.get("window"), "BT lengths", list(map(len, tokens)), flush=True)
    return result


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("tag")
    a.add_argument("mode", choices=["A", "B", "joint", "serial"])
    a.add_argument("--steps", type=int, default=64)
    a.add_argument("--prefetch", type=int, default=0)
    a.add_argument("--unrelated", action="store_true")
    a.add_argument("--trace-engine", type=Path)
    opts = a.parse_args()
    measure(
        opts.tag,
        opts.mode,
        opts.steps,
        opts.prefetch,
        opts.unrelated,
        opts.trace_engine,
    )
