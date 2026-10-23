"""Run each actual original collection serially and publish only replayed proofs."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import skb_artifact_task_v2 as task
from skb_artifact_grade_audit_v2 import validate_grade_report
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--bootstrap',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--storage',type=Path,required=True);p.add_argument('--storage-sha256',required=True)
    p.add_argument('--first-owner',type=Path);p.add_argument('--first-owner-sha256');a=p.parse_args()
    bp=task.pin(a.bootstrap.resolve());lp=task.pin(a.storage.resolve())
    task.demand(bp['sha256']==a.sha256 and lp['sha256']==a.storage_sha256,'collections_pin','Exact current sources required')
    bootstrap=task.read_json(bp);task.demand(len(bootstrap['taskDescriptorPins'])==10,'collections_scope','Exactly10 distinct tasks required')
    box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/actual-collections'/uuid.uuid4().hex;box.mkdir(parents=True)
    fresh(box/'driver-source.py',Path(__file__).read_bytes(),task.REPO)
    descriptors=[];collections=[]
    for i,dp in enumerate(bootstrap['taskDescriptorPins']):
        d=task.read_json(dp);task.demand(d['taskId']==task.TASK_IDS[i],'collections_order','Fixed task order changed')
        if i==0 and a.first_owner:
            op=task.pin(a.first_owner.resolve());task.demand(op['sha256']==a.first_owner_sha256,'collections_pin','Actual existing first owner changed')
            invocation=None
        else:
            command=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(Path(__file__).with_name('skb-ten-evidence-command-v1.py')),
                '--script','skb_artifact_ram_executor_v2.py','--timeout',str(d['originalResources']['verifier']['timeout_sec']+180),'--',
                '--task-descriptor',dp['path'],'--task-descriptor-sha256',dp['sha256'],'--storage-descriptor',lp['path'],'--storage-descriptor-sha256',lp['sha256'],
                '--mode','collect','--full-capacity']
            child=subprocess.Popen(command,cwd=task.REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            out,err=child.communicate(timeout=d['originalResources']['verifier']['timeout_sec']+240)
            raw_pin=fresh(box/(d['taskId']+'-driver-output.txt'),out+err,task.REPO)
            lines=[json.loads(x) for x in out.splitlines() if x.startswith(b'{')]
            invocation=lines[0]['runPin'] if lines else None
            task.demand(child.returncode==0 and len(lines)>=2 and lines[1].get('gradeOwnerPin'),'collection_child','Actual source-bound collection child failed; raw retained')
            op=lines[1]['gradeOwnerPin']
        replay=validate_grade_report(dp,op,True);result=replay['result']
        task.demand(result['collectionValid'] is True and result['mode']=='collect','collection_original','Actual complete original collection failed')
        value={'protocol':'skillsbench-private-collection-v1','taskId':d['taskId'],'verifierTreeIdentity':d['verifierTreeIdentity'],
            'runnerSourcePin':d['runnerSourcePin'],'privateRuntimeProofPin':d['privateRuntimeProofPin'],'bootstrapDescriptorPin':dp,
            'nodeIds':result['nodeIds'],'rawResultPin':replay['owner']['resultPins']['private-result.json'],'ownedClosurePin':op,
            'invocationPin':invocation,'sourcePin':task.pin(__file__),'observedAtUtc':datetime.now(timezone.utc).isoformat(),
            'actualRawGraphValidated':True,'modelCalls':0,'paidReady':False}
        cp=fresh(box/(d['taskId']+'-collection.json'),task.canonical(value),task.REPO)
        complete=task.descriptor(d['taskId'],d['candidateImageProofPin'],d['privateRuntimeProofPin'],cp)
        ready_pin=fresh(box/(d['taskId']+'-descriptor.json'),task.canonical(complete),task.REPO)
        task.validate_descriptor(complete,True);descriptors.append(ready_pin);collections.append(cp)
        print(json.dumps({'phase':'actual-full-collection-replayed','taskId':d['taskId'],'nodeCount':len(result['nodeIds']),'descriptorPin':ready_pin,'modelCalls':0}),flush=True)
    index=fresh(box/'index.json',task.canonical({'protocol':'skillsbench-ten-actual-collection-index-v2','bootstrapIndexPin':bp,'storageDescriptorPin':lp,
        'taskDescriptorPins':descriptors,'collectionPins':collections,'sourcePin':task.pin(__file__),'actualDistinctTaskCollections':10,'modelCalls':0,'paidReady':False}),task.REPO)
    print(json.dumps({'collectionIndexPin':index,'actualDistinctTaskCollections':10,'modelCalls':0,'paidReady':False}),flush=True)


if __name__=='__main__':main()
