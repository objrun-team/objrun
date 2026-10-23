"""Read-only verification of the separate MBPP ObjRun adapter experiment."""
import argparse,datetime,hashlib,json,pathlib,subprocess
root=pathlib.Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['canary','full']);ap.add_argument('--checkpoint',action='store_true');a=ap.parse_args()
out=root/'docs/evalplus-20261012/mbpp/objrun-adapter-v1'/a.mode
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
status=read(out/'status.json') if (out/'status.json').exists() else {}
rows=[read(p) for p in (out/'results/objrun').glob('*.json')]
calls=[read(p) for p in (out/'calls').rglob('receipt.json')]
dispatches=list((out/'calls').rglob('dispatch.json'))
missing=[p.parent for p in dispatches if not(p.parent/'receipt.json').exists()]
unresolved=[p for p in missing if (p/'dispatch-disposition.json').exists() and read(p/'dispatch-disposition.json').get('state')=='interrupted_no_response']
pending=[str(p) for p in missing if p not in unresolved]
old=read(out/'progress-checkpoint.json') if (out/'progress-checkpoint.json').exists() else {}
expected=['Mbpp/9'] if a.mode=='canary' else read(root/'docs/evalplus-20261012/mbpp/task-ids.json')
valid=[r for r in rows if r.get('grade',{}).get('valid')];passed=sum(bool(r['grade'].get('passed')) for r in valid)
pid=status.get('pid',0);ps=f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress'
proc=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True).stdout.strip()
report={'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'version':'objrun-adapter-v1','mode':a.mode,'stage':status.get('stage'),'completed':len(rows),'total':len(expected),'newSinceLastCheck':len(rows)-old.get('completed',0),'valid':len(valid),'passed':passed,'temporaryPassRate':passed/len(valid) if valid else None,'fixedDenominatorPassRate':passed/len(expected),'exceptions':len(rows)-len(valid),'modelProtocolFailures':sum(bool(r.get('modelProtocolFailure')) for r in rows),'protocolRepairCalls':sum(r.get('protocolRepairCalls',0) for r in rows),'process':json.loads(proc) if proc else None,'pendingRequests':pending,'modelCalls':len(dispatches),'knownCostUsd':sum(r.get('actualCostUsd') or 0 for r in calls),'unknownCostCount':sum(bool(r.get('unknownCost')) for r in calls),'unknownCostUpperBoundUsd':sum(r.get('upperBoundUsd') or 0 for r in calls if r.get('unknownCost')),'fixedIdsComplete':sorted(r['officialId'] for r in rows)==sorted(expected),'resultRoot':str(out),'dockerForbidden':True}
base=root/'docs/evalplus-20261012'
pins=read(base/'source-pins.json')['files']+read(base/'mbpp/objrun-adapter-v1-source-pins.json')['files']
mismatch=[r['path'] for r in pins if not pathlib.Path(r['path']).is_file() or hashlib.sha256(pathlib.Path(r['path']).read_bytes()).hexdigest()!=r['sha256']]
baseline=[read(p) for p in (base/'mbpp/full/results/baseline').glob('*.json')]
report.update({'sourcePinsChecked':len(pins),'sourceMismatch':mismatch,'elapsedSeconds':status.get('elapsedSeconds'),
 'unresolvedDispatches':[str(p) for p in unresolved],
 'unknownCostCount':report['unknownCostCount']+len(unresolved),
 'unknownCostUpperBoundUsd':report['unknownCostUpperBoundUsd']+sum(read(p/'dispatch-disposition.json')['upperBoundUsd'] for p in unresolved),
 'nativeRecoveryAttempts':sum(r.get('nativeRecoveryAttempts',0) for r in rows),
 'adapterTransportRevision':status.get('adapterTransportRevision'),
 'interfaceExceptions':sum(bool(r.get('interfaceFailure')) and not r.get('grade',{}).get('valid') for r in rows),
 'gradingOrRunnerExceptions':sum(not r.get('interfaceFailure') and not r.get('grade',{}).get('valid') for r in rows),
 'baseline':{'completed':len(baseline),'total':378,'passed':sum(bool(r.get('grade',{}).get('passed')) for r in baseline),'valid':sum(bool(r.get('grade',{}).get('valid')) for r in baseline)},
 'completionReady':report['fixedIdsComplete'] and proc=='' and not pending and not mismatch and status.get('stage') in ['complete','complete_with_exceptions'],
 'nativeSubmittedResults':sum(r.get('candidateHow')=='submitted' for r in rows),
 'unexpectedTaskIds':sorted(set(r['officialId'] for r in rows)-set(expected)),
 'duplicateTaskIds':len(rows)-len(set(r['officialId'] for r in rows)),
 'independentCancelled':True})
report['completeAndValid']=report['completionReady'] and report['exceptions']==0
if a.checkpoint:
 (out/'progress-checkpoint.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 with (out/'progress-history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(report)+'\n')
print(json.dumps(report,ensure_ascii=True,indent=2))
