import json,re,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[4]
out=root/'docs/repair-2026-10-10/full-f-rerun/chemiq'
session=Path('C:/Users/y1252/.codex/sessions/2026/10/10/rollout-2026-10-10T17-39-48-01a1252e-d4be-7043-be9f-3c475bc4364c.jsonl')
source=None
for raw in session.read_text(encoding='utf-8').splitlines():
    event=json.loads(raw)
    if event.get('timestamp','')>'2026-10-10T09:50:05.000Z':continue
    payload=event.get('payload',{})
    if payload.get('type') not in ('function_call','custom_tool_call'):continue
    code=payload.get('arguments',payload.get('input',''))
    for match in re.finditer(r'tools\.apply_patch\(("(?:\\.|[^"\\])*")\)',code):
        patch=json.loads(match.group(1));lines=patch.splitlines();i=0
        while i<len(lines):
            line=lines[i]
            if line.startswith('*** Add File: ') and line.endswith('/chemiq/run.ts'):
                i+=1;parts=[]
                while i<len(lines) and not lines[i].startswith('*** '):
                    if lines[i].startswith('+'):parts.append(lines[i][1:])
                    i+=1
                source='\n'.join(parts)+'\n';continue
            if line.startswith('*** Update File: ') and line.endswith('/chemiq/run.ts'):
                i+=1
                while i<len(lines) and not lines[i].startswith('*** '):
                    if lines[i].startswith('@@'):
                        i+=1;old=[];new=[]
                        while i<len(lines) and not lines[i].startswith(('@@','*** ')):
                            v=lines[i]
                            if v.startswith((' ','-')):old.append(v[1:])
                            if v.startswith((' ','+')):new.append(v[1:])
                            i+=1
                        before='\n'.join(old)+'\n';after='\n'.join(new)+'\n'
                        if source is None or source.count(before)!=1:raise RuntimeError('Ambiguous historical source hunk')
                        source=source.replace(before,after,1)
                    else:i+=1
                continue
            i+=1
if source is None:raise RuntimeError('Source creation unavailable')
active=json.loads((out/'active-run.json').read_text(encoding='utf-8-sig'))
manifest=json.loads((Path(active['output'])/'manifest.json').read_text(encoding='utf-8'))
expected=next(p['sha256'] for p in manifest['sourcePins'] if p['path'].replace('\\','/').endswith('/chemiq/run.ts'))
actual=hashlib.sha256(source.encode()).hexdigest()
if actual!=expected:raise RuntimeError('Historical source reconstruction hash mismatch')
recovery=out/'startup-recovery';recovery.mkdir(exist_ok=True)
(recovery/'original-run.ts').write_bytes(source.encode())
print(json.dumps({'reconstructed':True,'sha256':actual,'matchesFrozenSource':True}))

