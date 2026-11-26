"""Prospective E02-R calibration and independent matched Metal trajectories."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import numpy as np

from runner import BUILD, LAB, MODEL, PATCHED, Wire, cold, fingerprint, fixture

OUT = LAB / "runs/E02-R"
RAW = BUILD / "e02r-logits"
BIN = BUILD / "e02r-build/strata-inkling"
SPEC = LAB / "E02-R.md"
DEPTHS = (0, 1, 8, 32, 128, 256, 512, 1024)
LENGTHS = (1023, 1024, 1025, 2049)
CAL = range(28101, 28109)
HOLD = range(39101, 39105)
CORE = ("direct", "mixed", "serial")
SHORT = ("swapped", "reverse", "chunk64", "joint")
KEYS = ("max_abs", "rmse", "js", "top10_loss", "greedy_loss")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def write(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write("\n")


def read(path):
    return json.loads(path.read_text())


def timeout(*_):
    raise TimeoutError("trajectory exceeded 480 seconds")


@contextlib.contextmanager
def session(folder, chunk):
    cmd = [str(BIN), "--serve", "--native", str(MODEL), "--draft", "off", "--kv", "fp16",
           "--max-context", "3200", "--chunk", str(chunk), "--parallel", "2", "--no-anti-loop"]
    write(folder/"launch.json", {"cmd": cmd, "binary_sha256": digest(BIN)})
    with (folder/"metal.log").open("x") as err, subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
        env=dict(os.environ, STRATA_SCALING_LAB="1")
    ) as proc:
        w = Wire(proc)
        try:
            info, ready = w.line(), w.line()
            write(folder/"startup.json", [info, ready])
            required = {"backend=metal", "drafting=off", "batch_slots=2", "kv_dtype=fp16", f"chunk={chunk}"}
            if not required.issubset(info.split()) or ready.split()[:2] != ["READY", "3200"]:
                raise RuntimeError((info, ready))
            w.ctrl("LABTRACE", "TRACEOK")
            yield w
        finally:
            if proc.poll() is None:
                try:
                    w.send("QUIT")
                    proc.wait(timeout=10)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    proc.kill()
            proc.stdin.close()
            proc.stdout.close()


def submit(w, commands):
    w.send(commands[0] if len(commands) == 1 else "LABPAIR " + "|".join(commands))


def prime(w, slots, root):
    prompt = ",".join(map(str, root[:-1]))
    submit(w, [f"BGEN {s} 0 temperature=0 ckpt=0 {prompt}" for s in slots])
    done = []
    while len(done) < len(slots):
        fields = w.line().split()
        if fields[0] == "BADM" and fields[2] == "0":
            done.append(int(fields[1]))
        elif fields[0] not in ("PP", "DONE"):
            raise RuntimeError(fields[:8])
    if sorted(done) != sorted(slots):
        raise ValueError("wrong priming slots")


def decode(w, jobs, root, tails, length, reuse, array, shapes):
    commands = []
    mapping = dict(jobs)
    tokens = {s: [] for s in mapping}
    depths = [d for d in DEPTHS if d <= length]
    seen = set()
    admitted = []
    finished = set()
    for slot, leaf in jobs:
        forced = ",".join(map(str, tails[leaf][:length]))
        prompt = ",".join(map(str, root))
        commands.append(f"BGEN {slot} {length+1} slot_read=1 ckpt=0 temperature=0 teacher={forced} {prompt}")
    submit(w, commands)
    while len(finished) < len(jobs):
        p = w.line().split()
        if p[0] == "RLOG":
            slot, depth, nlog, nbatch = map(int,p[1:5])
            if (depth not in depths or (slot,depth) in seen or nlog != len(jobs)
                    or (depth and nbatch != len(jobs))):
                raise ValueError(("unexpected forward shape",p[:5],jobs))
            vector = np.frombuffer(bytes.fromhex(p[5]),dtype="<f4")
            if vector.shape != (200058,) or not np.isfinite(vector).all():
                raise ValueError("bad FP32 vocabulary")
            array[mapping[slot],depths.index(depth)] = vector
            shapes.append([mapping[slot],slot,depth,nlog,nbatch])
            seen.add((slot,depth))
        elif p[0] == "BT":
            tokens[int(p[1])].append(int(p[2]))
        elif p[0] == "DONE":
            if p[5] != "admit" or int(p[2]) != len(root) or int(p[-1]) != reuse:
                raise ValueError(("admission/reuse mismatch",p))
        elif p[0] == "BADM":
            admitted.append(int(p[1]))
        elif p[0] == "BDONE":
            slot = int(p[1])
            if int(p[2]) != length+1 or p[3] not in ("length","stop") or slot in finished:
                raise ValueError(p)
            finished.add(slot)
        elif p[0] not in ("PP","RESUME"):
            raise RuntimeError(p[:8])
    if sorted(admitted) != sorted(mapping) or len(seen) != len(depths)*len(mapping):
        raise ValueError("incomplete trajectory")
    for slot,leaf in jobs:
        expected = tails[leaf][:length]
        if tokens[slot][:-1] != expected or tokens[slot][-1] != int(array[leaf,-1].argmax()):
            raise ValueError("forced work or independent endpoint disagrees")


def run_arm(stage, seed, arm, restore=False):
    boundary = LENGTHS[(seed - (CAL.start if stage=="cal" else HOLD.start)) % len(LENGTHS)]
    root_list,tails = fixture(boundary+1,2,1024,seed)
    root = root_list[0]
    name = arm + ("-fork" if restore else "")
    folder = OUT/stage/str(seed)/name
    raw = RAW/stage/str(seed)/(name+".npy")
    result = folder/"result.json"
    if result.exists():
        meta = read(result)
        if meta["sha256"] != digest(raw) or meta["binary_sha256"] != digest(BIN):
            raise RuntimeError(f"artifact mismatch {result}")
        return raw
    folder.mkdir(parents=True, exist_ok=False)
    raw.parent.mkdir(parents=True, exist_ok=True)
    length = 1024 if arm in CORE else 32
    chunk = 64 if arm=="chunk64" else 128
    depths = [d for d in DEPTHS if d<=length]
    arr = np.empty((2,len(depths),200058),dtype="<f4")
    shapes = []
    source = seed % 2
    slots = [1,0] if arm=="swapped" else [0,1]
    jobs = list(zip(slots,range(2)))
    if arm=="reverse":
        jobs.reverse()
    signal.alarm(480)
    start = time.monotonic()
    try:
        with session(folder,chunk) as w:
            cold(w)
            if arm != "direct":
                if restore:
                    prime(w, [source], root)
                    count, size = map(int,w.ctrl(f"LABSAVE {source}","SAVED"))
                    if count != boundary or size <= 0:
                        raise ValueError("bad checkpoint")
                    cold(w)
                    for slot in slots:
                        if w.ctrl(f"LABRESTORE {slot}","RESTORED") != [str(boundary)]:
                            raise ValueError("bad restore")
                elif arm == "joint":
                    prime(w,slots,root)
                else:
                    for slot in slots:
                        prime(w,[slot],root)
            groups = [[j] for j in jobs] if arm=="serial" else [jobs]
            for group in groups:
                decode(w,group,root,tails,length,0 if arm=="direct" else boundary,arr,shapes)
            if restore:
                w.ctrl("LABDROP","DROPPED")
        np.save(raw,arr,allow_pickle=False)
        write(result, dict(seed=seed,boundary=boundary,arm=arm,restore=restore,source=source if restore else None,
                           work=fingerprint((root,tails)),raw=str(raw),sha256=digest(raw),
                           binary_sha256=digest(BIN),seconds=time.monotonic()-start,shapes=shapes))
    except BaseException as err:
        write(folder/"failure.json", {"reason":repr(err)})
        raise
    finally:
        signal.alarm(0)
    return raw


def metrics(a,b):
    exact = bool(a.tobytes()==b.tobytes())
    x,y = a.astype("f8"), b.astype("f8")
    diff=x-y
    def prob(v):
        log=v-v.max()
        log-=np.log(np.exp(log).sum())
        return log,np.exp(log)
    lx,px=prob(x)
    ly,py=prob(y)
    mid=np.logaddexp(lx,ly)-np.log(2.0)
    js=max(0., float(((px*(lx-mid)).sum()+(py*(ly-mid)).sum())/2))
    def top(v):
        return np.argsort(-v,kind="stable")[:10]
    overlap=len(set(top(x)).intersection(top(y)))/10
    same=bool(x.argmax()==y.argmax())
    return dict(max_abs=float(np.abs(diff).max()),rmse=float(np.sqrt(np.mean(diff*diff))),
                js=0. if exact else js,top10_loss=1-overlap,greedy_loss=float(not same),
                top10_overlap=overlap,greedy_agreement=same,exact=exact)


def compare(stage,seed,tag,left,right):
    a,b=[np.load(p,mmap_mode="r") for p in (left,right)]
    rows=[]
    for leaf in range(2):
        for i,d in enumerate(DEPTHS[:min(a.shape[1],b.shape[1])]):
            rows.append(dict(seed=seed,branch=leaf,depth=d,contrast=tag,**metrics(a[leaf,i],b[leaf,i])))
    path=OUT/stage/str(seed)/(tag+".json")
    if not path.exists():
        write(path,rows)
    elif rows != read(path):
        raise RuntimeError("comparison changed")
    return rows


def per_tree(rows):
    values={}
    for depth in DEPTHS:
        by_arm={}
        for r in rows:
            if r["depth"]==depth:
                by_arm.setdefault(r["contrast"],[]).append(r)
        if not by_arm or any(len(pair)!=2 for pair in by_arm.values()):
            raise ValueError("incomplete contrasts")
        values[str(depth)]={k:max(sum(r[k] for r in pair)/2 for pair in by_arm.values()) for k in KEYS}
    return values


def collect(stage,seed):
    paths={arm:run_arm(stage,seed,arm) for arm in CORE+SHORT}
    native=[]
    for arm in CORE[1:] + SHORT:
        native.extend(compare(stage,seed,"native-"+arm,paths["direct"],paths[arm]))
    for arm in SHORT:
        compare(stage,seed,"one-factor-"+arm,paths["mixed"],paths[arm])
    result={"native":per_tree(native)}
    if stage=="hold":
        candidate=[]
        exact=True
        forks={}
        for arm in ("mixed","serial","swapped","reverse","chunk64"):
            forks[arm]=run_arm(stage,seed,arm,True)
            matched=compare(stage,seed,"matched-"+arm,paths[arm],forks[arm])
            exact=exact and all(r["exact"] for r in matched)
            candidate.extend(compare(stage,seed,"cross-"+arm,paths["direct"],forks[arm]))
        native_effect=compare(stage,seed,"batch-effect-native",paths["serial"],paths["mixed"])
        fork_effect=compare(stage,seed,"batch-effect-fork",forks["serial"],forks["mixed"])
        result.update(candidate=per_tree(candidate),exact=exact,
                      interaction={k:max(abs(a[k]-b[k]) for a,b in zip(native_effect,fork_effect)) for k in KEYS})
    return result


def provenance():
    return {str(p):digest(p) for p in (SPEC,Path(__file__),LAB/"tools/runner.py",BIN,PATCHED,
                                      LAB/"archive/e02r-observer.patch",LAB/"archive/inventory.json")}


def main(stage):
    lock=OUT/"freeze.json"
    if stage=="cal" and lock.exists():
        raise ValueError("calibration already frozen")
    if stage=="hold":
        frozen=read(lock)
        if frozen["provenance"]!=provenance() or frozen["control_sha256"]!=digest(OUT/"cal-panel.json"):
            raise ValueError("frozen inputs changed")
        verify_path=OUT/"holdout-start.json"
        if not verify_path.exists():
            write(verify_path,{"freeze_sha256":digest(lock),"start_unix_ns":time.time_ns()})
        if read(verify_path)["freeze_sha256"]!=digest(lock):
            raise ValueError("freeze changed during holdout")
    panel=[]
    for seed in (CAL if stage=="cal" else HOLD):
        panel.append(collect(stage,seed))
        print(stage,seed,flush=True)
    write(OUT/(stage+"-panel.json"),panel)
    if stage=="cal":
        bounds={str(d):{k:max(r["native"][str(d)][k] for r in panel) for k in KEYS} for d in DEPTHS}
        write(lock,dict(bounds=bounds,control_seeds=list(CAL),holdout_seeds=list(HOLD),
                        control_sha256=digest(OUT/"cal-panel.json"),provenance=provenance(),unix_ns=time.time_ns()))
    else:
        failures=[]
        for name in ("native","candidate"):
            for d in DEPTHS:
                for k in KEYS:
                    value=float(np.mean([r[name][str(d)][k] for r in panel]))
                    limit=frozen["bounds"][str(d)][k]
                    if value>limit:
                        failures.append(dict(group=name,depth=d,metric=k,value=value,limit=limit))
        exact=all(r["exact"] for r in panel)
        status="passed"
        if not exact:
            status="exact_mismatch"
        elif any(f["group"]=="native" for f in failures):
            status="native_out_of_envelope"
        elif failures:
            status="candidate_out_of_envelope"
        write(OUT/"gate.json",dict(status=status,exact=exact,failures=failures,freeze_sha256=digest(lock)))
        print(status,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=("cal","hold"))
    signal.signal(signal.SIGALRM,timeout)
    main(parser.parse_args().stage)
