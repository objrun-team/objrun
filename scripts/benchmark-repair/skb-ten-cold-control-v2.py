"""Run one real fresh empty/oracle/wrong capture and independent private replay."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_native_identity_v2 as native
from skb_artifact_grade_audit_v2 import validate_grade_report
from skb_artifact_ram_executor_v2 import fresh


def invoke(script,args,seconds,box,label):
    argv=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(Path(__file__).with_name('skb-ten-evidence-command-v1.py')),
        '--script',script,'--timeout',str(seconds),'--',*args]
    child=subprocess.Popen(argv,cwd=task.REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    out,err=child.communicate(timeout=seconds+30)
    raw=fresh(box/(label+'-caller.txt'),out+err,task.REPO)
    lines=[json.loads(x) for x in out.splitlines() if x.startswith(b'{')]
    task.demand(child.returncode==0 and len(lines)>=2,'cold_child','Actual cold child failed; original raw caller/child retained')
    return lines[0]['runPin'],lines[1]


def main():
    p=argparse.ArgumentParser()
    for k in ('descriptor','storage'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    p.add_argument('--mode',choices=('empty','oracle','wrong'),required=True);a=p.parse_args();pins=[]
    for k in ('descriptor','storage'):
        value=task.pin(getattr(a,k).resolve());task.demand(value['sha256']==getattr(a,k+'_sha256'),'cold_pin','Source-bound actual descriptors required');pins.append(value)
    dp,lp=pins;d=task.read_json(dp);task.validate_descriptor(d,True)
    box=task.REPO/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/actual-cold-controls'/uuid.uuid4().hex;box.mkdir(parents=True)
    fresh(box/'driver-source.py',Path(__file__).read_bytes(),task.REPO)
    base=['--task-descriptor',dp['path'],'--task-descriptor-sha256',dp['sha256'],'--storage-descriptor',lp['path'],'--storage-descriptor-sha256',lp['sha256']]
    solver_call,solver=invoke('skb_artifact_solver_v2.py',[*base,'--cold',a.mode],d['originalResources']['agent']['timeout_sec']+120,box,'solver')
    cp=solver['capturePin'];closure=task.read_json(solver['closurePin'])
    task.demand(closure['ownedClosed'] is True and closure['fault'] is None and solver['fault'] is None,'cold_solver','Actual fresh solver/capture did not close')
    native.closed_identity(closure['actorPid'],int(datetime.fromisoformat(closure['completedAtUtc']).timestamp()*1000))
    grader_call,grade=invoke('skb_artifact_ram_executor_v2.py',[*base,'--mode','grade','--capture',cp['path'],'--capture-sha256',cp['sha256']],
        d['originalResources']['verifier']['timeout_sec']+180,box,'grader')
    op=grade['gradeOwnerPin'];replay=validate_grade_report(dp,op,True);evaluation=replay['result']['evaluation']
    expected=a.mode=='oracle'
    value={'protocol':'skillsbench-real-cold-artifact-control-v2','taskId':d['taskId'],'mode':a.mode,'taskDescriptorPin':dp,'storageDescriptorPin':lp,
        'solverInvocationPin':solver_call,'solverClosurePin':solver['closurePin'],'capturePin':cp,'gradeInvocationPin':grader_call,'gradeOwnerPin':op,
        'strictG':int(evaluation['allTestsPassed']),'officialReward':evaluation['officialReward'],'fullCollectionValid':evaluation['valid'],
        'evaluation':evaluation,'controlExpectedStrictG':int(expected),'controlMatched':evaluation['allTestsPassed']==expected and evaluation['officialReward']==int(expected) and (not expected or evaluation['valid']),
        'sourcePin':task.pin(__file__),'observedAtUtc':datetime.now(timezone.utc).isoformat(),'modelCalls':0,'paidReady':False,'scoreCertificate':False}
    out=fresh(box/'control.json',task.canonical(value),task.REPO)
    print(json.dumps({'controlPin':out,'taskId':d['taskId'],'mode':a.mode,'strictG':value['strictG'],'officialReward':value['officialReward'],
        'fullCollectionValid':value['fullCollectionValid'],'controlMatched':value['controlMatched'],'modelCalls':0}),flush=True)
    raise SystemExit(0 if value['controlMatched'] else 1)


if __name__=='__main__':main()
