"""Explicit second-round authorization: all six invalid first-round outcomes."""
from infra_retry_policy import ARMS,EXPERIMENT,PROTOCOL,classify,sha

REPAIR2='scibench-infra-retry2-20261016-v1-c32'
PREVIOUS='scibench-infra-retry-20261016-v1-c32'
AUTHORIZED_IDS={'scibench-atkins-011','scibench-atkins-020','scibench-atkins-031','scibench-atkins-037','scibench-class-045','scibench-quan-016'}

def make_plan(originals,previous,prior_plan,source_root,previous_root,archives):
    orig={(r['arm'],r['id']):r for r in originals};prior={(r['arm'],r['id']):r for r in previous};old={(r['arm'],r['id']):r for r in prior_plan['attempts']}
    assert len(orig)==len(originals)==1664 and len(prior)==len(previous)==len(old)==47
    assert set(prior)==set(old) and all(r['attemptNo']==1 and r['attemptId']==old[k]['attemptId'] for k,r in prior.items())
    remaining={k:r for k,r in prior.items() if not r['grade'].get('valid')}
    assert set(remaining)=={('objrun',tid) for tid in AUTHORIZED_IDS},'AuthorizationScopeChanged'
    attempts=[]
    for (arm,tid),r in sorted(remaining.items()):
        kind=classify(r)
        assert kind in {'infra_transport','infra_account_check','native_budget_exhausted','native_no_final_submission'}
        assert classify(orig[(arm,tid)]).startswith('infra_') and old[(arm,tid)]['originalResultSha256']==r['originalResultSha256']
        attempts.append({'arm':arm,'id':tid,'attemptId':EXPERIMENT+'/'+arm+'/'+tid+'/infra-retry-2','attemptNo':2,'originalExperiment':EXPERIMENT,'isNewFullAttempt':True,'eligible':True,'classification':kind,'authorization':'User explicitly requested all six remaining invalid first-round records, including native budget/no-submit; one new full attempt, no dollar cap.','nativeRetryExplicitlyAuthorized':kind.startswith('native_'),'originalResultPath':source_root+'/outputs/canonical/results/'+arm+'/'+tid+'.json','originalResultSha256':r['originalResultSha256'],'previousResultPath':previous_root+'/outputs/canonical/results/'+arm+'/'+tid+'.json','previousAttemptId':r['attemptId'],'previousResultSha256':None,'originalPromptSha256':r['promptSha256']})
    return {'schema':2,'run':REPAIR2,'attemptNo':2,'originalExperiment':EXPERIMENT,'sourceRoot':source_root,'previousRoot':previous_root,'sourceArchiveSha256':archives['original'],'previousArchiveSha256':archives['previous'],'globalSlots':32,'maxNewFullAttemptsPerIdentity':1,'attempts':attempts,'authorizedRemainingIds':sorted(AUTHORIZED_IDS),'allSixRemainingExplicitlyAuthorized':True,'originalSevenNativeExcluded':True,'mergeRule':'Keep all original and first-round valid scores. Replace only these six invalid first-round records with the unique second-round outcome, including valid failures and new invalid outcomes; never best-of. Preserve the original seven native invalid records.','primaryDenominatorPerArm':416}
