"""Recover exact existing orphan solvers; no model calls or new candidates."""
import argparse,json,threading,time,re
from pathlib import Path
import skb_artifact_solver_v2 as module
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
import skb_artifact_ram_executor_v2 as grader

def recover(box):
    box=Path(box); owner=json.loads((box/'owner-created.json').read_text())
    if (box/'owner-engine-deadline.json').exists(): owner=json.loads((box/'owner-engine-deadline.json').read_text())
    s=module.Solver.__new__(module.Solver)
    s.dp=owner['taskDescriptorPin'];s.lp=owner['storageDescriptorPin'];s.descriptor=task.read_json(s.dp);s.layout=task.read_json(s.lp)
    s.nonce=owner['instanceNonce'];s.plan_pin=task.pin(box/'solver-plan.json');s.plan=task.read_json(s.plan_pin);s.root=Path(s.layout['storePhysical']);s.box=box
    s.env=transport.sanitized_environment(s.layout,storage);s.snapshots=owner['sourceSnapshots'];s.sources=[x['originalPin'] for x in s.snapshots]
    s.records=[]
    commands=[p for p in box.glob('command-*.json') if re.fullmatch(r'command-\d+\.json',p.name)]
    for p in sorted(commands):
        row=json.loads(p.read_text());s.records.append({'recordPin':task.pin(p),'argv':row.get('argv'),'recoveredOriginalCommand':True})
    s.serial=max([int(re.match(r'command-(\d+)',p.name)[1]) for p in box.glob('command-*')],default=0)
    s.cid=owner['containerID'];s.running=True;s.closed=False;s.create_attempted=True;s.writable=0;s.tool_no=len(list(box.glob('tool-*.json')))
    s.deadline=owner['deadlineUnixMs'];s.started=owner['startedAtUnixMs'];s.stopped_at=None;s.capture_pins=[];s.cold_mode=owner['coldMode']
    s.operation_lock=threading.RLock();s.timer=None;s.expired=int(time.time()*1000)>=s.deadline;s.deadline_fault=None;s.engine_created_at=owner.get('engineCreatedAtUnixMs')
    s.guard_lock=threading.RLock();s.guard_observed=None;s.guard_at=0.;s.command_reserve=0
    s.inspect(False,closing=True)
    cp=s.capture(True);closed=s.close();task.demand(s.closed,'recovered_owned_close','Exact recovered solver removal failed')
    proof={'protocol':'skillsbench-orphan-recovery-v5','originalOwnerPin':task.pin(box/'owner-created.json'),'capturePin':cp,'closurePin':closed,'originalProcessInterrupted':True,'modelCalls':0,'generationValidityRestored':False}
    pin=grader.fresh(box/'orphan-recovery.json',task.canonical(proof),s.root)
    print(json.dumps({'recoveryPin':pin,**proof}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('box');recover(p.parse_args().box)
