from pathlib import Path
import difflib
n='engine/src/inkling2/metal/ink_metal_backend.mm'
p=Path('.work/forkspec/source')/n
before=p.read_text()
s=before.replace('            if (!runner_.forward_batch(st, nullptr, ver_ids, err)) return -1;','            observe(slot, anchor_pos, tm);\n            if (!runner_.forward_batch(st, nullptr, ver_ids, err)) return -1;',1)
s=s.replace('            if (acc < tm - 1) runner_.restore_verify_step(slot, acc);','''            if (acc < tm - 1) {
                runner_.restore_verify_step(slot, acc);
                last_ver_pos0_ = anchor_pos;
                check_rows(slot, anchor_pos + acc + 1);
            }''')
p.write_text(s)
Path('research/forkspec/adaptive-observer.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),s.splitlines(True),'a/'+n,'b/'+n)))
