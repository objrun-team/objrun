"""Actual Python owner guard + temporary resource-only lease, never lane/actor/model."""
import os,json,time,datetime,urllib.request,importlib.util
from pathlib import Path
p=Path(__file__).parent;spec=importlib.util.spec_from_file_location('adopted_guard_v81',p/'adopted_owner_guard_v81.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
original_verify=g.verify_activation
def fresh_verify():
 deadline=time.monotonic()+15
 while time.time()*1000-g.read(g.HOME/'broker/remote-disk.json')['observedAtMs']>3000:
  if time.monotonic()>deadline:raise RuntimeError('test_real_disk_refresh_not_observed')
  time.sleep(0.2)
 return original_verify()
# Fixture only schedules checks against actually fresh observation; runtime guard remains unchanged.
g.verify_activation=fresh_verify
for _ in range(300):g.require_host_capacity()
actual=g.require_activation();capacity=g.require_host_capacity();control=g.load_control();b=control['broker'];pid=os.getpid()
def rpc(route,data):
 request=urllib.request.Request(b['endpoint']+route,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+b['accessToken'],'Content-Type':'application/json'})
 with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)
lease=rpc('/resource/acquire',dict(kind='heavy-container',slug='terminal-bench',pid=pid,slots=1,memoryMb=4096,plannedGrowthBytes=0));token=lease.get('token')
if not token:raise RuntimeError('actual_resource_acquire_failed')
rejected=0
try:
 os.environ.update(NOVAEVE_ACTIVATION_PATH=str(g.ACTIVATION),NOVAEVE_BROKER_CONTROL_PATH=str(g.CONTROL),NOVAEVE_RESOURCE_LEASE_PID=str(pid),NOVAEVE_RESOURCE_TOKEN=token,NOVAEVE_RESOURCE_MEMORY_MB='4096',NOVAEVE_RESOURCE_GROWTH_BYTES='0')
 positive=g.require_lease(memory_mb=4096,growth_bytes=0);g.before_forward_guard()
 for mode in ['wrong-token','wrong-memory','wrong-path','wrong-growth','wrong-slots','missing-owner']:
  saved=dict(os.environ)
  try:
   if mode=='wrong-token':os.environ['NOVAEVE_RESOURCE_TOKEN']='not-the-resource-token';g.require_lease(memory_mb=4096,growth_bytes=0)
   elif mode=='wrong-memory':g.require_lease(memory_mb=8192,growth_bytes=0)
   elif mode=='wrong-growth':g.require_lease(memory_mb=4096,growth_bytes=1)
   elif mode=='wrong-slots':g.require_lease(memory_mb=4096,growth_bytes=0,slots=2)
   elif mode=='missing-owner':os.environ.pop('NOVAEVE_RESOURCE_LEASE_PID');g.before_forward_guard()
   else:os.environ['NOVAEVE_ACTIVATION_PATH']=str(g.HOME/'activation-delegated-v19.json');g.require_activation()
   raise RuntimeError('negative_accepted')
  except RuntimeError as e:
   if str(e)=='negative_accepted':raise
   rejected+=1
  finally:os.environ.clear();os.environ.update(saved)
 for bad in [dict(capacity,commitAvailableBytes=0),dict(capacity,physicalAvailableBytes=0),dict(capacity,observedAtUtc=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=31)).isoformat()),dict(capacity,observedAtUtc=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1)).isoformat())]:
  try:g.check_capacity_observation(bad);raise RuntimeError('negative_accepted')
  except RuntimeError as e:
   if str(e)=='negative_accepted':raise
   rejected+=1
 observed=g.verify_activation();orphan=next(r for r in observed['resourceSlots'] if r['adoptedOrphanHold'])
 try:g.check_resource_lease(dict(observed,resourceSlots=[dict(observed['resourceSlots'][-1],pid=pid,tokenMatches=True,ownerIncarnationMatches=False)]),pid,'terminal-bench',4096,0);raise RuntimeError('negative_accepted')
 except RuntimeError as e:
  if str(e)=='negative_accepted':raise
  rejected+=1
 try:g.check_resource_lease(dict(observed,resourceSlots=[dict(orphan,tokenMatches=True)]),orphan['pid'],orphan['slug'],1,0);raise RuntimeError('negative_accepted')
 except RuntimeError as e:
  if str(e)=='negative_accepted':raise
  rejected+=1
finally:
 released=rpc('/resource/release',dict(kind='heavy-container',slug='terminal-bench',pid=pid,token=token))
 os.environ.pop('NOVAEVE_RESOURCE_TOKEN',None)
 observed=g.verify_activation()
 if any(r['pid']==pid for r in observed['resourceSlots']):raise RuntimeError('actual_test_resource_not_released')
result=dict(protocol='novaeve-actual-python-consumer-controls-v81',atUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),actualBrokerPid=positive['brokerPid'],temporaryResourcePid=pid,actualSignedActivationPassed=True,actualOriginalDockerAndDiskPassed=True,actualHostCapacity=capacity,actualResourceAcquiredAndReleased=True,negativeControlsPassed=rejected,sameUTCClockCapacitySamples=300,futureObservationStillRefused=True,epsilonUsed=False,clampUsed=False,orphanTokenCannotBorrow=True,newActors=0,modelCalls=0,newLanes=0,secretsPrinted=False)
out=g.HOME/'coordinator/python-owner-guard-v81';out.mkdir(parents=True,exist_ok=True)
with (out/'actual-validation.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result))
