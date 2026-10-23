"""Free tests: actual backend/isolation, atomic reservations and full two-round flow."""
import copy,fcntl,shutil,subprocess,tempfile,urllib.request
from shared import *
from isolation import Admission,GlobalFault
from selection import classify
CHECKS=[]
def check(name,value):assert value,name;CHECKS.append({'name':name,'passed':True})

def validate_repair_manifest(p,plan):
    selected=p['selected'];primary={(e['arm'],e['key']) for e in plan['selected']}
    assert len({(e['arm'],e['key']) for e in selected})==len(selected)
    assert len({e['attemptId'] for e in selected})==len(selected)
    assert {(e['arm'],e['key']) for e in selected}<=primary
    assert p['maxNewAttemptsPerCell']==1 and not p['idOodAccessed']
    assert not any(c.get('selected') for c in p['cases'] if c['route'] in ['normal_completion','candidate_failure_not_repairable','reconcile_only'])
    assert all(e['maximumUsd']==cap(e['arm']) for e in selected)

def pools():
    for name in ['solve','feedback','fit']:
        p=Pool(name);gate=threading.Barrier(17);release=threading.Event();done=threading.Event()
        futures=[p.submit(lambda:(gate.wait(timeout=10),release.wait(10))) for _ in range(16)];gate.wait(timeout=10)
        check(name+'_16_parallel',p.metrics()['active']==p.metrics()['peak']==16)
        t=threading.Thread(target=lambda:(p.shutdown(),done.set()));t.start();time.sleep(.03);check(name+'_shutdown_waits_for_inflight',not done.is_set());release.set();t.join(10);assert done.is_set()
    gate=common.CellDispatchGate();gate.begin();closed=threading.Event();t=threading.Thread(target=lambda:(gate.close(),closed.set()));t.start();time.sleep(.03)
    check('real_provider_gate_close_waits_for_original_request',not closed.is_set());gate.end();t.join(10);assert closed.is_set()
    try:gate.begin()
    except common.TaskBudgetStop:check('closed_gateway_rejects_new_provider_dispatch',True)
    else:raise AssertionError('Close admitted a request')

def admission():
    a=Admission();a.unknown('/synthetic-cell');claimed=[];future=[]
    t=threading.Thread(target=lambda:future.append(a.claim(iter([1]),lambda e:claimed.append(e))));t.start();time.sleep(.03)
    check('unknown_pauses_next_claim_without_killing_inflight',not claimed)
    with a.condition:a.paused.clear();a.condition.notify_all()
    t.join(5);check('settled_unknown_allows_other_unstarted_cells',claimed==future==[1])
    a=Admission();jobs=iter([1]);claimed=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:got=list(pool.map(lambda _:a.claim(jobs,lambda e:claimed.append(e)),range(16)))
    check('16_claimers_only_one_unique_task',claimed==[1] and sum(x is not None for x in got)==1)
    a.close();check('closed_admission_does_not_restart_pending_units',a.claim(iter([2]),lambda _:None) is None)
    with tempfile.TemporaryDirectory(dir=ROOT) as td:
        p=pathlib.Path(td)/'lease';held=p.open('a');fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        script="import fcntl,sys;f=open(sys.argv[1],'a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        q=subprocess.run([sys.executable,'-c',script,str(p)],capture_output=True)
        check('shared_os_lease_rejects_second_controller',q.returncode!=0)
        inherited="import fcntl,os,sys;f=os.fdopen(int(sys.argv[1]),'a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);print('inherited')"
        q=subprocess.run([sys.executable,'-c',inherited,str(held.fileno())],pass_fds=(held.fileno(),),capture_output=True,text=True)
        check('launch_transfers_same_lease_without_unlock_gap',q.returncode==0 and q.stdout.strip()=='inherited')
        held.close()

def reservations():
    saved=(common.OUT,copy.deepcopy(common.CFG),common.ACCOUNT_REMAINING,common.ACCOUNT_RESERVED,common.RESERVED,urllib.request.urlopen)
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='reservation-free-') as td:
        common.OUT=pathlib.Path(td);common.CFG.update(priorUpperBoundUsd=77.96);common.ACCOUNT_REMAINING=.04;common.ACCOUNT_RESERVED=0;common.RESERVED={};common.HALT.clear()
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return json.dumps({'id':'synthetic-'+str(threading.get_ident()),'provider':'DigitalOcean','model':common.CFG['model'],'usage':{'cost':.001},'choices':[{'message':{'content':'{}'}}]}).encode()
        urllib.request.urlopen=lambda *a,**k:Response()
        def task(i):
            try:common.call(common.OUT/'tasks/baseline'/str(i),'new-independent-request-'+str(i),{'messages':[{'role':'user','content':'synthetic public'}]})
            except common.AccountStop:pass
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as p:list(p.map(task,range(16)))
            fees=ledger(common.OUT/'tasks');check('16_atomic_reservations_never_exceed_78_with_prior_holds',77.96+fees['accountedUpperBoundUsd']<=78+1e-9)
            check('atomic_reservations_fully_settle_after_close',abs(common.ACCOUNT_RESERVED)<1e-10 and not fees['unknownRequests'])
        finally:
            common.OUT= saved[0];common.CFG.clear();common.CFG.update(saved[1]);common.ACCOUNT_REMAINING,common.ACCOUNT_RESERVED,common.RESERVED,urllib.request.urlopen=saved[2:];common.HALT.clear()

def isolation_failures():
    from isolation import Admission
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='unknown-free-') as td:
        d=pathlib.Path(td)/'tasks/baseline'/('f'*24);p=d/'calls/new/attempt-0';request=common.wire({'messages':[{'role':'user','content':'synthetic'}]});raw=json.dumps(request,ensure_ascii=False,separators=(',',':')).encode();bound=len(raw)*.3/1e6+16384*1.2/1e6
        common.save(p/'request.json',request);common.save(p/'dispatch.json',{'requestSha256':hashlib.sha256(raw).hexdigest(),'reservedUpperBoundUsd':bound,'dispatchAtMs':1})
        gate=Admission();gate.unknown(d)
        try:gate.settle(d,0)
        except GlobalFault:check('orphan_without_terminal_receipt_is_global_fault',str(d) in gate.paused)
        else:raise AssertionError('orphan accepted')
        common.save(p/'receipt.json',{'actualCostUsd':None,'reservedUpperBoundUsd':bound/2,'completedAtMs':2})
        try:gate.settle(d,0)
        except GlobalFault:check('unknown_without_full_trustworthy_reserve_is_global_fault',True)
        else:raise AssertionError('bad reserve accepted')
        common.save(p/'receipt.json',{'actualCostUsd':None,'reservedUpperBoundUsd':bound,'completedAtMs':2})
        q=gate.settle(d,0);check('bounded_terminal_unknown_keeps_entire_reserve',q['accounting']['unknownReserveUsd']==bound and not gate.paused)

def eligibility():
    for e in ['CandidateFormat','CandidateSchema','InvalidExpression','TaskDollarCap']:
        check('exclude_'+e,not classify({'valid':False,'error':e},True,False,False)['eligible'])
    check('training_failure_is_normal_not_repair',not classify({'valid':True,'trainingGrade':{'passed':False}},True,False,True)['eligible'])
    check('unknown_with_existing_candidate_reconciles_only',classify({'valid':False,'error':'UnknownDispatch'},True,True,True)['route']=='reconcile_only')
    check('prior_never_started_not_a_repair_scope',not classify(None,False,False,False)['eligible'])
    p={'selected':[{'arm':'baseline','key':'a','attemptId':'repair-a','maximumUsd':.025}],'cases':[{'route':'interrupted','selected':True}],'maxNewAttemptsPerCell':1,'idOodAccessed':False};plan={'selected':[{'arm':'baseline','key':'a'}]};validate_repair_manifest(p,plan)
    bad=copy.deepcopy(p);bad['selected'].append(dict(p['selected'][0]))
    try:validate_repair_manifest(bad,plan)
    except AssertionError:check('repair_manifest_rejects_second_attempt',True)
    else:raise AssertionError('duplicate repair accepted')

def recovery_boundary():
    import prepare
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='inventory-free-') as td:
        roots=[pathlib.Path(td)/str(i) for i in range(3)];t=core.CATALOG[0]
        for r in roots:common.save(r/'outputs/status.json',{'stage':'complete','pid':0,'graderPid':0})
        common.save(roots[0]/'outputs/tasks/baseline'/t['key']/'result.json',{'valid':True});common.save(roots[1]/'outputs/tasks/objrun'/t['key']/'cell-start.json',{'pid':0});common.save(roots[2]/'outputs/tasks/baseline'/t['key']/'result.json',{'valid':True})
        q=prepare.inventory(roots,core.CATALOG);check('inventory_deduplicates_historical_repairs_and_keeps_interrupted_started',q['uniqueStarted']==2 and len(q['remaining'])==958)
        common.save(roots[1]/'outputs/concurrency16/claims/binary'/(t['key']+'.json'),{'arm':'binary','key':t['key']})
        try:prepare.inventory(roots,core.CATALOG)
        except AssertionError:check('claim_without_execution_evidence_blocks_automatic_recovery',True)
        else:raise AssertionError('unreviewed claim ignored')

def sqlite_snapshot():
    import sqlite3,raw_audit
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='sqlite-free-') as td:
        db=pathlib.Path(td)/'h2h.sqlite';connection=sqlite3.connect(db);connection.execute('pragma journal_mode=wal');connection.execute('create table evidence(value text)');connection.execute("insert into evidence values ('preserved')");connection.commit()
        paths=[p for p in pathlib.Path(td).iterdir() if p.is_file()];before={str(p):sha(p) for p in paths}
        try:
            with raw_audit.readonly_snapshot(db) as copy:assert copy.execute('select value from evidence').fetchone()==('preserved',)
            check('sqlite_audit_snapshot_preserves_db_wal_and_shared_memory',all(sha(pathlib.Path(p))==v for p,v in before.items()))
        finally:connection.close()

def reconciliation():
    import reconcile as module
    saved=(module.OUT,module.HISTORY,urllib.request.urlopen)
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='billing-free-') as td:
        top=pathlib.Path(td);d=top/'history/outputs/tasks/objrun'/('f'*24)/'calls/request/attempt-0';common.save(d/'dispatch.json',{'reservedUpperBoundUsd':.03,'dispatchAtMs':1});common.save(d/'receipt.json',{'actualCostUsd':None,'generationId':'synthetic-billing-id','reservedUpperBoundUsd':.03});before=sha(d/'receipt.json');module.OUT=top/'reports';module.HISTORY=[top/'history'];seen=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return b'{"data":{"total_cost":0.01}}'
        def fake(request,*a,**kw):
            assert request.full_url.startswith('https://openrouter.ai/api/v1/generation?');seen.append(request.full_url);return Response()
        urllib.request.urlopen=fake
        try:
            q=module.reconcile();again=module.reconcile()
            check('reconciliation_only_reads_metadata_never_replays_model',len(seen)==1 and q['modelCalls']==again['modelCalls']==0)
            check('reconciled_bill_keeps_original_receipt_and_reserve',sha(d/'receipt.json')==before and ledger(d)['unknownReserveUsd']==.03)
        finally:module.OUT,module.HISTORY,urllib.request.urlopen=saved

def chain():
    import numpy as np
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='pipeline-free-',ignore_cleanup_errors=True) as td:
        f=pathlib.Path(td);f.chmod(0o755);shutil.copytree(ROOT/'package',f/'package',ignore=shutil.ignore_patterns('__pycache__','node_modules','.env'));shutil.copytree(CONTROL,f/'control',ignore=shutil.ignore_patterns('__pycache__','*.tar.gz','free-checks.json','chain-free-checks.json','source-pins.json'))
        (f/'runtime').symlink_to(ROOT/'runtime',target_is_directory=True);(f/'bin').symlink_to(ROOT/'bin',target_is_directory=True);(f/'package/engine/app/node_modules').symlink_to((ROOT/'package/engine/app/node_modules').resolve(),target_is_directory=True)
        catalog=copy.deepcopy(core.CATALOG);catalog[0].update(prompt='SYNTHETIC_PUBLIC: y depends on x0 and x1',publicSha256='synthetic');catalog[1].update(prompt='SYNTHETIC_FAIL_ONCE: y depends on x0 and x1',publicSha256='synthetic-2');common.save(f/'data/public/catalog.json',catalog);common.save(f/'data/manifest.json',{'synthetic':True})
        x=np.linspace(.1,2,40)
        for t in catalog[:2]:np.savez(f/'data/public'/(t['key']+'.npz'),X=np.column_stack([x,x*x]),y=2*x*x)
        entries=[{'id':catalog[0]['id'],'key':catalog[0]['key'],'arm':a,'attemptId':'synthetic-main-'+a,'maximumUsd':cap(a)} for a in core.ARMS]+[{'id':catalog[1]['id'],'key':catalog[1]['key'],'arm':'objrun','attemptId':'synthetic-main-unknown','maximumUsd':.1}]
        p={'runId':'synthetic-v3','serverRoot':str(f),'selected':entries,'historicalAccounting':{'actualCostUsd':0,'accountedUpperBoundUsd':0,'unknownReserveUsd':0},'cases':[{'id':t['id'],'key':t['key'],'arm':a} for t in catalog for a in core.ARMS],'hiddenOldFailure':'HIDDEN_OLD_FAILURE','hiddenOldScore':'OLD_ID_OOD_SCORE'};common.save(f/'control/plan.json',p);common.save(f/'control/history-freeze.json',{'files':[]});common.save(f/'package/continuation-plan.json',{'allowedCells':entries});cfg=load(f/'package/experiment.json');cfg.update(priorUpperBoundUsd=0,priorUnknownReserveUsd=0);common.save(f/'package/experiment.json',cfg)
        proc=subprocess.run([str(ROOT/'runtime/bin/python'),str(CONTROL/'test_pipeline.py'),str(f)],capture_output=True,text=True,timeout=600)
        assert proc.returncode==0,proc.stderr[-5000:]+'\n'+proc.stdout[-3000:]
        proof=json.loads(proc.stdout.strip().splitlines()[-1]);assert proof['allPassed'] and proof['realApiCalls']==0
        for field in ['fourRealMethods','actualUnknownNativeSettledWithoutGlobalHalt','nextUnstartedCellContinued','automaticRepairExactlyOnce','actualStrictAndControlledAuditsSeparated','all960MappingsPreserved','noOldFailureOrScoresInWire','noPrivateDataDuringSolving','evaluationOnlyAfterBothFreezes','originalScoreEvidenceUnchanged']:
            check(field,proof[field])
        common.save(CONTROL/'chain-free-checks.json',proof)

if __name__=='__main__':
    eligibility();pools();admission();reservations();isolation_failures();recovery_boundary();sqlite_snapshot();reconciliation();chain()
    if (CONTROL/'plan.json').exists():
        p=load(CONTROL/'plan.json');check('formal_scope_exactly_258_unique_never_started',len(p['selected'])==len({(e['arm'],e['key']) for e in p['selected']})==258)
        check('history_plus_worst_primary_and_one_repair_within_78',p['maximumIncludingEveryPotentialRepairUsd']<=78)
    proof={'allPassed':True,'realApiCalls':0,'atUtc':utc(),'checks':CHECKS,'sourceFingerprints':source_pins()};common.save(CONTROL/'free-checks.json',proof);print(json.dumps(proof))
