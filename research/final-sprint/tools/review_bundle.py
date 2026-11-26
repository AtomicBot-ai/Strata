"""Bundle the final report, observations and small reproduction tools for local review."""
from pathlib import Path
import zipfile

sprint = Path(__file__).resolve().parents[1]
root = sprint.parents[1]
dest = root / "output/Atomic-Turbine-Sprint-Review.zip"
dest.parent.mkdir(exist_ok=True)
files = {sprint / "REPORT.md"}
for directory in [sprint / "runs", sprint / "tools"]:
    files.update(p for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
for name in ("runner.py", "e02r.py", "marginal_run.py"):
    files.add(sprint.parent / "strata-fork-scaling/tools" / name)
for name in ("strata-expert-trace.patch", "counters.c"):
    files.add(sprint.parent / "adaptive-intelligence/ssd" / name)
with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
    for path in sorted(files):
        archive.write(path, path.relative_to(root))
with zipfile.ZipFile(dest) as archive:
    if archive.testzip():
        raise ValueError("corrupt review archive")
print(dest, dest.stat().st_size)
