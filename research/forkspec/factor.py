"""Four policies on a common binary, two mirrored blocks and a plain reference."""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = Path(os.environ.get('FORKSPEC_RESULTS_DIR', HERE))
DATA.mkdir(parents=True, exist_ok=True)
sys.path.insert(0,str(HERE.parent/'fast-sprint'))
sys.path.insert(0, str(ROOT / 'Atomic-Turbine/terminal/tools'))
import run as prior
BIN=Path(os.environ.get('FORKSPEC_FACTOR_BINARY', ROOT/'.work/forkspec/policy-build/strata-inkling'))
OUT=DATA/'factor.jsonl'
MIXED='''A filesystem indexer reads a JSON-lines journal. A writer can crash halfway through the last record, and a later record for the same path replaces the old one. Implement recover_index(stream) in Python using the standard library. Return a dict mapping path to its latest revision, support deletes, and distinguish a truncated final line from bad data in the middle. Include two small tests and explain how you would avoid loading the whole journal into memory.

import json

def recover_index(stream):
    """Recover the latest revision for every live path."""
'''
def jobs():
    j=prior.prompts('ink')
    tokdir=ROOT/'.work/rc/prepared-tokenizer'
    vocab=json.loads((tokdir/'vocab.json').read_text())
    merges=(tokdir/'merges.txt').read_text().splitlines()
    tok=prior.Tokenizer(sorted(vocab,key=vocab.get),merges[1:] if merges[0].startswith('#version') else merges,
                        pre=json.loads((tokdir/'tokenizer.json').read_text())['pre'])
    return {**j,'mixed':tok.encode(MIXED,parse_special=False)}

@contextmanager
def engine(arm,label):
    if prior.others(): raise RuntimeError('neighbor workload')
    cmd=[str(BIN),'--serve','--native',str(prior.INK),'--draft','off' if arm=='plain' else 'dspark','--kv','fp16',
         '--max-context','2048','--parallel','1','--chunk','128']
    if arm!='plain': cmd.append('--draft-adapt')
    env=dict(FORKSPEC_MEASURE_COST=str(int(arm in ('B','D'))),FORKSPEC_WARM_FOUR=str(int(arm in ('C','D'))),
             FORKSPEC_POLICY_TRACE=str(int(label=='markers')),TURBINE_SNAPSHOT_MIB='0')
    log=DATA/f'factor-{label}.log'
    start=time.monotonic()
    with log.open('x') as f, subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=f,
                                                text=True,env={**os.environ,**env}) as proc:
        finished=threading.Event()
        def watch():
            while not finished.wait(1):
                if prior.others(proc.pid):
                    proc.terminate()
                    return
        monitor=threading.Thread(target=watch,daemon=True)
        monitor.start()
        def send(cmd):
            proc.stdin.write(cmd+'\n')
            proc.stdin.flush()
        def line():
            s=proc.stdout.readline().strip()
            if not s or s.startswith(('ERR','FATAL')):raise RuntimeError(s or f'engine exited {proc.poll()}')
            return s.split()
        try:
            info=line()
            assert f'drafting={"off" if arm=="plain" else "dspark"}' in info and line()[0]=='READY',info
            yield proc,send,line,log
        finally:
            finished.set()
            monitor.join()
            if proc.poll() is None:
                send('QUIT')
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill()
            write(dict(kind='process',arm=arm,label=label,seconds=time.monotonic()-start,args=cmd,env=env,
                       binary_sha256=hashlib.sha256(BIN.read_bytes()).hexdigest(),info=info))

def write(row):
    with OUT.open('a') as f: print(json.dumps(row),file=f)

def run(arm,label,items):
    with engine(arm,label) as (proc,send,line,log):
        for key,ids,n in items:
            output=[]
            start=time.monotonic()
            send(f'GEN {n} temperature=0 seed=83101 '+','.join(map(str,ids)))
            while True:
                fields=line()
                if fields[0]=='T':
                    if not output: first=time.monotonic()
                    output.append(int(fields[1]))
                if fields[0]=='DONE':break
            end=time.monotonic()
            summary=[s for s in log.read_text().splitlines() if s.startswith('factor ')][-1]
            counts={k:float(v) if '.' in v else int(v) for k,v in re.findall(r'(\w+)=([\d.]+)',summary)}
            assert int(fields[1])==len(output)>0
            peak=(ctypes.c_uint64*64)()
            assert ctypes.CDLL('/usr/lib/libproc.dylib').proc_pid_rusage(proc.pid,4,ctypes.byref(peak))==0
            write(dict(kind='request',label=label,arm=arm,fixture=key,input_ids=ids,output_ids=output,limit=n,
                       emitted_from_rounds=len(output)-1-counts['plain'],accepted=int(fields[6]),offered=int(fields[7]),
                       done=fields,tps=(len(output)-1)/(end-first),ttft_s=first-start,wall_s=end-start,
                       peak_bytes=peak[30],**counts))
            print(label,key,len(output),round((len(output)-1)/(end-first),1),flush=True)

if __name__=='__main__':
    fixtures=jobs()
    items=[(k,v,{'warm':8,'mixed':256}.get(k,128)) for k,v in fixtures.items()]
    def timeout(*_): raise TimeoutError('30 minute limit')
    signal.signal(signal.SIGALRM,timeout)
    signal.alarm(1800)
    if sys.argv[1:] == ['--confirm']:
        rows=[json.loads(s) for s in OUT.read_text().splitlines()]
        def score(arm):
            rates=[r['tps'] for r in rows if r.get('label') in ('1'+arm,'2'+arm) and r.get('fixture')=='mixed']
            assert len(rates)==2
            return sum(rates)/2
        winner=max('BCD',key=score)
        for arm in ('A',winner):
            run(arm,'3'+arm,items)
        sys.exit(0)
    if sys.argv[1:]: raise SystemExit('usage: factor.py [--confirm]')
    for block,order in enumerate(('ABCD','DCBA'),1):
        for arm in order:
            run(arm,f'{block}{arm}',items)
    run('plain','plain',items)
    run('D','markers',[items[0],items[-1]])
    rows=[json.loads(s) for s in OUT.read_text().splitlines()]
    def get(label,job): return next(r for r in rows if r['label']==label and r.get('fixture')==job)['output_ids']
    for job in ('prose','mixed','code'):
        a,d=get('1A',job),get('1D',job)
        div=next((i for i,(x,y) in enumerate(zip(a,d)) if x!=y),None)
        if div is not None:
            forced=[('forced-'+job,fixtures[job]+a[:div],1)]
            for arm in ('A','D'): run(arm,'replay'+arm,forced)
            break
