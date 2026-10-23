"""No-Bench original shared session plus real caller-owned Docker actor."""
import argparse,json,pathlib,os,time
from native_process import pin,capture
from docker_owned import OwnedDocker
import _bench_original_owned_guard as guard
p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args();request=pathlib.Path(a.request);r=json.loads(request.read_bytes());out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
assert callable(globals().get('_bench_authorized_history')) and _bench_authorized_history('zero-model-owned-sb-asset') is True
guard.require_lease(8192,10737418240,'skillsbench',1)
limit=json.loads(pathlib.Path(r['parentDeadlinePath']).read_bytes());assert limit['pid']==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
remaining=limit['deadline']/1000-time.time();assert 0<remaining<=600
child_env=dict(os.environ);child_env['NOVAEVE_INFRASTRUCTURE_DEADLINE_MS']=str(limit['deadline'])
row=capture([r['bunPin']['path'],r['entryPin']['path'],str(request),pin(request)['sha256'],r['sessionOutput']],out/'session-process',remaining,env=child_env,cwd=r['root'])
assert row['closeObserved'] and row['exitCode']==0 and not row['timedOut'] and not row['error'],'neutral_actual_session_child_failed'
session=json.loads((pathlib.Path(r['sessionOutput'])/'result.json').read_bytes());assert session['complete']
native=OwnedDocker(out/'native')
try:
 cid,initial,create=native.create('neutral-shared-sb-engine-no-task','sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9','/bin/sh',['-c','printf neutral-common-sb-session'],network='none',memory_mb=4096,cpus=2)
 start=native.start(cid,attach=True,timeout=30);assert native.text(start)=='neutral-common-sb-session';final=native.assert_actor(cid);assert final['State']['ExitCode']==0;removal,absence=native.remove(cid)
finally:
 for cid,role,name in native.open_actors():native.remove(cid)
 native.close()
(out/'result.json').write_text(json.dumps(dict(complete=True,actorClosed=True,actualSessionProcess=row,sessionResultPin=pin(pathlib.Path(r['sessionOutput'])/'result.json'),actualOriginalEngineZeroModelTasks=True,actualSharedCashLaneZeroRequests=True,initial=initial,create=create,start=start,final=final,removal=removal,absence=absence,modelCalls=0,gradeCalls=0,referenceCalls=0,noBenchContent=True,formalReady=False),indent=2)+'\n')
