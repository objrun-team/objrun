"""Audited claim-list drain. No signal or HALT is sent to in-flight work."""
import argparse,os,time
from support import *
def drain():
    assert not (CONTROL/'drain-request.json').exists(),'DrainAlreadyRequested'
    proof=load(CONTROL/'free-checks.json');assert proof['allPassed'] and proof['realApiCalls']==0
    assert proof['sourceFingerprints']==pins(),'CodeChangedAfterFreeChecks'
    old.protect();s=load(OUT/'status.json');launch=load(OLD/'launch.json')
    assert s['stage']=='running' and s['pid']==launch['pid'] and live(s['pid'],OLD/'runner.py') and live(s['graderPid'],ROOT/'package/grader.py')
    original=(OLD/'plan.json').read_bytes();backup=CONTROL/'predecessor-plan.original';backup.write_bytes(original)
    completed=[p.parent for p in (OUT/'tasks').glob('*/*/result.json')]
    hashes={f.relative_to(ROOT).as_posix():sha(f) for d in completed for f in d.rglob('*') if f.is_file()}
    request={'atUtc':core.utc(),'atMs':int(time.time()*1000),'oldPid':s['pid'],'oldEntry':str(OLD/'runner.py'),'oldGraderPid':s['graderPid'],'oldGraderEntry':str(ROOT/'package/grader.py'),'completedBeforeDrain':len(completed),'protectedCompletedFiles':hashes,'oldStatus':s,'originalPlanSha256':sha(backup),'mechanism':'atomic independent remainingCells=[]; no HALT/signal; real predecessor executor waits all consumers'}
    common.durable(CONTROL/'drain-request.json',request)
    p=json.loads(original);p['remainingCells']=[];p['controlledDrain']={'authorization':'User explicitly authorized necessary controlled concurrency handoff','requestAtUtc':request['atUtc'],'originalPlanSha256':request['originalPlanSha256']}
    common.save(OLD/'plan.json',p);common.save(CONTROL/'temporary-drain-plan.json',p)
    print(json.dumps({'drainRequested':True,'oldPid':s['pid'],'completed':len(completed),'active':s['active'],'noSignalSent':True}))
def status():
    p=load(CONTROL/'drain-request.json');s=load(OUT/'status.json')
    print(json.dumps({'oldControllerLive':live(p['oldPid'],p['oldEntry']),'oldGraderLive':live(p['oldGraderPid'],p['oldGraderEntry']),'state':{k:v for k,v in s.items() if k!='generationIds'},'exit':load(OLD/'controller-exit.json') if (OLD/'controller-exit.json').exists() else None}))
def seal():
    assert not (CONTROL/'plan.json').exists(),'HandoffAlreadySealed'
    p=load(CONTROL/'drain-request.json');assert not live(p['oldPid'],p['oldEntry']) and not live(p['oldGraderPid'],p['oldGraderEntry']),'WaitForNaturalDrain'
    exit=load(OLD/'controller-exit.json');assert exit['pid']==p['oldPid'] and exit['stage']=='needs_attention' and exit['stopReason']=='RuntimeError:CellOutsideApproved429Scope',exit
    backup=CONTROL/'predecessor-plan.original';assert sha(backup)==p['originalPlanSha256']
    # Restore the exact old bytes only after it cannot claim work again.
    tmp=OLD/'plan.restore.tmp';tmp.write_bytes(backup.read_bytes());os.replace(tmp,OLD/'plan.json')
    assert old.source_pins()==load(OLD/'source-pins.json') and core.sourcepins()==load(OUT/'source-pins.json')
    for path,digest in p['protectedCompletedFiles'].items():assert sha(ROOT/path)==digest,('CompletedEvidenceChangedDuringDrain',path)
    review=audit_exception.inspect(ROOT,False);assert review['approvedExceptionAuditPassed'],review
    started=[d for d in (OUT/'tasks').glob('*/*') if d.is_dir() and any(d.iterdir())]
    for d in started:
        assert (d/'result.json').exists(),('UnsettledStartedCell',str(d))
        if (d/'native-process.json').exists():
            n=load(d/'native-process.json');assert not live(n['pid'],ROOT/'package/native.ts'),'NativeStillActive'
    cells={(d.parent.name,d.name) for d in started};rows=core.all_results();assert len(rows)==len(cells)
    # Every dispatch is either settled or the already approved original unknown receipt.
    orphans=list((OUT/'tasks').rglob('dispatch.json'));assert all((f.parent/'receipt.json').exists() for f in orphans),'UnsettledPaidDispatch'
    protected={f.relative_to(ROOT).as_posix():sha(f) for d in started for f in d.rglob('*') if f.is_file()}
    calls={d.parent.name+'/'+d.name:sorted(f.relative_to(ROOT).as_posix() for f in (d/'calls').rglob('*') if f.is_file()) for d in started}
    remaining=[e for e in old.plan()['remainingCells'] if (e['arm'],e['key']) not in cells]
    assert len(cells)+len(remaining)==483 and len(cells)>=54
    plan={'authorization':'User 2026-10-19 explicitly authorized actual concurrency 16/16/16 and controlled drain; no extra paid canary','concurrency':{'solve':16,'trainingFeedback':16,'parameterFit':16},'remainingCells':remaining,'protectedCells':sorted(cells),'protectedFiles':protected,'protectedCallFiles':calls,'approvedUnknown':old.plan()['approvedUnknown'],'priorOriginal54':54,'prior429CompletedAtSwitch':len(cells)-54,'noStartedCellsReplayed':True}
    common.durable(CONTROL/'plan.json',plan);preserve()
    h={**{k:p[k] for k in ['oldPid','oldEntry','oldGraderPid','oldGraderEntry','originalPlanSha256']},'drainedAndVerified':True,'sealedAtUtc':core.utc(),'preservedCells':len(cells),'remainingCells':len(remaining),'allStartedHaveResult':True,'noUnsettledDispatch':True,'originalControlHashesRestored':True,'oldExit':exit,'v2Accounting':common.accounting(OUT/'tasks'),'frozenCoreFiles':len(core.sourcepins()),'approvedExceptionAudit':review}
    common.durable(CONTROL/'handoff.json',h)
    proof=load(CONTROL/'free-checks.json');proof['checks'].append({'name':'live_handoff_settled_and_all_existing_evidence_frozen','passed':True});proof['sourceFingerprints']=pins();common.save(CONTROL/'free-checks.json',proof);common.durable(CONTROL/'source-pins.json',pins())
    print(json.dumps({k:h[k] for k in ['drainedAndVerified','sealedAtUtc','preservedCells','remainingCells','allStartedHaveResult','noUnsettledDispatch','originalControlHashesRestored','v2Accounting']}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['drain','status','seal']);globals()[p.parse_args().action]()
