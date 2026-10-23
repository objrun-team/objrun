"""Persist the full task-to-explicit-policy worklist; zero execution/readiness."""
import json
from pathlib import Path
from prepare import HOME,public,save,utc
from artifact_policies import policy

def main():
    manifest=json.loads((HOME/'manifest.json').read_bytes());rows=[]
    for task in manifest['taskSchedule']:
        tid=task['taskId'];p=policy(tid)
        rows.append({'taskId':tid,'taskSourcePin':task['taskSourcePin'],'policy':p,
                     'policySourcePin':public.pin(Path(__file__).with_name('artifact_policies.py')),
                     'policySourcePins':[public.pin(Path(__file__).with_name(n)) for n in ('artifact_policies.py','multi_policies.py')],
                     'policyReviewed':p is not None,'privateGraderReady':False,'scoreCertified':False})
    save(HOME/'artifact-policy-inventory.json',{'protocol':'skillsbench-full-f-artifact-policy-inventory-v1',
        'updatedAtUtc':utc(),'denominator':87,'reviewedPolicyCount':sum(r['policyReviewed'] for r in rows),
        'policiesPending':sum(not r['policyReviewed'] for r in rows),'rows':rows,'modelCalls':0})
    print(json.dumps({'denominator':87,'reviewedPolicyCount':sum(r['policyReviewed'] for r in rows),'modelCalls':0}))

if __name__=='__main__':main()
