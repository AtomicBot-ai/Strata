import json
from statistics import median
from pathlib import Path
rs=[json.loads(l) for l in Path('research/fast-sprint/results.jsonl').read_text().splitlines()]
bad={(r['family'],r['mode'],r['label']) for r in rs if 'error' in r}
q=[r for r in rs if (r['family'],r['mode'],r['label']) not in bad and r.get('template')=='pack-chat-thinking-off' and r.get('fixture') in ('code','prose')]
for fixture in ('code','prose'):
    print(fixture)
    data=[r for r in q if r['fixture']==fixture]
    modes={mode:[r for r in data if r['mode']==mode] for mode in ('off','stock','narrow')}
    for mode,rows in modes.items():
        if not rows: continue
        print(mode, 'TPS', [round(r['tps'],2) for r in rows], 'TTFT',round(median(r['ttft_s'] for r in rows),2), 'wall',round(median(r['wall_s'] for r in rows),2), 'GiB',round(median(r['peak_footprint_bytes']/2**30 for r in rows),2))
        print('  disk0 MB/t', [round(r['disk0_decode_bytes']/1e6/(len(r['output_ids'])-1),1) for r in rows], '250ms idle MB', [round(r['disk0_idle_bytes_250ms']/1e6,2) for r in rows])
        if mode!='off': print('  rounds', [r['draft_rounds'] for r in rows], 'accepted/round', [round(r['accepted']/r['draft_rounds'],2) if r['draft_rounds'] else None for r in rows], 'total decode ms/round', [round(float(r['done'][4])/r['draft_rounds'],1) if r['draft_rounds'] else None for r in rows])
        print('parity', [r['output_ids']==modes['off'][0]['output_ids'] for r in rows])
    for metric in ['tps','disk0_decode_bytes']:
        ratios=[b[metric]/a[metric] for a,b in zip(modes['stock'],modes['narrow'])]
        if ratios: print(metric,'delta %', [round((i-1)*100,1) for i in ratios], 'median',round((median(ratios)-1)*100,1))
