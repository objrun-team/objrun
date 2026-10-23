from pathlib import Path
import json,re,hashlib
root=Path(__file__).resolve().parents[5]
broker=Path(__file__).resolve().parent
base=root/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/broker-live-handoff-v70'
base.mkdir(parents=True,exist_ok=True)
def pin(p):
 data=p.read_bytes();return dict(path=str(p),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
seen=set()
def scan(p):
 p=p.resolve()
 if p in seen:return
 assert p.exists(),str(p)
 seen.add(p)
 if p.suffix in ('.ts','.js'):
  for rel in re.findall(r'''(?:from\s*|import\s*\(\s*)['"]([^'"]+)['"]''',p.read_text(encoding='utf8')):
   if rel.startswith('.'):
    q=(p.parent/rel).resolve()
    if not q.exists():q=Path(str(q)+'.ts')
    scan(q)
for name in ['start-adoption-v70.ts','capture-live-state-v70.ts','sign-adoption-v70.ts','publish-adoption-v70.ts','shared-admission-owned-v70.ts','pause-old-for-handoff-v70.ts','check-http-adoption-v70.ts','check-durable-adoption-v70.ts','port-quiescence-v70.py','freeze-v70.py']:
 scan(broker/name)
manifest=dict(protocol='novaeve-broker-v70-executed-source-manifest',sourcePins=[pin(p) for p in sorted(seen)],compiledBundle=False,oldSourcesUnmodified=True)
with (base/'source-manifest.json').open('x',encoding='utf8') as f:json.dump(manifest,f,indent=2);f.write('\n')
print(json.dumps(dict(manifestPin=pin(base/'source-manifest.json'),sourceCount=len(seen))))

