"""Real formal-parent/shared-lease financial policy fixture; no Bench contents or model requests."""
import argparse,json,pathlib,os,time
from native_process import pin,capture
from docker_owned import OwnedDocker
import _bench_original_owned_guard as guard
def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
 assert callable(globals().get('_bench_authorized_history')) and _bench_authorized_history('zero-model-owned-sb-asset') is True
 observed=guard.verify_activation();assert observed['financialBudgetMode']=='unlimited' and observed['monetaryCeilings'] is None
 assert observed['allocation']['capUsd'] is None
 root=pathlib.Path(guard.ROOT);bun=guard.BUN;cli=root/'scripts/bench-runner/financial-neutral-lane.ts'
 plan=json.loads(pathlib.Path(a.plan).read_bytes())['plan'];limit=json.loads((pathlib.Path(plan['output'])/'absolute-deadline.json').read_bytes())
 assert limit['pid']==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
 remaining=(limit['deadline']-time.time()*1000)/1000;assert remaining>0
 laneout=pathlib.Path(plan['financialLaneOutput']);assert laneout.resolve().is_relative_to(root/'docs/repair-2026-10-10/full-f-rerun/skillsbench')
 laneout.parent.mkdir(parents=True,exist_ok=True)
 child=capture([str(bun),'--smol',str(cli),a.plan,str(laneout)],out/'actual-financial-bun-child',min(120,remaining));assert child['closeObserved'] and child['exitCode']==0 and not child['timedOut']
 lane=json.loads((laneout/'result.json').read_bytes());assert lane['actualModelRequests']==0 and lane['cash']['financialBudgetMode']=='unlimited' and lane['cash']['capUsd'] is None and lane['laneClosure']['closed'] is True
 native=OwnedDocker(out/'native');cid=None
 try:
  cid,initial,created=native.create('neutral-explicit-unlimited-owned','sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9','/bin/sh',['-c','printf neutral-unlimited-custody'],network='none',memory_mb=2048,cpus=1)
  started=native.start(cid,attach=True,timeout=30);assert native.text(started)=='neutral-unlimited-custody';final=native.assert_actor(cid);assert final['State']['Status']=='exited' and final['State']['ExitCode']==0
  removal,absence=native.remove(cid);cid=None
 finally:
  for actor,role,name in native.open_actors():native.remove(actor)
  native.close()
 result=dict(complete=True,explicitUnlimitedActualParentChild=True,actualZeroRequestLaneClosed=True,actualCashNullCap=True,actorRemoved=True,initial=initial,create=created,start=started,final=final,removal=removal,absence=absence,financialChildPin=pin(out/'actual-financial-bun-child.json'),laneResultPin=pin(laneout/'result.json'),actualModelRequests=0,modelCalls=0,gradeCalls=0,referenceCalls=0,feeAllocationUsd=0,noBenchContent=True)
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
