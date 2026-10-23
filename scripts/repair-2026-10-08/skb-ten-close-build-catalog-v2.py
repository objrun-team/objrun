"""Join actual ten-solver replay and separately closed sealed-private build."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_build_audit_v2 as audit
import skb_artifact_native_identity_v2 as native
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser()
    for k in ('solver-replay','private-run'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    a=p.parse_args();pins={}
    for k in ('solver_replay','private_run'):
        value=task.pin(getattr(a,k).resolve());task.demand(value['sha256']==getattr(a,k+'_sha256'),'catalog_pin','Exact original real evidence pins required');pins[k]=value
    replay=task.read_json(pins['solver_replay']);sr=task.read_json(replay['buildRunPin']);pr=task.read_json(pins['private_run'])
    task.demand(replay['protocol']=='skillsbench-solver-only-build-replay-v2' and replay['actualTenSolverImagesValidated'] is True
                and [x['taskId'] for x in sr['results']]==list(task.TASK_IDS),'catalog_solvers','Actual all10 source-bound solver replay required')
    task.demand(pr['protocol']=='skillsbench-ten-environment-build-actual-run-v1' and pr['fault'] is None and len(pr['results'])==1
                and pr['results'][0]['taskId']=='private-runtime' and pr['actualPrivateImageBuiltAndProbed'] is True,'catalog_private','Actual separate private build/probe required')
    checks=[audit.validate_stage(x['stagePin'],sr) for x in sr['results']]+[audit.validate_stage(pr['results'][0]['stagePin'],pr)]
    observations=[]
    for run in (sr,pr):
        layout=task.read_json(run['storageDescriptorPin']);storage.validate_descriptor(layout)
        lease=task.read_json(run['buildLeasePin'])
        task.demand(lease['held'] is False and lease['pid']==run['actorPid'] and lease['nonce']==layout['ownerNonce'],'catalog_lease','Actual source-bound build actor lease not closed')
        observations.append(native.closed_identity(run['actorPid'],int(datetime.fromisoformat(run['completedAtUtc']).timestamp()*1000)))
    root=Path(task.read_json(pr['storageDescriptorPin'])['storePhysical']);box=Path(pins['private_run']['path']).parent
    value={'protocol':audit.PROTOCOL,'solverReplayPin':pins['solver_replay'],'privateBuildRunPin':pins['private_run'],
        'solverBuildRunPin':replay['buildRunPin'],'stageChecks':checks,'producerObservations':observations,'auditorPid':os.getpid(),
        'sourcePin':task.pin(__file__),'replaySourcePin':task.pin(audit.__file__),'nativeQuerySourcePin':task.pin(native.__file__),
        'observedAtUtc':datetime.now(timezone.utc).isoformat(),'parentAuditorClosureRequired':True,'actualDistinctTaskImages':10,
        'actualSealedPrivateRuntime':True,'actualTestCollections':0,'actualColdControls':0,'modelCalls':0,'paidReady':False,'scoreCertificate':False}
    catalog=fresh(box/'build-closed-catalog.json',task.canonical(value),root)
    proof_dir=box/'closed-image-proofs';proof_dir.mkdir()
    proofs=[]
    for check in checks:
        stage=task.read_json(check['stagePin']);proof={**stage,'originStagePin':check['stagePin'],'buildClosedCatalogPin':catalog}
        proof_pin=fresh(proof_dir/(check['taskId']+'.json'),task.canonical(proof),root);proofs.append({'taskId':check['taskId'],'proofPin':proof_pin})
    out=fresh(box/'closed-image-proof-index.json',task.canonical({'protocol':'skillsbench-closed-image-proof-index-v2','catalogPin':catalog,'proofs':proofs,'modelCalls':0,'paidReady':False}),root)
    print(json.dumps({'imageProofIndexPin':out,'catalogPin':catalog,'modelCalls':0,'paidReady':False}))


if __name__=='__main__':main()
