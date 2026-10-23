"""Small read-only status sample; writes only this resume's observation, never scores."""
import datetime,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[3]
BASE=ROOT/'docs/repair-2026-10-10/full-f-rerun';OUT=BASE/'efficient-resume-20261012'
def read(p):return json.loads(p.read_bytes())
def present(p):return read(p) if p.exists() else {}
c=read(BASE/'control.json');h=read(pathlib.Path(c['broker']['healthPath']))
inventory=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,@{n='birthUtc';e={$_.CreationDate.ToUniversalTime().ToString('o')}}) | ConvertTo-Json -Compress"],text=True))
live={p['ProcessId']:p for p in inventory}
sb=BASE/'skillsbench';tb=BASE/'terminal-bench'
owner=read(sb/'event-ready-scheduler-owner.json');state_path=pathlib.Path(owner['folder'])/'state.json';state=present(state_path);queue=read(sb/'task-queue-v2.json')
ts=read(tb/'event-scheduler/process.json');audit=read(tb/'actual-run-audit.json')
valid=[t for t in audit['tasks'] if t.get('valid')]
preparingSB=[x for x in state.get('preparationContinuations',[]) if x['pid'] in live]
activeSB=[x for x in state.get('activeTasks',[]) if x['pid'] in live]
activeTB=[dict(taskId=j['taskId'],kind=j['kind'],pid=j.get('childPid')) for j in ts['jobs'].values() if j['state']=='running' and j.get('childPid') in live]
lanes=[{k:l.get(k) for k in ['slug','runId','dispatched','billedUsd','unknownCount','closed']} for l in h.get('lanes',[])]
responseDir=pathlib.Path(c['broker']['healthPath']).parent/'responses';generations=[]
for p in responseDir.glob('*.json'):
 d=read(p)
 if d.get('id') and d.get('usage',{}).get('cost') is not None:generations.append(dict(id=d['id'],usd=d['usage']['cost']))
formal={b:sum(l['slug']==b and not l['closed'] and l['dispatched']>0 for l in lanes) for b in ['skillsbench','terminal-bench']}
result=dict(atUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),baselineEffective={'skillsbench':35,'terminal-bench':25},effective={'skillsbench':len(queue['completed']),'terminal-bench':len(valid)},denominators={'skillsbench':87,'terminal-bench':89},actualFormal= formal,broker=dict(pid=h['pid'],alive=h['pid'] in live,healthy=h['healthy'],snapshotAtUtc=h['atUtc'],activeRequests=h['activeRequests'],queuedRequests=h['queuedRequests'],resourceCount=len(h.get('resourceSlots',[]))),schedulers={'skillsbench':dict(pid=owner['pid'],alive=owner['pid'] in live,active=activeSB,preparing=preparingSB),'terminal-bench':dict(pid=ts['pid'],alive=ts['pid'] in live,active=activeTB)},newEpoch=dict(lanes=lanes,uniqueGenerations=len({x['id'] for x in generations}),knownResponseUSD=sum(x['usd'] for x in generations)),historicalUnknownCostsRetained=True,automaticPaidRetry=False,formalLimitPerBench=read(OUT/'dispatch-policy.json')['formalPerBench'],preparationLimitPerBench=read(OUT/'dispatch-policy.json')['preparationPerBench'],monitorAutomationId='sb-tb')
(OUT/'snapshot.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result))
