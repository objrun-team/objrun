"""Readonly full SkillsBench task/private/actor/cold graph; cash has its own replay."""
import argparse
import json
import os
from pathlib import Path
import socket
import skb_artifact_task_v2 as task
import skb_artifact_native_identity_v2 as native
from skb_artifact_grade_audit_v2 import validate_grade_report
from skb_artifact_solver_audit_v2 import validate_solver_closed
from skb_artifact_ram_executor_v2 import fresh


def audit(recipe_pin,kind):
    r=task.read_json(recipe_pin);lp=r['storageDescriptorPin'];layout=task.read_json(lp)
    task.demand(r['family']=='skillsbench-artifact-journal-v1' and r['selectedDistinctTasks']==10 and r['plannedTaskRuns']==20,'audit_scope','Fixed20 task recipe required')
    for p in [*r['sourcePins'],r['freezePin'],*r['taskDescriptorPins']]:task.verify_pin(p,512*1024**2)
    cold=task.read_json(r['coldControlIndexPin']);task.demand(cold['actualColdControls']==30 and cold['actualDistinctTaskTriplets']==10
        and len(cold['controlPins'])==30 and len({x['path'] for x in cold['controlPins']})==30,'audit_cold','Actual30 unique cold controls required')
    for i,cp in enumerate(cold['controlPins']):
        c=task.read_json(cp);task.demand(c['taskDescriptorPin']==r['taskDescriptorPins'][i//3] and c['mode']==('empty','oracle','wrong')[i%3]
            and c['controlMatched'] is True and c['strictG']==int(i%3==1),'audit_cold','Exact source-bound 0/1/0 cold graph differs')
        replay=validate_grade_report(c['taskDescriptorPin'],c['gradeOwnerPin'],True)
        e=replay['result']['evaluation'];graph=validate_solver_closed(c['taskDescriptorPin'],c['solverClosurePin'],True)
        task.demand(e==c['evaluation'] and int(e['allTestsPassed'])==c['strictG']==int(i%3==1) and e['officialReward']==c['officialReward']==int(i%3==1)
            and e['valid']==c['fullCollectionValid'] and (i%3!=1 or e['valid']) and replay['owner']['capturePin']==c['capturePin']
            and c['capturePin'] in graph['closure']['capturePins'],'audit_cold','Actual cold reward or exact solver/grade capture differs')
    output=Path(r['output']);raw=task.read_json(task.pin(output/'raw-close.json'));owned=task.read_json(task.pin(output/'owned-close.json'))
    bridge=task.read_json(owned['bridgeClosurePin']);task.demand(bridge['closed'] is True and bridge['directChildClosed'] is True and bridge['portClosed'] is True,'audit_bridge','Actual native bridge child/listener closure required')
    bc=task.read_json(owned['bridgeOwnedClosePin']);task.demand(bc['ownedSolversClosed'] is True and bc['closeFault'] is None,'audit_bridge','Actual bridge container close cannot be replaced by service exit')
    actor_observations=[]
    for rp in owned['registrationPins']:
        row=task.read_json(rp);task.demand(row['family']==r['family'] and row['runId']==r['runId'],'audit_actor','Foreign registered actor')
        actor_observations.append(native.closed_identity(row['pid'],row['registeredAtUnixMs']))
    for port in owned['ports']:
        with socket.socket() as s:
            s.settimeout(.3);rc=s.connect_ex(('127.0.0.1',port));task.demand(rc in (10061,111),'audit_listener','Exact owned listener closure ambiguous or live')
    task_pins=raw['taskPins'];expected=r['taskSchedule'][:2] if kind=='local-mock' else r['taskSchedule'];task.demand(len(task_pins)<=len(expected),'audit_tasks','Extra task record')
    records=[]
    for p,e in zip(task_pins,expected):
        v=task.read_json(p);task.demand(all(v[k]==e[k] for k in e) and v['taskDescriptorPin']==r['taskDescriptorPins'][e['index']//2]
            and v['deadlineUnixMs']==v['actualCreatedAt']+e['taskSeconds']*1000,'audit_task','Fixed task/arm/replica/prompt/resource/deadline differs')
        solver=validate_solver_closed(v['taskDescriptorPin'],v['solverClosurePin'],True)
        task.demand(v['artifactCapture']['capturePin'] in solver['closure']['capturePins'],'audit_artifact','Final artifact is not exact owned solver capture')
        for q in v['databasePins']:task.verify_pin(q,512*1024**2)
        if v['finalGradeOwnerPin']:
            graded=validate_grade_report(v['taskDescriptorPin'],v['finalGradeOwnerPin'],True)
            task.demand(graded['result']['evaluation']==v['finalEvaluation'] and graded['owner']['capturePin']==v['artifactCapture']['capturePin']
                and v['finalGradeStartedAtUnixMs']>=raw['generationClosedAtUnixMs'],'audit_grade','Independent final grade/source/capture/order differs')
        if kind=='score':task.demand(v['finalGradeOwnerPin'] and v['finalEvaluation']['valid'] is True and v['generationValid'] is True
            and v['acceptance']['valid'] is True,'audit_score','Actual full final private grade required for every score task')
        task.demand(v['explicitVerifyCalls']<=e['explicitVerifyChecks'],'audit_checks','Explicit query budget exceeded')
        records.append(v)
    for gp in bc['gradeOwnerPins']:
        g=task.read_json(gp);validate_grade_report(g['taskDescriptorPin'],gp,True)
    for cp in bc['solverClosures']:
        c=task.read_json(cp);validate_solver_closed(c['taskDescriptorPin'],cp,True)
    if kind in ('score','local-mock'):task.demand(len(records)==len(expected),'audit_complete','Required actual run inventory incomplete')
    if kind=='local-mock':
        ledger=task.read_json(raw['toolLedgerPin'])
        for v in records:
            tools={q['tool'] for q in ledger['receipts'] if q['place']=='skb:'+v['id'] and q['forwarded']}
            task.demand({'bash','read','write','edit','glob','grep'}<=tools,'audit_six_tools','Actual six-tool engine forwards missing')
    real=[v for v in records if r['providerKind']=='real-provider' and any(x.get('providerAttempted') is True and x.get('httpStatus')==200 and x.get('completionValid') is True and x.get('usage') for x in v['apiCalls'])]
    paired=[tid for tid in task.TASK_IDS if {v['arm'] for v in real if v['officialId']==tid}=={'U','F'}]
    if kind=='score':task.demand(r['providerKind']=='real-provider' and len(real)==20 and len(paired)==10,'audit_real_pairs','Score requires ten actual successful-provider U/F pairs')
    return {'protocol':'skillsbench-ten-independent-native-audit-v2','family':r['family'],'runId':r['runId'],'kind':kind,'recipePin':recipe_pin,
        'taskPins':task_pins,'actualTaskRuns':len(records),'actualDistinctRealTasks':len(paired),'realInferenceTaskRuns':len(real),
        'originalSourcePreserved':True,'actualColdControlsReplayed':30,'actualActorObservations':actor_observations,'ownedActorsClosed':True,
        'allIndependentFinalGradesAfterGenerationClosure':True,'candidateProgramsExecutedInPrivateGrader':False,'modelCalls':0,'scoreCertificate':False,
        'sourcePin':task.pin(__file__)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--kind',choices=('score','financial-abort','local-mock'),required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    rp=task.pin(a.recipe.resolve());task.demand(rp['sha256']==a.sha256,'audit_recipe','Exact recipe required')
    result=audit(rp,a.kind);layout=task.read_json(task.read_json(rp)['storageDescriptorPin'])
    out=fresh(a.output.resolve(),task.canonical(result),Path(layout['storePhysical']))
    print(json.dumps({'nativeAuditPin':out,'modelCalls':0}),flush=True)


if __name__=='__main__':main()
