"""One new attempt per frozen infrastructure cell; 16/16/16, all old cells immutable."""
import fcntl,os,subprocess,traceback
from shared import *
CLAIMED=set();GUARD=threading.RLock();CLOSE=threading.Event();SOLVE=Pool('solve');BASE_CALL=common.call
def call(taskdir,logical,body,*args,**kw):
    attempt=load(pathlib.Path(taskdir)/'attempt.json')['attemptId']
    return BASE_CALL(taskdir,attempt+'--'+logical,body,*args,**kw)
def execute(e):
    pair=(e['arm'],e['key']);d=OUT/'tasks'/e['arm']/e['key']
    assert pair in {(x['arm'],x['key']) for x in load(CONTROL/'plan.json')['selected']},'OutsideFrozenSupplementalScope'
    with GUARD:
        if CLOSE.is_set() or core.STOP.is_set():return
        assert pair not in CLAIMED and (not d.exists() or not any(d.iterdir())),'SupplementalAttemptAlreadyStarted'
        CLAIMED.add(pair);common.durable(d/'attempt.json',{'attemptId':e['attemptId'],'arm':e['arm'],'key':e['key'],'ownerPid':os.getpid(),'atUtc':utc(),'independentAttempt':True,'oldLogicalRequestsReplayed':False})
    task=next(t for t in core.CATALOG if t['key']==e['key'])
    # No original status, candidate, error or evaluation is passed to execute/native.
    result=core.execute(task,e['arm'])
    if not (d/'result.json').exists():
        assert core.STOP.is_set(),'UnsettledNewAttempt'
        common.durable(d/'result.json',{'protocolVersion':'v2','id':task['id'],'key':task['key'],'subset':task['subset'],'arm':e['arm'],'publicInputSha256':task['publicSha256'],'valid':False,'answer':'','error':'CampaignStoppedBeforeNewAttemptDispatch','completedAtUtc':utc(),'completedAtMs':int(time.time()*1000),**common.accounting(d)})
    return result
def metrics():
    q={'atUtc':utc(),'solve':SOLVE.metrics(),'trainingFeedback':core.FEEDBACK_POOL.metrics(),'parameterFit':core.get(core.GRADER_URL+'/concurrency'),'claimed':len(CLAIMED)};common.save(OUT/'concurrency.json',q);return q
def observer():
    while not core.STOP.wait(10):
        if (CONTROL/'stop-claims.json').exists():CLOSE.set()
        try:metrics();core.status()
        except Exception:traceback.print_exc()
def main():
    lock=(ROOT/'admission.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert not (CONTROL/'runner.lock.json').exists(),'OneRoundOnlyNoAutomaticRestart'
    import prepare
    ready,why=prepare.ready();assert ready,why
    verify_sources();verify_originals();p=load(CONTROL/'plan.json');proof=load(CONTROL/'free-checks.json');assert proof['allPassed'] and proof['realApiCalls']==0
    assert not list((OUT/'tasks').glob('*/*/attempt.json')),'NeverResumeOldSupplementalCell'
    common.durable(CONTROL/'runner.lock.json',{'pid':os.getpid(),'atUtc':utc()});common.call=call
    core.STATE.update(stage='starting',controllerEntry=str(CONTROL/'runner.py'),graderEntry=str(CONTROL/'fit_service.py'),executionSegment='infrastructure-r1',roundId=p['roundId'],expectedRecords=len(p['selected']),concurrency={'solve':16,'trainingFeedback':16,'parameterFit':16})
    core.status()
    try:
        import reconcile
        reconcile.main()
        if not p['selected']:
            common.durable(OUT/'candidate-fee-freeze.json',{'atUtc':utc(),'roundId':p['roundId'],'selected':0,'started':0,'completed':0,'records':[],'files':[],'accounting':ledger(OUT/'tasks'),'idOodAccessed':False})
            import audit_round,evaluate
            common.save(OUT/'audit.json',audit_round.audit(True));evaluate.main();core.STATE['stage']='complete';return
        common.preflight();common.save(OUT/'balance-hold.json',{'originalUnknownReserveUsd':common.CFG['priorUnknownReserveUsd'],'remainingAfterHoldUsd':common.ACCOUNT_REMAINING})
        core.FEEDBACK_POOL.shutdown();core.FEEDBACK_POOL=Pool('feedback');port=core.freeport();core.GRADER_URL='http://127.0.0.1:'+str(port)
        env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ['KEY','TOKEN','SECRET'])};env['GRADER_PORT']=str(port);log=(OUT/'grader.log').open('ab');core.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'fit_service.py')],env=env,stdout=log,stderr=log);core.STATE.update(graderPid=core.GRADER.pid)
        for _ in range(150):
            try:
                if core.get(core.GRADER_URL+'/health')['ok']:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('SupplementalGraderStartup')
        core.STATE['stage']='running';core.status();threading.Thread(target=observer,daemon=True).start();jobs=iter(p['selected'])
        def consumer():
            while not core.STOP.is_set() and not CLOSE.is_set():
                with GUARD:
                    if (CONTROL/'stop-claims.json').exists():CLOSE.set();return
                    try:e=next(jobs)
                    except StopIteration:return
                try:execute(e)
                except Exception:CLOSE.set();raise
        fs=[SOLVE.submit(consumer) for _ in range(16)]
        try:
            for f in fs:f.result()
        finally:SOLVE.shutdown();core.FEEDBACK_POOL.shutdown()
        metrics();rows=core.all_results();core.cost_snapshots(rows)
        common.durable(OUT/'candidate-fee-freeze.json',{'atUtc':utc(),'roundId':p['roundId'],'selected':len(p['selected']),'started':len(CLAIMED),'completed':len(rows),'records':[{'arm':r['arm'],'key':r['key'],'rawResultSha256':sha(OUT/'tasks'/r['arm']/r['key']/'result.json'),'answerSha256':r.get('finalCandidateSha256')} for r in rows],'files':[{'path':f.relative_to(ROOT).as_posix(),'sha256':sha(f)} for d in [OUT/'tasks',OUT/'fits'] for f in d.rglob('*') if f.is_file()],'accounting':ledger(OUT/'tasks'),'idOodAccessed':False})
        import audit_round
        review=audit_round.audit(len(rows)==len(p['selected']));common.save(OUT/'audit.json',review)
        # New unknown costs stay reserved. The one round stops; never regenerate it.
        critical=[x for x in review['issues'] if not x.startswith('TerminatedUnknownPaidRequest:') and x!='UnattemptedSelectedCells']
        if critical:core.STATE['stage']='needs_attention';return
        core.STATE['stage']='final_evaluation';core.status()
        import evaluate
        evaluate.main();verify_originals();core.STATE['stage']='complete' if review['allPassed'] and not core.STOP.is_set() and not CLOSE.is_set() else 'complete_partial'
    except Exception as e:core.STATE.update(stage='needs_attention',stopReason=type(e).__name__+':'+str(e));traceback.print_exc()
    finally:
        core.STOP.set()
        if core.GRADER is not None:core.GRADER.terminate();core.GRADER.wait(timeout=15)
        core.status();common.save(CONTROL/'controller-exit.json',{'pid':os.getpid(),'atUtc':utc(),'stage':core.STATE['stage'],'stopReason':core.STATE.get('stopReason')})
if __name__=='__main__':main()
