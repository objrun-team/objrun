"""Seal exact native interrupted build and actual terminal BuildKit inventory."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--history',type=Path,required=True);p.add_argument('--history-sha256',required=True);a=p.parse_args()
    rp=task.pin(a.run);hp=task.pin(a.history)
    task.demand(rp['sha256']==a.sha256 and hp['sha256']==a.history_sha256,'interrupted_pin','Exact recorded inputs required')
    run=task.read_json(rp);history=task.read_json(hp);layout=task.read_json(run['storageDescriptorPin']);storage.validate_descriptor(layout)
    box=Path(rp['path']).parent;root=Path(layout['storePhysical']);storage.ordinary(box,root)
    task.demand(run['protocol']=='skillsbench-ten-environment-build-actual-run-v1' and run['results']==[]
                and run['fault']=={'kind':'bounded_child','type':'GradeFault'} and len(run['lastCommandRecords'])==2,
                'interrupted_scope','Exact third command interrupted build with zero completed images required')
    kids=[]
    for i,entry in enumerate(run['lastCommandRecords'],1):
        rec=transport.validate_command_record(entry['recordPin'],run['actorPid'],i,entry['argv'],box/'3d-scan-calc',4*1024**2)
        kids.append(storage.native_actor_absent(rec['pid']))
    fault_pin=task.pin(box/'3d-scan-calc/command-003.json');fault=task.read_json(fault_pin)
    task.demand(fault['faults']==['FileNotFoundError'] and fault['directChildWaitReturned'] is True and fault['pipeReadersClosed'] is True
                and fault['captureFsyncReturned'] is True and fault['stdoutPin']['bytes']==fault['stderrPin']['bytes']==0,
                'interrupted_raw','Exact interrupted child fault/capture closure required')
    for k in ('intentPin','childPin','stdoutPin','stderrPin'):task.verify_pin(fault[k])
    intent=task.read_json(fault['intentPin']);child=task.read_json(fault['childPin'])
    task.demand(child['ownerPid']==intent['ownerPid']==run['actorPid'] and child['serial']==intent['serial']==3
                and child['argvSha256']==intent['argvSha256']==fault['argvSha256'] and child['childPid']==fault['pid']
                and child['intentPin']==fault['intentPin'],'interrupted_child','Actual faulted intent/child graph differs')
    kids.append(storage.native_actor_absent(fault['pid']))
    task.demand(history['protocol']=='skillsbench-build-history-readonly-v1' and task.read_json(history['layoutPin'])==layout,'interrupted_history','Same exact Docker namespace history required')
    hb=Path(history['commandRecordPin']['path']).parent
    argv=['D:/Program/resources/cli-plugins/docker-buildx.exe','history','ls','--format=json','--no-trunc']
    hrec=transport.validate_command_record(history['commandRecordPin'],history['actorPid'],1,argv,hb)
    task.demand(hrec['exitCode']==0,'interrupted_history','Actual BuildKit history query failed')
    rows=[json.loads(x) for x in Path(hrec['stdoutPin']['path']).read_bytes().splitlines()]
    task.demand(rows and all(x['status'] in ('Completed','Error') and x.get('completed_at') for x in rows),'interrupted_buildkit','Terminal actual BuildKit inventory required before retry')
    task.demand(datetime.fromisoformat(history['observedAtUtc'])>datetime.fromisoformat(run['completedAtUtc']),'interrupted_history','Post-exit daemon observation required')
    lease=task.read_json(run['buildLeasePin'])
    task.demand(lease['held'] is False and lease['nonce']==layout['ownerNonce'] and lease['pid']==run['actorPid'] and lease['root']==str(root),'interrupted_lease','Exact build lease still held')
    for pair in run['sourceSnapshots']:
        task.verify_pin(pair['snapshotPin']);task.demand(pair['snapshotPin']['sha256']==pair['originalPin']['sha256'],'interrupted_source','Executed archived source differs')
    value={'protocol':'skillsbench-interrupted-build-observed-closed-v1','buildRunPin':rp,'faultedCommandPin':fault_pin,'historyObservationPin':hp,
        'producerObservation':storage.native_actor_absent(run['actorPid']),'childObservations':kids,
        'historyProducerObservation':storage.native_actor_absent(history['actorPid']),'historyChildObservation':storage.native_actor_absent(hrec['pid']),
        'buildLeasePin':run['buildLeasePin'],'sourcePin':task.pin(__file__),'observedAtUtc':datetime.now(timezone.utc).isoformat(),
        'terminalBuildKitInventoryObserved':True,'preDispatchCertified':False,'ownedNativeActorsClosed':True,'namespaceRetired':True,
        'futureWritersAuthorized':False,'modelCalls':0,'paidLockReleased':False,'scoreCertificate':False}
    path=box/'native-closed.json'
    with path.open('xb') as f:f.write(task.canonical(value));f.flush();os.fsync(f.fileno())
    print(json.dumps({'closurePin':task.pin(path),'modelCalls':0}))


if __name__=='__main__':main()
