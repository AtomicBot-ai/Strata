import json,subprocess,sys,time,os
from pathlib import Path
root=Path.cwd()
lab=root/'research/final-sprint'
pid=int(sys.argv[1])
while subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout.strip().endswith('research/final-sprint/tools/s01.py'):
    time.sleep(5)
for stage,cmd in [('S02',['ssd_sprint.py','S02']),('S03',['ssd_sprint.py','S03']),('S04',['s04.py'])]:
    exe=[sys.executable,'-B',str(lab/'tools'/cmd[0]),*cmd[1:]]
    res=subprocess.run(exe)
    print(stage,res.returncode,flush=True)
    (lab/'runs'/f'{stage}-exit.json').write_text(json.dumps(dict(code=res.returncode,command=exe)))
