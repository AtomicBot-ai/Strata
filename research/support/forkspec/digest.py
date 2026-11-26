import fcntl,hashlib,json,os,subprocess,time
from pathlib import Path
os.nice(15)
p=Path('../atomic-turbine/.work/models/Inkling-2-Mini-SQ-10.strata')
h=hashlib.sha256()
with p.open('rb',buffering=0) as f:
 fcntl.fcntl(f,48,1)
 while True:
  procs=subprocess.check_output(['ps','-Aco','comm='],text=True)
  if any(Path(x.strip()).name in ('strata','strata-inkling','clang','cmake','ninja','llama-server') for x in procs.splitlines()):
   time.sleep(2)
   continue
  buf=f.read(32<<20)
  if not buf:break
  h.update(buf)
records={'base':'90ebd75b51210c85fdfcd2854f34bf7ddb41109c','product_at_end':subprocess.check_output(['git','-C','Atomic-Turbine','rev-parse','HEAD'],text=True).strip(),'model':{'file':p.name,'bytes':p.stat().st_size,'sha256':h.hexdigest()},'binaries':{}}
for n,loc in [('forced_and_short','forced-observer-binary'),('adaptive_observer','build/strata-inkling'),('factor','policy-build/strata-inkling')]:
 q=Path('.work/forkspec')/loc
 records['binaries'][n]=hashlib.sha256(q.read_bytes()).hexdigest()
Path('research/forkspec/provenance.json').write_text(json.dumps(records,indent=2)+'\n')
