"""Independent fixture through the original SB Transport and bounded child code."""
import argparse,json,os,pathlib,uuid
from original_sb_pipeline import Transport
from original_sb_transport import require_original_lease,collect_bounded_command_evidence
from native_process import pin
p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
resources={'environment':{'memory_mb':4096,'cpus':2,'storage_mb':10240}};owner=os.getppid();lease=require_original_lease(owner,resources)
try:require_original_lease(-1,resources);raise RuntimeError('invalid_owner_accepted')
except AssertionError:owner_rejected=True
try:require_original_lease(owner,{'environment':{'memory_mb':8192,'cpus':2,'storage_mb':10240}});raise RuntimeError('undersized_aggregate_accepted')
except AssertionError:resource_rejected=True
home=out/'commands';home.mkdir();t=Transport(home,owner,resources);cid=None
try:
 identity=json.loads(t.command(['image','inspect','sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9']))[0];assert identity['Id']=='sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9'
 cid=t.command(['create','--name','neutral-sb-bounded-'+uuid.uuid4().hex,'--label','bench-neutral=true','--memory',str(4096*1024**2),'--cpus','2','--network','none','--entrypoint','/bin/sh',identity['Id'],'-c','sleep 600']).decode().strip()
 t.command(['start',cid]);t.command(['exec',cid,'/bin/mkdir','/neutral']);t.command(['cp',a.input,cid+':/neutral/input.txt'])
 digest=t.command(['exec',cid,'sha256sum','/neutral/input.txt']).decode().split()[0];assert digest==pin(a.input)['sha256']
 output=t.command(['exec',cid,'/bin/sh','-c','test "$(cat /neutral/input.txt)" = "neutral-sb-bounded-fixture" && printf "neutral-run-ok\n"']).decode();assert output=='neutral-run-ok\n'
 try:t.command(['exec',cid,'/bin/sh','-c','printf "intentional-neutral-error\n" >&2; exit 7']);raise AssertionError('original_transport_negative_did_not_raise')
 except RuntimeError:
  negative=json.loads(t.last.with_suffix('.json').read_bytes());assert negative['exitCode']==7 and not negative['faults'];assert t.last.with_suffix('.stderr').read_text()=='intentional-neutral-error\n'
finally:
 if cid:t.command(['rm','-f',cid])
evidence=collect_bounded_command_evidence(out);result={'complete':True,'neutralContentOnly':True,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'actorClosed':True,'policyLeaseBinding':lease,'invalidOwnerRejected':owner_rejected,'undersizedAggregateRejected':resource_rejected,'actualGuestSha256':digest,'inputPin':pin(a.input),'actualRunOutput':output,'negativeExitCode':negative['exitCode'],'originalBoundedEvidence':evidence}
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
