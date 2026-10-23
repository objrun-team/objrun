"""No-provider concurrency, real predecessor drain, duplicate, reservation and close tests."""
import concurrent.futures,copy,json,pathlib,tempfile,threading,time,urllib.request
from support import *
checks=[]
def check(name,condition):assert condition,name;checks.append({'name':name,'passed':True})
def drain_fixture():
    # Exercise the actual predecessor main(), consumer loop and execute_new().
    # Only provider/solver/grader fixtures and file roots are substituted.
    with tempfile.TemporaryDirectory(dir=CONTROL,prefix='drain-free-') as td:
        tmp=pathlib.Path(td);p=copy.deepcopy(old.plan());p['remainingCells']=p['remainingCells'][:20]
        common.save(tmp/'plan.json',p);saved={k:getattr(old,k) for k in ['CONTROL','OUT','protect','source_pins','apply_extra_hold']};names=['STATE','GRADER','GRADER_URL','execute','status','post','get','heartbeat'];cs={k:getattr(core,k) for k in names}
        other=(old.continuation.verify_plan,old.continuation.acceptance,common.preflight,subprocess_popen:=old.subprocess.Popen)
        old.CONTROL=tmp;old.OUT=tmp/'outputs';old.protect=lambda:p;old.source_pins=lambda:[];old.apply_extra_hold=lambda:0
        common.save(tmp/'source-pins.json',[]);common.save(tmp/'free-checks.json',{'allPassed':True,'realApiCalls':0})
        core.STATE={'active':[],'stopReason':None};core.GRADER=None;core.status=lambda:None;core.get=lambda u:{'ok':True};core.heartbeat=lambda:None
        old.continuation.verify_plan=lambda:None;old.continuation.acceptance=lambda:None;common.preflight=lambda:None
        class FakeGrader:
            pid=999999999
            def terminate(self):assert settled==4,'GraderKilledBeforeSettlement'
            def wait(self,timeout):return 0
        old.subprocess.Popen=lambda *a,**k:FakeGrader()
        entered=threading.Barrier(5);release=threading.Event();settled=0;calls=[]
        def solve(task,arm):
            nonlocal settled
            calls.append((arm,task['key']));entered.wait(timeout=10);release.wait(10)
            assert not core.STOP.is_set(),'HaltSetBeforeInflightRequestsSettled'
            # Represents a request then pending training/fit settlement, all within execute.
            time.sleep(.03)
            common.save(old.OUT/'tasks'/arm/task['key']/'result.json',{'arm':arm,'key':task['key']})
            with old.GUARD:settled+=1
        core.execute=solve;core.STOP.clear();old.CLAIMED.clear()
        t=threading.Thread(target=old.main);t.start()
        try:
            entered.wait(timeout=10);closed={**p,'remainingCells':[]};common.save(tmp/'plan.json',closed)
            time.sleep(.03);check('real_old_controller_waits_for_inflight_before_exit',t.is_alive() and settled==0 and not core.STOP.is_set())
            release.set();t.join(15)
            check('real_old_controller_empty_admission_drains_without_replay',not t.is_alive() and len(calls)==len(set(calls))==settled==4 and len(list((old.OUT/'tasks').glob('*/*/result.json')))==4)
            check('real_old_controller_closes_grader_only_after_settlement',(tmp/'controller-exit.json').exists() and 'CellOutsideApproved429Scope' in core.STATE['stopReason'])
        finally:
            release.set();t.join(15)
            for k,v in saved.items():setattr(old,k,v)
            for k,v in cs.items():setattr(core,k,v)
            old.continuation.verify_plan,old.continuation.acceptance,common.preflight,old.subprocess.Popen=other
            old.CLAIMED.clear();core.STOP.clear()
def pools():
    for label in ['solve','trainingFeedback','parameterFit']:
        pool=MeteredPool(16,label);barrier=threading.Barrier(17);release=threading.Event()
        def work():barrier.wait(timeout=10);release.wait(10)
        fs=[pool.submit(work) for _ in range(16)];barrier.wait(timeout=10)
        check(label+'_actual16_active',pool.metrics()['active']==pool.metrics()['peak']==16)
        drained=threading.Event();closer=threading.Thread(target=lambda:(pool.shutdown(wait=True),drained.set()));closer.start();time.sleep(.02);assert not drained.is_set()
        release.set();closer.join(10);check(label+'_close_waits_all16',drained.is_set() and pool.metrics()['completed']==16 and pool.metrics()['active']==0)
def reservation():
    saved=(common.OUT,common.CFG,common.ACCOUNT_REMAINING,common.ACCOUNT_RESERVED,common.RESERVED,urllib.request.urlopen)
    with tempfile.TemporaryDirectory(dir=CONTROL,prefix='money-free-') as td:
        common.OUT=pathlib.Path(td);common.CFG={**common.CFG,'formalSolverMaximumUsd':78,'priorUpperBoundUsd':0};common.ACCOUNT_REMAINING=10;common.ACCOUNT_RESERVED=0;common.RESERVED={};common.HALT.clear()
        barrier=threading.Barrier(16);seen=[];gate=threading.Event()
        class Fake:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return json.dumps({'model':common.CFG['model'],'provider':'DigitalOcean','id':'free-fixture','usage':{'cost':.001},'choices':[{'message':{'content':'{}'}}]}).encode()
        def fake(req,timeout):
            with common.LOCK:seen.append(common.ACCOUNT_RESERVED);assert common.ACCOUNT_RESERVED<=10
            barrier.wait(timeout=15);return Fake()
        urllib.request.urlopen=fake
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                fs=[pool.submit(common.call,common.OUT/'tasks/baseline'/str(i),'sample-0',{'messages':[{'role':'user','content':'fixture'}]}) for i in range(16)]
                for f in fs:f.result()
            a=common.accounting(common.OUT/'tasks');check('real_common_16_atomic_reservations_and_settlement',len(seen)==16 and a['modelCalls']==16 and a['unknownCostCount']==0 and abs(a['actualCostUsd']-.016)<1e-10 and abs(common.ACCOUNT_RESERVED)<1e-10)
            common.OUT=pathlib.Path(td)/'cap';common.CFG={**common.CFG,'formalSolverMaximumUsd':.04};common.ACCOUNT_REMAINING=.04;common.ACCOUNT_RESERVED=0;common.RESERVED={};common.HALT.clear();paid=[]
            def small(req,timeout):paid.append(1);time.sleep(.03);return Fake()
            urllib.request.urlopen=small
            def call(i):
                try:common.call(common.OUT/'tasks/baseline'/str(i),'sample-0',{'messages':[{'role':'user','content':'fixture'}]})
                except common.AccountStop:pass
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:list(pool.map(call,range(16)))
            a=common.accounting(common.OUT/'tasks');check('real_common_global_account_cap_16_contention',a['accountedUpperBoundUsd']<=.04 and not a['unknownCostCount'] and abs(common.ACCOUNT_RESERVED)<1e-10 and len(paid)<16)
        finally:common.OUT,common.CFG,common.ACCOUNT_REMAINING,common.ACCOUNT_RESERVED,common.RESERVED,urllib.request.urlopen=saved;common.HALT.clear()
def duplicate():
    import importlib.util
    spec=importlib.util.spec_from_file_location('new16',CONTROL/'runner.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    with tempfile.TemporaryDirectory(dir=CONTROL,prefix='unique-free-') as td:
        tmp=pathlib.Path(td);e=old.plan()['remainingCells'][0];common.save(tmp/'plan.json',{'remainingCells':[e]});r.CONTROL=tmp;r.OUT=tmp/'outputs';saved=core.execute;calls=[]
        def fake(t,a):calls.append(1);common.save(r.OUT/'tasks'/a/t['key']/'result.json',{})
        core.execute=fake
        try:
            def one(i):
                try:r.execute_new({'key':e['key']},e['arm']);return True
                except AssertionError:return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:answers=list(pool.map(one,range(16)))
            check('16_simultaneous_claims_execute_one_cell_once',sum(answers)==len(calls)==1)
            r.CLAIMS_CLOSED.set();r.execute_new({'key':'forbidden'},'baseline');check('new_stop_claims_prevents_next_dispatch',len(calls)==1)
        finally:core.execute=saved;r.SOLVE.shutdown()
def actual_services():
    import fit_service,grader
    from http.server import ThreadingHTTPServer
    saved=(grader.fit,core.FEEDBACK_POOL,core.grade,common.call)
    entered=threading.Barrier(17);release=threading.Event();seen=[]
    def fakefit(key,answer):seen.append(answer);entered.wait(timeout=15);release.wait(15);return {'valid':True,'passed':False,'nmse':1}
    grader.fit=fakefit;service=ThreadingHTTPServer(('127.0.0.1',0),fit_service.Handler);threading.Thread(target=service.serve_forever,daemon=True).start();url='http://127.0.0.1:'+str(service.server_port)
    task=core.CATALOG[0]
    try:
        jobs=[core.post(url+'/fit',{'key':task['key'],'answer':str(i)})['job'] for i in range(16)];entered.wait(timeout=15)
        repeat=core.post(url+'/fit',{'key':task['key'],'answer':'0'})['job']
        check('real_fit_http_16_workers_and_duplicate_job_reused',core.get(url+'/concurrency')['active']==16 and repeat==jobs[0] and len(seen)==16)
        release.set();grader.POOL.shutdown(wait=True);service.shutdown();service.server_close()
        with tempfile.TemporaryDirectory(dir=CONTROL,prefix='gateway-free-') as td:
            core.FEEDBACK_POOL=MeteredPool(16,'feedback-test');gate=threading.Barrier(17);done=threading.Event()
            def grade(t,a):gate.wait(timeout=15);done.wait(15);return {'valid':True,'passed':False,'nmse':1}
            core.grade=grade;gw=core.Gateway(task,'binary',pathlib.Path(td))
            # A Gateway has the fixed five-candidate ceiling. Sixteen real gateways
            # test shared feedback capacity while retaining that per-cell ceiling.
            gateways=[gw]+[core.Gateway(task,'binary',pathlib.Path(td)/str(i)) for i in range(1,16)]
            for g in gateways:core.post(g.url+'/feedback',{'key':task['key'],'arm':'binary','answer':'{}'})
            gate.wait(timeout=15);check('real_gateway_feedback_pool_16_and_binary_projection',core.FEEDBACK_POOL.metrics()['active']==16)
            closed=threading.Event();t=threading.Thread(target=lambda:(gw.close(),closed.set()));t.start();time.sleep(.03);assert not closed.is_set();done.set();t.join(10)
            for g in gateways[1:]:g.close()
            core.FEEDBACK_POOL.shutdown();check('real_gateway_close_drains_feedback_before_return',closed.is_set() and all(len(g.events)==1 and set(g.events[0]['exposed'])=={'value'} for g in gateways))
    finally:
        release.set();grader.fit,core.FEEDBACK_POOL,core.grade,common.call=saved
if __name__=='__main__':
    check('frozen_v2_original79_and_original_control8_match',core.sourcepins()==load(OUT/'source-pins.json') and old.source_pins()==load(OLD/'source-pins.json'))
    check('original_exception_remains_the_only_exception',audit_exception.inspect(ROOT,False)['approvedExceptionAuditPassed'])
    drain_fixture();pools();reservation();duplicate();actual_services()
    proof={'allPassed':True,'realApiCalls':0,'checks':checks,'sourceFingerprints':pins(),'atUtc':core.utc()};common.save(CONTROL/'free-checks.json',proof);print(json.dumps(proof))
