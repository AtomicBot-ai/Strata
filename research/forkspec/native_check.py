"""Targeted native Metal experiments. Run from turbine-intelligence after building candidate + observer."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = Path(os.environ.get('FORKSPEC_RESULTS_DIR', HERE))
DATA.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HERE.parent / 'fast-sprint'))
sys.path.insert(0, str(ROOT / 'Atomic-Turbine/terminal/tools'))
import run as prior
sys.path.insert(0, str(HERE.parent / 'strata-fork-scaling/tools'))
from runner import Wire, memory
BUILD = Path(os.environ.get('FORKSPEC_BINARY', ROOT / '.work/forkspec/build/strata-inkling'))
OUT = DATA / 'results.jsonl'


def record(case, **result):
    with OUT.open('a') as f:
        print(json.dumps(dict(case=case, **result)), file=f, flush=True)
    print(case, {k:v for k,v in result.items() if k in ('status','payload','probes','seconds')}, flush=True)


@contextmanager
def session(case, draft='dspark', cap=320, enabled=True, extra=None):
    if prior.others():
        raise RuntimeError('engine or build active')
    cmd = [str(BUILD), '--serve', '--native', str(prior.INK), '--draft', draft, '--draft-adapt', '--kv','fp16',
           '--max-context','1408','--parallel','2','--chunk','128','--no-anti-loop']
    env = dict(TURBINE_SNAPSHOT_MIB=str(cap), TURBINE_FORK_DSPARK=str(int(enabled)), TURBINE_TEST_LOGITS='1', **(extra or {}))
    log = DATA / (case+'.log')
    start = time.monotonic()
    with log.open('w') as err, subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,
                                                  text=True,env={**os.environ,**env}) as proc:
        finished = threading.Event()
        def watch():
            while not finished.wait(1):
                if prior.others(proc.pid):
                    proc.terminate()
                    return
        thread = threading.Thread(target=watch,daemon=True)
        thread.start()
        try:
            w=Wire(proc)
            info=w.line()
            assert w.line().startswith('READY '), info
            record(case+'-start', info=info, argv=cmd, env=env, binary_sha256=hashlib.sha256(BUILD.read_bytes()).hexdigest())
            assert f'drafting={draft}' in info.split()
            assert f'native_fork={int(cap>0 and (enabled or draft=="off"))}' in info.split()
            yield w
            record(case+'-end', seconds=round(time.monotonic()-start,3), **memory(proc.pid))
        finally:
            finished.set()
            thread.join()
            if proc.poll() is None:
                w.send('QUIT')
                try: proc.wait(timeout=12)
                except subprocess.TimeoutExpired: proc.kill()


def gen(w, slot, ids, n):
    w.send(f'BGEN {slot} {n} ckpt=0 temperature=0 seed=83101 '+','.join(map(str,ids)))
    tokens=[]; endpoint=None; events=[]
    while True:
        f=w.line().split()
        if f[0]=='LOGITS': endpoint=hashlib.sha256(bytes.fromhex(f[-1])).hexdigest()
        elif f[0] in ('T','BT'): tokens.append(int(f[-1]))
        else: events.append(f)
        if f[0]=='ERR': raise ValueError(f)
        if f[:2]==['BDONE',str(slot)] or f==['BADM',str(slot),'0']: break
    assert len(tokens)==n, (n,tokens,events)
    return dict(tokens=tokens, endpoint=endpoint, events=events)


def restore(w, slot, handle, prefix):
    assert w.ctrl(f'STATE_RESTORE {slot} {handle}', 'RESTORED')==[str(len(prefix))]


def run(case):
    ids=prior.prompts('ink')['code']
    if case=='children':
        with session(case) as w:
            prefix=ids[:99]
            parent=gen(w,0,prefix,12)
            committed=prefix+parent['tokens'][:-1]
            h,count,size=w.ctrl('STATE_SAVE 0','SAVED')
            assert int(count)==len(committed)
            # First continue in-place, then fork into an independent slot with identical token IDs.
            tail=[822,235]
            live=gen(w,0,committed+tail,32)
            restore(w,1,h,committed)
            fork=gen(w,1,committed+tail,32)
            for branch in (live,fork):
                offered=[part for part in branch['events'][-1] if part.startswith('drafts=')]
                assert offered and int(offered[0].split('=')[1].split(':')[0])>0, branch
                assert ['RESUME',count] in branch['events']
            assert live['tokens']==fork['tokens']
            w.ctrl('STATE_DROP '+h,'DROPPED')
            record(case,status='pass',input_ids=prefix,tail=tail,payload=int(size),parent=parent,live=live,fork=fork)
        return
    if case in ('ring','natural'):
        opts={'FORKSPEC_OBSERVE':'1'}
        if case=='ring': opts.update(STRATA_INK_SPEC='block',FORKSPEC_FORCE_REJECT='1')
        with session(case, extra=opts) as w:
            prefix=(ids*2)[:1033]
            got=gen(w,0,prefix,14 if case=="ring" else 96)
            probes=[s for s in (DATA/(case+'.log')).read_text().splitlines() if s.startswith('ring_probe ')]
            if case=="ring": assert probes, got
            handle,count,size=w.ctrl('STATE_SAVE 0','SAVED')
            assert int(count)==len(prefix)+len(got['tokens'])-1
            failed=any(' changed=0 ' not in s for s in probes)
            record('wrapped-reject-'+case, status='fail' if failed else 'pass' if probes else 'unobserved',
                   input_ids=prefix, generation=got, probes=probes, payload=int(size))
            w.ctrl('STATE_DROP '+handle,'DROPPED')
        return not failed
    if case in ('budget','disabled'):
        with session(case,cap=1 if case=='budget' else 320,enabled=case!='disabled') as w:
            gen(w,0,ids[:60],0)
            reply=w.ctrl('STATE_SAVE 0','ERR')
            assert ('budget' in reply if case=='budget' else 'disabled' in reply)
            record(case,status='pass',reply=reply)
        return
    plain=case=='draft-off'
    with session(case,draft='off' if plain else 'dspark') as w:
        # Two children continue from the committed inputs. The pending next token is explicit in GEN.
        prefix=ids[:99]
        generated=gen(w,0,prefix,12)
        committed=prefix+generated['tokens'][:-1]
        h,count,size=w.ctrl('STATE_SAVE 0','SAVED')
        assert int(count)==len(committed)
        # Capture the live parent's continuation before any restore changes its slot.
        suffix=[822,235]
        reference=gen(w,0,committed+suffix,1)
        assert reference['endpoint'] and ['RESUME',count] in reference['events'],reference
        trials=[]
        for slot,tail in [(1,suffix),(0,[444]),(1,suffix),(0,suffix)]:
            restore(w,slot,h,committed)
            sample=gen(w,slot,committed+tail,1)
            assert sample['endpoint'] and ['RESUME',count] in sample['events']
            if tail==suffix: assert sample['endpoint']==reference['endpoint'] and sample['tokens']==reference['tokens']
            trials.append(dict(slot=slot,tail=tail,**sample))
        restore(w,1,h,committed)
        if not plain:
            fail=w.ctrl('BGEN 1 5 temperature=0.8 '+','.join(map(str,committed+suffix)),'ERR')
            assert 'greedy' in fail
        w.send('BGEN 1 300 temperature=0 '+','.join(map(str,committed+suffix)))
        while w.line()!='BADM 1 1': pass
        w.send(f'STATE_RESTORE 1 {h}\nBSTOP 1')
        busy=cancel=False
        while not (busy and cancel):
            line=w.line()
            busy |= line.startswith('ERR invalid command or busy slot')
            cancel |= line.startswith('BDONE 1 ') and 'cancel' in line
        w.ctrl('STATE_DROP '+h,'DROPPED')
        assert w.ctrl(f'STATE_RESTORE 0 {h}','ERR')==['invalid','snapshot','handle']
        reused=gen(w,1,[125,912,550],1)
        record(case,status='pass',payload=int(size),input_ids=prefix,generation=generated,reference=reference,
               trials=trials,reused=reused,busy_refused=busy,cancelled=cancel)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('cases',nargs='+',choices=['short','children','ring','natural','draft-off','disabled','budget'])
    args=p.parse_args()
    failed=False
    for case in args.cases:
        signal.alarm(120)
        try: failed |= run(case) is False
        except BaseException as exc:
            record(case,status='error',error=repr(exc))
            raise
        finally: signal.alarm(0)
    sys.exit(int(failed))
