"""Free tests for the additional controller. Actual frozen v2 solver is not changed."""
import hashlib,json,pathlib,shutil,subprocess,sys,tempfile
import runner as driver,audit_exception
ROOT=driver.ROOT;CONTROL=driver.CONTROL;checks=[]
def check(name,condition):assert condition,name;checks.append({'name':name,'passed':True})
p=driver.protect();check('live_frozen_core_and_54_records_protected_429_scope',len(p['remainingCells'])==429)
report=audit_exception.inspect(ROOT,False)
check('original_audit_still_fails_only_approved_unresolved_request',report['approvedExceptionAuditPassed'] and not report['originalOfflineAuditPassed'] and len(report['originalAudit']['issues'])==1)
before=driver.common.ACCOUNT_REMAINING;driver.common.ACCOUNT_REMAINING=1
driver.apply_extra_hold();check('additional_unknown_bill_hold_is_reserved',abs(driver.common.ACCOUNT_REMAINING-(1-.0496791))<1e-12);driver.common.ACCOUNT_REMAINING=before
with tempfile.TemporaryDirectory(prefix='scope-free-',dir=CONTROL) as td:
    tmp=pathlib.Path(td);oldcontrol=driver.CONTROL;oldout=driver.OUT;oldexecute=driver.core.execute
    driver.CONTROL=tmp;driver.OUT=tmp/'outputs';(tmp/'plan.json').write_text(json.dumps(p));calls=[]
    def fake(task,arm):
        calls.append((arm,task['key']));d=driver.OUT/'tasks'/arm/task['key'];driver.save(d/'result.json',{'arm':arm,'key':task['key'],'fixture':True});return {'fixture':True}
    driver.core.execute=fake
    try:
        arm,key=p['protectedCells'][0]
        try:driver.execute_new({'key':key},arm)
        except RuntimeError as e:assert str(e)=='CellOutsideApproved429Scope'
        else:raise AssertionError('Protected cell reached the solver')
        check('protected_cell_rejected_before_solver_or_write',not calls)
        e=p['remainingCells'][0];driver.execute_new({'key':e['key']},e['arm'])
        try:driver.execute_new({'key':e['key']},e['arm'])
        except RuntimeError as ex:assert str(ex)=='ContinuationCellAlreadyStarted'
        else:raise AssertionError('Duplicate cell reached the solver')
        check('fresh_cell_executes_once_duplicate_start_rejected',len(calls)==1)
    finally:driver.CONTROL=oldcontrol;driver.OUT=oldout;driver.core.execute=oldexecute;driver.CLAIMED.clear()
with tempfile.TemporaryDirectory(prefix='audit-free-',dir=CONTROL,ignore_cleanup_errors=True) as td:
    fixture=pathlib.Path(td);shutil.copytree(ROOT/'package',fixture/'package',ignore=shutil.ignore_patterns('__pycache__','node_modules','.env'))
    (fixture/'data/public').mkdir(parents=True);shutil.copy2(ROOT/'data/public/catalog.json',fixture/'data/public/catalog.json')
    (fixture/'outputs/continuation-429').mkdir(parents=True);shutil.copy2(CONTROL/'plan.json',fixture/'outputs/continuation-429/plan.json');shutil.copy2(ROOT/'outputs/source-pins.json',fixture/'outputs/source-pins.json')
    shutil.copytree(ROOT/'outputs/tasks',fixture/'outputs/tasks')
    assert audit_exception.inspect(fixture,False)['approvedExceptionAuditPassed']
    e=next(e for e in p['remainingCells'] if e['arm']=='baseline');t=next(t for t in driver.core.CATALOG if t['key']==e['key']);d=fixture/'outputs/tasks'/e['arm']/e['key'];call=d/'calls/free-new-unknown/attempt-0'
    driver.save(call/'request.json',driver.common.wire({'messages':[{'role':'user','content':t['prompt']}]}));driver.save(call/'dispatch.json',{'dispatchAtMs':0,'reservedUpperBoundUsd':.02});driver.save(call/'receipt.json',{'actualCostUsd':None,'unknownCost':True,'reservedUpperBoundUsd':.02});(call/'response.raw.txt').write_text(' ')
    driver.save(d/'result.json',{'protocolVersion':'v2','id':e['id'],'arm':e['arm'],'key':e['key'],'publicInputSha256':t['publicSha256'],'valid':False,'answer':'','completedAtMs':1,'actualCostUsd':0,'accountedUpperBoundUsd':.02,'unknownCostCount':1,'modelCalls':1,'error':'SyntheticUnknownFixture'})
    red=audit_exception.inspect(fixture,False)
    check('real_original_auditor_rejects_any_second_unknown',not red['approvedExceptionAuditPassed'] and len(red['originalAudit']['issues'])==2)
    shutil.rmtree(d)
    path=next(path for path in p['protectedFiles'] if path.endswith('response.raw.txt'));file=fixture/path;file.write_bytes(file.read_bytes()+b' ')
    red=audit_exception.inspect(fixture,False)
    check('protected_original_raw_response_mutation_rejected',not red['approvedExceptionAuditPassed'] and any('protectedEvidenceChanged' in x for x in red['additionalIssues'] if isinstance(x,dict)))
v=driver.annotate_combined({'v2AuditPassed':True,'allVersionsIntegrityPassed':True})
check('analysis_never_labels_original_v2_audit_as_passed',v['v2AuditPassed'] is False and v['allVersionsIntegrityPassed'] is False and v['approvedExceptionAuditPassed'])
# Re-run the actual frozen 960-mapping finalizer under the production annotation.
code=r'''
import pathlib,sys
r=pathlib.Path(__ROOT__);control=r/'outputs/continuation-429';sys.path.insert(0,str(control));sys.path.insert(0,str(r/'package'))
import runner as d,continuation
original=continuation.save
def honest(p,v):
    if pathlib.Path(p).name=='combined-analysis-audit.json':
        v=d.annotate_combined(v);assert v['v2AuditPassed'] is False and v['approvedExceptionAuditPassed']
    return original(p,v)
continuation.save=honest
src=r/'combined_v2_control.py';text=src.read_text().replace("save(REAL/'outputs/controls/combined-free-checks.json',proof)","save(REAL/'outputs/continuation-429/full-finalizer-free-checks.json',proof)")
exec(compile(text,str(src),'exec'),{'__file__':str(src),'__name__':'__main__'})
'''.replace('__ROOT__',repr(str(ROOT)))
q=subprocess.run([str(ROOT/'runtime/bin/python'),'-c',code],capture_output=True,text=True,timeout=360)
assert q.returncode==0,q.stderr[-2500:]
proof=json.loads((CONTROL/'full-finalizer-free-checks.json').read_text());check('actual_960_mapping_finalizer_preserves_failure_and_raw_fees',proof['allPassed'] and proof['rawV1BytesAndCostMismatchPreserved'])
result={'allPassed':True,'realApiCalls':0,'frozenV2FilesChecked':len(driver.core.sourcepins()),'original33FreeChecksRetained':True,'checks':checks,'sourceFingerprints':driver.source_pins()}
driver.save(CONTROL/'free-checks.json',result);print(json.dumps(result))
