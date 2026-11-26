"""Matched Metal runs. Each arm starts a fresh process. Both engines keep native batching and prefix caches."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time


def read_peak(pid):
    usage = (ctypes.c_uint64 * 64)()
    if ctypes.CDLL("/usr/lib/libproc.dylib").proc_pid_rusage(pid, 4, ctypes.byref(usage)):
        raise OSError("proc_pid_rusage")
    return usage[30]


def measure(binary, config, family, prefix, children, limit, fork, folder):
    binary = binary.resolve()
    argv = [os.path.expandvars(value) for value in config["args"]]
    if any(value.startswith("$") for value in argv):
        raise ValueError("set the model and pack environment variables named in the profile")
    argv[argv.index("--max-context")+1] = str(len(prefix) + limit + 128 if family == "inkling" else 512)
    env = {**os.environ, **config.get("env", {})}
    if family == "qwen":
        argv[argv.index("--batch")+1] = "3" if fork else "2"
        env["TURBINE_QWEN_FORK"] = "1" if fork else "0"
    else:
        env["TURBINE_SNAPSHOT_MIB"] = "4096" if fork else "0"
    folder.mkdir(parents=True)
    with (folder/"engine.log").open("w") as log, subprocess.Popen([binary, *argv], env=env, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log) as proc:
        def send(command):
            proc.stdin.write(command + "\n")
            proc.stdin.flush()

        def frame():
            line = proc.stdout.readline()
            if not line or line.startswith(("ERR", "FATAL")):
                raise RuntimeError(f"{binary.name} {line.strip() or 'exited'}")
            return line.split()

        def until(kind):
            while True:
                fields = frame()
                if fields and fields[0] == kind:
                    return fields[1:]

        parent = ",".join(map(str, prefix))
        ids = [f"{parent}," + ",".join(map(str, suffix)) for suffix in children]
        try:
            info = []
            while True:
                header = frame()
                if header[0] == "INFO":
                    info.extend(header[1:])
                if header[0] == "READY":
                    break
            if "batch_slots=2" not in info or (fork and not
                    ({"native_fork=1", "native_parent_fork=1"} & set(info))):
                raise RuntimeError(f"wrong configuration: {info}")
            started = time.monotonic()
            if family == "inkling":
                send(f"BGEN 0 0 {parent}")
                if until("BADM") != ["0", "0"]:
                    raise RuntimeError("parent prefill failed")
            elif fork:
                send(f"GEN 1 temperature=0 {parent}")
                until("DONE")
            prepared = time.monotonic()
            save_location = "0" if family == "inkling" else "MAIN"
            handle = None
            if fork:
                send(f"STATE_SAVE {save_location}")
                handle, tokens, *_ = until("SAVED")
                if int(tokens) != len(prefix):
                    raise RuntimeError("saved prefix length mismatch")
            output = [[] for _ in ids]
            restores = 0
            # Two admissions per wave. Never consume another slot's tokens while waiting for BADM/RESTORED.
            for first in range(0, len(ids), 2):
                done = set()
                def receive(expected, admitting):
                    while True:
                        f = frame()
                        if f[0] == expected:
                            return f[1:]
                        if f[0] == "T":
                            output[first+admitting].append(int(f[1]))
                        elif f[0] == "BT":
                            output[first+int(f[1])].append(int(f[2]))
                        elif f[0] == "BDONE":
                            done.add(int(f[1]))
                            if expected == "end" and len(done) == 2:
                                return
                for slot in (0, 1):
                    if fork:
                        location = slot if family == "inkling" else "MAIN"
                        send(f"STATE_RESTORE {location} {handle}")
                        if receive("RESTORED", slot) != [str(len(prefix))]:
                            raise RuntimeError("restore length mismatch")
                        restores += 1
                    send(f"BGEN {slot} {limit} temperature=0 {ids[first+slot]}")
                    admission = receive("BADM", slot)
                    if admission[0] != str(slot):
                        raise RuntimeError("unexpected slot")
                    if admission[1] == "0":
                        done.add(slot)
                if len(done) < 2:
                    receive("end", 0)
            if fork:
                send(f"STATE_DROP {handle}")
                until("DROPPED")
            end = time.monotonic()
            result = dict(binary=binary.name, fork=fork, prefix_tokens=len(prefix), branches=len(children),
                          max_tokens=limit, outputs=output, native_restores=restores,
                          elapsed_s=end-(prepared if family == "inkling" else started),
                          parent_prefill_s=prepared-started, total_s=end-started, peak_bytes=read_peak(proc.pid))
            result["useful_tokens_s"] = sum(map(len, output))/result["elapsed_s"]
            send("QUIT")
            proc.wait(timeout=30)
            return result
        finally:
            if proc.poll() is None:
                proc.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=["inkling", "qwen"])
    parser.add_argument("config", type=Path, help="launcher JSON with args and optional env")
    parser.add_argument("stock", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--jobs", type=Path, default=Path(__file__).with_name("qwen-prompts.json"),
                        help="Qwen input JSON, four tokenized prompts")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    cfg = cfg.get(args.family, cfg)
    is_ink = args.family == "inkling"
    qwen = None if is_ink else json.loads(args.jobs.read_text())
    profiles = [(16384, 4), (32768, 8)] if is_ink else [(22, 4), (len(qwen["long"]["prefix"]), 4)]
    for count, branches in profiles:
        for pair in range(3):
            rng = random.Random(83101 + pair)
            if is_ink:
                prefix = [rng.randrange(1000, 50000) for _ in range(count)]
                suffixes = [[60000+i] for i in range(branches)]
            elif count == 22:
                jobs = qwen["jobs"]
                prefix = jobs["0"]["ids"][:22]
                suffixes = [jobs[str(i)]["ids"][22:] for i in range(branches)]
            else:
                prefix = qwen["long"]["prefix"]
                suffixes = qwen["long"]["suffixes"]
            runs = []
            for fork in ((False, True) if pair % 2 == 0 else (True, False)):
                binary = args.candidate if fork else args.stock
                folder = args.out / f"{args.family}-{count}-{pair}" / ("fork" if fork else "stock")
                path = folder / "result.json"
                row = measure(binary, cfg, args.family, prefix, suffixes, 128 if is_ink else 16, fork, folder)
                row["sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
                row["seed"] = 83101 + pair
                path.write_text(json.dumps(row, indent=2)+"\n")
                runs.append(row)
                print(folder, round(row["elapsed_s"], 3), flush=True)
            if runs[0]["outputs"] != runs[1]["outputs"]:
                print("Different generated tokens; record this pair separately.", flush=True)


if __name__ == "__main__":
    main()
