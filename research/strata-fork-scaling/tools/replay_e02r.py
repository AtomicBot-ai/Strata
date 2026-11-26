"""Reproduce E02-R in a fresh results directory without changing the archived run."""
import argparse
from pathlib import Path
import signal

import e02r

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("raw", type=Path, help="directory for full FP32 vectors, about 1 GiB")
    args = parser.parse_args()
    e02r.OUT = args.out.resolve()
    e02r.RAW = args.raw.resolve()
    if e02r.OUT == e02r.RAW or e02r.OUT.exists() or e02r.RAW.exists():
        parser.error("choose two distinct new directories")
    e02r.OUT.mkdir(parents=True)
    signal.signal(signal.SIGALRM,e02r.timeout)
    e02r.main("cal")
    from e02r_seal import seal
    seal()
    e02r.main("hold")
