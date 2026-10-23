"""Real lab partial numeric reward control using an oracle CSV data mutation."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import uuid
import skb_artifact_task_v2 as task
from skb_artifact_solver_v2 import Solver
from skb_artifact_ram_executor_v2 import grade_captured,fresh
from skb_artifact_grade_audit_v2 import validate_grade_report
import skb_artifact_capture_v2 as capture


def main():
    p=argparse.ArgumentParser()
    for k in ('oracle','storage'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    a=p.parse_args();pins=[]
    for k in ('oracle','storage'):
        q=task.pin(getattr(a,k).resolve());task.demand(q['sha256']==getattr(a,k+'_sha256'),'fractional_pin','Exact actual oracle/source required');pins.append(q)
    oracle,lp=pins;o=task.read_json(oracle);dp=o['taskDescriptorPin'];d=task.read_json(dp)
    task.demand(d['taskId']=='lab-unit-harmonization' and o['mode']=='oracle' and o['strictG']==1,'fractional_oracle','Actual all-pass lab oracle required')
    c=capture.validate_capture_receipt(dp,o['capturePin']);solver=Solver(dp,lp);cp=None;closure=None
    fresh(solver.box/'fractional-control-source.py',Path(__file__).read_bytes(),solver.root)
    try:
        solver.create(False);path=d['outputArtifacts'][0]['containerPath'];q=c['artifactPin'];task.verify_pin(q,task.MAX_ARTIFACT)
        solver.command('cp',q['path'],solver.cid+':'+path)
        code="import csv,json;from pathlib import Path;p=Path("+repr(path)+");rows=list(csv.DictReader(p.open(newline='')));names=list(rows[0]);key=next(k for k in names if k not in ('id','patient_id','subject_id','visit','date') and rows[0][k].replace('.','',1).replace('-','',1).isdigit());old=rows[0][key];rows[0][key]=format(float(old)+10000,'.2f');f=p.open('w',newline='');w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows(rows);f.close();print(json.dumps({'column':key,'row':0,'old':old,'new':rows[0][key]}))"
        _,raw,_=solver.command('exec',solver.cid,'/usr/local/bin/python3','-I','-B','-c',code)
        mutation=fresh(solver.box/'fractional-data-mutation.json',raw,solver.root);cp=solver.capture(True)
    finally:closure=solver.close()
    task.demand(solver.closed and cp,'fractional_closed','Owned data mutation solver did not close')
    op=grade_captured(dp,lp,cp);replay=validate_grade_report(dp,op,False);e=replay['result']['evaluation']
    task.demand(e['valid'] and not e['allTestsPassed'] and 0<e['officialReward']<1 and e['passedTests']+e['failedTests']==48,
        'fractional_reward','Actual full collection must retain fractional reward and strict false')
    result=fresh(solver.box/'fractional-control.json',task.canonical({'protocol':'skillsbench-real-fractional-control-v2','taskId':d['taskId'],'taskDescriptorPin':dp,
        'oracleControlPin':oracle,'capturePin':cp,'solverClosurePin':closure,'gradeOwnerPin':op,'mutationPin':mutation,'evaluation':e,
        'numericReward':e['officialReward'],'strictG':0,'fullCollectionValidated':True,'sourcePin':task.pin(__file__),'observedAtUtc':datetime.now(timezone.utc).isoformat(),'modelCalls':0}),solver.root)
    print(json.dumps({'fractionalControlPin':result,'officialReward':e['officialReward'],'strictG':0,'modelCalls':0}),flush=True)


if __name__=='__main__':main()
