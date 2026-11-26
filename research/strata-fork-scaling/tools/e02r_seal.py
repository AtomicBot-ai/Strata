"""Bind the fitted envelope to all calibration observations before independent evaluation."""
from e02r import BIN, CAL, HOLD, LAB, OUT, digest, read, write
from pathlib import Path
import time


def seal():
    if (OUT/"hold").exists() or (OUT/"holdout-start.json").exists():
        raise ValueError("refusing to create a retrospective seal")
    freeze=read(OUT/"freeze.json")
    if freeze["control_seeds"]!=list(CAL) or freeze["holdout_seeds"]!=list(HOLD):
        raise ValueError("split changed")
    control=OUT/"cal"
    files={str(p.relative_to(OUT)):digest(p) for p in sorted(control.rglob("*.json"))}
    observations=[]
    for result in sorted(control.glob("*/*/result.json")):
        arm=read(result)
        if arm["restore"] or arm["binary_sha256"]!=digest(BIN):
            raise ValueError(f"invalid calibration arm: {result}")
        raw=Path(arm["raw"])
        if arm["sha256"]!=digest(raw):
            raise ValueError(f"invalid logits file: {raw}")
        observations.append([arm["seed"],arm["arm"],arm["work"],arm["sha256"]])
    if len(observations)!=7*len(CAL):
        raise ValueError("incomplete native controls")
    write(OUT/"calibration-seal.json",{
        "sealed_unix_ns":time.time_ns(),"freeze_sha256":digest(OUT/"freeze.json"),
        "inputs":files,"raw_arrays":observations,"original_G0_sha256":digest(LAB/"runs/E02/mapped-state/gate.json")})


if __name__=="__main__":
    seal()
