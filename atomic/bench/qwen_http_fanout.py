"""Compare two Flash-Next gateway profiles using four ordinary HTTP requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

from http_runs import free_port, gateway

SERVER = Path(__file__).resolve().parents[2] / "terminal/serve/server.py"
HISTORY = [
    {"role": "system", "content": "Read the supplied release record and answer the final question with only the requested value."},
    {"role": "user", "content": """Release record for the fictional Harbor service
The release owner is Atlas. The service listens on TCP port 8080. The deployment region is Dublin.
The retry limit is 3. The deployment team first checks that the package matches the expected checksum.
After the package has been staged, the team reviews the health check and forwards the record to the release owner.
The recovery procedure reads the last successful deployment record and keeps a copy for the next on-call shift.
The team repeats the health check after deployment. Answer future questions using the values in this record."""},
    {"role": "assistant", "content": "Ready."},
]
QUESTIONS = [
    ("Who is the release owner?", "Atlas"),
    ("Which TCP port does the service listen on?", "8080"),
    ("Which region is the deployment in?", "Dublin"),
    ("What is the retry limit?", "3"),
]


def completion(base, model, messages):
    body = {"model": model, "messages": messages, "temperature": 0, "reasoning_effort": "none", "max_tokens": 12}
    request = Request(base + "/chat/completions", data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=600) as reply:
        return json.load(reply)


def measure(profile, mode, pair, dest):
    run = dest / f"pair-{pair}-{mode}"
    run.mkdir()
    cfg = json.loads(profile.read_text())
    cfg["log"] = str(run / "engine.log")
    config_path = run / "config.json"
    config_path.write_text(json.dumps(cfg, indent=2))
    port = free_port()
    command = [sys.executable, SERVER, "--engine", "strata", "--config", config_path,
               "--host", "127.0.0.1", "--port", str(port), "--offline", "--no-api-key"]
    with gateway(command, run, port) as (base, _):
        with urlopen(base + "/turbine/capabilities", timeout=10) as reply:
            caps = json.load(reply)
        if caps["active_slots"] != 2 or caps["native_fork"] != (mode == "on"):
            raise RuntimeError(f"Unexpected profile: {caps}")
        completion(base, cfg["model_name"], [{"role": "user", "content": "Say OK."}])
        offset = (run / "engine.log").stat().st_size

        def ask(item):
            question, expected = item
            reply = completion(base, cfg["model_name"], HISTORY + [{"role": "user", "content": question}])
            answer = (reply["choices"][0]["message"]["content"] or "").strip()
            return dict(question=question, expected=expected, answer=answer, usage=reply["usage"],
                        correct=answer.casefold().rstrip(".") == expected.casefold(),
                        finished_s=round(time.perf_counter() - start, 4))

        with ThreadPoolExecutor(max_workers=len(QUESTIONS)) as pool:
            start = time.perf_counter()
            answers = list(pool.map(ask, QUESTIONS))
            elapsed = time.perf_counter() - start
    with (run / "engine.log").open("rb") as stream:
        stream.seek(offset)
        events = [line for line in stream.read().decode(errors="replace").splitlines()
                  if line.startswith("turbine: automatic parent ")]
    result = dict(pair=pair, mode=mode, wall_s=round(elapsed, 4), capabilities=caps,
                  automatic_events=events, answers=answers)
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(pair, mode, result["wall_s"], sum(a["correct"] for a in answers), "correct",
          sum("restored" in line for line in events), "restores", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("off", type=Path)
    parser.add_argument("on", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    dest = args.output.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    runs = []
    for pair, order in enumerate((("off", "on"), ("on", "off"), ("off", "on")), 1):
        for mode in order:
            runs.append(measure(getattr(args, mode), mode, pair, dest))
    (dest / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
