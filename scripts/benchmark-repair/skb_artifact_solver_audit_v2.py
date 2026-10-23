"""Independent native command, exact solver ownership and stopped capture replay."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_transport_v2 as transport
import skb_artifact_solver_plan_v2 as plan_source
import skb_artifact_ram_executor_v2 as ram
import skb_artifact_capture_v2 as capture
import skb_artifact_native_identity_v2 as native


def validate_solver_closed(descriptor_pin,closure_pin,require_actor_closed=True,require_capture=True):
    d=task.read_json(descriptor_pin);task.validate_descriptor(d,True)
    c=task.read_json(closure_pin);box=Path(closure_pin['path']).parent
    task.demand(c['protocol']=='skillsbench-task-owned-solver-execution-v2' and c['taskDescriptorPin']==descriptor_pin
        and c['taskId']==d['taskId'] and c['ownedClosed'] is True and c['fault'] is None
        and c['instanceNonce']==box.name.removeprefix('solver-'),'solver_audit','Complete exact owned solver closure required')
    p=task.read_json(c['solverPlanPin']);expected=plan_source.plan(d,c['instanceNonce']);caps=[]
    if not require_capture and p.get('coldOriginalShellCapabilities'):
        caps=['CHOWN','DAC_OVERRIDE','FOWNER','SETGID','SETUID'];argv=expected['createArgv'].copy();at=argv.index(expected['imageId'])
        argv[at:at]=[part for cap in caps for part in ('--cap-add',cap)];expected={**expected,'createArgv':argv,'coldOriginalShellCapabilities':caps}
    task.demand(p==expected,'solver_audit_plan','Executed solver plan differs from original task/resource/runtime or exact separate cold shell capability delta')
    for pair in c['sourceSnapshots']:
        task.verify_pin(pair['snapshotPin'])
        if require_capture or Path(pair['originalPin']['path']).name!='skb-ten-original-shell-v2.py':task.verify_pin(pair['originalPin'])
        task.demand(pair['snapshotPin']['sha256']==pair['originalPin']['sha256'],'solver_audit_source','Executed byte snapshot differs')
    rows=[]
    for i,e in enumerate(c['commandRecords'],1):
        task.demand(e['argv'][:3]==[str(transport.DOCKER),'--host',transport.DOCKER_HOST],'solver_audit_client','Exact Docker client/daemon required')
        r=transport.validate_command_record(e['recordPin'],c['actorPid'],i,e['argv'],box,e['maximumStdoutBytes'])
        if require_actor_closed:native.closed_identity(r['pid'],task.read_json(r['childPin'])['atUnixMs'])
        rows.append((e['argv'][3:],r))
    cid=c['containerID'];task.demand(isinstance(cid,str) and len(cid)==64,'solver_audit_cid','Exact actual CID required')
    made=[r for a,r in rows if a==p['createArgv']]
    removed=[r for a,r in rows if a==['rm','-f',cid]]
    absent=[r for a,r in rows if a==['container','inspect',cid] and ram.missing_target(r['exitCode'],Path(r['stdoutPin']['path']).read_bytes(),Path(r['stderrPin']['path']).read_bytes(),'container',cid)]
    task.demand(len(made)==len(removed)==len(absent)==1 and made[0]['exitCode']==removed[0]['exitCode']==0,'solver_audit_lifecycle','Actual create/remove/post-absence graph required')
    states=[]
    for a,r in rows:
        if a==['container','inspect','--size',cid] and r['exitCode']==0:
            x=json.loads(Path(r['stdoutPin']['path']).read_bytes())[0];h=x['HostConfig'];cfg=x['Config'];labels=cfg.get('Labels') or {}
            task.demand(x['Id']==cid and x['Name']=='/'+p['name'] and x['Image']==cfg['Image']==p['imageId']
                and labels.get('objrun.skb.instance-nonce')==p['instanceNonce'] and labels.get('objrun.skb.task-id')==d['taskId']
                and labels.get('objrun.skb.role')=='solver' and h['Memory']==h['MemorySwap']==p['memoryBytes'] and h['NanoCpus']==p['cpus']*10**9
                and h['NetworkMode']=='bridge' and not h.get('Binds') and not h.get('Mounts') and not h['Privileged']
                and h['CapDrop']==['ALL'] and sorted(x.removeprefix('CAP_') for x in (h.get('CapAdd') or []))==sorted(caps) and not h.get('PidMode') and h['LogConfig']['Type']=='none'
                and type(x.get('SizeRw')) is int and 0<=x['SizeRw']<=p['solverWritableMaximumBytes'],'solver_audit_namespace','Actual original-resource namespace differs')
            task.demand(not any(v.partition('=')[0] in ('DEEPSEEK_API_KEY','TGENGIN_GRADER_TOKEN','TGENGIN_CONFIG','TGENGIN_PUBLISHER_TOKEN','OBJRUN_SKB_JOURNAL_PROXY_KEY') for v in cfg.get('Env',[])),
                'solver_audit_credential','Private credential entered solver')
            states.append(x)
    task.demand(any(x['State']['Running'] for x in states) and (not require_capture or any(not x['State']['Running'] and x['State']['Pid']==0 for x in states)),'solver_audit_freeze','Actual running and stopped states required')
    captures=[]
    for cp in c['capturePins']:
        q=capture.validate_capture_receipt(descriptor_pin,cp);task.demand(q['ownedContainerID']==cid,'solver_audit_capture','Foreign artifact capture');captures.append(q)
    if require_capture:task.demand(captures,'solver_audit_capture','No actual stopped capture')
    if require_actor_closed:native.closed_identity(c['actorPid'],int(datetime.fromisoformat(c['completedAtUtc']).timestamp()*1000))
    return {'closure':c,'plan':p,'commandRecords':rows,'captures':captures,'actualSolverGraphValidated':True}
