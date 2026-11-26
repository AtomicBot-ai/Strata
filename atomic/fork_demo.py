"""Four independent read-only questions about the packaged launcher."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(base, path, body=None, headers=None, method=None):
    payload = None if body is None else json.dumps(body).encode()
    req = Request(base + path, payload, {"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urlopen(req, timeout=180) as response:
            data = response.read()
            return json.loads(data) if data else None
    except HTTPError as error:
        raise RuntimeError(f"{error.code} {error.read().decode()}") from error


QUESTIONS = (
    ("Which host address does serve-inkling bind to?", "127.0.0.1"),
    ("What TCP port does serve-inkling use by default?", "8080"),
    ("Which KV data type does serve-inkling pass to the engine?", "fp16"),
    ("What value does serve-inkling pass to --chunk?", "128"),
)


def run(base, model, ordinary=False):
    start = time.perf_counter()
    source = Path(__file__).with_name("atomic-turbine").read_text()
    parent = [{"role": "system", "content": "Answer questions about the following Python source. "
               "Respond only with the requested value.\n" + source}]
    common = {"model": model, "reasoning_effort": "none", "messages": parent}
    checkpoint = None
    if not ordinary:
        checkpoint = call(base, "/turbine/checkpoints", common)
    prepared = time.perf_counter()
    try:
        def branch(task):
            question, expected = task
            req = {**common, "messages": parent + [{"role": "user", "content": question}],
                   "max_tokens": 32, "temperature": 0}
            reply = call(base, "/chat/completions", req,
                         {"X-Turbine-Checkpoint": checkpoint["id"]} if checkpoint else {})
            answer = reply["choices"][0]["message"]["content"]
            return {"question": question, "answer": answer, "expected": expected,
                    "success": (answer or "").strip().lower() == expected, "request": reply["id"],
                    "completion_tokens": reply["usage"]["completion_tokens"]}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(branch, QUESTIONS))
    finally:
        if checkpoint:
            call(base, "/turbine/checkpoints/" + checkpoint["id"], method="DELETE")
    return {"mode": "ordinary" if ordinary else "native", "tokens": checkpoint["tokens"] if checkpoint else None,
            "prepare_s": prepared-start, "elapsed_s": time.perf_counter()-start, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", default="inkling")
    parser.add_argument("--ordinary", action="store_true")
    args = parser.parse_args()
    result = run(args.base, args.model, args.ordinary)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if all(item["success"] for item in result["results"]) else 1)
