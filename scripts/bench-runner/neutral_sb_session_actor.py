"""No Bench content: verify a caller-owned SB lease and one real neutral actor."""
import argparse,json,os,pathlib,uuid,urllib.request,urllib.error
import _bench_original_owned_guard as guard
from skillsbench_original_stand import Stand
p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--output',required=True);a=p.parse_args()
plan=json.loads(pathlib.Path(a.plan).read_bytes())['plan'];out=pathlib.Path(a.output);out.mkdir(parents=True)
guard.require_lease(8192,3221225472,'skillsbench',1);_bench_authorized_history('spring-boot-jakarta-migration')
native=Stand({'output':str(out),'runId':plan['neutralRunId'],'schedule':[],'taskReadiness':{},'resourceOwnerPid':int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])});cid=None;result={'complete':False,'modelCalls':0,'gradeCalls':0}
try:
 nonce=uuid.uuid4().hex
 cid=native.command(['create','--network','none','--memory','4096m','--cpus','1','--label','objrun.skb.role=full-f-solver','--label','objrun.skb.nonce='+nonce,plan['baseImageId'],'/bin/sh','-c','sleep 180']).decode().strip()
 native.current={'cid':cid};native.command(['start',cid]);raw=native.command(['exec',cid,'/bin/sh','-c',"printf 'neutral-shared-session\\n'"]).decode();assert raw.strip()=='neutral-shared-session'
 result.update(complete=True,cid=cid,actualExecution=raw)
finally:
 if cid:
  result['originalClosure']=native.stop()
  try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/containers/'+cid+'/json',timeout=5);raise AssertionError('actor_present')
  except urllib.error.HTTPError as error:assert error.code==404
  result.update(actorClosed=True,currentActorStatus=404)
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
