"""Package the sprint release using the versioned fork packaging tool."""
import subprocess
import sys
from pathlib import Path

workspace = Path(__file__).resolve().parents[3]
subprocess.run([sys.executable, str(workspace / "Atomic-Turbine/atomic/package.py"),
                *sys.argv[1:], "--output", str(workspace / "output")], check=True)
