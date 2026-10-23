from pathlib import Path
import json,re,hashlib
root=Path(__file__).resolve().parents[5]
broker=Path(__file__).resolve().parent
base=root/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/broker-state-guard-recovery-v76'
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
for name in ['start-adoption-v76.ts','capture-guard-failure-v76.ts','sign-adoption-v76.ts','publish-adoption-v76.ts','shared-admission-owned-v76.ts','check-claim-races-v76.ts','check-http-adoption-v76.ts','check-durable-adoption-v76.ts','port-quiescence-v76.py','freeze-v76.py','check-state-guard-v76.ts']:
 scan(broker/name)
manifest=dict(protocol='novaeve-broker-v76-executed-source-manifest',sourcePins=[pin(p) for p in sorted(seen)],compiledBundle=False,oldSourcesUnmodified=True)
with (base/'source-manifest.json').open('x',encoding='utf8') as f:json.dump(manifest,f,indent=2);f.write('\n')
print(json.dumps(dict(manifestPin=pin(base/'source-manifest.json'),sourceCount=len(seen))))

