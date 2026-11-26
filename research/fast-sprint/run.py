"""Run one bounded native Metal arm from the turbine-intelligence workspace."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".work/fast-sprint"
PACKAGE = WORK / "Atomic-Turbine-0.1.0-61d705eb"
HERE = Path(__file__).resolve().parent
INK = ROOT.parent / "atomic-turbine/.work/models/Inkling-2-Mini-SQ-10.strata"
QWEN = Path.home() / "code/models/qwen38-iq3"
PACK = ROOT / ".work/ssd-qwen-pack"
sys.path.insert(0, str(PACKAGE / "terminal/tools"))
from strata_tokenizer import Tokenizer


def prompts(family, chat=False):
    folder = ROOT / ".work/rc/prepared-tokenizer" if family == "ink" else PACK / "tokenizer"
    vocab = json.loads((folder / "vocab.json").read_text())
    merges = (folder / "merges.txt").read_text().splitlines()
    if merges[0].startswith("#version"):
        merges = merges[1:]
    pre = json.loads((folder / "tokenizer.json").read_text())["pre"]
    types = json.loads((folder / "token_type.json").read_text()) if chat else None
    tok = Tokenizer(sorted(vocab, key=vocab.get), merges, token_types=types, pre=pre)
    count = 90 if family == "ink" else 7
    code = "".join(f'    "item_{i}": {i},\n' for i in range(count))
    prose = " ".join(f"On day {i} the crew checked its water and recorded the weather." for i in range(count))
    texts = {
        "warm": "List five colors of the rainbow in order. The first color is",
        "code": "Continue this Python dictionary through item_999.\nitems = {\n" + code,
        "prose": "Expedition log. " + prose + "\nDescribe in detail what happened when the crew finally reached the island. ",
    }
    if chat:
        from jinja2 import Environment
        template = Environment().from_string((folder / "chat_template.jinja").read_text())
        texts = {k: template.render(messages=[dict(role="user", content=v)], add_generation_prompt=True,
                                    enable_thinking=False) for k, v in texts.items()}
    return {k: tok.encode(v, parse_special=chat) for k, v in texts.items()}


def profile(family, mode, chat):
    if family == "ink":
        binary = (WORK / "build" if mode in {"tree", "narrow", "trace"} else PACKAGE / "bin") / "strata-inkling"
        args = ["--serve", "--native", str(INK), "--draft", "off" if mode in {"off", "state"} else "dspark",
                "--kv", "fp16", "--max-context", "17000" if mode == "state" else "2048",
                "--chunk", "128", "--parallel", "2" if mode == "state" else "1"]
        env = {"TURBINE_SNAPSHOT_MIB": "1536" if mode == "state" else "0"}
        if mode == "narrow":
            env["TURBINE_NARROW_TREE"] = "1"
        if mode == "trace":
            env["TURBINE_TRACE_VERIFY"] = "1"
        if mode == "adapt":
            args.append("--draft-adapt")
    else:
        binary = PACKAGE / "bin/strata"
        args = ["--serve", "--pack", str(PACK), "--native", str(next(QWEN.glob("*-00001-of-00002.gguf"))),
                "--ple-gguf", str(next(QWEN.glob("*-00002-of-00002.gguf"))), "--expert-profile", str(QWEN / "profile.bin"),
                "--max-context", "2048", "--expert-cache", "64", "--batch", "1", "--prefill", "auto",
                "--spec", "2" if mode == "off" else ("3" if mode == "narrow" else "6"),
                "--suffix-draft", "3" if chat and mode != "off" else "0", "--mmap-experts"]
        env = dict(STRATA_METAL_STREAM="1", STRATA_METAL_ARENA_GB="6", STRATA_METAL_STREAM_FAKE="0",
                   STRATA_METAL_PREFETCH="0", STRATA_METAL_PREFETCH2="0", STRATA_DRAFT_LOG="1",
                   TURBINE_QWEN_FORK="0")
        if mode != "off":
            args += ["--draft", "dflash2", "--draft-model", str(WORK / "qwen-dflash2.pack"), "--draft-fallback",
                     "none", "--mtp-draft-vocab", str(QWEN / "draft/vocab.bin"), "--draft-conf", "0.5"]
    return [str(binary), *args], env


def write(row):
    with (HERE / "results.jsonl").open("a") as out:
        print(json.dumps(row), file=out)


def others(own_pid=None):
    procs = subprocess.check_output(["ps", "-Aco", "pid=,comm="], text=True)
    busy = []
    for row in procs.splitlines():
        pid, name = row.strip().split(None, 1)
        if int(pid) != own_pid and re.fullmatch(r"(strata(-inkling)?|clang(\+\+)?|ninja|cmake|llama-(cli|server|bench)|xcodebuild)", Path(name).name):
            busy.append(f"{pid} {name}")
    return busy


def run(family, mode, label, chat=False):
    cmd, env = profile(family, mode, chat)
    jobs = prompts(family, chat)
    path = WORK / f"{family}-{mode}-{label}.log"
    if others():
        raise SystemExit("Machine busy. No engine started.")
    meta = dict(template="pack-chat-thinking-off" if chat else "raw", family=family, mode=mode, label=label, command=cmd, env=env,
                binary_sha256=hashlib.sha256(Path(cmd[0]).read_bytes()).hexdigest(), source="61d705eb",
                log=str(path.relative_to(ROOT)))
    lib = ctypes.CDLL(str(ROOT / ".work/ssd-counters.dylib")) if family == "qwen" else None
    disk = None
    if lib and lib.open_disk(b"disk0"):
        disk = lib.disk_read
        disk.restype = ctypes.c_int64
    with path.open("x", buffering=1) as log, subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=log, text=True, env={**os.environ, **env}) as proc:
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("engine timeout")))
        signal.alarm(240)
        finished = threading.Event()
        conflict = []
        def watch():
            while not finished.wait(1):
                busy = others(proc.pid)
                if busy:
                    conflict.extend(busy)
                    proc.terminate()
                    return
        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        def send(line):
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
        def line():
            s = proc.stdout.readline().strip()
            if conflict:
                raise RuntimeError(f"external workload appeared: {conflict}")
            if not s or s.startswith(("ERR", "FATAL")):
                raise RuntimeError(s or f"engine exited, see {path}")
            return s.split()
        try:
            headers = []
            while not headers or headers[-1][0] != "READY":
                headers.append(line())
            if mode == "state":
                ids = (jobs["code"] * 32)[:16384]
                send("BGEN 0 0 " + ",".join(map(str, ids)))
                while line()[0] != "BADM":
                    pass
                start = time.monotonic()
                send("STATE_SAVE 0")
                saved = line()
                assert saved[0] == "SAVED" and int(saved[2]) == len(ids), saved
                capture = (time.monotonic() - start) * 1000
                restores, outputs = [], []
                for _ in range(2):
                    t = time.monotonic()
                    send(f"STATE_RESTORE 1 {saved[1]}")
                    assert line() == ["RESTORED", str(len(ids))]
                    restores.append((time.monotonic() - t) * 1000)
                    send("BGEN 1 4 temperature=0 " + ",".join(map(str, ids + [1000])))
                    output = []
                    while True:
                        f = line()
                        if f[0] in {"T", "BT"}:
                            output.append(int(f[1] if f[0] == "T" else f[2]))
                        if f[0] == "BDONE" or f[:3] == ["BADM","1","0"]:
                            break
                    outputs.append(output)
                send("STATE_DROP " + saved[1])
                assert line()[0] == "DROPPED"
                write(dict(meta, parent_tokens=len(ids), payload_bytes=int(saved[3]), capture_ms=capture,
                           restore_ms=restores, outputs=outputs, parity=bool(outputs[0]) and outputs[0]==outputs[1]))
            else:
                for key, ids in jobs.items():
                    limit = 8 if key == "warm" else (128 if family == "ink" else 64)
                    idle_start = disk() if disk else None
                    if disk:
                        time.sleep(0.25)
                    disk0 = disk() if disk else None
                    disk_first = None
                    log_start = os.stat(path).st_size
                    t = time.monotonic()
                    send(f"GEN {limit} temperature=0 seed=83101 " + ",".join(map(str, ids)))
                    output, first = [], None
                    while True:
                        f = line()
                        if f[0] == "T":
                            if first is None:
                                first = time.monotonic()
                                disk_first = disk() if disk else None
                            output.append(int(f[1]))
                        if f[0] == "DONE":
                            break
                    end = time.monotonic()
                    disk_end = disk() if disk else None
                    valid_disk = disk and 0 <= idle_start <= disk0 <= disk_first <= disk_end
                    read_bytes = disk_end - disk0 if valid_disk else None
                    with path.open("rb") as trace:
                        trace.seek(log_start)
                        trace_lines = trace.read().decode(errors="replace").splitlines()
                    rounds = [int(x.group(1)) for s in trace_lines if (x := re.search(r"strata draft:.* rounds=(\d+)", s))]
                    usage = (ctypes.c_uint64 * 64)()
                    ret = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pid_rusage(proc.pid, 4, ctypes.byref(usage))
                    if first is None or not output:
                        raise RuntimeError(f"no emitted tokens {f}")
                    row = dict(meta, fixture=key, input_ids=ids, output_ids=output, max_output=limit,
                               header=headers, done=f, ttft_s=first-t, wall_s=end-t, decode_s=end-first,
                               tps=(len(output)-1)/(end-first), peak_footprint_bytes=None if ret else usage[30],
                               disk0_request_bytes=read_bytes, disk0_idle_bytes_250ms=disk0-idle_start if valid_disk else None,
                               disk0_decode_bytes=disk_end-disk_first if valid_disk else None,
                               draft_rounds=rounds[-1] if rounds else None,
                               phase_trace=[s for s in trace_lines if s.startswith("verify_trace")],
                               accepted=int(f[6]), offered=int(f[7]))
                    write(row)
                    print(family, mode, key, len(output), round(row["tps"], 2), f[6:9], flush=True)
            send("QUIT")
            proc.wait(timeout=15)
        except BaseException as exc:
            write(dict(meta, error=str(exc)))
            raise
        finally:
            finished.set()
            monitor.join()
            signal.alarm(0)
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("family", choices=["ink","qwen"])
    p.add_argument("mode", choices=["off","stock","tree","trace","adapt","narrow","state"])
    p.add_argument("label")
    p.add_argument("--chat", action="store_true", help="Qwen pack template and native prompt lookup in speculative modes")
    a = p.parse_args()
    if a.chat and a.family != "qwen":
        p.error("--chat is a Qwen fixture")
    run(a.family, a.mode, a.label, a.chat)
