"""No-Bench fixture: original guard calls and actor lifecycle in one actual owned lease."""
import argparse,ctypes,json,os,pathlib,time
import _bench_original_owned_guard as guard
from native_process import pin
from docker_owned import OwnedDocker

def birth(pid):
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.restype=ctypes.c_void_p;k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.CloseHandle.argtypes=[ctypes.c_void_p]
 class FT(ctypes.Structure):_fields_=[('lo',ctypes.c_ulong),('hi',ctypes.c_ulong)]
 h=k.OpenProcess(0x1000,False,pid)
 if not h:
  assert ctypes.get_last_error()==87,'persistent_fixture_process_identity_unknown';return None
 try:
  fields=[FT()for _ in range(4)];assert k.GetProcessTimes(ctypes.c_void_p(h),*[ctypes.byref(x)for x in fields]);return str(fields[0].lo+(fields[0].hi<<32))
 finally:k.CloseHandle(h)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);a=parser.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
 assert _bench_authorized_history('zero-model-owned-sb-asset')is True
 memory=int(os.environ['NOVAEVE_RESOURCE_MEMORY_MB']);growth=int(os.environ['NOVAEVE_RESOURCE_GROWTH_BYTES']);bench=os.environ['NOVAEVE_RESOURCE_BENCH'];leasePid=os.environ['NOVAEVE_RESOURCE_LEASE_PID'];token=os.environ['NOVAEVE_RESOURCE_TOKEN']
 assert memory==2048 and growth==10737418240 and bench=='skillsbench'and int(leasePid)!=os.getpid()
 channel=guard._bench_guard_bridge;checks=[];native=None
 def valid(label):
  start=time.monotonic();v=guard.require_lease(memory,growth,bench,1);assert v['verified']and v['resourceLeasePid']==int(leasePid);checks.append(dict(check=label,passed=True,elapsedSeconds=time.monotonic()-start));return v
 def rejected(label):
  try:guard.require_lease(memory,growth,bench,1);raise AssertionError('persistent_fixture_original_lease_guard_not_enforced')
  except RuntimeError as e:assert str(e)=='actual_live_new_resource_lease_required';checks.append(dict(check=label,passed=True,actualError=str(e)))
 try:
  valid('actual-current-owned-lease')
  times=[]
  for label,call in [('before_forward_guard',guard.before_forward_guard),('guard',guard.guard),('require_lease',lambda:guard.require_lease(memory,growth,bench,1))]:
   start=time.monotonic();call();times.append(dict(check=label,elapsedSeconds=time.monotonic()-start,originalFreshCallPreserved=True))
  os.environ['NOVAEVE_RESOURCE_TOKEN']='neutral-current-token-negative';rejected('wrong-current-token-same-persistent-child');os.environ['NOVAEVE_RESOURCE_TOKEN']=token;valid('actual-token-restored')
  os.environ['NOVAEVE_RESOURCE_LEASE_PID']=str(os.getpid());rejected('foreign-child-not-resource-owner');os.environ['NOVAEVE_RESOURCE_LEASE_PID']=leasePid;valid('actual-owner-restored')
  native=OwnedDocker(out/'native');cid,initial,created=native.create('neutral-persistent-readonly-guard','sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9','/bin/sh',['-c','printf persistent-readonly-guard-fixture'],network='none',memory_mb=2048,cpus=1)
  started=native.start(cid,attach=True,timeout=30);assert native.text(started)=='persistent-readonly-guard-fixture'
  final=native.assert_actor(cid);assert final['State']['Status']=='exited'and final['State']['ExitCode']==0
  removed,absence=native.remove(cid)
 finally:
  os.environ['NOVAEVE_RESOURCE_TOKEN']=token;os.environ['NOVAEVE_RESOURCE_LEASE_PID']=leasePid
  if native is not None:
   for cid,role,name in native.open_actors():native.remove(cid)
   native.close()
  channel.close_channel()
 config=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes());directory=pathlib.Path(config['childEvidenceRoot'])/'persistent-readonly-guard';closes=[]
 for path in directory.glob(str(os.getpid())+'-*.close.json'):
  value=json.loads(path.read_bytes());assert value['closeObserved']and value['exitCode']==0 and not value['intentionalKill']and not value['readerError']and value['stdoutReaderClosed']and value['stderrReaderClosed']
  current=birth(value['pid']);assert current!=value['incarnation'];closes.append(dict(closurePin=pin(path),originalPid=value['pid'],originalIncarnation=value['incarnation'],currentIncarnation=current,originalProcessAbsent=True))
 assert len(closes)==1,'single_original_persistent_channel_required'
 result=dict(complete=True,noBenchContent=True,modelCalls=0,referenceCalls=0,gradeCalls=0,originalThreeFreshGuardCalls=times,checks=checks,wrongCurrentTokenRejected=True,foreignResourceOwnerRejected=True,validTokenAndOwnerRestored=True,actualOwnedActorRemoved=True,initial=initial,create=created,start=started,final=final,removal=removed,absence=absence,persistentProcessClosures=closes,revokedLeaseAfterParentReleaseTested=False,laneAdmissionUnchanged=True)
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
if __name__=='__main__':main()
