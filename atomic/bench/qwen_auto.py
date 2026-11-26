"""Exercise ordinary Flash-Next requests against a locally configured engine."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(config, log):
    args = [os.path.expandvars(arg) for arg in config["args"]]
    # A short fixture exercises the same boundary as the default 2048-token floor.
    args += ["--prompt-cache-root", "32", "--conversation-cache-mib", "0"]
    turn = 248045
    if "--turn-token" in args:
        turn = int(args[args.index("--turn-token") + 1])
    prefix = [turn] + [7734, 264, 1248, 47193] * 14
    unrelated = [7734, 264, 310, 13]
    env = {**os.environ, **config.get("env", {}), "TURBINE_QWEN_FORK": "1"}
    with log.open("w") as err, subprocess.Popen([config["exe"], *args], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=err, text=True, env=env) as proc:
        def command(line):
            proc.stdin.write(line + "\n")
            proc.stdin.flush()

        def frame(kind):
            for line in proc.stdout:
                fields = line.split()
                if fields and fields[0] == kind:
                    return fields[1:]
                if fields and fields[0] == "ERR":
                    raise RuntimeError(line.rstrip())
            raise RuntimeError(f"engine exited before {kind}, see {log}")

        def gen(tokens, slot=None):
            verb = "GEN" if slot is None else f"BGEN {slot}"
            command(f"{verb} 1 temperature=0 " + ",".join(map(str, tokens)))
            token = int(frame("T")[0])
            reused = int(frame("DONE")[7])
            if slot is not None and frame("BADM") != [str(slot), "0"]:
                raise RuntimeError("one-token branch did not finish")
            return token, reused

        try:
            frame("READY")
            # Replace MAIN between forks. The two visible slots use different suffixes.
            # The final request changes the first token and must miss the parent.
            branches = [prefix + [turn, 11346, suffix, turn, 13] for suffix in (13, 310, 539, 264)]
            gen(branches[0])
            reused = []
            predictions = []
            for i, branch in enumerate(branches + [[47193] + branches[0][1:]]):
                gen(unrelated)
                token, count = gen(branch, i % 2)
                predictions.append(token)
                reused.append(count)
            if any(count < len(prefix) for count in reused[:-1]) or reused[-1] != 0:
                raise RuntimeError(f"incorrect branch reuse: {reused}")
            # An explicit owner may claim the same row while it holds an automatic parent.
            gen(unrelated)
            command("STATE_SAVE MAIN")
            handle, length = frame("SAVED")
            if int(length) != len(unrelated):
                raise RuntimeError("wrong explicit parent")
            gen(branches[0])
            command("STATE_RESTORE MAIN " + handle)
            if frame("RESTORED") != [length]:
                raise RuntimeError("ordinary request displaced explicit parent")
            command("STATE_DROP " + handle)
            frame("DROPPED")
            command("QUIT")
            if proc.wait(timeout=30):
                raise RuntimeError("engine failed on shutdown")
        finally:
            if proc.poll() is None:
                proc.kill()
    events = [line for line in log.read_text(errors="replace").splitlines()
              if line.startswith("turbine: automatic parent ")]
    if f"turbine: automatic parent restored tokens={len(prefix)}" not in events:
        raise RuntimeError(f"no confirmed automatic restore: {events}")
    return {"reused_tokens": reused, "first_tokens": predictions, "events": events, "explicit_restore_tokens": int(length)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    opts = parser.parse_args()
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "engine.log"
        try:
            print(json.dumps(check(json.loads(opts.config.read_text()), log)))
        except Exception:
            if log.exists():
                print(log.read_text(errors="replace")[-2000:])
            raise
