"""Time the same four reference-client tasks against two pinned gateways on one Mac."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

import psutil
from native import read_peak

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fork_demo


@contextmanager
def gateway(command, state_dir, port, env=None):
    base = f"http://127.0.0.1:{port}/v1"
    with (state_dir / "server.log").open("w") as log:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, cwd=state_dir,
                                env={**os.environ, **(env or {}), "STRATA_DATA_DIR": str(state_dir),
                                     "PYTHONDONTWRITEBYTECODE": "1", "NO_PROXY": "127.0.0.1,localhost"},
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for _ in range(300):
                if proc.poll() is not None:
                    raise RuntimeError((state_dir/"server.log").read_text()[-1200:])
                try:
                    if fork_demo.call(base, "/models")["data"]:
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                raise TimeoutError("gateway startup")
            yield base, proc
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGINT)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith('{"turbine":')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("stock_server", "stock_binary", "package", "model", "tokenizer", "out"):
        parser.add_argument(arg, type=lambda s: Path(s).resolve())
    a = parser.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for pair in range(3):
        for native in ((False, True) if pair % 2 == 0 else (True, False)):
            destination = a.out / f"agent-{pair}-{'fork' if native else 'stock'}.json"
            if destination.is_file():
                continue
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                port = free_port()
                if native:
                    command = [a.package/"atomic-turbine", "serve-inkling", "--model", a.model, "--tokenizer", a.tokenizer,
                               "--snapshot-mib", "1536", "--port", str(port)]
                else:
                    cfg = dict(exe=str(a.stock_binary), arch="inkling2_loop", tokenizer=str(a.tokenizer), model_name="inkling",
                               args=["--serve", "--native", str(a.model), "--draft", "off", "--kv", "fp16", "--parallel", "2",
                                     "--max-context", "24576", "--chunk", "128"])
                    (d/"config.json").write_text(json.dumps(cfg))
                    command = [sys.executable, a.stock_server, "--engine", "strata", "--config", d/"config.json",
                               "--host", "127.0.0.1", "--port", str(port), "--parallel", "2", "--offline", "--no-api-key"]
                with gateway(command, d, port) as (base, proc):
                    engines = [p for p in psutil.Process(proc.pid).children(recursive=True) if p.name() == "strata-inkling"]
                    if len(engines) != 1:
                        raise RuntimeError("expected one Inkling engine")
                    result = fork_demo.run(base, "inkling", ordinary=not native)
                    result["peak_bytes"] = read_peak(engines[0].pid)
                result["events"] = read_events(d/"server.log")
                result["pair"] = pair
                if native:
                    expected = {row["request"].removeprefix("chatcmpl-") for row in result["results"]}
                    for name in ("checkpoint_restored", "fork_admitted"):
                        actual = [e["request_id"] for e in result["events"] if e["turbine"] == name]
                        if len(actual) != 4 or set(actual) != expected:
                            raise RuntimeError(f"{name} did not match the four completion IDs")
                destination.write_text(json.dumps(result, indent=2)+"\n")
                print(destination.name, round(result["elapsed_s"], 3), flush=True)


if __name__ == "__main__":
    main()
