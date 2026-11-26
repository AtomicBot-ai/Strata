import json, datetime, hashlib, statistics
from pathlib import Path
from collections import Counter
p=Path('research/adaptive-intelligence/runs/stepback-live-01')
lock=json.loads((p/'lock.json').read_text())
tasks={r['id']:r for r in json.loads((p/'tasks.json').read_text())}
rr=[]
for t,s,m in lock['schedule']:
 f=p/'jobs'/f'{t}-{s}-{m}.json'
 if not f.is_file():break
 rr.append(json.loads(f.read_text()))
def pub(r):
 sel=r['selected']['code']
 return bool(sel) and any(c['code_sha']==hashlib.sha256(sel.encode()).hexdigest() and c['passed']==len(tasks[r['task']]['public']) for c in r['public_checks'])
rows=rr[:len(rr)//4*4]
stats={}
for m in 'ABCD':
 a=[r for r in rows if r['mode']==m]
 ch=[(r,b) for r in a for b in r['branches'] if b['parent'] is not None]
 stats[m]=dict(passed=sum(pub(r) for r in a),sent=sum(bool(r['selected']['code']) for r in a),ms=round(statistics.median(r['selected']['published_ms'] for r in a)/1000,2),pruned=sum(r['pruned'] for r in a),forked=len(ch),forkcode=sum(bool(b['code']) for r,b in ch),chosen=sum(r['selected']['branch']==b['name'] for r,b in ch),miss=sum(r['selected']['deadline_missed'] for r in a),div=sum(r['divergent_sibling_ticks']>0 for r in a),maxmem=round(max(r['metal_bytes']+r['peak_snapshot_bytes'] for r in a)/2**30,2),foot=round(max(r['peak_footprint'] for r in a)/2**30,2))
ix={(r['task'],r['seed'],r['mode']):r for r in rows}; pairs={}
for m,n in [('B','A'),('C','B'),('D','C')]:
 diff=[];ident=0
 for t,s,z in ix:
  if z!=m:continue
  a,b=ix[t,s,m],ix[t,s,n];delta=int(pub(a))-int(pub(b));ident+=a['selected']['code']==b['selected']['code']
  if delta:diff.append([t,s,delta])
 pairs[m+n]=dict(diff=diff,ident=ident)
out=dict(clock=datetime.datetime.now().astimezone().strftime('%H:%M:%S'),all=len(rr),n=len(rows)//4,nt=len(set(r['task'] for r in rows)),levels=dict(Counter(tasks[r['task']]['level'] for r in rows if r['mode']=='A')),last=[rr[-1][x] for x in ('task','seed','mode')],stats=stats,pairs=pairs)
print(json.dumps(out,ensure_ascii=False,indent=2))
