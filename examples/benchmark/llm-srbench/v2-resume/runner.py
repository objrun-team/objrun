"""Human-approved controller for 429 untouched cells; imports the unmodified v2 solver."""
import concurrent.futures,hashlib,json,os,pathlib,shutil,subprocess,sys,threading,time,traceback
CONTROL=pathlib.Path(__file__).resolve().parent;ROOT=CONTROL.parents[1];OUT=ROOT/'outputs'
sys.path.insert(0,str(ROOT/'package'))
import common,run as core,continuation
import audit_exception
from common import save,durable,digest,accounting
def plan():return json.loads((CONTROL/'plan.json').read_text())
def source_pins():return [{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(CONTROL.iterdir()) if p.name in ['runner.py','audit_exception.py','checks.py','launch.py','export.py','ops.py','plan.json','README.md']]
def protect():
    p=plan();assert p['authorization']['humanAnswer']=='保留异常，仅续跑429单元'
    assert core.sourcepins()==json.loads((OUT/'source-pins.json').read_text()),'FrozenV2PackageChanged'
    report=audit_exception.inspect(ROOT,False);assert report['approvedExceptionAuditPassed'],report['additionalIssues']
    original={(e['arm'],e['key']) for e in json.loads((ROOT/'package/continuation-plan.json').read_text())['allowedCells']}
    allowed={(e['arm'],e['key']) for e in p['remainingCells']};old={tuple(e) for e in p['protectedCells']}
    assert len(allowed)==429 and len(old)==54 and not allowed&old and allowed|old==original
    return p
def apply_extra_hold():
    hold=plan()['approvedUnknown']['reservedUpperBoundUsd']
    assert common.ACCOUNT_REMAINING is not None
    common.ACCOUNT_REMAINING-=hold
    if common.ACCOUNT_REMAINING<=0:raise common.AccountStop('InsufficientBalanceAfterApprovedUnknownHold')
    return hold
CLAIMED=set();GUARD=threading.RLock()
def execute_new(task,arm):
    pair=(arm,task['key']);allowed={(e['arm'],e['key']) for e in plan()['remainingCells']}
    if pair not in allowed:raise RuntimeError('CellOutsideApproved429Scope')
    with GUARD:
        d=OUT/'tasks'/arm/task['key']
        if pair in CLAIMED or (d.exists() and any(d.iterdir())):raise RuntimeError('ContinuationCellAlreadyStarted')
        if core.STOP.is_set():return None
        CLAIMED.add(pair)
    result=core.execute(task,arm)
    if (d/'result.json').exists():save(CONTROL/'segments'/arm/(task['key']+'.json'),{'arm':arm,'key':task['key'],'segment':'approved-429','rawResultSha256':hashlib.sha256((d/'result.json').read_bytes()).hexdigest()})
    return result
def annotate_combined(value):
    return {**value,'v2AuditPassed':False,'originalV2OfflineAuditPassed':False,'approvedExceptionAuditPassed':True,'approvedUnknownCostReserveUsd':plan()['approvedUnknown']['reservedUpperBoundUsd'],'allVersionsIntegrityPassed':False}
def final_analysis():
    original_save=continuation.save
    def honest_save(path,value):
        if pathlib.Path(path)==OUT/'combined-analysis-audit.json':value=annotate_combined(value)
        return original_save(path,value)
    continuation.save=honest_save
    try:continuation.finalize(core)
    finally:continuation.save=original_save
    provenance={'originalV1AuditPassed':False,'originalV2OfflineAuditPassed':False,'approvedExceptionAuditPassed':True,'unresolvedV2CostReserveUsd':plan()['approvedUnknown']['reservedUpperBoundUsd'],'v2Segments':{'initial':54,'approvedContinuation':429},'frozenV2SolverUnchanged':True}
    for directory in [OUT,ROOT/'analysis/outputs']:
        report=directory/'REPORT.md';shutil.copy2(report,directory/'REPORT.original-v2.md')
        report.write_text(report.read_text()+'\n\n用户批准保留v2的一条未知费用异常后，仅续跑429个原未启动单元；最初54条记录未改动。冻结v2求解器不变，独立控制有单独哈希。原版v1审计及v2费用审计仍未通过；独立例外审计仅确认唯一已批准未知费用及其上界保持原样，所有其他检查通过，不代表全部费用已知。\n',encoding='utf8')
        summary=directory/'summary.json';shutil.copy2(summary,directory/'summary.original-v2.json');v=json.loads(summary.read_text());v['auditProvenance']=provenance;save(summary,v)
    save(CONTROL/'final-provenance.json',provenance)
def main():
    lock=CONTROL/'runner.lock.json'
    if lock.exists():raise RuntimeError('ContinuationLaunchOrRecoveryRequiresAudit')
    durable(lock,{'pid':os.getpid(),'entry':str(CONTROL/'runner.py'),'atUtc':core.utc()})
    auth=plan();core.STATE.update(stage='starting_approved_continuation',controllerEntry=str(CONTROL/'runner.py'),protocolVersion='v2',executionSegment='approved-429',expectedNewRecords=483,approvedAdditionalCells=429,preservedV2Records=54,originalOfflineAuditPassed=False,approvedUnknownCells=[{'arm':auth['approvedUnknown']['arm'],'key':auth['approvedUnknown']['key']}]);core.status()
    try:
        p=protect();assert source_pins()==json.loads((CONTROL/'source-pins.json').read_text()),'ContinuationControlChanged'
        checks=json.loads((CONTROL/'free-checks.json').read_text());assert checks['allPassed'] and checks['realApiCalls']==0
        continuation.verify_plan();continuation.acceptance()
        for e in p['remainingCells']:
            d=OUT/'tasks'/e['arm']/e['key'];assert not d.exists() or not any(d.iterdir()),'UnapprovedResumeOfStartedCell'
        common.preflight();hold=apply_extra_hold();save(CONTROL/'balance-hold.json',{'additionalHoldUsd':hold,'existingV1HoldUsd':common.CFG['priorUnknownReserveUsd'],'remainingAfterHoldsUsd':common.ACCOUNT_REMAINING})
        port=core.freeport();core.GRADER_URL='http://127.0.0.1:'+str(port)
        env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ['KEY','TOKEN','SECRET'])};env['GRADER_PORT']=str(port)
        log=(CONTROL/'grader.log').open('ab');core.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(ROOT/'package/grader.py')],env=env,stdout=log,stderr=log)
        core.STATE.update(stage='starting_approved_continuation',controllerEntry=str(CONTROL/'runner.py'),graderPid=core.GRADER.pid,protocolVersion='v2',executionSegment='approved-429',expectedNewRecords=483,approvedAdditionalCells=429,preservedV2Records=54,originalOfflineAuditPassed=False,approvedUnknownCells=[{'arm':p['approvedUnknown']['arm'],'key':p['approvedUnknown']['key']}])
        core.status()
        for _ in range(100):
            try:
                if core.get(core.GRADER_URL+'/health')['ok']:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('GraderStartup')
        threading.Thread(target=core.heartbeat,daemon=True).start();core.STATE['stage']='running';core.status()
        book={t['key']:t for t in core.CATALOG};jobs=iter(p['remainingCells'])
        def consumer():
            while not core.STOP.is_set():
                with GUARD:
                    try:e=next(jobs)
                    except StopIteration:return
                execute_new(book[e['key']],e['arm'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:consumer(),range(4)))
        if core.STOP.is_set():core.STATE['stage']='needs_attention';return
        rows=core.all_results();assert len(rows)==483 and len(CLAIMED)==429
        # Do not add or change files under the original 54 cells. Their cost checkpoints
        # are computed on the analysis copy, before any ID/OOD access, by frozen finalize().
        newrows=[r for r in rows if (r['arm'],r['key']) in CLAIMED];core.cost_snapshots(newrows)
        save(OUT/'all-candidates-frozen.json',{'atUtc':core.utc(),'count':483,'original54Preserved':True,'inheritedCostCheckpointsInAnalysis':True,'idOodAccessed':False,'records':[{'arm':r['arm'],'key':r['key'],'sha256':r.get('finalCandidateSha256'),'valid':r['valid']} for r in rows]})
        review=audit_exception.inspect(ROOT,True);save(CONTROL/'exception-audit.json',review);save(CONTROL/'original-v2-audit.json',review['originalAudit'])
        assert review['approvedExceptionAuditPassed'],review['additionalIssues']
        core.STATE.update(stage='final_evaluation',approvedExceptionAuditPassed=True);core.status();final_analysis()
        assert audit_exception.inspect(ROOT,True)['approvedExceptionAuditPassed']
        core.STATE['stage']='complete_with_exceptions'
    except Exception as e:core.STATE.update(stage='needs_attention',stopReason=type(e).__name__+':'+str(e));traceback.print_exc()
    finally:
        core.STOP.set()
        if core.GRADER is not None:core.GRADER.terminate();core.GRADER.wait(timeout=15)
        core.status();save(CONTROL/'controller-exit.json',{'atUtc':core.utc(),'pid':os.getpid(),'stage':core.STATE['stage'],'stopReason':core.STATE.get('stopReason')})
if __name__=='__main__':main()
