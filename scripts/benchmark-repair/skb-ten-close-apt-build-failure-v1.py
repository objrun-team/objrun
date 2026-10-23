"""Seal the exact failed BuildKit APT solve after native actors have exited."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',required=True,type=Path);p.add_argument('--sha256',required=True)
    a=p.parse_args();rp=task.pin(a.run)
    task.demand(rp['sha256']==a.sha256,'failure_pin','Exact failed build run required')
    run=task.read_json(rp)
    task.demand(run.get('protocol')=='skillsbench-ten-environment-build-actual-run-v1' and run.get('results')==[]
                and run.get('fault',{}).get('kind')=='build_docker_command','failure_scope','Only failed first-environment build with zero completed probes')
    layout=task.read_json(run['storageDescriptorPin']);storage.validate_descriptor(layout)
    root=Path(layout['storePhysical']);box=Path(rp['path']).parent;storage.ordinary(box,root)
    task.demand(box.parent==Path(layout['directories']['taskmeta']) and box.name.startswith('environment-builds-'),'failure_scope','Exact owned build directory required')
    for pair in run['sourceSnapshots']:
        task.verify_pin(pair['snapshotPin'])
        task.demand(all(pair['snapshotPin'][k]==pair['originalPin'][k] for k in ('bytes','sha256')),'failure_source','Executed source snapshot differs')
    rows=run['lastCommandRecords'];task.demand(len(rows)==3,'failure_commands','Exact three-command failed build required')
    children=[]
    for serial,entry in enumerate(rows,1):
        rec=transport.validate_command_record(entry['recordPin'],run['actorPid'],serial,entry['argv'],box/'3d-scan-calc',4*1024**2)
        children.append(storage.native_actor_absent(rec['pid']))
        if serial<3:task.demand(rec['exitCode']==0,'failure_commands','Base image/buildx observations failed')
        else:
            raw=Path(rec['stderrPin']['path']).read_text(encoding='utf-8')
            task.demand(entry['argv'][1]=='build' and rec['exitCode']==1 and rec['stdoutPin']['bytes']==0
                        and '502  Bad Gateway' in raw and 'failed to solve' in raw and 'exit code: 100' in raw,
                        'failure_solve','Raw completed BuildKit failed APT solve not proven')
    lease=task.read_json(run['buildLeasePin'])
    task.demand(lease.get('protocol')==storage.PROTOCOL+'-native-lease' and lease.get('held') is False
                and lease.get('nonce')==layout['ownerNonce'] and lease.get('pid')==run['actorPid']
                and lease.get('root')==str(root) and lease.get('fixtureOnly') is False,'failure_lease','Exact native build lease is not closed')
    value={'protocol':'skillsbench-build-apt-failure-closed-v1','buildRunPin':rp,'storageDescriptorPin':run['storageDescriptorPin'],
           'producerObservation':storage.native_actor_absent(run['actorPid']),'childObservations':children,
           'buildLeasePin':run['buildLeasePin'],'sourcePin':task.pin(__file__),'querySourcePin':task.pin(storage.__file__),
           'observedAtUtc':datetime.now(timezone.utc).isoformat(),'ownedClosed':True,'namespaceRetired':True,
           'futureWritersAuthorized':False,'ownedStoreObservation':storage.observe_owned_store(layout),
           'completedEnvironments':0,'modelCalls':0,'paidLockReleased':False,'scoreCertificate':False,
           'buildKitResult':'actual failed APT solve; partial image cache may remain; no ready image certified'}
    path=box/'native-closed.json';raw=task.canonical(value)
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    task.demand(path.read_bytes()==raw,'failure_readback','Closed record readback differs')
    print(json.dumps({'closurePin':task.pin(path),'ownedClosed':True,'modelCalls':0}))


if __name__=='__main__':main()
