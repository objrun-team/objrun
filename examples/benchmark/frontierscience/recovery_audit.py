"""Offline, evidence-based eligibility. Never runs a model or edits the original run."""
from pathlib import Path
import json
import hashlib
import sys

ORIGINAL = 'frontierscience-formal-20261016-v1-deepseek-c32'
NAME = 'frontierscience-recovery-20261016-v1-deepseek-c32'
REPO = Path(__file__).resolve().parents[3]
LOCAL = REPO/'docs/frontierscience'/NAME
read = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
sha = lambda b: hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()

def classify(record, final, evidence):
    """Eligibility is decided from failure cause, never from correctness."""
    if not record.get('solverValid'):
        if evidence.get('normalBudgetBoundary'):
            return 'exclude_normal_budget', 'original 600-second wall exhausted; raw error flag retained'
        if record.get('finishReason') == 'length':
            return 'exclude_model_truncation', 'genuine solver token limit is not infrastructure failure'
        if record.get('answer'):
            if final.get('grade', {}).get('valid'):
                return 'reuse_original_final', 'complete original delivery already has a valid blind grade'
            return 'score_once', 'complete original delivery; only grading is missing'
        if record['arm'] == 'objrun' and evidence.get('earlyInfrastructureFailure'):
            return 'objrun_once', 'genuine interface/judge fault interrupted delivery before original wall'
        return 'exclude_unproven_failure', 'no proven eligible infrastructure cause'
    if not final.get('grade', {}).get('valid'):
        return 'score_once', 'original frozen candidate lacks a valid planned blind regrade'
    if not record.get('onlineGrade', {}).get('valid'):
        return 'reuse_original_final', 'valid original blind regrade supersedes failed online score; no API call'
    return 'keep_original', 'original final outcome retained regardless of correctness'

def inspect(root):
    out=root/'outputs/canonical'; cfg=read(root/'package/experiment.json')
    originals={(r['arm'],r['id']):r for p in (out/'results').glob('*/*.json') for r in [read(p)]}
    finals={(r['arm'],r['id']):r for p in (out/'final-results').glob('*/*.json') for r in [read(p)]}
    assert len(originals)==len(finals)==200 and set(originals)==set(finals)
    receipts=[(p,read(p)) for p in (out/'calls').glob('**/receipt.json')]
    jobs=[read(p) for p in (out/'jobs/online').glob('*.json')]
    failed_judges=[]
    for j in jobs:
        p=out/'judgments/online'/(j['key']+'.json')
        g=read(p)
        if not g.get('valid'):
            rs=[{'path':p.relative_to(root).as_posix(),**r} for p,r in receipts if p.relative_to(out/'calls').parts[:2]==('online',j['key'])]
            failed_judges.append({'id':j['id'],'key':j['key'],'grade':g,'receipts':rs})
    entries=[]
    for ident,r in sorted(originals.items()):
        arm,tid=ident; f=finals[ident]; deadline=r['deadlineEpoch'];ended=r['solverEndedEpoch']
        solve_errors=[{'path':p.relative_to(root).as_posix(),**v} for p,v in receipts if v.get('error') and p.relative_to(out/'calls').parts[:3]==('solve',tid,arm)]
        judge_errors=[v for v in failed_judges if v['id']==tid and any(z['startedEpoch']<ended and z['endedEpoch']<=ended+1 for z in v['receipts'])]
        # Boundary means an actual transport remained in flight until the original wall,
        # not merely that a later exception happened to contain the word timeout.
        boundary=bool(ended>=deadline and solve_errors and all(v['startedEpoch']<deadline and abs(v['endedEpoch']-deadline)<2 for v in solve_errors))
        early_judge='PrivateGraderUnavailable' in str(r.get('error')) and judge_errors and ended<deadline-2
        early_transport=any(v['endedEpoch']<deadline-2 for v in solve_errors) and ended<deadline-2
        ev={'originalStartedEpoch':r['startedEpoch'],'originalDeadlineEpoch':deadline,'originalEndedEpoch':ended,
            'normalBudgetBoundary':boundary,'earlyInfrastructureFailure':bool(early_judge or early_transport),
            'failedSolverReceipts':solve_errors,'failedOnlineJudgeJobs':judge_errors}
        action,reason=classify(r,f,ev)
        entries.append({'arm':arm,'id':tid,'subject':r['subject'],'action':action,'reason':reason,'round':1,
                        'extraSolveSeconds':600 if action=='objrun_once' else 0,
                        'originalCandidateSha256':r['candidateSha256'],'originalSolverValid':r['solverValid'],
                        'originalFinalGradeValid':f['grade'].get('valid',False),'evidence':ev})
    return entries,cfg

def controls():
    r={'arm':'objrun','solverValid':False,'answer':''}
    cases=[('normal-wall',r,{}, {'normalBudgetBoundary':True},'exclude_normal_budget'),
           ('judge-fault',r,{}, {'earlyInfrastructureFailure':True},'objrun_once'),
           ('timeout-without-proof',r,{}, {},'exclude_unproven_failure'),
           ('real-solver-length',dict(r,finishReason='length'),{}, {'earlyInfrastructureFailure':True},'exclude_model_truncation'),
           ('completed-grade-missing',dict(r,solverValid=True,answer='x'),{}, {},'score_once'),
           ('completed-blind-valid',dict(r,solverValid=True,answer='x'),{'grade':{'valid':True,'passed':False}}, {},'reuse_original_final'),
           ('ordinary-wrong',dict(r,solverValid=True,answer='x',onlineGrade={'valid':True,'passed':False}),{'grade':{'valid':True,'passed':False}}, {},'keep_original'),
           ('ordinary-correct',dict(r,solverValid=True,answer='x',onlineGrade={'valid':True,'passed':True}),{'grade':{'valid':True,'passed':True}}, {},'keep_original')]
    return [{'name':n,'passed':classify(a,b,c)[0]==want} for n,a,b,c,want in cases]

def main():
    local_original=REPO/'docs/frontierscience'/ORIGINAL
    verification=read(local_original/'LOCAL_VERIFICATION.json')
    assert verification['allPassed'], 'Original full archive verification must pass first'
    meta=read(local_original/'retrieval.json');root=local_original/'full-results'
    entries,cfg=inspect(root);LOCAL.mkdir(parents=True,exist_ok=True)
    checks=controls();assert all(x['passed'] for x in checks)
    manifest={'run':NAME,'originalRun':ORIGINAL,'round':1,'originalArchiveSha256':meta['sha256'],
              'originalArchiveBytes':meta['bytes'],'protocolSha256':cfg['protocolSha256'],
              'dataSha256':read(root/'data/source.json')['fileSha256'],'dataRevision':cfg['dataRevision'],
              'authorization':'user 2026-10-16: exactly one independent bounded recovery after original blind final and drain',
              'selectionRule':'eligibility and valid result, never maximum score; original and recovery both reported',
              'controls':checks,'entries':entries}
    target=LOCAL/'recovery-manifest.json'
    raw=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'
    if target.exists():assert target.read_text(encoding='utf-8')==raw, 'Immutable manifest mismatch'
    else:target.write_text(raw,encoding='utf-8')
    from collections import Counter
    print(json.dumps({'manifest':str(target),'sha256':sha(raw),'actions':dict(Counter(x['action'] for x in entries)),
                      'recovery':[{'arm':x['arm'],'id':x['id'],'action':x['action']} for x in entries if x['action'] in {'score_once','objrun_once'}]}))

if __name__=='__main__':main()
