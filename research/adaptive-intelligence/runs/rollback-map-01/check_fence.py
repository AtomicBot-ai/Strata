"""Post-hoc parser sensitivity check for the positive code example. No model calls."""
import json
import re
import sys
from pathlib import Path

folder = Path(__file__).resolve().parent
sys.path.insert(0, str(folder.parents[1] / "branching"))
from engine import record
from grade import final_text, run_cases
from prepare import DATA

task = "abc393_d"
cases = json.loads((DATA / ("labels-" + folder.name + ".json")).read_text())[task]
with (folder / "code-fence-check.jsonl").open("x") as output:
    for stage in ("drafts", "branches"):
        for line in (folder / (stage + ".jsonl")).open():
            row = json.loads(line)
            if row["task"] != task or row["mode"] not in ("draft", "restart", "extra_restart"):
                continue
            match = re.search(r"```python[ \t]*\n(.*)", final_text(row["text"]), re.S)
            program = match[1].split("```", 1)[0] if match else None
            first = run_cases(program, cases[:3])
            correct = all(first) and all(run_cases(program, cases[3:]))
            record(output, task=task, mode=row["mode"], seed=row["seed"], correct=correct)
