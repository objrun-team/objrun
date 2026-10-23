"""One owner, 258 new primaries, then one isolated newly-failed repair round."""
import fcntl,subprocess,traceback
from shared import *
from isolation import Admission,GlobalFault
from selection import classify,usable_candidate

ADMISSION=Admission();CLAIMED=set();ROUND='main';ROUND_OUT=round_out('main');SOLVE=None
ORIGINAL_CALL=common.call;STATE={'pid':os.getpid(),'stage':'starting','round':'main','controllerEntry':str(CONTROL/'runner.py'),'graderEntry':str(CONTROL/'fit_service.py')}

def call(d,logical,body,*a,**kw):
    attempt=load(pathlib.Path(d)/'attempt.json')['attemptId'];ADMISSION.begin_call(d)
    try:return ORIGINAL_CALL(d,attempt+'--'+logical,body,*a,**kw)
    except common.UnknownDispatch:ADMISSION.unknown(d);raise
    finally:ADMISSION.end_call(d)

def claim(e):
    pair=(ROUND,e['arm'],e['key']);d=ROUND_OUT/'tasks'/e['arm']/e['key']
    if pair in CLAIMED or d.exists() and any(d.iterdir()):raise GlobalFault('AttemptAlreadyStarted')
    CLAIMED.add(pair)
    common.durable(d/'attempt.json',{'attemptId':e['attemptId'],'ownerPid':os.getpid(),'round':ROUND,'arm':e['arm'],'key':e['key'],'atUtc':utc(),'newIndependentAttempt':True})

def execute(e):
    d=ROUND_OUT/'tasks'/e['arm']/e['key'];t=next(t for t in core.CATALOG if t['key']==e['key'])
    r=core.execute(t,e['arm'])
    if not (d/'result.json').exists():
        if not common.HALT.is_set():raise GlobalFault('UnsettledResult')
        r={'protocolVersion':'v2','id':t['id'],'key':t['key'],'subset':t['subset'],'arm':e['arm'],'publicInputSha256':t['publicSha256'],'valid':False,'answer':'','error':'AccountStop:CampaignStopped','completedAtUtc':utc(),'completedAtMs':int(time.time()*1000),**common.accounting(d)}
        common.durable(d/'result.json',r)
    ADMISSION.settle(d)
    err=r.get('error','')
    if any(x in err for x in ['GraderInfrastructure','GraderProcessExited','AccountStop:','PermissionError','Unsettled','SourceChanged','FiniteProviderRetriesExhausted']):
        common.HALT.set();ADMISSION.close();raise GlobalFault(err)
    return r

def write_status():
    with common.LOCK:
        main=ledger(round_out('main')/'tasks');repair=ledger(round_out('repair')/'tasks');p=load(CONTROL/'plan.json');prior=p['historicalAccounting']
        state={**STATE,'updatedAtUtc':utc(),'active':list(core.STATE['active']),'completedByRound':{n:len(list(round_out(n).glob('tasks/*/*/result.json'))) for n in ['main','repair']},'expectedMain':len(p['selected']),'expectedRepair':len(load(OUT/'repair-plan.json')['selected']) if (OUT/'repair-plan.json').exists() else None,'concurrency':{'solve':16,'trainingFeedback':16,'parameterFit':16},'mainAccounting':main,'repairAccounting':repair,'historicalAccounting':prior,'cumulativeActualCostUsd':math.fsum([prior['actualCostUsd'],main['actualCostUsd'],repair['actualCostUsd']]),'cumulativeUpperBoundUsd':math.fsum([prior['accountedUpperBoundUsd'],main['accountedUpperBoundUsd'],repair['accountedUpperBoundUsd']]),'admissionPausedCells':sorted(ADMISSION.paused),'globalFault':STATE.get('globalFault'),'historicalAuditsPassed':False}
        common.save(OUT/'status.json',state)

def metrics():
    q={'atUtc':utc(),'round':ROUND,'solve':SOLVE.metrics(),'trainingFeedback':core.FEEDBACK_POOL.metrics(),'parameterFit':core.get(core.GRADER_URL+'/concurrency'),'claimed':sum(x[0]==ROUND for x in CLAIMED)}
    common.save(ROUND_OUT/'concurrency.json',q);common.save(OUT/'concurrency.json',q)
    return q

def freeze_round(name):
    d=round_out(name);rows=[load(p) for p in d.glob('tasks/*/*/result.json')]
    core.cost_snapshots(rows)
    value={'atUtc':utc(),'round':name,'idOodAccessed':False,'records':len(rows),'accounting':ledger(d/'tasks'),'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for folder in ['tasks','fits'] for p in (d/folder).rglob('*') if p.is_file()]}
    common.durable(d/'candidate-fee-freeze.json',value)
    return value

def prepare_repair(plan):
    cases=[];selected=[];main=ledger(round_out('main')/'tasks');left=78-plan['historicalAccounting']['accountedUpperBoundUsd']-main['accountedUpperBoundUsd']
    for e in plan['selected']:
        d=round_out('main')/'tasks'/e['arm']/e['key'];r=load(d/'result.json');a=ledger(d);c=classify(r,True,bool(a['unknownRequests']),usable_candidate(d,r));case={**e,**c,'sourceRound':'main','rawResultSha256':sha(d/'result.json'),'accounting':a}
        if c['eligible']:
            maximum=cap(e['arm'])
            if maximum<=left+1e-10:
                new={**e,'attemptId':plan['runId']+'-repair-'+e['arm']+'-'+e['key'],'maximumUsd':maximum};selected.append(new);case.update(selected=True,repairAttemptId=new['attemptId']);left-=maximum
            else:case.update(selected=False,budgetInsufficient=True)
        cases.append(case)
    p={'atUtc':utc(),'selected':selected,'cases':cases,'maxNewAttemptsPerCell':1,'sourceMainFreezeSha256':sha(round_out('main')/'candidate-fee-freeze.json'),'selectionUsesOnlyPublicTrainingAndExecution':True,'idOodAccessed':False}
    from checks import validate_repair_manifest
    validate_repair_manifest(p,plan)
    common.durable(OUT/'repair-plan.json',p)
    common.durable(OUT/'repair-free-checks.json',{'allPassed':True,'realApiCalls':0,'checks':['subset_of_this_primary_only','unique_pairs_and_attempts','one_attempt','candidate_and_training_failures_excluded','unknown_valid_candidate_reconcile_only','all_cost_caps_reserved'],'repairManifestSha256':sha(OUT/'repair-plan.json')})
    return p

def run_round(name,entries,prior):
    global ROUND,ROUND_OUT,ADMISSION,SOLVE
    ROUND=name;ROUND_OUT=set_round(name,prior);ADMISSION=Admission();SOLVE=Pool('solve-'+name)
    common.save(ROUND_OUT/'source-pins.json',core.sourcepins());common.save(ROUND_OUT/'runtime-accounting.json',prior)
    core.STATE.update(stage='running',active=[],round=name,controllerEntry=STATE['controllerEntry'],graderEntry=STATE['graderEntry']);STATE.update(round=name,stage='running')
    core.FEEDBACK_POOL.shutdown();core.FEEDBACK_POOL=Pool('feedback-'+name)
    port=core.freeport();core.GRADER_URL='http://127.0.0.1:'+str(port)
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['KEY','TOKEN','SECRET'])};env.update(GRADER_PORT=str(port),BENCH_ROUND=name)
    log=(ROUND_OUT/'grader.log').open('ab');core.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'fit_service.py')],env=env,stdout=log,stderr=log);STATE['graderPid']=core.GRADER.pid
    try:
        for _ in range(150):
            try:
                if core.get(core.GRADER_URL+'/health')['ok']:break
            except Exception:time.sleep(.1)
        else:raise GlobalFault('GraderStartupGlobalFault')
        jobs=iter(entries);done=threading.Event()
        def observer():
            while not done.wait(10):
                try:
                    if (CONTROL/'stop-claims.json').exists():ADMISSION.close()
                    verify_sources();metrics();write_status()
                    if core.GRADER.poll() is not None:raise GlobalFault('GraderProcessExited')
                except Exception as e:STATE['globalFault']=type(e).__name__+':'+str(e);common.HALT.set();ADMISSION.close()
        thread=threading.Thread(target=observer,daemon=True);thread.start()
        def consumer():
            while True:
                try:
                    e=ADMISSION.claim(jobs,claim)
                    if e is None:return
                    execute(e)
                except Exception as error:
                    STATE['globalFault']=type(error).__name__+':'+str(error);common.HALT.set();ADMISSION.close();raise
        futures=[SOLVE.submit(consumer) for _ in range(16)]
        failures=[]
        for f in futures:
            try:f.result()
            except Exception as error:failures.append(str(error))
        SOLVE.shutdown();core.FEEDBACK_POOL.shutdown();done.set();thread.join(timeout=15);metrics()
        if failures or STATE.get('globalFault'):STATE['stage']='needs_attention'
    finally:
        core.FEEDBACK_POOL.shutdown();SOLVE.shutdown()
        if core.GRADER is not None:core.GRADER.terminate();core.GRADER.wait(timeout=30)
    frozen=freeze_round(name);write_status()
    if frozen['records']!=len(entries):STATE['globalFault']=STATE.get('globalFault') or 'UnattemptedSelectedCells';STATE['stage']='needs_attention'
    return frozen

def main():
    lease=os.fdopen(int(os.environ['BENCH_ADMISSION_FD']),'a') if 'BENCH_ADMISSION_FD' in os.environ else (BASE/'llm-srbench-20261019-admission.lock').open('a')
    fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert all(processes_exited(r) for r in HISTORY),'OldControllerOrNativeStillLive'
    assert not (CONTROL/'runner.lock.json').exists(),'NeverRestartExistingController'
    verify_sources();verify_history();plan=load(CONTROL/'plan.json');assert load(CONTROL/'free-checks.json')['allPassed']
    common.durable(CONTROL/'runner.lock.json',{'pid':os.getpid(),'atUtc':utc()});common.call=call
    try:
        common.preflight();common.save(OUT/'provider-preflight.json',load(common.OUT/'provider-preflight.json'))
        first=run_round('main',plan['selected'],plan['historicalAccounting'])
        if not STATE.get('globalFault') and not common.HALT.is_set() and first['records']==len(plan['selected']):
            from reconcile import reconcile
            reconcile()
            repair=prepare_repair(plan)
            prior={k:math.fsum([plan['historicalAccounting'][k],first['accounting'][k]]) for k in ['actualCostUsd','accountedUpperBoundUsd','unknownReserveUsd']}
            run_round('repair',repair['selected'],prior)
            reconcile()
        from audit_round import audit
        review=audit(ROOT,originals=True);common.save(OUT/'audit.json',review)
        if not review['controlledAuditPassed']:STATE['globalFault']=STATE.get('globalFault') or 'ControlledAuditRejected'
        if not STATE.get('globalFault'):
            STATE['stage']='final_evaluation';write_status()
            import evaluate
            evaluate.main();verify_history();STATE['stage']='complete'
        else:STATE['stage']='needs_attention'
    except Exception as e:STATE.update(stage='needs_attention',globalFault=type(e).__name__+':'+str(e));traceback.print_exc()
    finally:
        common.HALT.set();write_status();common.save(CONTROL/'controller-exit.json',{'pid':os.getpid(),'atUtc':utc(),'stage':STATE['stage'],'globalFault':STATE.get('globalFault')})
if __name__=='__main__':main()
