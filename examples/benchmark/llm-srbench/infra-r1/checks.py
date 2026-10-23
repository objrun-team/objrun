"""Free admission, billing, freeze ordering, isolation and actual-chain acceptance."""
import copy,os,shutil,subprocess,tempfile,urllib.request
from shared import *
from selection import classify
checks=[]
def check(name,v):assert v,name;checks.append({'name':name,'passed':True})
def selection_checks():
    def c(error='',valid=False,unknown=False,candidate=False,started=True,row=True):return classify({'valid':valid,'error':error} if row else None,started,unknown,candidate)
    check('startup_connection_read_and_interrupted_selected',all(c(x)['eligible'] for x in ['NativeEngine: the engine did not come up','ConnectionResetError','IncompleteRead','NativeControllerTimeout']) and c(row=False)['eligible'])
    check('wrong_answers_format_and_training_failures_excluded',all(not c(x)['eligible'] for x in ['CandidateFormat','CandidateSchema','CandidateCPUTimeout','InvalidExpression']) and not c(valid=True)['eligible'])
    check('valid_candidate_unknown_billing_routes_to_reconciliation',c(unknown=True,candidate=True)['route']=='reconcile_only' and not c(unknown=True,candidate=True,row=False)['eligible'])
    check('unknown_without_candidate_can_be_new_independent_attempt',c(unknown=True)['eligible'])
    check('unstarted_and_ambiguous_not_silently_repaired',not c(started=False,row=False)['eligible'] and not c('arbitrary unexplained failure')['eligible'])
    check('global_shutdown_interruptions_included_but_cell_dollar_caps_excluded',c('AccountStop:CampaignStopped')['eligible'] and not c('TaskDollarCap')['eligible'])
def pool_checks():
    for label in ['solve','feedback','fit']:
        p=Pool(label);barrier=threading.Barrier(17);release=threading.Event()
        def work():barrier.wait(timeout=10);release.wait(10)
        fs=[p.submit(work) for _ in range(16)];barrier.wait(timeout=10);assert p.metrics()['active']==p.metrics()['peak']==16
        closed=threading.Event();t=threading.Thread(target=lambda:(p.shutdown(),closed.set()));t.start();time.sleep(.02);assert not closed.is_set();release.set();t.join(10);check(label+'_16_parallel_and_close_drains',closed.is_set() and p.metrics()['completed']==16)
def money_checks():
    saved=(common.OUT,common.CFG,common.ACCOUNT_REMAINING,common.ACCOUNT_RESERVED,common.RESERVED,urllib.request.urlopen)
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='money-free-') as td:
        common.OUT=pathlib.Path(td);common.CFG={**common.CFG,'priorUpperBoundUsd':0,'formalSolverMaximumUsd':78};common.ACCOUNT_REMAINING=10;common.ACCOUNT_RESERVED=0;common.RESERVED={};common.HALT.clear();barrier=threading.Barrier(16)
        class R:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return json.dumps({'id':'mock','model':common.CFG['model'],'provider':'DigitalOcean','usage':{'cost':.001},'choices':[{'message':{'content':'{}'}}]}).encode()
        def fake(req,*a,**kw):barrier.wait(timeout=15);return R()
        urllib.request.urlopen=fake
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                fs=[pool.submit(common.call,common.OUT/'tasks/baseline'/str(i),'infra-new-'+str(i)+'--sample-0',{'messages':[{'role':'user','content':'public only'}]}) for i in range(16)]
                for f in fs:f.result()
            a=ledger(common.OUT/'tasks');check('16_real_frozen_atomic_reservations_all_settle',a['modelCalls']==16 and not a['unknownRequests'] and abs(a['actualCostUsd']-.016)<1e-10 and abs(common.ACCOUNT_RESERVED)<1e-10)
            common.OUT=pathlib.Path(td)/'limited';common.CFG={**common.CFG,'priorUpperBoundUsd':77.96};common.ACCOUNT_REMAINING=.04;common.ACCOUNT_RESERVED=0;common.RESERVED={};common.HALT.clear()
            def limited(req,*a,**kw):time.sleep(.05);return R()
            urllib.request.urlopen=limited
            def run(i):
                try:common.call(common.OUT/'tasks/baseline'/str(i),'new--sample-0',{'messages':[{'role':'user','content':'public'}]})
                except common.AccountStop:pass
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:list(pool.map(run,range(16)))
            a=ledger(common.OUT/'tasks');check('original_plus_unknown_hold_plus_round_stays_below_78',77.96+a['accountedUpperBoundUsd']<=78+1e-10 and not a['unknownRequests'] and abs(common.ACCOUNT_RESERVED)<1e-10)
        finally:common.OUT,common.CFG,common.ACCOUNT_REMAINING,common.ACCOUNT_RESERVED,common.RESERVED,urllib.request.urlopen=saved;common.HALT.clear()
def duplicate_checks():
    import runner as r
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='scope-free-') as td:
        d=pathlib.Path(td);oldout=r.OUT;oldcontrol=r.CONTROL;oldexecute=core.execute;calls=[];e={'arm':'baseline','key':core.CATALOG[0]['key'],'attemptId':'new-independent-attempt'};r.OUT=d/'outputs';r.CONTROL=d;common.save(d/'plan.json',{'selected':[e]})
        def fake(task,arm):calls.append(task);common.save(r.OUT/'tasks'/arm/task['key']/'result.json',{'valid':True});return {}
        core.execute=fake
        try:
            def one(i):
                try:r.execute(e);return True
                except AssertionError:return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:success=list(pool.map(one,range(16)))
            check('16_claimers_get_one_new_attempt_no_native_restart',sum(success)==len(calls)==1)
            check('solver_input_exact_public_catalog_without_failure_context',calls[0]==core.CATALOG[0])
            got=[];original=r.BASE_CALL;r.BASE_CALL=lambda directory,logical,*a,**kw:got.append(logical)
            r.call(r.OUT/'tasks'/e['arm']/e['key'],'sample-0',{});r.BASE_CALL=original
            check('new_attempt_has_distinct_logical_namespace',got==['new-independent-attempt--sample-0'])
        finally:r.OUT=oldout;r.CONTROL=oldcontrol;core.execute=oldexecute;r.CLAIMED.clear();r.SOLVE.shutdown()
def chain_checks():
    import numpy as np
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='chain-free-',ignore_cleanup_errors=True) as td:
        f=pathlib.Path(td);f.chmod(0o755);shutil.copytree(ROOT/'package',f/'package',ignore=shutil.ignore_patterns('__pycache__','node_modules','.env'));shutil.copytree(CONTROL,f/'control',ignore=shutil.ignore_patterns('__pycache__','*.tar*','free-checks.json','main-freeze.json','plan.json'))
        (f/'runtime').symlink_to(ROOT/'runtime',target_is_directory=True);(f/'bin').symlink_to(ROOT/'bin',target_is_directory=True);(f/'package/engine/app/node_modules').symlink_to((ROOT/'package/engine/app/node_modules').resolve(),target_is_directory=True)
        (f/'data/public').mkdir(parents=True);(f/'outputs').mkdir();t=copy.deepcopy(core.CATALOG[0]);t.update(id='synthetic-infrastructure-fixture',prompt='Synthetic public fixture: y depends on x0 and x1. Return expression JSON.',publicSha256='synthetic-only')
        common.save(f/'data/public/catalog.json',[t]);common.save(f/'data/manifest.json',{'syntheticFixture':True,'realBenchmarkArraysChanged':False});x=np.linspace(.1,2,40);np.savez(f/'data/public'/(t['key']+'.npz'),X=np.column_stack([x,x*x]),y=2*x*x)
        selected=[{'id':t['id'],'arm':a,'key':t['key'],'attemptId':'free-infra-r1-'+a} for a in ['baseline','independent','objrun','binary']];common.save(f/'control/plan.json',{'selected':selected,'oldFailure':'HIDDEN_OLD_FAILURE','oldTestScore':'OLD_ID_OOD_SCORE'});common.save(f/'package/continuation-plan.json',{'allowedCells':selected})
        cfg=load(f/'package/experiment.json');cfg.update(priorUpperBoundUsd=0,priorUnknownReserveUsd=0);common.save(f/'package/experiment.json',cfg)
        q=subprocess.run([str(ROOT/'runtime/bin/python'),str(CONTROL/'test_chain.py'),str(f)],capture_output=True,text=True,timeout=300)
        assert q.returncode==0,q.stderr[-4000:]+'\n'+q.stdout[-2000:]
        proof=json.loads(q.stdout.strip().splitlines()[-1]);check('real_four_arm_execute_native_gateway_and_training_fitter',proof['allPassed'] and proof['realApiCalls']==0 and proof['fourArms']==4)
        check('real_wire_contains_no_old_failures_or_test_scores',proof['noOriginalFailureOrTestScoresInWire'] and proof['noPrivateDataDuringSolving'])
        check('real_audit_evaluation_comparison_preserve_original_results',proof['actualRoundAuditAndEvaluationPassed'] and proof['originalScoresUnchanged'])
        common.save(CONTROL/'chain-free-checks.json',proof)
def freeze_checks():
    import evaluate
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='freeze-free-') as td:
        p=pathlib.Path(td);old=evaluate.OUT;evaluate.OUT=p
        try:
            try:evaluate.verify_freeze()
            except FileNotFoundError:pass
            else:raise AssertionError('Evaluation started without candidate/fee freeze')
            check('evaluation_refuses_access_before_candidate_and_fee_freeze',True)
        finally:evaluate.OUT=old
    if (CONTROL/'plan.json').exists():
        p=load(CONTROL/'plan.json');assert p['maxNewAttemptsPerCell']==1 and len({(e['arm'],e['key']) for e in p['selected']})==len(p['selected'])
        assert p['originalAccounting']['accountedUpperBoundUsd']+p['reservedAttemptMaximumUsd']<=78+1e-10
        cfg=load(ROOT/'package/experiment.json');base=load(CONTROL/'base-experiment.json');assert {k:v for k,v in cfg.items() if k not in ['priorUpperBoundUsd','priorUnknownReserveUsd']}=={k:v for k,v in base.items() if k not in ['priorUpperBoundUsd','priorUnknownReserveUsd']}
        assert {(x['arm'],x['key']) for x in load(ROOT/'package/continuation-plan.json')['allowedCells']}=={(x['arm'],x['key']) for x in p['selected']}
        check('final_manifest_unique_scope_and_full_caps_within_budget',True)
def planner_checks():
    import prepare as p
    names=['ROOT','OUT','CONTROL','MAIN','V1'];saved={n:getattr(p,n) for n in names};oldroot=core.ROOT
    with tempfile.TemporaryDirectory(dir=ROOT,prefix='planner-free-') as td:
        top=pathlib.Path(td);v1=top/'v1';main=top/'v2';new=top/'supplemental'
        for r in [v1,main]:common.save(r/'outputs/status.json',{'stage':'complete_with_exceptions','pid':0,'graderPid':0});common.save(r/'outputs/source-pins.json',[])
        common.save(main/'outputs/concurrency16/source-pins.json',[])
        t=copy.deepcopy(core.CATALOG[0]);t2={**t,'key':'f'*24,'id':'synthetic-second'};common.save(main/'data/public/catalog.json',[t,t2])
        d=v1/'outputs/tasks/baseline'/t['key'];common.save(d/'cell-start.json',{'pid':0});common.save(d/'calls/old/attempt-0/dispatch.json',{'dispatchAtMs':0,'reservedUpperBoundUsd':.02})
        common.save(v1/'outputs/tasks/objrun'/t['key']/'result.json',{'valid':False,'answer':'','error':'NativeEngine: the engine did not come up'})
        common.save(main/'outputs/tasks/independent'/t['key']/'result.json',{'valid':True,'answer':'{}','error':None})
        common.save(main/'outputs/tasks/binary'/t['key']/'result.json',{'valid':False,'answer':'','error':'ConnectionResetError'})
        u=main/'outputs/tasks/independent'/t2['key'];common.save(u/'result.json',{'valid':False,'answer':'','error':'UnknownPaidResponse'});common.save(u/'calls/old/attempt-0/dispatch.json',{'dispatchAtMs':0,'reservedUpperBoundUsd':.02});common.save(u/'samples.json',[{'answer':'{"expression":"p0*x1"}','grade':{'valid':True,'expression':'p0*x1','parameters':[1],'passed':False}}])
        def setup(r):
            common.save(r/'package/experiment.json',load(CONTROL/'base-experiment.json'));common.save(r/'package/continuation-plan.json',{});common.save(r/'control/base-experiment.json',load(CONTROL/'base-experiment.json'));common.save(r/'control/base-source-pins.json',[{'path':'package/experiment.json','sha256':sha(r/'control/base-experiment.json')}]);common.save(r/'control/blueprint-pins.json',[])
            # save() serializes both configuration copies identically.
            for n,v in {'ROOT':r,'OUT':r/'outputs','CONTROL':r/'control','MAIN':main,'V1':v1}.items():setattr(p,n,v)
            core.ROOT=r
        try:
            setup(new);q=p.prepare();manifest=load(new/'control/plan.json');before=sha(new/'control/plan.json');again=p.prepare()
            check('actual_planner_includes_prior_interruption_and_startup_without_scores',q['selected']==3 and q['reconcileOnly']==1 and all(e['arm']!='independent' for e in manifest['selected']) and manifest['noIdOodReadForSelection'])
            check('actual_manifest_frozen_once_and_each_attempt_unique',again['alreadyFrozen'] and sha(new/'control/plan.json')==before and len({e['attemptId'] for e in manifest['selected']})==3)
            common.save(d/'calls/old/attempt-0/dispatch.json',{'dispatchAtMs':0,'reservedUpperBoundUsd':77.97});setup(top/'budget-insufficient');q=p.prepare()
            check('actual_planner_records_budget_insufficient_without_new_attempts',q['selected']==0 and q['budgetSkipped']==3)
        finally:
            for n,v in saved.items():setattr(p,n,v)
            core.ROOT=oldroot
if __name__=='__main__':
    selection_checks();pool_checks();money_checks();duplicate_checks();chain_checks();freeze_checks();planner_checks()
    result={'allPassed':True,'realApiCalls':0,'atUtc':utc(),'checks':checks,'sourceFingerprints':source_pins(),'originalProtocolUnchanged':True};common.save(CONTROL/'free-checks.json',result);print(json.dumps(result))
