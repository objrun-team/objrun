from pathlib import Path
import json,hashlib,re,difflib
root=Path(__file__).resolve().parents[5];home=root/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013';out=home/'coordinator/broker-adoption-v48';src=Path(__file__).parent
def pin(p):
 b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
seen=set()
def scan(p):
 p=p.resolve()
 if p in seen:return
 if not p.is_file():raise RuntimeError('missing import '+str(p))
 seen.add(p)
 if p.suffix not in ('.ts','.js'):return
 for rel in re.findall(r"(?:from\s*|import\s*\()\s*['\"](\.[^'\"]+)['\"]",p.read_text(encoding='utf-8')):scan(p.parent/rel)
for n in ['start-adoption-v48.ts','sign-adoption-v48.ts','check-durable-adoption-v48.ts','check-http-adoption-v48.ts','publish-adoption-v48.ts','check-consumer-v48.ts']:scan(src/n)
for n in ['build-adoption-v48.py','finish-build-v48.py','build-consumer-v48.py','finish-consumer-v48.py','port-absence-v48.py','seal-adoption-v48.py']:seen.add(src/n)
runtime=home/'coordinator/broker-adoption-v48-fixtures/8a5af0fe145b1044/actual-runtime-source-pins.json'
for p in json.loads(runtime.read_text()):scan(Path(p['path']))
pins=[pin(p) for p in sorted(seen)]
previous=list((root/'.phase1-data').glob('broker-adoption-v46-*.json'))
if len(previous)!=1:raise RuntimeError('exact one previous adoption guard required')
plan=dict(protocol='novaeve-root-reviewed-broker-adoption-v48',rootReviewed=True,originalBudgetMustNotReset=True,originalLocksMustRemainUnchanged=True,oldLanesAreHeldNotForwardable=True,singleSharedPool=16,primaryPort=17895,aliasPorts=[17889],noNewFunding=True,rehydrateProofPin=pin(home/'coordinator/broker-adoption-v46/rehydrate-proof.json'),restartProofPin=pin(out/'durable-proof.json'),previousAdoptionGuardPin=pin(previous[0]),secondRebootObservationPin=pin(home/'coordinator/second-reboot-v48/initial-readonly-observation.json'),sourcePins=pins,remoteDiskObservationPath=str(home/'broker/remote-disk.json'),outputDirectory=str(home/'broker/adoption-v48/production-second'))
for name,v in [('plan.reviewed-unsigned-v2.json',plan),('source-manifest-v2.json',dict(protocol='novaeve-broker-adoption-source-manifest-v48',sourcePins=pins,actualRuntimeImportEvidencePin=pin(runtime),compiledBundleUsed=False,previousLedgerMutation=False))]:
 with (out/name).open('x',encoding='utf-8') as f:json.dump(v,f,indent=2);f.write('\n')
for old,new in [('broker-adoption-v46.ts','broker-adoption-v48.ts'),('adopted-parent-v46.ts','adopted-parent-v48.ts'),('preflight-adoption-v46.ts','preflight-adoption-v48.ts'),('adopted-consumer-guard-v46.ts','adopted-consumer-guard-v48.ts'),('publish-adoption-v46.ts','publish-adoption-v48.ts')]:
 (out/(new+'.diff')).write_text(''.join(difflib.unified_diff((src/old).read_text().splitlines(True),(src/new).read_text().splitlines(True),fromfile=old,tofile=new)))
print(json.dumps(dict(planPin=pin(out/'plan.reviewed-unsigned-v2.json'),manifestPin=pin(out/'source-manifest-v2.json'),sourceCount=len(pins))))
