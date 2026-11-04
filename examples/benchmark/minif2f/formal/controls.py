"""Real Lean controls plus real loopback HTTP concurrency; zero paid model calls."""
from concurrent.futures import Future, ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
import sys
import threading
import time
from lean_worker import Grader, digest, save
from transport import Transport, BudgetStop
from scheduler import Scheduler
import lean_controls

class Loopback:
    def __init__(self, cfg, reply, hold=False):
        self.cfg,self.reply,self.hold=cfg,reply,hold
        self.lock=threading.Lock();self.count=self.active=self.peak=0
        self.starts=[];self.gates=[threading.Event() for _ in range(100)]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with owner.lock:
                    index=owner.count;owner.count+=1;owner.active+=1;owner.peak=max(owner.peak,owner.active)
                    owner.starts.append({'index':index,'atMonotonic':time.monotonic(),'request':request})
                try:
                    if owner.hold and not owner.gates[index].wait(20):raise TimeoutError('Control release timeout')
                    status,value=owner.reply(index,request)
                    raw=json.dumps(value).encode();self.send_response(status)
                    self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                    self.end_headers();self.wfile.write(raw);self.wfile.flush()
                finally:
                    with owner.lock:owner.active-=1
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)+'/chat/completions'
    def await_count(self,count,seconds=10):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            with self.lock:
                if self.count>=count:return
            time.sleep(.005)
        raise AssertionError('Loopback request count did not reach '+str(count))
    def release(self):
        for e in self.gates:e.set()
    def close(self):self.release();self.server.shutdown();self.server.server_close();self.thread.join(5)

class SyntheticGrader:
    active=0;peak=0
    def __init__(self,passed=True,hold=False):
        self.passed=passed;self.hold=hold;self.lock=threading.Lock();self.pending=[]
    def accept(self,task,answer):
        f=Future();value={'valid':True,'passed':self.passed,'candidateSha256':digest(answer),
                         'identity':'synthetic-control-only','cacheHit':False,'outcome':'synthetic-control-only'}
        with self.lock:
            if self.hold:self.pending.append((f,value))
            else:f.set_result(value)
        return f
    def release(self):
        with self.lock:
            self.hold=False
            for f,v in self.pending:f.set_result(v)
            self.pending=[]
    def close(self):pass

def public(count):
    return [{'id':'control/task_'+str(i),'name':'task_'+str(i),'split':'control','header':'',
             'statement':'True','prompt':'CONTROL_PUBLIC_TASK_'+str(i),
             'promptSha256':digest('CONTROL_PUBLIC_TASK_'+str(i))} for i in range(count)]

def main(root):
    root=Path(root).resolve()
    lean_controls.main(root)
    cfg=json.loads((root/'package/experiment.json').read_text())
    controls=json.loads((root/'outputs/controls.json').read_text())
    checks=controls['checks']
    out=root/'outputs/control'/('formal-'+str(time.time_ns()));out.mkdir()
    fixture=dict(cfg,controlOnly=True,maxTokens=1,inputUsdPerMillionCeiling=0.,
        outputUsdPerMillionCeiling=1.,batchDollarCap=1.,perTaskDollarCap=.10)
    def reply(index,request,content='synthetic proof',cost=.000001,finish='stop'):
        return (200,{'id':'synthetic-control-'+str(index),'model':cfg['model'],'provider':cfg['provider'],
            'choices':[{'message':{'content':content,'reasoning':'PRIVATE_REASONING_CONTROL'},'finish_reason':finish}],
            'usage':{} if cost is None else {'cost':cost}})
    # Hold sixteen real HTTP requests. Release one while its grade remains blocked.
    case=out/'actual-sixteen-and-refill';case.mkdir()
    server=Loopback(fixture,reply,hold=True);grader=SyntheticGrader(hold=True)
    transport=Transport(case,fixture,'DUMMY_LOOPBACK_ONLY',server.url)
    scheduler=Scheduler(case,dict(fixture,expectedRecords=20),public(10),transport,grader)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(scheduler.run)
        try:
            server.await_count(16)
            assert server.peak==transport.peak==16
            assert server.count==16
            released=time.monotonic();server.gates[0].set()
            server.await_count(17,5)
            refill=server.starts[16]['atMonotonic']-released
            assert refill<5 and grader.pending and not grader.pending[0][0].done()
        finally:server.release();grader.release()
        values=future.result(timeout=30)
    server.close()
    save(case/'server-observations.json',{'syntheticLoopbackOnly':True,'realPaidModelCalls':0,
        'actualServerPeak':server.peak,'starts':server.starts,'replacementStartedWithinSeconds':refill})
    assert len(values)==20 and all(r['grade']['passed'] for r in values)
    assert {r['arm'] for r in values}=={'independent','binary'}
    checks.append({'name':'actual_loopback_http_shared_16_and_immediate_refill_without_waiting_for_lean',
        'passed':True,'actualServerPeak':server.peak,'actualTransportPeak':transport.peak,
        'replacementStartedWithinSeconds':refill,'realPaidModelCalls':0,'loopbackRequests':server.count})
    # A 429 retry waits on the delayed queue while other work uses the freed slot.
    case=out/'retry-does-not-hold-slot';case.mkdir()
    retry_cfg=dict(fixture,modelConcurrency=2,transportBackoffSeconds=.3,expectedRecords=6)
    server=Loopback(retry_cfg,lambda i,r:(429,{'error':{'code':429}}) if i==0 else reply(i,r))
    transport=Transport(case,retry_cfg,'DUMMY_LOOPBACK_ONLY',server.url)
    values=Scheduler(case,retry_cfg,public(3),transport,SyntheticGrader()).run();server.close()
    save(case/'server-observations.json',{'syntheticLoopbackOnly':True,'realPaidModelCalls':0,'starts':server.starts})
    events=[json.loads(s) for s in (case/'outputs/scheduler-events.jsonl').read_text().splitlines()]
    retry_event=next(e for e in events if e['event']=='retry_scheduled')
    retry_path=case/'outputs/calls'/retry_event['group']/'attempt-00/transport-01/receipt.json'
    retry_receipt=json.loads(retry_path.read_text())
    first=json.loads(retry_path.with_name('receipt.json').parents[1].joinpath('transport-00/receipt.json').read_text())
    delay=retry_receipt['networkStartedAtEpoch']-first['networkEndedAtEpoch']
    assert delay>=.28 and server.count==7 and all(r['grade']['passed'] for r in values)
    assert server.starts[2]['atMonotonic']<server.starts[-1]['atMonotonic']
    checks.append({'name':'http429_backoff_releases_model_slot','passed':True,
        'configuredControlBackoffSeconds':.3,'observedBackoffSeconds':delay,'realPaidModelCalls':0})
    # Three transport attempts exhaust cleanly; no failed verdict is sent to a model.
    case=out/'bounded-retry';case.mkdir()
    retry_cfg=dict(fixture,modelConcurrency=2,transportBackoffSeconds=.01,expectedRecords=2)
    server=Loopback(retry_cfg,lambda i,r:(429,{'error':{'code':429}}))
    transport=Transport(case,retry_cfg,'DUMMY_LOOPBACK_ONLY',server.url)
    values=Scheduler(case,retry_cfg,public(1),transport,SyntheticGrader()).run();server.close()
    assert server.count==6 and all(not r['grade']['valid'] for r in values)
    assert all(len(list((case/'outputs/calls'/r['arm']/r['name']).rglob('receipt.json')))==3 for r in values)
    checks.append({'name':'bounded_three_transport_attempts_and_infrastructure_separation','passed':True,'realPaidModelCalls':0})
    # Two unknown costs consume the entire shared cap, including across arms.
    case=out/'unknown-cost-shared-cap';case.mkdir()
    budget_cfg=dict(fixture,batchDollarCap=.000002)
    server=Loopback(budget_cfg,lambda i,r:reply(i,r,cost=None),hold=True)
    transport=Transport(case,budget_cfg,'DUMMY_LOOPBACK_ONLY',server.url)
    sent=[{'role':'user','content':'synthetic control'}]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(transport.dispatch_once,g,0,0,sent,time.time()+30)
                 for g in ['independent/a','binary/b']]
        try:
            server.await_count(2)
            try:transport.dispatch_once('binary/c',0,0,sent,time.time()+30)
            except BudgetStop:blocked_inflight=True
            else:blocked_inflight=False
        finally:server.release()
        [f.result() for f in futures]
    try:transport.dispatch_once('binary/c',0,0,sent,time.time()+30)
    except BudgetStop:blocked_after=True
    else:blocked_after=False
    server.close();book=transport.accounting()
    assert blocked_inflight and blocked_after and server.count==2
    assert book['unknownCostCount']==2 and abs(book['budgetChargedUsd']-.000002)<1e-12
    checks.append({'name':'concurrent_shared_cap_and_unknown_reservations','passed':True,'accounting':book,'realPaidModelCalls':0})
    # Empty visible answers and length stops each consume one complete attempt.
    case=out/'empty-truncated-and-feedback';case.mkdir()
    empty_cfg=dict(fixture,expectedRecords=4)
    server=Loopback(empty_cfg,lambda i,r:reply(i,r,content=None,finish='length'))
    transport=Transport(case,empty_cfg,'DUMMY_LOOPBACK_ONLY',server.url)
    values=Scheduler(case,empty_cfg,public(2),transport,SyntheticGrader(passed=False)).run();server.close()
    assert server.count==20 and all(r['sampleCount']==5 and r['grade']['valid'] and not r['grade']['passed'] for r in values)
    for start in server.starts:
        wire=start['request'];assert 'PRIVATE_REASONING_CONTROL' not in json.dumps(wire)
        assert not wire.get('tools')
    checks.append({'name':'empty_and_length_consume_rounds_without_reasoning_leak','passed':True,'realPaidModelCalls':0})
    # Four genuine sandboxed Lean processes exercise the retained resource pool.
    identity=digest(json.dumps(json.loads((root/'outputs/environment.json').read_text()),sort_keys=True))
    grader=Grader(root,cfg,identity)
    header='import Mathlib\nimport Aesop\n'
    pending=[]
    for i in range(4):
        name='mf_formal_four_'+str(time.time_ns())+'_'+str(i)
        task={'id':'control/'+name,'name':name,'header':header,'statement':'theorem '+name+' : True := by\n'}
        pending.append(grader.accept(task,task['statement']+'  run_tac do IO.sleep 2000\n  trivial\n'))
    values=[f.result(timeout=1000) for f in pending];grader.close()
    assert all(v['valid'] and v['passed'] for v in values) and grader.peak==4
    checks.append({'name':'four_real_lean_workers_original_sandbox_and_resources','passed':True,
                   'actualGraderPeak':grader.peak,'workerMemoryGiB':cfg['workerMemoryGiB'],'compileTimeoutSeconds':cfg['compileTimeoutSeconds']})
    controls.update(allPassed=all(c['passed'] for c in checks),checks=checks,modelCalls=0,atEpoch=time.time())
    controls['sourcePins']={str(p.relative_to(root)):digest(p.read_bytes()) for d in ['package','vendor','data'] for p in (root/d).iterdir() if p.is_file()}
    save(out/'controls.json',controls);save(root/'outputs/controls.json',controls)
    print(json.dumps({'allPassed':controls['allPassed'],'controls':len(checks),'actualModelControlPeak':16,'actualLeanPeak':4,'paidModelCalls':0}),flush=True)

if __name__=='__main__':main(sys.argv[1])
