"""Prospective evidence-gated rollback experiment on unused local tasks."""

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

import sympy as sp
from tokenizers import Tokenizer

from blind_critic import BIN, BUDGET, DATA, POST_CAP, SEEDS, TOKENIZER, drafts, locked, one, sha, value
from critic_summary import cluster_interval
from engine import engine, record
from grade import final_text, run_cases
from prepare import CODE_REV, MATH_REV, tests
from rollback_map import decode, load, read_rows, write

CAP = 96
NAMES = ("restart", "static", "critic")


def prepare(out):
    excluded = {t["id"] for t in load(DATA / "public.json")}
    for name in ("rollback-map-01", "blind-critic-01"):
        excluded.update(t["id"] for t in load(out.parent / name / "tasks.json"))
    pool = {}
    for r in read_rows(DATA / "math.jsonl"):
        if re.fullmatch(r"-?\d+", r["answer"]):
            pool[r["unique_id"]] = ("math", r["level"], r["problem"], [], r["answer"])
    for p in sorted(DATA.glob("code6-*.jsonl")):
        for line in p.open("rb"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r["platform"] == "atcoder" and not r["starter_code"]:
                cases = json.loads(r["public_test_cases"])
                if cases and all(c["testtype"] == "stdin" for c in cases):
                    pool[r["question_id"]] = (
                        "code",
                        r["difficulty"],
                        r["question_content"],
                        cases,
                        r["private_test_cases"],
                    )
    tasks, labels = [], {}
    for domain, level, n in (("math", 4, 4), ("math", 5, 4), ("code", "easy", 1), ("code", "hard", 3)):
        ids = sorted(
            (k for k, v in pool.items() if k not in excluded and v[:2] == (domain, level)),
            key=lambda k: hashlib.sha256(("evidence-critic-v1/" + k).encode()).digest(),
        )[:n]
        assert len(ids) == n
        for k in ids:
            _, _, question, public, ref = pool[k]
            tasks.append(dict(id=k, domain=domain, level=level, question=question, public=public))
            labels[k] = ref if domain == "math" else tests(ref)
            if domain == "code":
                assert labels[k] and all(t["testtype"] == "stdin" for t in labels[k])
    out.mkdir(exist_ok=False)
    write(out / "tasks.json", tasks)
    write(DATA / ("labels-" + out.name + ".json"), labels)
    write(
        out / "protocol.json",
        dict(
            excluded=sorted(excluded),
            seeds=SEEDS,
            draft_seed=1571,
            draft_cap=BUDGET,
            post_cap=POST_CAP,
            critic_cap=CAP,
            math_revision=MATH_REV,
            code_revision=CODE_REV,
            binary=sha(BIN),
            tokenizer=sha(TOKENIZER),
            tasks=sha(out / "tasks.json"),
            policy="Truncated: continue by default. Terminal code truncation stays on continue. Completed invalid program or public failure: rewrite from last available step. Math: ask model for earliest false numeric equality, authorize only on independently verified whole adjacent terms at that location. No certificate: default. Suppress inspection if it could starve default continuation. No gold or corrective hint in generator. Same three seeds, all tasks.",
            metrics="Paired gains/losses against static and restart at 2048 processed tokens after common draft; separate changed actions and critic overhead. Descriptive exact percentile bootstrap resampling whole tasks.",
        ),
    )


def exact(expr, sign):
    """Bounded, closed scalar arithmetic. Never evaluate model text as Python."""
    s = expr.replace("±", sign).replace("−", "-").replace("×", "*").replace("·", "*").replace("÷", "/")
    s = s.replace(r"\times", "*").replace(r"\cdot", "*").replace("^", "**").strip()
    for _ in range(3):
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", s)
        s = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", s)
    s = s.replace("{", "(").replace("}", ")")
    if len(s) > 128 or not re.fullmatch(r"[0-9+*/().\s\-sqrt]+", s):
        raise ValueError
    node = ast.parse(s, mode="eval").body
    if len(list(ast.walk(node))) > 48:
        raise ValueError

    def calc(n):
        if isinstance(n, ast.Constant) and type(n.value) is int and abs(n.value) < 10**12:
            return sp.Integer(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = calc(n.operand)
            return v if isinstance(n.op, ast.UAdd) else -v
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "sqrt"
            and len(n.args) == 1
            and not n.keywords
        ):
            return sp.sqrt(calc(n.args[0]))
        if isinstance(n, ast.BinOp):
            a, b = calc(n.left), calc(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Div) and b != 0:
                return a / b
            if (
                isinstance(n.op, ast.Pow)
                and b.is_Integer
                and abs(b) <= 12
                and a.is_Rational
                and max(abs(a.p).bit_length(), a.q.bit_length()) < 256
            ):
                return a**b
        raise ValueError

    result = calc(node)
    if result.is_real is not True or result.is_finite is not True:
        raise ValueError
    return result


def certified(text, quote):
    # The quote must span an equals sign. Compare entire equation members; a
    # substring such as '2 = 3' inside '1 + 2 = 3' cannot serve as evidence.
    if "=" not in quote or text.count(quote) != 1:
        return None
    start = text.index(quote)
    for match in re.finditer("=", quote):
        pos = start + match.start()
        # Do not split on a decimal point or thousands separator.
        split = r"=|\$|\n|;|(?<!\d),|,(?!\d)|\.(?!\d)|\\\[|\\\]"
        lhs = re.split(split, text[:pos])[-1].strip()
        rhs = re.split(split, text[pos + 1 :])[0].strip()
        # A prose introduction before ':' can introduce a numeric equation.
        lhs = lhs.rsplit(":", 1)[-1].strip()
        try:
            left = {exact(lhs, s) for s in ("+", "-")}
            right = {exact(rhs, s) for s in ("+", "-")}
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
            continue
        if any(
            all((a - b).is_zero is False for b in other)
            for own, other in ((left, right), (right, left))
            for a in own
        ):
            return dict(
                lhs=lhs, rhs=rhs, left=sorted(map(str, left)), right=sorted(map(str, right)), offset=pos
            )
    return None


def prefix(d, a):
    if a == "CONTINUE":
        return d["tokens"]
    if a == "RESTART":
        return []
    return d["tokens"][: d["points"][a.lower()]]


def locate(d, tok, offset):
    steps = [(len("Step 1:" + decode(tok, d["tokens"][:n])), a.upper()) for a, n in d["points"].items()]
    return max([(0, "RESTART")] + [(n, a) for n, a in steps if n <= offset])[1]


def inspect(t, d, tok, s):
    text = final_text(d["text"])
    default = "CONTINUE" if d["reason"] == "length" else "KEEP"
    res = dict(task=t["id"], default=default, action=default, inspection_cost=0, certificate=None)
    if t["domain"] == "code":
        program = value(text, "code")
        if not program:
            res["status"] = "no program"
            return res
        try:
            compile(program, "<draft>", "exec")
        except (SyntaxError, ValueError) as e:
            cert = dict(kind="syntax", line=getattr(e, "lineno", None), message=str(e))
            if default == "CONTINUE":
                res["status"] = "incomplete program"
                res["diagnostic"] = cert
                return res
        else:
            flags = run_cases(program, t["public"])
            res["public_pass"] = flags
            if all(flags) or default == "CONTINUE":
                res["status"] = (
                    "public checks recorded; no localized error before truncation"
                    if default == "CONTINUE"
                    else "public pass"
                )
                return res
            cert = dict(kind="public failure", index=flags.index(False))
        action = locate(d, tok, len(text))
    else:
        body = (
            "Identify the earliest false numerical equality explicitly written in the draft. "
            "Check arithmetic. Copy a short EXACT substring of the draft spanning the wrong equals sign, "
            "retaining its symbols and spaces. If none, return NONE. One line only.\nProblem:\n"
            + t["question"]
            + "\nDraft:\n"
            + text
            + "\nReturn the quote alone or NONE."
        )
        ids = tok.encode(
            "<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>"
            "<|message_user|><|content_text|>" + body + "<|end_message|><|message_model|><|content_text|>",
            add_special_tokens=False,
        ).ids
        reserve = len(d["base"]) + (len(d["tokens"]) if default == "CONTINUE" else 0)
        if len(ids) + CAP + reserve > POST_CAP:
            res["status"] = "inspection skipped for budget"
            return res
        r = one(s, ids, CAP, 1, 0)
        raw = final_text(decode(tok, r["tokens"]))
        res.update(inspection_cost=r["processed"], model_reply=raw)
        lines = raw.strip().splitlines()
        quote = lines[0].strip().strip('`"') if lines else ""
        cert = certified(text, quote)
        if not cert:
            res["status"] = "no verified equality"
            return res
        action = locate(d, tok, cert["offset"])
    if len(d["base"]) + len(prefix(d, action)) + res["inspection_cost"] <= POST_CAP:
        res.update(action=action, certificate=cert, status="verified intervention")
    else:
        res.update(status="unaffordable", certificate=cert)
    return res


def decide(out):
    tok = Tokenizer.from_file(str(TOKENIZER))
    initial = {r["task"]: r for r in read_rows(out / "drafts.jsonl")}
    with engine(out / "critic.log", checkpoints=False) as s, (out / "decisions.jsonl").open("x") as f:
        for t in load(out / "tasks.json"):
            record(f, **inspect(t, initial[t["id"]], tok, s))
    write(
        out / "lock.json",
        {f: sha(out / f) for f in ("tasks.json", "protocol.json", "drafts.jsonl", "decisions.jsonl")},
    )


def generate(out):
    locked(out)
    tok = Tokenizer.from_file(str(TOKENIZER))
    ds = {r["task"]: r for r in read_rows(out / "decisions.jsonl")}
    with engine(out / "branches.log", checkpoints=False) as s, (out / "answers.jsonl").open("x") as f:
        for d in read_rows(out / "drafts.jsonl"):
            k = d["task"]
            c = ds[k]
            policies = dict(restart="RESTART", static=c["default"], critic=c["action"])
            for seed in SEEDS:
                for a in dict.fromkeys(policies.values()):
                    names = [name for name in NAMES if policies[name] == a]
                    costs = {name: c["inspection_cost"] if name == "critic" else 0 for name in names}
                    if a == "KEEP":
                        for name in names:
                            record(
                                f,
                                task=k,
                                seed=seed,
                                policy=name,
                                action=a,
                                text=d["text"],
                                processed=costs[name],
                            )
                        continue
                    pre = prefix(d, a)
                    ids = d["base"] + pre
                    limits = {name: POST_CAP - len(ids) - cost + 1 for name, cost in costs.items()}
                    if min(limits.values()) < 1:
                        raise ValueError("action cannot fit")
                    r = one(s, ids, max(limits.values()), seed, 1)
                    for name in names:
                        suffix = r["tokens"][: limits[name]]
                        cost = costs[name] + len(ids) + max(0, len(suffix) - 1)
                        assert cost <= POST_CAP
                        record(
                            f,
                            task=k,
                            seed=seed,
                            policy=name,
                            action=a,
                            processed=cost,
                            new_tokens=len(suffix),
                            text="Step 1:" + decode(tok, pre + suffix),
                        )
            print(k, flush=True)


def grade(out):
    locked(out)
    tasks = {t["id"]: t for t in load(out / "tasks.json")}
    refs = load(DATA / ("labels-" + out.name + ".json"))
    memo = {}
    answers = read_rows(out / "answers.jsonl")
    expected = {(k, seed, name) for k in tasks for seed in SEEDS for name in NAMES}
    assert (
        len(answers) == len(expected) and {(r["task"], r["seed"], r["policy"]) for r in answers} == expected
    )
    groups = {}
    for r in answers:
        k = r["task"]
        domain = tasks[k]["domain"]
        v = value(r["text"], domain)
        if (k, v) not in memo:
            if domain == "math":
                ok = v == refs[k]
            else:
                cases = refs[k]
                ok = (
                    bool(v)
                    and all(run_cases(v, cases[:3]))
                    and (len(cases) <= 3 or all(run_cases(v, cases[3:])))
                )
            memo[k, v] = ok
        groups.setdefault((k, r["seed"]), {})[r["policy"]] = memo[k, v]
    with (out / "scores.jsonl").open("x") as f:
        for (k, seed), g in groups.items():
            record(f, task=k, seed=seed, domain=tasks[k]["domain"], **g)
    totals = {n: sum(g[n] for g in groups.values()) for n in NAMES}
    pairs = {}
    for n in ("static", "restart"):
        ds = [sum(groups[k, seed]["critic"] - groups[k, seed][n] for seed in SEEDS) for k in tasks]
        pairs[n] = dict(
            gains=sum(g["critic"] and not g[n] for g in groups.values()),
            losses=sum(g[n] and not g["critic"] for g in groups.values()),
            ci_pp=cluster_interval(ds),
        )
    write(out / "summary.json", dict(totals=totals, pairs=pairs, count=len(groups)))
    print(totals, pairs, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    stages = dict(prepare=prepare, drafts=drafts, decide=decide, generate=generate, grade=grade)
    p.add_argument("stage", choices=stages)
    p.add_argument("out", type=Path)
    a = p.parse_args()
    stages[a.stage](a.out)
