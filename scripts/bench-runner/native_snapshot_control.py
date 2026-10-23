"""Parameterized original reference or snapshot-grade qualification phase.

Each invocation consumes one original phase clock. Original grading and artifact
capture stay in their pinned modules; this file contains no task solutions/tests.
"""
import argparse,json,pathlib,time
from native_process import pin
from docker_owned import OwnedDocker
from profiles import PROFILES
from snapshot_grader import grade_snapshot

def exact_bytes(path, expected):
    actual=pin(path)
    assert actual['bytes']==expected['bytes'] and actual['sha256']==expected['sha256']
    return pathlib.Path(actual['path'])

def run_control(r, output):
    assert r['protocol'] in ('bench-original-snapshot-control-phase-v1','bench-neutral-snapshot-control-phase-v1')
    neutral=r['protocol']=='bench-neutral-snapshot-control-phase-v1'
    if neutral:assert r['taskId']=='neutral-snapshot-control' and r['profile']=={'kind':'data','artifacts':{'/app/value.txt':128}}
    # The explicit pinned child Loader installs this task-scoped verified-policy
    # closure in every configured module; ordinary imports fail closed.
    history_check=globals().get('_bench_authorized_history')
    assert callable(history_check), 'explicit_child_history_callback_required'
    policy_task=r['neutralPolicyTaskId'] if neutral else r['taskId']
    if neutral:assert policy_task=='zero-model-owned-sb-asset'
    assert history_check(policy_task) is True, 'task_scoped_history_policy_rejected'
    assert r['phase'] in ('reference','grade') and r['label'] in ('missing-output','reference','wrong-output')
    context_dir=pathlib.Path(r['contextDirectory']).resolve()
    context=json.loads(exact_bytes(context_dir/'context-manifest.json',r['contextPin']).read_bytes())
    tasks=[x for x in context['tasks'] if x['taskId']==r['taskId']];assert len(tasks)==1
    task=tasks[0];assert PROFILES[r['taskId']]==r['profile'] and r['profile']['kind']=='data'
    environment=task['officialEnvironment'];assert r['phaseSeconds']==task['agentSeconds' if r['phase']=='reference' else 'verifierSeconds']
    output=pathlib.Path(output);output.mkdir(parents=True,exist_ok=False)
    native=OwnedDocker(output/'native');result=None
    try:
        inspected=native.checked(['image','inspect',r['candidateImage']]);identity=json.loads(native.text(inspected))[0]
        assert identity['Id']==r['candidateImage']
        if r.get('candidateIdentityPin'):
            expected=json.loads(exact_bytes(r['candidateIdentityPin']['path'],r['candidateIdentityPin']).read_bytes())
            if isinstance(expected,list):assert len(expected)==1;expected=expected[0]
            assert all(identity[k]==expected[k] for k in ('Id','RootFS','Os','Architecture'))
            assert all(identity['Config'].get(k)==v for k,v in expected['Config'].items())
        cid,initial,created=native.create('qualification-'+r['label'],r['candidateImage'],'/bin/sh',['-c','sleep 3600'],network='bridge' if r['phase']=='reference' and environment['allow_internet'] else 'none',memory_mb=environment['memory_mb'],cpus=environment['cpus'],drop_capabilities=r['phase']!='reference')
        native.start(cid)
        boundary=['/bin/sh','-c','test ! -e /tests && test ! -e /solution && test ! -e /opt/tb12/checker']
        before=native.execute(cid,boundary)
        if r['phase']=='reference':
            assert r['label']=='reference'
            source=exact_bytes(r['referenceFile'],r['referencePin'])
            native.upload(source,cid,'/tmp/bench-original-qualification-reference.sh')
            executed=native.execute(cid,['/bin/bash','/tmp/bench-original-qualification-reference.sh'],timeout=task['agentSeconds'])
            assert executed['exitCode']==0,'original_reference_failed'
            native.execute(cid,['/bin/rm','/tmp/bench-original-qualification-reference.sh'])
            after=native.execute(cid,boundary);native.pause(cid)
            image,committed=native.commit(cid,'private-reference-control')
            result={'complete':True,'phase':'reference','taskId':r['taskId'],'referenceExecution':executed,'referencePin':r['referencePin'],'referenceImage':image,'referenceCommit':committed,'privateQualificationOnly':True,'eligibleForPaidCandidate':False}
        else:
            if r['label']=='missing-output':
                for path in r['profile']['artifacts']:native.execute(cid,['/bin/rm','-f','--',path])
            for item in r.get('plantFiles',[]):
                assert r['label']=='wrong-output' and item['destination'] in r['profile']['artifacts']
                source=exact_bytes(item['source'],item['pin']);assert source.stat().st_size<=r['profile']['artifacts'][item['destination']]
                native.execute(cid,['/bin/mkdir','-p',str(pathlib.PurePosixPath(item['destination']).parent)])
                native.upload(source,cid,item['destination'])
            graded=grade_snapshot(native,cid,task,context,context_dir,r['privateBaseImage'],output/'grade')
            assert graded['result']['reward']==r['expectedReward'],'original_control_reward_mismatch'
            assert native.assert_actor(cid)['State']['Paused'];native.unpause(cid);after=native.execute(cid,boundary)
            result={'complete':True,'phase':'grade','taskId':r['taskId'],'label':r['label'],'expectedReward':r['expectedReward'],'actualReward':graded['result']['reward'],'originalGrade':graded}
        result.update(verifiedHistoryPolicyTaskId=policy_task,explicitChildHistoryVerified=True,initial=initial,create=created,privateTestsAbsentBefore=before,privateTestsAbsentAfter=after,neutralContentOnly=neutral,modelCalls=0,gradeCalls=int(r['phase']=='grade' and not neutral),referenceCalls=int(r['phase']=='reference' and not neutral),formalScore=False)
    finally:
        for cid,role,name in native.open_actors():native.remove(cid)
        native.close()
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps({'complete':run_control(json.loads(pathlib.Path(a.request).read_bytes()),a.output)['complete']}))
