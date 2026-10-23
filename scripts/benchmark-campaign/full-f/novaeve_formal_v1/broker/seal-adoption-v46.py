from pathlib import Path
import json,hashlib,re
root=Path(__file__).resolve().parents[5];home=root/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013';out=home/'coordinator/broker-adoption-v46';src=Path(__file__).parent
def pin(p):
 b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
seen=set()
def scan(p):
 p=p.resolve()
 if p in seen:return
 if not p.is_file():raise RuntimeError('missing actual import '+str(p))
 seen.add(p)
 if p.suffix not in ('.ts','.js'):return
 s=p.read_text(encoding='utf-8')
 for rel in re.findall(r"(?:from\s*|import\s*\()\s*['\"](\.[^'\"]+)['\"]",s):scan(p.parent/rel)
for n in ['start-adoption-v46.ts','sign-adoption-v46.ts','rehydrate-v46.ts','check-adoption-v46.ts','check-http-adoption-v46.ts']:scan(src/n)
for n in ['build-broker-adoption-v46.py','prepare-http-check-v46.py','seal-adoption-v46.py']:seen.add(src/n)
runtime=home/'coordinator/broker-adoption-v46-fixtures/8a449e44a014d1b7/actual-runtime-source-pins.json'
for p in json.loads(runtime.read_text()):scan(Path(p['path']))
pins=[pin(p) for p in sorted(seen)]
plan=dict(protocol='novaeve-root-reviewed-broker-adoption-v46',rootReviewed=True,originalBudgetMustNotReset=True,originalLocksMustRemainUnchanged=True,oldLanesAreHeldNotForwardable=True,singleSharedPool=16,primaryPort=17895,aliasPorts=[17889],noNewFunding=True,rehydrateProofPin=pin(out/'rehydrate-proof.json'),sourcePins=pins,remoteDiskObservationPath=str(home/'broker/remote-disk.json'),outputDirectory=str(home/'broker/adoption-v46/production-first'))
for name,v in [('plan.reviewed-unsigned-v3.json',plan),('source-manifest-v3.json',dict(protocol='novaeve-broker-adoption-source-manifest-v46',sourcePins=pins,actualRuntimeImportEvidencePin=pin(runtime),compiledBundleUsed=False))]:
 p=out/name
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,indent=2);f.write('\n')
print(json.dumps(dict(planPin=pin(out/'plan.reviewed-unsigned-v3.json'),manifestPin=pin(out/'source-manifest-v3.json'),sourceCount=len(pins))))
