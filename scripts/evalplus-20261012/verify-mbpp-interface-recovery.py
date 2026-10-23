"""Extra MBPP recovery audits, in addition to the frozen full-run verifier."""
import datetime,hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];base=root/'docs/evalplus-20261012';mbpp=base/'mbpp';out=mbpp/'objrun-adapter-v1/full'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
full=json.loads(subprocess.run([sys.executable,str(root/'scripts/evalplus-20261012/verify-mbpp-objrun-adapter.py'),'full','--checkpoint'],check=True,capture_output=True,text=True).stdout)
scope=read(mbpp/'interface-recovery-scope.json');rows=[read(p) for p in (out/'results/objrun').glob('*.json')]
old=read(out/'recovery/progress-checkpoint.json') if (out/'recovery/progress-checkpoint.json').exists() else {}
targets=[r for r in rows if r['officialId'] in scope['taskIds']]
resolved=[r for r in targets if r.get('grade',{}).get('valid')]
pins=read(mbpp/'interface-recovery-source-pins.json')['files']
retained=read(mbpp/'diagnosis/interface-recovery-retention-pins.json')['files']
baseline=read(mbpp/'diagnosis/baseline-retention-pins.json')
if isinstance(baseline,dict):baseline=baseline['files']
bad=lambda items:[r['path'] for r in items if not Path(r['path']).is_file() or hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()!=r['sha256']]
prior=read(mbpp/'diagnosis/interface-recovery-original-sources.json')
report={**full,'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'recoveryScope':len(targets),'recoveryResolved':len(resolved),'newlyResolved':len(resolved)-old.get('recoveryResolved',0),'recoveryPassed':sum(bool(r['grade'].get('passed')) for r in resolved),'remainingInterfaceTaskIds':[r['officialId'] for r in targets if not r.get('grade',{}).get('valid')],'recoverySourcePinsChecked':len(pins),'recoverySourceMismatch':bad(pins),'retainedValidResultsChecked':len(retained),'retainedValidResultMismatch':bad(retained),'baselineFilesChecked':len(baseline),'baselineFileMismatch':bad(baseline),'recoveryKnownCostUsd':round(full['knownCostUsd']-prior['knownCostUsd'],12),'additionalUnknownCostCount':full['unknownCostCount']-prior['unknownCostCount'],'additionalUnknownCostUpperBoundUsd':round(full['unknownCostUpperBoundUsd']-prior['unknownCostUpperBoundUsd'],12),'recoveryRound':read(out/'status.json').get('recoveryRound')}
report['recoveryCompleteAndValid']=full['completeAndValid'] and len(resolved)==len(scope['taskIds']) and not report['recoverySourceMismatch'] and not report['retainedValidResultMismatch'] and not report['baselineFileMismatch']
(out/'recovery/progress-checkpoint.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=True,indent=2))
