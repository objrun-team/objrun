"""Read-only verification of the separate HumanEval ObjRun adapter experiment."""
import argparse,datetime,json,pathlib,subprocess
root=pathlib.Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['canary','full']);ap.add_argument('--checkpoint',action='store_true');a=ap.parse_args()
out=root/'docs/evalplus-20261012/humaneval/objrun-adapter-v1'/a.mode
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
status=read(out/'status.json') if (out/'status.json').exists() else {}
rows=[read(p) for p in (out/'results/objrun').glob('*.json')]
calls=[read(p) for p in (out/'calls').rglob('receipt.json')]
dispatches=list((out/'calls').rglob('dispatch.json'))
pending=[str(p.parent) for p in dispatches if not(p.parent/'receipt.json').exists()]
old=read(out/'progress-checkpoint.json') if (out/'progress-checkpoint.json').exists() else {}
expected=['HumanEval/8'] if a.mode=='canary' else read(root/'docs/evalplus-20261012/humaneval/task-ids.json')
valid=[r for r in rows if r.get('grade',{}).get('valid')];passed=sum(bool(r['grade'].get('passed')) for r in valid)
pid=status.get('pid',0);ps=f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress'
proc=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True).stdout.strip()
report={'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'version':'objrun-adapter-v1','mode':a.mode,'stage':status.get('stage'),'completed':len(rows),'total':len(expected),'newSinceLastCheck':len(rows)-old.get('completed',0),'valid':len(valid),'passed':passed,'temporaryPassRate':passed/len(valid) if valid else None,'fixedDenominatorPassRate':passed/len(expected),'exceptions':len(rows)-len(valid),'modelProtocolFailures':sum(bool(r.get('modelProtocolFailure')) for r in rows),'protocolRepairCalls':sum(r.get('protocolRepairCalls',0) for r in rows),'process':json.loads(proc) if proc else None,'pendingRequests':pending,'modelCalls':len(dispatches),'knownCostUsd':sum(r.get('actualCostUsd') or 0 for r in calls),'unknownCostCount':sum(bool(r.get('unknownCost')) for r in calls),'unknownCostUpperBoundUsd':sum(r.get('upperBoundUsd') or 0 for r in calls if r.get('unknownCost')),'fixedIdsComplete':sorted(r['officialId'] for r in rows)==sorted(expected),'resultRoot':str(out),'dockerForbidden':True}
if a.checkpoint:
 (out/'progress-checkpoint.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 with (out/'progress-history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(report)+'\n')
print(json.dumps(report,ensure_ascii=True,indent=2))
