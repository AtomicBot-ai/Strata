import fcntl, hashlib, json, time, subprocess
from pathlib import Path
root=Path.cwd()
q=Path.home()/'code/models/qwen38-iq3'
files=[*sorted(q.glob('*.gguf'))[:2],root.parent/'atomic-turbine/.work/models/Inkling-2-Mini-SQ-10.strata',root/'.work/fast-sprint/qwen-dflash2.pack',q/'profile.bin',q/'draft/vocab.bin',root/'.work/ssd-qwen-pack/dense.bin']
def busy():
    rows=subprocess.check_output(['ps','-Aco','comm='],text=True)
    return any(Path(s.strip()).name in ('strata','strata-inkling','clang','cmake','ninja','llama-server') for s in rows.splitlines())
rows=[]
for p in files:
    h=hashlib.sha256()
    with p.open('rb',buffering=0) as f:
        fcntl.fcntl(f,48,1)  # Darwin F_NOCACHE
        while True:
            while busy(): time.sleep(3)
            for _ in range(32):
                b=f.read(8<<20)
                if not b: break
                h.update(b)
            if not b: break
    rows.append(dict(file=p.name,bytes=p.stat().st_size,sha256=h.hexdigest()))
    print(p.name,flush=True)
(root/'research/spec-policy-fast/weights.json').write_text(json.dumps(rows,indent=2)+'\n')
