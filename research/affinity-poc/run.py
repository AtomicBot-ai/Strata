"""Bounded Qwen native-fork admission experiment. Run serially on the local Metal GPU."""
import collections
import contextlib
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "research/final-sprint/tools"))
from ssd_sprint import probe_disk, memory, Tokenizer, BPE, ByteLevel, PACK

PLAN = json.loads((HERE / "plan.json").read_text())
OUT = HERE / "runs"
PROBE = ROOT / ".work/affinity/build/strata"
STOCK = ROOT / ".work/final-sprint/qwen-release/strata"
BASE = json.loads((ROOT / "research/final-sprint/runs/S02/n2-block0/D/input.json").read_text())
CLOCK = time.monotonic


def save(path, obj):
    path.with_suffix(".tmp").write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
    path.with_suffix(".tmp").replace(path)


def fixture(load):
    tokenizer = Tokenizer(BPE.from_file(str(PACK/"tokenizer/vocab.json"), str(PACK/"tokenizer/merges.txt")))
    tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=False)
    enc = lambda text: tokenizer.encode(text).ids
    if load == "mixed":
        roots = ["Review the following Python cache implementation. Explain the behavior of the function for each case. The first case concerns",
                 "Review the following customer support conversation. Explain what the agent should do for each case. The first case concerns"]
    else:
        roots = ["You are reviewing a database migration. The system writes an audit entry for each transaction. The migration creates an index while existing connections continue serving reads. Document the assumptions, the relevant evidence, and the steps needed to verify",
                 "You are investigating a greenhouse experiment. The operator records humidity and temperature after each irrigation cycle. Some measurements are missing. Document the assumptions, the relevant evidence, and the steps needed to verify"]
    tails = [" insertion", " recovery", " invalidation", " concurrency", " delivery", " scheduling", " failure", " reporting"]
    parents = [enc(text) for text in roots]
    inputs = [parents[i//4] + enc(tail) for i,tail in enumerate(tails)]
    return parents, inputs, enc("\nContinue the analysis with the next relevant detail:")


class Wire:
    def __init__(self, proc):
        self.proc = proc

    def send(self, *lines):
        self.proc.stdin.write("\n".join(lines) + "\n")
        self.proc.stdin.flush()

    def read(self):
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"engine closed, status {self.proc.poll()}")
        words = line.split()
        if words and words[0] in ("ERR","SERR","FATAL"):
            raise ValueError(line.strip())
        return words

    def until(self, tag):
        while True:
            line = self.read()
            if line and line[0] == tag:
                return line[1:]


def ids(values):
    return ",".join(map(str, values))


@contextlib.contextmanager
def engine(folder, stock=False):
    cmd = BASE["cmd"].copy()
    cmd[0] = str(STOCK if stock else PROBE)
    cmd[cmd.index("--batch")+1] = "3" if stock else "4"
    cmd.extend(["--conversation-cache-mib","0"])
    env = {k:v for k,v in BASE["env"].items() if k.startswith("STRATA_METAL_")}
    env["TURBINE_QWEN_FORK"] = "1"
    save(folder/"engine.json", {"cmd":cmd, "env":env, "sha256":hashlib.sha256(Path(cmd[0]).read_bytes()).hexdigest()})
    with (folder/"metal.log").open("w") as log, subprocess.Popen(cmd, stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=log,text=True,env=dict(os.environ,**env)) as proc:
        try:
            wire = Wire(proc)
            info = wire.until("INFO")
            assert "batch_slots=2" in info and "native_parent_fork=1" in info, info
            wire.until("READY")
            yield wire
            wire.send("QUIT")
            assert proc.wait(timeout=15) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def save_parent(w, prompt, bank, stock=False):
    if not stock:
        w.send(f"AFF_BANK {bank}")
        w.until("BANKED")
    w.send("GEN 1 temperature=0 " + ids(prompt))
    w.until("DONE")
    w.send("STATE_SAVE MAIN")
    handle, count = w.until("SAVED")
    assert int(count) == len(prompt)
    return handle


def single(w, slot, prompt, count):
    w.send(f"BGEN {slot} {count} temperature=0 " + ids(prompt))
    output = []
    reuse = None
    while True:
        f = w.read()
        if f[0] in ("T","BT"):
            output.append(int(f[-1]))
        elif f[0] == "DONE":
            reuse = int(f[8])
        elif f[0] == "BDONE":
            assert int(f[1]) == slot and len(output) == count, (f, output)
            return output, reuse


def restore(w, bank, handle, stock=False):
    if not stock:
        w.send(f"AFF_BANK {bank}")
        w.until("BANKED")
    w.send("STATE_RESTORE MAIN "+handle)
    return int(w.until("RESTORED")[0])


def audit():
    """Identical single-slot decode shape, one child per bank vs the shipped one-bank engine."""
    path = OUT/"audit"
    if (path/"passed.json").exists(): return
    parents, prompts, _ = fixture("mixed")
    results = {}
    for stock in (False, True):
        folder = path/("stock" if stock else "poc")
        folder.mkdir(parents=True,exist_ok=True)
        with engine(folder, stock) as w:
            handles = {}
            if not stock:
                for bank in range(2):
                    handles[bank] = save_parent(w,parents[bank],bank)
            rows = []
            for bank in (1,0):
                h = save_parent(w,parents[bank],bank,True) if stock else handles[bank]
                assert restore(w,bank,h,stock) == len(parents[bank])
                tokens, reused = single(w,0,prompts[bank*4],6)
                assert reused == len(parents[bank])
                rows.append(tokens)
                w.send("STATE_DROP "+h)
                w.until("DROPPED")
            results[folder.name] = rows
    assert results["poc"] == results["stock"], results
    save(path/"passed.json",results)


def choose(mode, queue, active, scores, waits, bypass):
    head = queue[0]
    if mode == "parent" and active:
        family = next(iter(active.values()))//4
        return next((i for i in queue if i//4 == family), head), "parent"
    if mode != "cache": return head, "fifo"
    overdue = [i for i in queue if waits[i] >= 10 or bypass[i] >= 3]
    # Preserve the FIFO position of unknown requests even when a newer request is overdue.
    if overdue:
        candidate = overdue[0]
        for i in queue[:queue.index(candidate)]:
            if scores[i][0] == 0: return head, "fifo-before-unknown"
        return candidate, "age-bound"
    eligible = []
    for i in queue:
        if scores[i][0] == 0: break
        eligible.append(i)
    if not eligible: return head, "new-fifo"
    return min(eligible,key=lambda i: scores[i][1] - waits[i]*16*2**20), "cache"


def measure(w, load, mode, seed, folder):
    spec = PLAN["loads"][load]
    parents, prompts, suffix = fixture(load)
    handles = [save_parent(w, p, b) for b,p in enumerate(parents)]
    first_turn = {}
    for i in spec["returning"]:
        slot = i % 2
        w.send(f"AFF_BIND {slot} {i}")
        w.until("BOUND")
        restore(w,i//4,handles[i//4])
        tokens, reuse = single(w,slot,prompts[i],6)
        assert reuse == len(parents[i//4])
        first_turn[i] = tokens
        prompts[i] += tokens + suffix
        w.send(f"AFF_BIND {slot} -1")
        w.until("BOUND")
    for slot in (0,1):
        single(w,slot,[713+slot,127,521,881],3)
    w.send("AFF_SCORES")
    parse = lambda f: [tuple(map(int,word.split(":"))) for word in f]
    initial = parse(w.until("SCORES"))
    assert all(initial[i][0] == (4 if i in first_turn else 0) for i in range(8)), initial

    queue = list(range(8))
    random.Random(seed).shuffle(queue)
    arrival_order = queue.copy()
    entered = {}
    for i in queue:
        entered[i] = CLOCK()
        if i != queue[-1]: time.sleep(.08)
    save(folder/"input.json",dict(parents=parents,prompts=prompts,first_turn=first_turn,arrival_order=arrival_order,
                                  initial_scores=initial,cap=spec["new_tokens"],seed=seed))
    counter = probe_disk()
    active, pending, tokens, reused, latency = {}, collections.deque(), {i:[] for i in queue}, {}, {}
    skipped = [0]*8
    restored, decisions = [], []
    begin = counter(w.proc.pid)
    start = CLOCK()

    def accept(f):
        if f[0]=="T": tokens[pending[0]].append(int(f[-1]))
        elif f[0]=="BT": tokens[active[int(f[1])]].append(int(f[2]))
        elif f[0]=="DONE":
            i=pending[0]
            assert int(f[2]) == len(prompts[i])
            reused[i]=int(f[8])
        elif f[0]=="BADM":
            assert int(f[2])==1 and pending.popleft()==active[int(f[1])]
        elif f[0]=="RESTORED": restored.append(int(f[1]))
        elif f[0]=="BDONE":
            i=active.pop(int(f[1]))
            assert len(tokens[i])==spec["new_tokens"],(i,f,tokens[i])
            latency[i]=CLOCK()-entered[i]
        elif f[0] not in ("BANKED","SESSION","PP","RESUME","REUSED","SWAIT"):
            raise ValueError(f)

    while queue or active:
        if queue and len(active)<2:
            scores=None
            if mode=="cache":
                w.send("AFF_SCORES")
                while True:
                    f=w.read()
                    if f[0]=="SCORES":
                        scores=parse(f[1:])
                        break
                    accept(f)
            commands=[]
            for slot in (0,1):
                if slot in active or not queue:continue
                now=CLOCK()
                waits={i:now-entered[i] for i in queue}
                i,reason=choose(mode,queue,active,scores,waits,skipped)
                decisions.append(dict(id=i,slot=slot,reason=reason,ready=queue.copy(),wait=waits,
                                      active=dict(active),scores=scores,bypass=skipped.copy(),at_s=now-start))
                for other in queue[:queue.index(i)]: skipped[other]+=1
                queue.remove(i)
                active[slot]=i
                pending.append(i)
                commands.extend([f"AFF_BANK {i//4}","STATE_RESTORE MAIN "+handles[i//4],
                                 f"BGEN {slot} {spec['new_tokens']} temperature=0 "+ids(prompts[i])])
            w.send(*commands)
        else:
            accept(w.read())
    end=counter(w.proc.pid)
    sizes=[len(parents[d["id"]//4]) for d in decisions]
    assert restored == sizes, (restored,sizes)
    assert all(reused[i]==len(parents[i//4]) for i in reused) and len(reused)==8, reused
    peak=memory(w.proc.pid)["peak_footprint"]
    assert peak<=32*2**30
    for bank,h in enumerate(handles):
        w.send(f"AFF_BANK {bank}","STATE_DROP "+h)
        w.until("DROPPED")
    result=dict(wall_s=(end[0]-begin[0])/1e9,disk0_bytes=end[1]-begin[1],process_read=end[2]-begin[2],
                counter_start=begin,counter_end=end,peak_bytes=peak,decisions=decisions,tokens=tokens,
                reused=reused,restored=restored,read_prompt_tokens=sum(len(prompts[i])-r for i,r in reused.items()),
                latency_s=latency,first_turn=first_turn)
    save(folder/"result.json",result)
    print(load,seed,mode,round(result["wall_s"],2),flush=True)


def run():
    OUT.mkdir(exist_ok=True)
    audit()
    for block,seed in enumerate(PLAN["seeds"]):
        for idx,load in enumerate(PLAN["loads"]):
            arms=PLAN["arms"]
            shift=(block+idx)%3
            for mode in arms[shift:]+arms[:shift]:
                folder=OUT/load/str(seed)/mode
                if (folder/"result.json").exists():continue
                if folder.exists():folder.rename(folder.with_name(mode+"-interrupted-"+str(time.time_ns())))
                folder.mkdir(parents=True)
                signal.alarm(240)
                try:
                    with engine(folder) as w:measure(w,load,mode,seed,folder)
                finally:signal.alarm(0)


if __name__=="__main__":
    def timeout(*_):raise TimeoutError("affinity trial exceeded watchdog")
    signal.signal(signal.SIGALRM,timeout)
    signal.alarm(240)
    run()
