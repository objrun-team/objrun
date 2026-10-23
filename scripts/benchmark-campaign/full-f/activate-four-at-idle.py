"""One-shot source-pinned switch; never interrupts a task or its resources."""
import datetime,hashlib,json,pathlib,subprocess,time,os,shutil
ROOT=pathlib.Path(__file__).resolve().parents[3]
BASE=ROOT/'docs/repair-2026-10-10/full-f-rerun';OUT=BASE/'efficient-resume-20261012/concurrency-four'
BUN='C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe'
def read(p):return json.loads(p.read_bytes())
def save(p,d):
 tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,indent=2)+'\n',encoding='utf8');os.replace(tmp,p)
def pin(p):
 b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def ps(command):return subprocess.check_output(['powershell','-NoProfile','-NonInteractive','-Command',command],text=True,creationflags=subprocess.CREATE_NO_WINDOW)
def identity(pid):
 raw=ps("Get-CimInstance Win32_Process -Filter 'ProcessId="+str(pid)+"' | ForEach-Object { @{pid=$_.ProcessId;birthUtc=$_.CreationDate.ToUniversalTime().ToString('o');command=$_.CommandLine} } | ConvertTo-Json -Compress").strip()
 return json.loads(raw) if raw else None
staged=read(OUT/'staged.json');old=read(BASE/'control.json')['broker'];sb=read(BASE/'skillsbench/event-ready-scheduler-owner.json');tb=read(BASE/'terminal-bench/event-scheduler/process.json')
actors={role:identity(pid) for role,pid in [('broker',old['pid']),('skillsbench',sb['pid']),('terminal-bench',tb['pid'])]}
assert all(actors.values())
for key in ['brokerPin','sbPin','tbPin']:assert pin(pathlib.Path(staged[key]['path']))==staged[key]
state=dict(pid=os.getpid(),startedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),stage='waiting-for-natural-idle',targetFormalPerBench=4,preparationPerBench=8,previousPids={k:v['pid'] for k,v in actors.items()},interruptedTaskCount=0)
save(OUT/'activation.json',state)
try:
 while True:
  c=read(BASE/'control.json');assert c['broker']['pid']==old['pid'],'broker_changed_by_another_owner'
  h=read(pathlib.Path(old['healthPath']));s=read(BASE/'skillsbench/event-ready-scheduler-owner.json');ss=read(pathlib.Path(s['folder'])/'state.json');t=read(BASE/'terminal-bench/event-scheduler/process.json')
  assert s['pid']==actors['skillsbench']['pid'] and t['pid']==actors['terminal-bench']['pid'],'scheduler_changed_by_another_owner'
  busy=dict(resources=len(h.get('resourceSlots',[])),activeRequests=h['activeRequests'],queuedRequests=h['queuedRequests'],openLanes=sum(not x['closed'] for x in h['lanes']),sbTasks=len(ss.get('activeTasks',[])),sbPreparing=len(ss.get('preparationContinuations',[])),tbJobs=sum(j['state'] in ('running','queued') for j in t['jobs'].values()))
  state.update(observedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),busy=busy);save(OUT/'activation.json',state)
  if not any(busy.values()) and not h.get('canonicalOwner'):break
  time.sleep(10)
 for role in ['skillsbench','terminal-bench']:
  assert identity(actors[role]['pid'])==actors[role],role+'_identity_changed'
  ps('Stop-Process -Id '+str(actors[role]['pid'])+' -Force')
  assert identity(actors[role]['pid']) is None
 # Recheck after retiring only the empty schedulers; no producer can race this gap.
 h=read(pathlib.Path(old['healthPath']));assert not h['activeRequests'] and not h['queuedRequests'] and not h['resourceSlots'] and all(x['closed'] for x in h['lanes']) and not h.get('canonicalOwner')
 assert not (ROOT/'.phase1-data/owned-paid-campaign.lock.json').exists(),'canonical_owner_not_released'
 assert identity(old['pid'])==actors['broker']
 shutil.copy2(BASE/'control.json',OUT/'control-before-switch.json');shutil.copy2(pathlib.Path(old['healthPath']),OUT/'closed-broker-health.json')
 ps('Stop-Process -Id '+str(old['pid'])+' -Force');assert identity(old['pid']) is None
 c=read(BASE/'control.json');c['brokerHistory'].append(dict(pid=old['pid'],runId=old['runId'],healthPath=old['healthPath'],closedHealthPin=pin(OUT/'closed-broker-health.json'),reason='human requested four formal tasks per bench; all lanes and resources naturally closed'));c['paidReady']=False;save(BASE/'control.json',c)
 def launch(role,entry,args=[]):
  with (OUT/(role+'.stdout')).open('xb') as stdout,(OUT/(role+'.stderr')).open('xb') as stderr:
   p=subprocess.Popen([BUN,'run',entry,*args],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
  return p.pid
 newbroker=launch('broker',staged['brokerPin']['path'])
 for _ in range(60):
  c=read(BASE/'control.json')
  if c['broker']['pid']==newbroker and c['paidReady']:break
  time.sleep(1)
 else:raise RuntimeError('new_broker_publication_failed')
 h=read(pathlib.Path(c['broker']['healthPath']));assert h['healthy'] and h['perBenchHeavySlots']==12 and h['perBenchLimits']['skillsbench']==4 and h['perBenchLimits']['terminal-bench']==4
 p=BASE/'skillsbench/parallel-eight-runtime-publication.json';d=read(p);shutil.copy2(p,OUT/'sb-publication-before.json');d.update(sharedBrokerRunId=c['broker']['runId'],sharedBrokerPid=newbroker,currentSharedSourcePins=c['broker']['sourcePins'],sharedSourcePins=c['broker']['sourcePins']);save(p,d)
 p=BASE/'efficient-resume-20261012/dispatch-policy.json';d=read(p);d.update(formalPerBench=4,preparationPerBench=8,totalFormalLimit=8,resourceCapacityPerBench=12,updatedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat());save(p,d)
 p=BASE/'skillsbench/preparation-capacity-control.json';d=read(p);d.update(maxPreparationContinuations=8,readyCandidateCapacityTarget=8,reason='human requested four formal and eight preparation slots per bench');save(p,d)
 newtb=launch('tb',staged['tbPin']['path'],['--run']);newsb=launch('sb',staged['sbPin']['path'])
 time.sleep(3);assert identity(newtb) and identity(newsb)
 state.update(stage='active-four-per-bench',completedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),newPids=dict(broker=newbroker,skillsbench=newsb,terminalBench=newtb),sourcePins=staged,interruptedTaskCount=0)
 save(OUT/'activation.json',state)
except BaseException as e:
 state.update(stage='switch-needs-attention',error=str(e));save(OUT/'activation.json',state);raise
