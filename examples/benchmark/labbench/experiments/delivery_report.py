"""Final local delivery note, retaining the original and paused-recovery views."""
from pathlib import Path
import json
from ops import LOCAL
from protocol import digest


def main():
    verified=json.loads((LOCAL/'LOCAL_VERIFICATION.json').read_text(encoding='utf-8'))
    if not verified['allPassed']:raise RuntimeError('FullLocalVerificationRequired')
    retrieval=json.loads((LOCAL/'retrieval.json').read_text(encoding='utf-8'));root=Path(retrieval['fullResults']);out=root/'outputs/canonical'
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    cfg=read(root/'package/experiment.json');rows=[read(p) for p in (out/'results').glob('*/*.json')]
    assert len(rows)==1416
    def counts(items):
        known=[r for r in items if r['solverValid'] and r['grade'].get('valid')]
        passed=sum(r['grade']['passed'] for r in known);n=len(items);u=n-len(known)
        return {'total':n,'valid':len(known),'passed':passed,'unknown':u,'accuracyBounds':[passed/n,(passed+u)/n]}
    recovery=cfg.get('canaryTransportRecovery',{});original={};checks=[];timings=[]
    for tid,spec in recovery.items():
        original[('objrun',tid)]=read(out/'prior-canary/results/objrun'/(tid+'.json'))
        current=next(r for r in rows if r['arm']=='objrun' and r['id']==tid)
        home=out/'calls/solve'/tid/'objrun/native-001';dispatches=[read(p) for p in home.glob('attempt-*/dispatch.json')]
        checks.append({'id':tid,'firstLogicalWireUnchanged':len({p['requestSha256'] for p in dispatches})==1,'totalAttempts':len(dispatches),'withinOriginalThree':len(dispatches)<=3})
        timings.append({'id':tid,'consumedBeforeRecovery':spec['consumedSolveSeconds'],'remainingGranted':spec['remainingSolveSeconds'],
                        'cumulativeSolverWallSeconds':current.get('cumulativeSolveSeconds'),'repairDowntimeSeconds':current.get('recoveryWallGapSeconds'),
                        'budgetInterpretation':'600s cumulative active task clock; repair downtime excluded and separately disclosed; not uninterrupted wall clock'})
    views={}
    for name,items in [('withTransportRecovery',rows),('originalInterruptedView',[original.get((r['arm'],r['id']),r) for r in rows]),
                       ('excludingPausedRecoveryItems',[r for r in rows if r['id'] not in recovery])]:
        views[name]={a:counts([r for r in items if r['arm']==a]) for a in cfg['arms']}
    for check in checks:assert check['firstLogicalWireUnchanged'] and check['withinOriginalThree']
    summary=read(out/'SUMMARY.json');original_archive=read(LOCAL/'original-pilot-archive.json')
    assert original_archive['twoEndsSha256Verified'] and digest(Path(original_archive['localArchive']).read_bytes())==original_archive['sha256']
    report={'delivered':True,'verified':True,'retrieval':retrieval,'originalPilotArchive':original_archive,'views':views,'recoveryChecks':checks,'recoveryTiming':timings,
            'accounting':summary['accounting'],'costDeduplication':'v2 ledger already includes every inherited v1 receipt; do not add original pilot costs again',
            'analysisSourceSha256':digest(Path(__file__).read_bytes())}
    (LOCAL/'DELIVERY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# LAB-Bench complete delivery','','ProtocolQA108 + SeqQA600; single-shot and full ObjRun only. The full method receives ground-truth correctness feedback.','',
           '|Result view|Arm|Valid/total|Passed|Accuracy bounds|','|---|---|---:|---:|---|']
    for view,arms in views.items():
        for arm,s in arms.items():lines.append(f"|{view}|{arm}|{s['valid']}/{s['total']}|{s['passed']}|{s['accuracyBounds']}|")
    lines+=['','The 3 recovered units had delivered no prior candidates. Their first logical requests resumed the original wire payload with remaining transport attempts. About 303 seconds were used and about 297 remained; repair downtime is recorded separately, so these were not uninterrupted 600-second wall-clock experiments. Preserve both the original interrupted view and paired bounds excluding these 3 tasks.',
            '', 'Costs use the complete v2 ledger, including original v1 receipts and new recovery charges; do not add pilot costs again. Missing costs remain unknown.', '', '|Arm|Known actual USD|Unknown-cost requests|Requests|','|---|---:|---:|---:|']
    for arm,c in summary['accounting']['byArm'].items():lines.append(f"|{arm}|{c['knownActualCostUsd']:.9f}|{c['unknownCostRequests']}|{c['requests']}|")
    lines+=['',f"Full archive: {retrieval['archive']}",f"SHA256: {retrieval['sha256']}",f"Original pilot archive: {original_archive['localArchive']}",f"Original pilot SHA256: {original_archive['sha256']}",
            '',f"Local verification passed {verified['checkCount']} checks. Per-task CSVs, source data, candidates, raw requests/responses, costs, logs, SQLite, and trajectories are in the full archive and full-results.",
            'See SUMMARY.json for accuracy, precision, coverage, and subtask results; the prespecified sensitivity analysis for identical-text options is reported separately. Correct final selection does not automatically establish repaired biological reasoning.']
    (LOCAL/'DELIVERY_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'delivered':True,'verified':True,'views':views,'accounting':summary['accounting']}))


if __name__=='__main__':main()
