"""16/16/16 supervisor for cells proven unstarted after a drained handoff."""
import fcntl,json,os,subprocess,threading,time,traceback
from support import *
CLAIMED=set();GUARD=threading.RLock();CLAIMS_CLOSED=threading.Event();SOLVE=MeteredPool(16,'solve')
def execute_new(task,arm):
    pair=(arm,task['key']);p=load(CONTROL/'plan.json');allowed={(e['arm'],e['key']) for e in p['remainingCells']}
    with GUARD:
        if CLAIMS_CLOSED.is_set() or core.STOP.is_set():return
        assert pair in allowed,'OutsideUnstartedScope'
        d=OUT/'tasks'/arm/task['key'];assert pair not in CLAIMED and (not d.exists() or not any(d.iterdir())),'AlreadyStarted'
        CLAIMED.add(pair);common.durable(CONTROL/'claims'/arm/(task['key']+'.json'),{'arm':arm,'key':task['key'],'atUtc':core.utc(),'ownerPid':os.getpid()})
    result=core.execute(task,arm)
    assert (d/'result.json').exists(),'StartedCellDidNotSettle'
    common.save(CONTROL/'segments'/arm/(task['key']+'.json'),{'arm':arm,'key':task['key'],'segment':'concurrency16','rawResultSha256':sha(d/'result.json')})
    return result
def metrics():
    q={'atUtc':core.utc(),'solve':SOLVE.metrics(),'trainingFeedback':core.FEEDBACK_POOL.metrics(),'parameterFit':core.get(core.GRADER_URL+'/concurrency'),'claimed':len(CLAIMED),'claimsClosed':CLAIMS_CLOSED.is_set()}
    common.save(CONTROL/'concurrency-latest.json',q)
    with (CONTROL/'concurrency-history.jsonl').open('a') as f:f.write(json.dumps(q)+'\n')
    return q
def observer():
    while not core.STOP.wait(3):
        if (CONTROL/'stop-claims.json').exists():CLAIMS_CLOSED.set()
        try:metrics();core.status()
        except Exception:traceback.print_exc()
def main():
    # OS lock plus verified predecessor exit fence: no overlap in task admission.
    owner=(OUT/'controller-admission.lock').open('a');fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert not (CONTROL/'runner.lock.json').exists(),'NoAutomaticRelaunch'
    p=preserve();handoff=load(CONTROL/'handoff.json')
    assert handoff['drainedAndVerified'] and not live(handoff['oldPid'],handoff['oldEntry']) and not live(handoff['oldGraderPid'],handoff['oldGraderEntry'])
    assert pins()==load(CONTROL/'source-pins.json'),'NewControlChanged'
    proof=load(CONTROL/'free-checks.json');assert proof['allPassed'] and proof['realApiCalls']==0
    for e in p['remainingCells']:
        d=OUT/'tasks'/e['arm']/e['key'];assert not d.exists() or not any(d.iterdir()),'UnapprovedReplay'
    common.durable(CONTROL/'runner.lock.json',{'pid':os.getpid(),'atUtc':core.utc()})
    core.STATE.update(stage='starting_concurrency16',controllerEntry=str(CONTROL/'runner.py'),graderEntry=str(CONTROL/'fit_service.py'),protocolVersion='v2',executionSegment='concurrency16',expectedNewRecords=483,preservedV2Records=len(p['protectedCells']),segmentCells=len(p['remainingCells']),originalOfflineAuditPassed=False,approvedUnknownCells=[{'arm':'objrun','key':'aa6d065a7b7d4d4bd2f0c0b2'}],concurrency={'solve':16,'trainingFeedback':16,'parameterFit':16})
    try:
        old.continuation.verify_plan();old.continuation.acceptance();common.preflight();hold=old.apply_extra_hold()
        common.save(CONTROL/'balance-hold.json',{'additionalHoldUsd':hold,'existingV1HoldUsd':common.CFG['priorUnknownReserveUsd'],'remainingAfterHoldsUsd':common.ACCOUNT_REMAINING})
        core.FEEDBACK_POOL.shutdown(wait=True);core.FEEDBACK_POOL=MeteredPool(16,'training-feedback')
        port=core.freeport();core.GRADER_URL='http://127.0.0.1:'+str(port)
        env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['KEY','TOKEN','SECRET'])};env['GRADER_PORT']=str(port)
        log=(CONTROL/'grader.log').open('ab');core.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'fit_service.py')],env=env,stdout=log,stderr=log)
        core.STATE.update(graderPid=core.GRADER.pid,graderUrl=core.GRADER_URL)
        for _ in range(150):
            try:
                if core.get(core.GRADER_URL+'/health')['ok']:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('GraderStartup')
        core.STATE['stage']='running';core.status();threading.Thread(target=observer,daemon=True).start()
        jobs=iter(p['remainingCells']);book={t['key']:t for t in core.CATALOG}
        def consumer():
            while not core.STOP.is_set():
                with GUARD:
                    if CLAIMS_CLOSED.is_set() or (CONTROL/'stop-claims.json').exists():CLAIMS_CLOSED.set();return
                    try:e=next(jobs)
                    except StopIteration:return
                execute_new(book[e['key']],e['arm'])
        futures=[SOLVE.submit(consumer) for _ in range(16)]
        try:
            for f in futures:f.result()
        finally:SOLVE.shutdown(wait=True);core.FEEDBACK_POOL.shutdown(wait=True)
        metrics()
        if core.STOP.is_set():core.STATE['stage']='needs_attention';return
        if CLAIMS_CLOSED.is_set():core.STATE.update(stage='drained',stopReason='UserRequestedAdmissionDrain');return
        rows=core.all_results();assert len(rows)==483 and len(CLAIMED)==len(p['remainingCells'])
        preserve()
        # Preserve ALL predecessor raw directories. Frozen finalize computes checkpoints
        # in its analysis copy, after all 483 candidates and full costs are frozen.
        common.save(OUT/'all-candidates-frozen.json',{'atUtc':core.utc(),'count':483,'allPredecessorCellsPreserved':True,'costCheckpointsInAnalysis':True,'idOodAccessed':False,'records':[{'arm':r['arm'],'key':r['key'],'sha256':r.get('finalCandidateSha256'),'valid':r['valid']} for r in rows]})
        audit=audit_exception.inspect(ROOT,True);common.save(CONTROL/'exception-audit.json',audit);assert audit['approvedExceptionAuditPassed'],audit
        core.STATE.update(stage='final_evaluation',approvedExceptionAuditPassed=True);core.status();old.final_analysis()
        for directory in [OUT,ROOT/'analysis/outputs']:
            report=directory/'REPORT.md';report.write_text(report.read_text()+'\n\nConcurrency transition: after the old controller drained and exited, only '+str(len(p['remainingCells']))+' unstarted units used the independent 16/16/16 controller. The preceding '+str(len(p['protectedCells']))+' original v2 records remain unchanged; execution-segment manifests, hashes, and concurrency observations are in outputs/concurrency16.\n',encoding='utf8')
            summary=load(directory/'summary.json');summary['concurrencyHandoff']={'preserved':len(p['protectedCells']),'concurrency16':len(p['remainingCells']),'capacities':[16,16,16],'allOriginalAuditsPassed':False};common.save(directory/'summary.json',summary)
        preserve();core.STATE['stage']='complete_with_exceptions'
    except Exception as e:core.STATE.update(stage='needs_attention',stopReason=type(e).__name__+':'+str(e));traceback.print_exc()
    finally:
        core.STOP.set()
        if core.GRADER is not None:core.GRADER.terminate();core.GRADER.wait(timeout=15)
        core.status();common.save(CONTROL/'controller-exit.json',{'pid':os.getpid(),'atUtc':core.utc(),'stage':core.STATE['stage'],'stopReason':core.STATE.get('stopReason')})
if __name__=='__main__':main()
