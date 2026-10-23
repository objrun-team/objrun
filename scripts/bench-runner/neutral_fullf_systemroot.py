"""Actual original fullF environment/Windows Docker CLI boundary, no task payload."""
import argparse,json,pathlib,os
import build_environment as original
from native_process import pin
from docker_owned import OwnedDocker
import _bench_original_owned_guard as guard
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
 assert _bench_authorized_history('zero-model-owned-sb-asset') is True
 assert os.environ.get('SYSTEMROOT') and original.ENV.get('SYSTEMROOT')==os.environ['SYSTEMROOT'] and original.ENV['DOCKER_HOST']==os.environ['DOCKER_HOST']
 guard.require_lease(2048,10737418240,'skillsbench',1)
 base='sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9';argv=[original.DOCKER,'image','inspect',base]
 previous=dict(original.ENV);previous.pop('SYSTEMROOT',None)
 bad=original.bounded_run(argv,previous,out/'original-whitelist.stdout',out/'original-whitelist.stderr',30)
 good=original.bounded_run(argv,original.ENV,out/'fixed-whitelist.stdout',out/'fixed-whitelist.stderr',30)
 assert good['exitCode']==0 and good['directChildClosed'] and good['pipeReadersClosed'] and not good['faults']
 inspected=json.loads((out/'fixed-whitelist.stdout').read_bytes());assert len(inspected)==1 and inspected[0]['Id']==base
 native=OwnedDocker(out/'native')
 try:
  cid,initial,create=native.create('neutral-fullf-systemroot',base,'/bin/sh',['-c','printf neutral-fullf-systemroot'],network='none',memory_mb=2048,cpus=1)
  start=native.start(cid,attach=True,timeout=30);assert native.text(start)=='neutral-fullf-systemroot';final=native.assert_actor(cid);assert final['State']['Status']=='exited' and final['State']['ExitCode']==0
  removal,absence=native.remove(cid)
 finally:
  for cid,role,name in native.open_actors():native.remove(cid)
  native.close()
 result=dict(complete=True,actualOriginalFullfEnv=True,systemRootKeyPreserved=True,originalDockerCliSuccess=True,originalWhitelistObservation=bad,fixedWhitelistObservation=good,oldMissingKeyFailureReproduced=bad['exitCode']!=0,actualOwnedActorRemoved=True,initial=initial,create=create,start=start,final=final,removal=removal,absence=absence,cliRawPins=[pin(out/name)for name in ['original-whitelist.stdout','original-whitelist.stderr','fixed-whitelist.stdout','fixed-whitelist.stderr']],noBenchContent=True,modelCalls=0,gradeCalls=0,referenceCalls=0)
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
