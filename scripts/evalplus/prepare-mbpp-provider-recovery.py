"""MBPP-only provider recovery: original runners and core stay frozen."""
import argparse,datetime,importlib.util,json,re,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('mbpp_old_recovery',Path(__file__).with_name('prepare-mbpp-interface-recovery.py'))
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
ROOT=old.ROOT;MBPP=old.MBPP;OUT=old.OUT
AUTHORITY='2026-10-12 user: 供应商可以多换几个试下，不要换到有量化的就行了；精度未知的也能用'

def process_snapshot():
 engines=[old.read(p) for p in OUT.glob('tasks/objrun/*/engine-process.json')]
 ids={int(e['pid']) for e in engines}
 for name in ['status.json','launch.json','runner-lock.json']:
  p=OUT/name
  if p.exists() and old.read(p).get('pid'):ids.add(int(old.read(p)['pid']))
 literal=','.join(str(i) for i in sorted(ids)) or '0'
 command="@(Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -in @("+literal+") -or ($_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-mbpp-(objrun-adapter|interface-recovery|provider-recovery)\\.ts')} | Select-Object ProcessId,Name,@{Name='CreationUtc';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}},CommandLine) | ConvertTo-Json -Compress"
 raw=subprocess.run(['powershell.exe','-NoProfile','-Command',command],check=True,capture_output=True,text=True,encoding='utf-8',errors='replace').stdout.strip()
 rows=json.loads(raw) if raw else []
 if isinstance(rows,dict):rows=[rows]
 is_owned=lambda row:old.owned(row,engines) or (row.get('Name','').lower()=='bun.exe' and re.search(r'run-mbpp-provider-recovery\.ts',row.get('CommandLine') or ''))
 return {'live':[r for r in rows if is_owned(r)],'ignoredReusedProcesses':[r for r in rows if not is_owned(r)]}

def make_plan(live):
 scope=old.read(MBPP/'interface-recovery-scope.json');plan=old.make_plan(OUT,scope,live)
 active=old.read(OUT/'recovery/active-pass.json');previous=old.read(Path(active['path']))
 previous_targets={t['officialId']:t for t in previous['targets']};blocked=[]
 for b in plan['blockedTasks']:
  tid=b['officialId'];short=tid.replace('/','-');p=OUT/'results/objrun'/(short+'.json');r=old.read(p)
  t=previous_targets.get(tid)
  unattempted=(previous.get('state')=='stopped' and t and t['resultSha256']==old.sha(p) and not (OUT/'tasks/objrun'/short/'engine').exists())
  provider_failed=[]
  for group in (OUT/'calls/objrun'/short/'schema-v3').glob('*/attempt-*'):
   attempts=list(group.glob('provider-*'))
   if attempts and all((x/'receipt.json').exists() and (old.transient(old.read(x/'receipt.json')) or (old.read(x/'receipt.json').get('httpStatus')==404 and re.search(r'endpoint|provider|route',str(old.read(x/'receipt.json').get('fault')),re.I))) for x in attempts):provider_failed.append(str(group))
  if r.get('interfaceFailure') and (unattempted or provider_failed):
   plan['targets'].append({'officialId':tid,'resultPath':str(p),'resultSha256':old.sha(p),'action':'retry_interface_task','failedRequestGroups':provider_failed,'unattemptedBecauseOfGracefulStop':bool(unattempted)})
  else:blocked.append(b)
 plan['blockedTasks']=blocked
 return plan

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--apply',action='store_true');ap.add_argument('--check-ready',action='store_true');a=ap.parse_args()
 for pin in [old.BASE/'source-pins.json',MBPP/'objrun-adapter-v1-source-pins.json',MBPP/'interface-recovery-source-pins.json',MBPP/'provider-recovery-source-pins.json',MBPP/'diagnosis/interface-recovery-round2-valid-retention.json',MBPP/'diagnosis/baseline-retention-pins.json']:old.verify_pins(pin)
 cfg=old.read(MBPP/'provider-recovery-config.json');proc=process_snapshot()
 if a.check_ready:
  if proc['live']:raise RuntimeError('OwnedRunnerOrEngineStillLive')
  active=old.read(OUT/'recovery/active-pass.json');record=old.read(Path(active['path']))
  if record.get('state')!='ready' or record.get('providerRecoveryVersion')!=cfg['version']:raise RuntimeError('ProviderPassNotReady')
  print(json.dumps({'state':'ready','round':record['round'],'targets':len(record['targets'])}));return
 plan=make_plan(proc['live']);plan.update(providerRecoveryVersion=cfg['version'],ignoredReusedProcesses=proc['ignoredReusedProcesses'])
 if not a.apply:print(json.dumps({**plan,'dryRun':True},indent=2));return
 past=[old.read(p) for p in (OUT/'recovery').glob('interface-pass-*.json') if not p.name.endswith('-prior-stop.json')]
 count=sum(r.get('providerRecoveryVersion')==cfg['version'] for r in past)
 if count>=cfg['maxProviderPasses'] and plan['targets']:raise RuntimeError('FiniteProviderRecoveryPassesExhausted')
 result=old.apply_plan(OUT,plan)
 if result.get('launchRequired'):
  result.update(providerRecoveryVersion=cfg['version'],providerPhaseRound=count+1,authorizedBy=AUTHORITY,providers=cfg['providers'],taskPrimaryProviders=cfg['taskPrimaryProviders'])
  path=Path(old.read(OUT/'recovery/active-pass.json')['path']);old.save(path,result)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
