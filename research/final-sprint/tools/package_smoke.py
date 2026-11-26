"""Check the local packaged HTTP entry point and one deterministic completion."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib import request

SPRINT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPRINT.parent / "strata-fork-scaling/tools"))
from runner import MODEL
from state_regression import engine, prefill, cold


def check_packaged_tokens(binary, out):
    parent = [178+i for i in range(63)]
    with engine(binary, 32, out / "native.log", False) as wire:
        def generate():
            suffix = ",".join(map(str, parent + [811]))
            wire.send(f"BGEN 1 6 temperature=0 seed=411 {suffix}")
            tokens = []
            while True:
                fields = wire.line().split()
                if fields[0] in ("T","BT"): tokens.append(int(fields[-1]))
                if fields[0]=="ERR": raise ValueError(fields)
                if fields[0]=="BDONE":
                    assert len(tokens)==6
                    return tokens
        prefill(wire, 0, parent)
        handle, _, _ = wire.ctrl("STATE_SAVE 0", "SAVED")
        wire.ctrl(f"STATE_RESTORE 1 {handle}", "RESTORED")
        candidate = generate()
        cold(wire)
        prefill(wire, 1, parent)
        reference = generate()
        assert candidate == reference
        return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--http-only", action="store_true")
    args = parser.parse_args()
    package = args.package.resolve()
    launcher = package / "atomic-turbine"
    out = SPRINT / "runs/engineering/package"
    out.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([launcher, "--version"], text=True).strip()
    assert version == "Atomic Turbine 0.1.0", version
    matched_tokens = None if args.http_only else check_packaged_tokens(package / "bin/strata-inkling", out)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}/v1"
    scratch = SPRINT.parents[1] / ".work/final-sprint"
    env = dict(os.environ, STRATA_DATA_DIR=str(scratch / "package-server-state"), NO_PROXY="127.0.0.1,localhost", PYTHONDONTWRITEBYTECODE="1")
    with (out / "server.log").open("a") as log:
        child = subprocess.Popen([launcher, "serve-inkling", "--model", MODEL, "--tokenizer", scratch / "ink-tokenizer",
                                  "--port", str(port), "--context", "2048"], env=env, cwd=package, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(120):
                if child.poll() is not None:
                    raise RuntimeError(f"packaged API quit with {child.returncode}")
                try:
                    with request.urlopen(url+"/models",timeout=2) as res:
                        models = json.load(res)
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise TimeoutError("packaged API startup")
            model = models["data"][0]["id"]
            body = {"model": model, "messages": [{"role":"user","content":"Reply with the word hello."}],
                    "temperature":0, "max_tokens":256}
            req = request.Request(url+"/chat/completions", json.dumps(body).encode(), {"Content-Type":"application/json"})
            with request.urlopen(req,timeout=60) as response:
                reply=json.load(response)
            choice = reply["choices"][0]
            assert (choice["message"].get("content") or "").strip() and reply["usage"]["completion_tokens"] > 0
            output_name = "http-result.json" if args.http_only else "result.json"
            (out / output_name).write_text(json.dumps(dict(version=version, models=models, matched_native_tokens=matched_tokens, response=reply), indent=2)+"\n")
            print(version, model, reply["usage"])
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL)
                    child.wait()


if __name__ == "__main__":
    main()
