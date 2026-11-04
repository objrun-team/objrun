"""Verify provider recovery without changing the original verifier or scorer."""
import json,hashlib,subprocess,sys,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[3];m=root/'docs/evalplus-20261012/mbpp';out=m/'objrun-adapter-v1/full'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
report=json.loads(subprocess.run([sys.executable,str(root/'examples/benchmark/evalplus/verify-mbpp-interface-recovery.py')],check=True,capture_output=True,text=True).stdout)
pins=read(m/'provider-recovery-source-pins.json')['files'];retained=read(m/'diagnosis/interface-recovery-round2-valid-retention.json')['files']
bad=lambda items:[r['path'] for r in items if not Path(r['path']).is_file() or hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()!=r['sha256']]
new=[read(p) for p in (out/'calls').rglob('receipt.json') if read(p).get('providerRecoveryVersion')=='provider-recovery-v1']
counts={}
for r in new:
 tag=r['requestedProviderTag'];entry=counts.setdefault(tag,{'calls':0,'knownCostUsd':0,'unknownCostCount':0,'unknownCostUpperBoundUsd':0,'precision':r['officialCatalogPrecision']})
 entry['calls']+=1;entry['knownCostUsd']+=r['actualCostUsd'] or 0;entry['unknownCostCount']+=bool(r['unknownCost']);entry['unknownCostUpperBoundUsd']+=(r['upperBoundUsd'] if r['unknownCost'] else 0)
rows=[read(p) for p in (out/'results/objrun').glob('*.json')];provider_rows=[r for r in rows if r.get('providerRecoveryVersion')=='provider-recovery-v1']
wire_bad=[]
for p in (out/'calls').rglob('receipt.json'):
 r=read(p)
 if r.get('providerRecoveryVersion')!='provider-recovery-v1':continue
 wire=read(p.parent/'request.json');tag=r['requestedProviderTag']
 if wire['provider'].get('only')!=[tag] or wire['provider'].get('allow_fallbacks') is not False or 'fp8' in wire['provider'].get('quantizations',[]) or r['officialCatalogPrecision'] not in ['fp16','bf16','fp32','unknown']:wire_bad.append(str(p))
report.update(atUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),providerRecoveryVersion='provider-recovery-v1',providerSourcePinsChecked=len(pins),providerSourceMismatch=bad(pins),allPriorValidResultsChecked=len(retained),allPriorValidResultMismatch=bad(retained),providerCalls=counts,providerResolved=sum(bool(r.get('grade',{}).get('valid')) for r in provider_rows),providerPassed=sum(bool(r.get('grade',{}).get('valid')) and bool(r['grade'].get('passed')) for r in provider_rows),providerWireMismatch=wire_bad,mixedProviders=True)
report['providerRecoveryCompleteAndValid']=report['recoveryCompleteAndValid'] and not report['providerSourceMismatch'] and not report['allPriorValidResultMismatch'] and not wire_bad
(out/'recovery/provider-progress-checkpoint.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
