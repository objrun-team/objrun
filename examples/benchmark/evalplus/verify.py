"""Read-only progress and artifact audit. Never starts an experiment or container."""
import argparse,datetime,hashlib,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[3];BASE=ROOT/'docs/evalplus-20261012'
ap=argparse.ArgumentParser();ap.add_argument('dataset',choices=['humaneval','mbpp']);ap.add_argument('phase',choices=['pilot','full'],default='full',nargs='?');ap.add_argument('--checkpoint',action='store_true');a=ap.parse_args()
out=BASE/a.dataset/a.phase
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
status=read(out/'status.json') if (out/'status.json').exists() else {}
records=[read(p) for p in (out/'results').rglob('*.json')]
calls=[read(p) for p in (out/'calls').rglob('receipt.json')]
dispatch=[p for p in (out/'calls').rglob('dispatch.json')]
pending=[str(p.parent) for p in dispatch if not (p.parent/'receipt.json').exists()]
ids=read(BASE/a.dataset/'task-ids.json');ids=ids[:10] if a.phase=='pilot' else ids
arms={}
for arm in ['baseline','objrun','independent']:
 rr=[r for r in records if r['arm']==arm];valid=[r for r in rr if r.get('grade',{}).get('valid')];passed=sum(r['grade'].get('passed',False) for r in valid)
 arms[arm]={'completed':len(rr),'total':len(ids),'valid':len(valid),'passed':passed,'temporaryPassRate':passed/len(valid) if valid else None,'exceptions':len(rr)-len(valid),'fullDenominatorPassRate':passed/len(ids),'duplicateIds':len(rr)-len({r['officialId'] for r in rr})}
old=read(out/'progress-checkpoint.json') if (out/'progress-checkpoint.json').exists() else {'arms':{}}
delta={arm:row['completed']-old['arms'].get(arm,{}).get('completed',0) for arm,row in arms.items()}
ps="Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress" % status.get('pid',0)
process=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True).stdout.strip()
latest=max([p.stat().st_mtime for p in out.rglob('*') if p.is_file() and p.name not in ['status.json','progress-checkpoint.json','runner-lock.json']],default=0)
audit={'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'dataset':a.dataset,'phase':a.phase,'dockerForbidden':True,'stage':status.get('stage'),'currentArm':status.get('currentArm'),'arms':arms,'newSinceLastCheck':delta,'process':json.loads(process) if process else None,'pendingRequests':pending,'modelCalls':len([r for r in calls if r.get('dispatched')]),'actualCostUsd':sum(r.get('actualCostUsd') or 0 for r in calls),'unknownCostCount':sum(bool(r.get('unknownCost')) for r in calls),'unknownCostUpperBoundUsd':sum(r.get('upperBoundUsd',0) for r in calls if r.get('unknownCost')),'lastArtifactAtUtc':datetime.datetime.fromtimestamp(latest,datetime.timezone.utc).isoformat() if latest else None,'resultRoot':str(out),'completeAndValid':all(x['completed']==x['total'] and not x['exceptions'] and not x['duplicateIds'] for x in arms.values())}
audit['modelCalls']=len(dispatch)
audit['completedCalls']=len(calls)
audit['modelProtocolFailures']=sum(bool(r.get('modelProtocolFailure')) for r in records)
if a.checkpoint:
 (out/'progress-checkpoint.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
 with (out/'progress-history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(audit)+'\n')
print(json.dumps(audit,ensure_ascii=False,indent=2))
