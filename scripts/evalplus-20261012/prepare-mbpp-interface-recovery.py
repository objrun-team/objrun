"""Prepare an MBPP-only recovery pass; no model calls or changes to scoring/core."""
import argparse, datetime, hashlib, json, re, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/evalplus-20261012'
MBPP=BASE/'mbpp'
OUT=MBPP/'objrun-adapter-v1/full'
AUTHORITY='2026-10-12 user: 接口异常问题也需要修复啊 单独跑接口异常的题'

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=True,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
def within(p,out):
 p=p.resolve()
 if not p.is_relative_to(out.resolve()): raise RuntimeError('RecoveryPathOutsideResultRoot:'+str(p))
 return p
def transient(r):
 if not r:return False
 return r.get('fault')=='ExplicitRateLimit' or r.get('httpStatus') in [408,500,502,503,504] or (
  r.get('httpStatus') in [0,200] and re.search(r'socket.*closed|connection.*closed|connection reset|network connection lost|ECONNRESET|ECONNREFUSED|ETIMEDOUT|fetch failed|timed? out|timeout',str(r.get('fault','')),re.I))

def owned(row,engines):
 if row.get('Name','').lower()!='bun.exe':return False
 cmd=row.get('CommandLine') or ''
 if re.search(r'run-mbpp-(objrun-adapter|interface-recovery)\.ts',cmd):return True
 for e in engines:
  if e['pid']!=row['ProcessId']:continue
  if not row.get('CreationUtc') or not cmd:return True
  born=datetime.datetime.fromisoformat(row['CreationUtc'].replace('Z','+00:00'))
  saved=datetime.datetime.fromisoformat(e['atUtc'].replace('Z','+00:00'))
  if born<=saved and str(ROOT/'app/src/main.ts').replace('/','\\').lower() in cmd.replace('/','\\').lower():return True
 return False

def process_snapshot(out):
 paths=[out/'status.json',out/'launch.json',out/'runner-lock.json',*out.glob('tasks/objrun/*/engine-process.json')]
 ids=set();engines=[]
 for p in paths:
  if p.exists():
   r=read(p)
   if r.get('pid'):
    ids.add(int(r['pid']))
    if p.name=='engine-process.json':engines.append(r)
 literal=','.join(str(i) for i in sorted(ids)) or '0'
 cmd="@(Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -in @("+literal+") -or ($_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-mbpp-(objrun-adapter|interface-recovery)\\.ts')} | Select-Object ProcessId,Name,@{Name='CreationUtc';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}},CommandLine) | ConvertTo-Json -Compress"
 result=subprocess.run(['powershell.exe','-NoProfile','-Command',cmd],check=True,capture_output=True,text=True,encoding='utf-8',errors='replace').stdout.strip()
 rows=json.loads(result) if result else []
 if isinstance(rows,dict):rows=[rows]
 return {'live':[r for r in rows if owned(r,engines)],'ignoredReusedProcesses':[r for r in rows if not owned(r,engines)]}

def verify_pins(pin):
 value=read(pin)
 for r in value if isinstance(value,list) else value['files']:
  p=Path(r['path'])
  if not p.is_file() or sha(p)!=r['sha256']:raise RuntimeError('FrozenSourceChanged:'+str(p))

def make_plan(out,scope,live):
 rows=[(p,read(p)) for p in sorted((out/'results/objrun').glob('*.json'))]
 expected=scope['fullTaskIds'];targets=set(scope['taskIds'])
 guards=[]
 if live:guards.append('OwnedRunnerOrEngineStillLive')
 if sorted(r['officialId'] for _,r in rows)!=sorted(expected):guards.append('IncompleteOrDuplicateFixedTaskList')
 for p in (out/'calls').rglob('dispatch.json'):
  if (p.parent/'receipt.json').exists():continue
  disp=p.parent/'dispatch-disposition.json'
  if not disp.exists() or read(disp).get('state')!='interrupted_no_response' or not read(disp).get('ownerExited'):
   guards.append('UnreconciledDispatch:'+str(p))
 plan={'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'resultRoot':str(out),'guards':guards,'liveProcesses':live,'targets':[],'blockedTasks':[],'validResultsUntouched':sum(bool(r.get('grade',{}).get('valid')) for _,r in rows)}
 for p,r in rows:
  if r['officialId'] not in targets:
   if not r.get('grade',{}).get('valid'):guards.append('InvalidTaskOutsideAuthorizedScope:'+r['officialId'])
   continue
  if r.get('grade',{}).get('valid'):continue
  short=r['officialId'].replace('/','-')
  if not re.fullmatch(r'Mbpp/\d+',r['officialId']) or p.name!=short+'.json':raise RuntimeError('UnexpectedIdentity:'+str(p))
  t={'officialId':r['officialId'],'resultPath':str(p),'resultSha256':sha(p)}
  if 'answer' in r:
   if r.get('candidateHow')!='submitted':plan['blockedTasks'].append({'officialId':r['officialId'],'reason':'NonNativeCandidate'});continue
   t['action']='regrade_existing_candidate';plan['targets'].append(t);continue
  if not r.get('interfaceFailure'):
   plan['blockedTasks'].append({'officialId':r['officialId'],'reason':'NonInterfaceFailure'});continue
  calls=out/'calls/objrun'/short;failed=[]
  for group in sorted((calls/'schema-v3').glob('*/attempt-*')):
   paths=[group,*sorted(group.glob('authorized-interface-retry-*'))]
   terminal=paths[-1];receipt=read(terminal/'receipt.json') if (terminal/'receipt.json').exists() else None
   disp=read(terminal/'dispatch-disposition.json') if (terminal/'dispatch-disposition.json').exists() else {}
   interrupted=(terminal/'dispatch.json').exists() and not receipt and disp.get('state')=='interrupted_no_response' and disp.get('ownerExited')
   if transient(receipt) or interrupted:failed.append(str(group))
  # Native HTTP timeout after successfully cached provider responses can be
  # recovered without another paid request. Failed request groups stay archived.
  if failed or r.get('nativeInterfaceTimeout'):
   t.update(action='retry_interface_task',failedRequestGroups=failed);plan['targets'].append(t)
  else:plan['blockedTasks'].append({'officialId':r['officialId'],'reason':'NoDiagnosedRecoverableInterfaceFailure'})
 return plan

def apply_plan(out,plan):
 if plan['guards'] or plan['blockedTasks']:raise RuntimeError('RecoveryNotSafe:'+json.dumps(plan['guards']+plan['blockedTasks']))
 n=1
 while (out/'recovery'/('interface-pass-%04d.json'%n)).exists():n+=1
 label='interface-pass-%04d'%n
 record={**plan,'round':n,'label':label,'state':'preparing','moves':[],'authorizedBy':AUTHORITY,'unknownOldCostsRetained':True,'coreModified':False,'scoringChanged':False}
 if not plan['targets']:return {**record,'state':'no_action','launchRequired':False}
 moves=[]
 for t in plan['targets']:
  short=t['officialId'].replace('/','-');task=out/'tasks/objrun'/short;calls=out/'calls/objrun'/short;history=task/'retained-recovery'/label
  if sha(Path(t['resultPath']))!=t['resultSha256']:raise RuntimeError('ResultChangedBeforePreparation')
  if t['action']=='regrade_existing_candidate':continue
  for name in ['engine','engine-process.json','trace.json','submit-response-attempts.json','candidate.json','native-interface-evidence.json']:
   source=task/name
   if source.exists():moves.append((source,history/name))
  for source in t['failedRequestGroups']:
   source=Path(source);moves.append((source,calls/'retained-recovery'/label/source.relative_to(calls)))
  # Keep the original result until the replacement is complete: all 378 IDs
  # remain represented during recovery. The old invalid result is also archived.
  save(history/'result.json',read(Path(t['resultPath'])))
 for source,dest in moves:
  within(source,out);within(dest,out)
  if not source.exists() or dest.exists():raise RuntimeError('RecoveryMovePreconditionChanged:'+str(source))
  record['moves'].append({'source':str(source),'destination':str(dest)})
 record_path=within(out/'recovery'/(label+'.json'),out);save(record_path,record)
 for source,dest in moves:
  dest.parent.mkdir(parents=True,exist_ok=True);source.rename(dest)
 stop=out/'stop-after-current-tasks.json'
 if stop.exists():stop.rename(out/'recovery'/(label+'-prior-stop.json'))
 record.update(state='ready',launchRequired=True);save(record_path,record);save(out/'recovery/active-pass.json',{'path':str(record_path),'round':n,'label':label})
 return record

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--apply',action='store_true');ap.add_argument('--check-ready',action='store_true');a=ap.parse_args()
 for p in [BASE/'source-pins.json',MBPP/'objrun-adapter-v1-source-pins.json',MBPP/'interface-recovery-source-pins.json',MBPP/'diagnosis/interface-recovery-retention-pins.json',MBPP/'diagnosis/baseline-retention-pins.json']:verify_pins(p)
 proc=process_snapshot(OUT)
 if a.check_ready:
  if proc['live']:raise RuntimeError('OwnedRunnerOrEngineStillLive')
  active=read(OUT/'recovery/active-pass.json');record=read(Path(active['path']))
  if record['state']!='ready':raise RuntimeError('PassNotReady')
  print(json.dumps({'state':'ready','round':record['round'],'targetCount':len(record['targets']),'live':proc['live']}));return
 plan=make_plan(OUT,read(MBPP/'interface-recovery-scope.json'),proc['live']);plan.update(ignoredReusedProcesses=proc['ignoredReusedProcesses'])
 result=apply_plan(OUT,plan) if a.apply else {**plan,'dryRun':True}
 print(json.dumps(result,ensure_ascii=True,indent=2))
if __name__=='__main__':main()
