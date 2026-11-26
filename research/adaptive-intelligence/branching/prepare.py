"""Prepare public-only inputs and separate evaluation labels from pinned JSONL files.
Use complete JSON records from the declared byte ranges. Never deserialize pickle objects.
"""

import base64
import hashlib
import json
import pickletools
import re
import zlib
from engine import ROOT

DATA = ROOT / ".work/pilot-data"
MATH_REV = "6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be"
CODE_REV = "0fe84c3912ea0c4d4a78037083943e8f0c4dd505"


def tests(encoded):
    if encoded.startswith("["):
        return json.loads(encoded)
    raw = zlib.decompress(base64.b64decode(encoded))
    ops = list(pickletools.genops(raw))
    strings = [arg for op, arg, _ in ops if op.name in ("BINUNICODE", "BINUNICODE8", "SHORT_BINUNICODE")]
    allowed = {"PROTO", "FRAME", "MEMOIZE", "STOP", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8"}
    if len(strings) != 1 or any(op.name not in allowed for op, _, _ in ops):
        raise ValueError("unsupported encoded JSON")
    return json.loads(strings[0])


def main():
    pools = {"math": {}, "code": {}}
    for line in (DATA / "math.jsonl").read_text().splitlines():
        r = json.loads(line)
        if re.fullmatch(r"-?[0-9]+", r["answer"]) and r["level"] <= 4:
            pools["math"][r["unique_id"]] = (dict(question=r["problem"]), r["answer"])
    for path in sorted(DATA.glob("code6-*.jsonl")):
        for line in path.read_bytes().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue  # partial boundary line in HTTP range
            if r["difficulty"] == "hard" or r["starter_code"] or r["platform"] != "atcoder":
                continue
            public = json.loads(r["public_test_cases"])
            if not public or not all(t["testtype"] == "stdin" for t in public):
                continue
            private = tests(r["private_test_cases"])
            if not private or not all(t["testtype"] == "stdin" for t in private):
                continue
            pools["code"][r["question_id"]] = (dict(question=r["question_content"], public=public), private)
    tasks, labels = [], {}
    for domain, pool in pools.items():
        ids = sorted(pool, key=lambda k: hashlib.sha256(("strata-01/" + k).encode()).digest())
        if len(ids) < 4:
            raise ValueError(f"insufficient {domain} IDs: {ids}")
        for n, k in enumerate(ids[:7]):  # keep at least one unseen task
            split = "debug" if n < 2 else "pilot" if 2 <= n < min(6, len(ids) - 1) else "holdout"
            task, label = pool[k]
            tasks.append(dict(id=k, domain=domain, split=split, **task))
            labels[k] = label
    (DATA / "public.json").write_text(json.dumps(tasks))
    (DATA / "labels.json").write_text(json.dumps(labels))
    print([(t["domain"], t["id"], t["split"]) for t in tasks])


if __name__ == "__main__":
    main()
