"""Exercise the actual paid-call seam with a fake provider; never make API calls."""
import http.client,importlib.util,json,pathlib,shutil,sys,tempfile,threading,time
PROPOSED=pathlib.Path(__file__).resolve().parent;ROOT=PROPOSED.parent
HERE=ROOT/'outputs/controls';HERE.mkdir(parents=True,exist_ok=True)
FROZEN=ROOT.parent/'llm-srbench-20261019-v1/package'

class WitnessLock:
    def __init__(self):self.inner=threading.RLock();self.waiting=threading.Event()
    def __enter__(self):self.waiting.set();self.inner.acquire();return self
    def __exit__(self,*args):self.inner.release()

class Reply:
    status=200
    def __init__(self,payload=None,fault=None):self.payload=payload;self.fault=fault
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):
        if self.fault:raise self.fault
        return json.dumps(self.payload).encode()

def load(source,root,name):
    p=root/'package';p.mkdir();shutil.copy2(source/'common.py',p/'common.py');shutil.copy2(source/'experiment.json',p/'experiment.json')
    spec=importlib.util.spec_from_file_location(name,p/'common.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ACCOUNT_REMAINING=10.0
    return module

def payload():return {'id':'fixture-free','provider':'DigitalOcean','model':'deepseek/deepseek-v4.1-flash','usage':{'cost':.001},'choices':[{'message':{'content':'fixture'},'finish_reason':'stop'}]}

checks=[]
with tempfile.TemporaryDirectory(prefix='dispatch-gate-',dir=HERE) as tmp:
    root=pathlib.Path(tmp)
    for proposed in [False,True]:
        r=root/('new' if proposed else 'old');r.mkdir();m=load(PROPOSED if proposed else FROZEN,r,'new_gate' if proposed else 'old_gate')
        lock=WitnessLock();m.LOCK=lock;lock.inner.acquire();calls=[];errors=[];closed=threading.Event();gate=m.CellDispatchGate() if proposed else None
        def fake(*args,**kwargs):calls.append({'afterClose':closed.is_set()});return Reply(payload())
        m.urllib.request.urlopen=fake
        def solve():
            if gate:gate.begin()
            try:m.call(r/'outputs/tasks/binary/test','sample',{'messages':[{'role':'user','content':'free fixture'}]},**({'dispatch_gate':gate} if gate else {}))
            except Exception as e:errors.append(type(e).__name__)
            finally:
                if gate:gate.end()
        t=threading.Thread(target=solve);t.start();assert lock.waiting.wait(3)
        closed.set()
        if gate:gate.closed.set()
        lock.inner.release();t.join(3);assert not t.is_alive()
        if proposed:assert not calls and errors==['TaskBudgetStop']
        else:assert len(calls)==1 and calls[0]['afterClose']
        checks.append({'name':'proposed_closing_guard' if proposed else 'frozen_late_dispatch_reproduced','passed':True,'fakeProviderCalls':len(calls),'realApiCalls':0})

    r=root/'halt';r.mkdir();m=load(PROPOSED,r,'halt_gate');lock=WitnessLock();m.LOCK=lock;lock.inner.acquire();calls=[];errors=[]
    m.urllib.request.urlopen=lambda *a,**k:(calls.append(True) or Reply(payload()))
    def halted():
        try:m.call(r/'outputs/tasks/binary/test','sample',{'messages':[]})
        except Exception as e:errors.append(type(e).__name__)
    t=threading.Thread(target=halted);t.start();assert lock.waiting.wait(3);m.HALT.set();lock.inner.release();t.join(3)
    assert not t.is_alive() and not calls and errors==['AccountStop'];checks.append({'name':'halt_rechecked_after_financial_lock','passed':True,'realApiCalls':0})

    r=root/'settle';r.mkdir();m=load(PROPOSED,r,'settle_gate');gate=m.CellDispatchGate();entered=threading.Event();release=threading.Event();settled=threading.Event();errors=[]
    def slow(*a,**k):entered.set();assert release.wait(3);return Reply(payload())
    m.urllib.request.urlopen=slow
    def billed():
        gate.begin()
        try:m.call(r/'outputs/tasks/binary/test','sample',{'messages':[]},dispatch_gate=gate)
        except Exception as e:errors.append(str(e))
        finally:gate.end()
    t=threading.Thread(target=billed);t.start();assert entered.wait(3)
    c=threading.Thread(target=lambda:(gate.close(),settled.set()));c.start();assert not settled.wait(.05);release.set();t.join(3);c.join(3)
    assert settled.is_set() and not errors and m.accounting(r/'outputs/tasks/binary/test')['actualCostUsd']==.001
    checks.append({'name':'financial_snapshot_waits_for_admitted_request','passed':True,'realApiCalls':0})

    r=root/'unknown';r.mkdir();m=load(PROPOSED,r,'unknown_gate');calls=[]
    def timeout(*a,**k):calls.append(True);return Reply(fault=TimeoutError('free fixture timeout'))
    m.urllib.request.urlopen=timeout
    for _ in range(2):
        try:m.call(r/'outputs/tasks/binary/test','sample',{'messages':[]})
        except m.UnknownDispatch:pass
        else:raise AssertionError('Expected an explicit unknown dispatch')
    assert len(calls)==1 and m.accounting(r/'outputs/tasks/binary/test')['unknownCostCount']==1
    checks.append({'name':'http200_read_timeout_is_unknown_and_never_reissued','passed':True,'realApiCalls':0})

    r=root/'cancel';r.mkdir();m=load(PROPOSED,r,'cancel_gate');gate=m.CellDispatchGate();calls=[];original=m.durable
    def cancel(p,v):
        original(p,v)
        if p.name=='dispatch.json':gate.closed.set()
    m.durable=cancel;m.urllib.request.urlopen=lambda *a,**k:(calls.append(True) or Reply(payload()))
    try:m.call(r/'outputs/tasks/binary/test','sample',{'messages':[]},dispatch_gate=gate)
    except m.TaskBudgetStop:pass
    else:raise AssertionError('Expected cancellation before provider contact')
    money=m.accounting(r/'outputs/tasks/binary/test')
    assert not calls and money['actualCostUsd']==money['accountedUpperBoundUsd']==0 and money['unknownCostCount']==0
    checks.append({'name':'cancelled_durable_intent_has_zero_known_cost','passed':True,'realApiCalls':0})

    # Exercise the real Gateway HTTP handler and close(), rather than only its gate.
    for queued in [True,False]:
        r=root/('gateway-queued' if queued else 'gateway-inflight');r.mkdir();m=load(PROPOSED,r,'gateway_common')
        (r/'data/public').mkdir(parents=True);(r/'data/public/catalog.json').write_text('[]');(r/'data/manifest.json').write_text('{}')
        shutil.copy2(PROPOSED/'run.py',r/'package/run.py');sys.modules['common']=m
        spec=importlib.util.spec_from_file_location('gateway_fixture',r/'package/run.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        gateway=runner.Gateway({'key':'test'},'binary',r/'outputs/tasks/binary/test')
        lock=WitnessLock();m.LOCK=lock;entered=threading.Event();release=threading.Event();closed=threading.Event();provider_calls=[];responses=[]
        if queued:lock.inner.acquire()
        def provider(*a,**k):
            provider_calls.append(True);entered.set()
            if not queued:assert release.wait(3)
            return Reply(payload())
        m.urllib.request.urlopen=provider
        def client():
            c=http.client.HTTPConnection('127.0.0.1',gateway.service.server_port,timeout=5)
            c.request('POST','/model',body=json.dumps({'body':{'messages':[]},'remainingSeconds':600}),headers={'Content-Type':'application/json'})
            response=c.getresponse();responses.append(response.status);response.read();c.close()
        t=threading.Thread(target=client);t.start()
        assert (lock.waiting if queued else entered).wait(3)
        c=threading.Thread(target=lambda:(gateway.close(),closed.set()));c.start();assert gateway.dispatch_gate.closed.wait(3)
        assert not closed.wait(.05)
        if queued:lock.inner.release()
        else:release.set()
        t.join(5);c.join(5);assert not t.is_alive() and not c.is_alive() and closed.is_set()
        if queued:assert not provider_calls and responses==[402]
        else:assert len(provider_calls)==1 and responses==[200] and m.accounting(gateway.d)['actualCostUsd']==.001
        checks.append({'name':'real_gateway_cancels_queued_call' if queued else 'real_gateway_close_waits_for_fee_receipt','passed':True,'realApiCalls':0})

result={'allPassed':True,'proposalOnly':False,'realApiCalls':0,'serverPackageChanged':False,'checks':checks}
(HERE/'dispatch-free-checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
