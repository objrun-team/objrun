"""Prepare exact collection-bootstrap descriptors from actually closed images."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import uuid
import skb_artifact_task_v2 as task


def main():
    p=argparse.ArgumentParser();p.add_argument('--images',required=True,type=Path);p.add_argument('--sha256',required=True);a=p.parse_args()
    ip=task.pin(a.images.resolve());task.demand(ip['sha256']==a.sha256,'bootstrap_pin','Exact closed image proof index required')
    index=task.read_json(ip)
    task.demand(index['protocol']=='skillsbench-closed-image-proof-index-v2' and [x['taskId'] for x in index['proofs']]==[*task.TASK_IDS,'private-runtime'],'bootstrap_images','Exact ordered10+private image proofs required')
    proofs={x['taskId']:x['proofPin'] for x in index['proofs']};box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/collection-bootstraps'/uuid.uuid4().hex;box.mkdir(parents=True)
    descriptors=[]
    for tid in task.TASK_IDS:
        d=task.descriptor(tid,proofs[tid],proofs['private-runtime']);task.validate_ready_graph(d,False)
        path=box/(tid+'.json')
        with path.open('xb') as f:f.write(task.canonical(d));f.flush();os.fsync(f.fileno())
        descriptors.append(task.pin(path))
    value={'protocol':'skillsbench-source-bound-collection-bootstrap-index-v2','imageProofIndexPin':ip,'taskDescriptorPins':descriptors,
        'sourcePin':task.pin(__file__),'createdAtUtc':datetime.now(timezone.utc).isoformat(),'modelCalls':0,'paidReady':False,'actualCollections':0}
    path=box/'index.json'
    with path.open('xb') as f:f.write(task.canonical(value));f.flush();os.fsync(f.fileno())
    print(json.dumps({'bootstrapIndexPin':task.pin(path),'descriptors':10,'modelCalls':0,'paidReady':False}))


if __name__=='__main__':main()
