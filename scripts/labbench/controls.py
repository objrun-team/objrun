"""Server acceptance: private labels, public parser, mocked transport, real engine."""
import ast
import concurrent.futures as futures
import json
import os
import random
import secrets
import sqlite3
import string
import threading
import time
from protocol import PARAMETERS,PROTOCOL_SHA,MODEL,CANONICAL,REFUSE,parse,grade,digest
import runtime
from runtime import ROOT,OUT,CFG,read,save,Judge,broker,wire,OpenRouter,Fault,provider_error_code,retry_receipt,TRANSIENT
from controller import frozen,native


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    save(OUT/'controls-started.json',{'atEpoch':time.time(),'pid':os.getpid()},True)
    checks=[]
    def check(name,value,**details):
        checks.append({'name':name,'passed':bool(value),**details})
        save(OUT/'controls-progress.json',{'checks':len(checks),'failed':[x for x in checks if not x['passed']],'modelCalls':0})
    frozen(True)
    rows=read(ROOT/'data/private-tasks.json');public=read(ROOT/'data/public-tasks.json');book={r['id']:r for r in rows}
    check('scope708',len(rows)==len(public)==len(book)==708)
    check('two-arms-only',CFG['arms']==['baseline','objrun'])
    check('public-whitelist',all(set(r)=={'id','category','subtask','prompt','choiceCount'} for r in public))
    check('twenty-canary',len(set(read(ROOT/'data/source.json')['canaryIds']))==20)
    for p in public:
        r=book[p['id']];g=grade('[ANSWER]'+r['target']+'[/ANSWER]',r)
        check('label-roundtrip:'+p['id'],g['passed'] and g['sure'] and r['promptSha256']==digest(p['prompt']))
        check('abstain:'+p['id'],not grade(r['unsure'],r)['passed'] and grade(r['unsure'],r)['abstain'])
        raw=ROOT/'data/original'/r['source'];original=json.loads(raw.read_text(encoding='utf-8').splitlines()[r['sourceRow']])
        choices=[original['ideal'],REFUSE,*original['distractors']]
        check('private-permutation:'+p['id'],choices[r['permutation'][ord(r['target'])-65]]==original['ideal'] and digest(r['permutation'])==r['permutationSha256'])
        if p['category']=='ProtocolQA':check('protocol-present:'+p['id'],original['protocol']+original['question'] in p['prompt'])
    cases=[('A',5,'A'),('[ANSWER]h[/ANSWER]',8,'H'),('[ANSWER]F[/ANSWER]',5,None),('',5,None),
           ('Some text A or B',5,None),('[ANSWER]A[/ANSWER][ANSWER]B[/ANSWER]',5,None),
           ('[ANSWER]AB[/ANSWER]',5,None),('[ANSWER]A[/ANSWER][ANSWER]',5,None),
           ('[ANSWER]A or B[/ANSWER]',5,None),('Reasoning. [ANSWER]C[/ANSWER]',5,'C')]
    for i,(text,n,expected) in enumerate(cases):check('parser:'+str(i),parse(text,n)==expected)
    # Compare the copied official metrics function without importing provider SDKs.
    tree=ast.parse((ROOT/'package/vendor/labbench/evaluator.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Evaluator')
    func=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='compute_metrics');func.decorator_list=[];scope={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[])),'official_metrics','exec'),scope)
    check('official-metrics',scope['compute_metrics']([{'correct':True,'sure':True},{'correct':False,'sure':True},{'correct':False,'sure':False}])=={'accuracy':1/3,'precision':1/2,'coverage':2/3,'n_total':3})
    check('pinned-wire',all(wire({'messages':[{'role':'user','content':'x'}]}).get(k)==v for k,v in PARAMETERS.items()))
    check('http200-body504-classified',provider_error_code({'error':{'message':'Provider timed out after 301575ms','code':504}}) in TRANSIENT)
    preserved=wire({'messages':[{'role':'assistant','content':'','reasoning_content':'original thinking'}],'tools':[{'type':'function','function':{'name':'submit'}}]})
    check('reasoning-preserved',preserved['messages'][0]['reasoning_content']=='original thinking')
    # Real transport code against a fake opener: never any network or paid generation.
    original_out=runtime.OUT;runtime.OUT=OUT/'controls/transport';oldkey=os.environ.get('OPENROUTER_API_KEY');os.environ['OPENROUTER_API_KEY']='offline-fixture-placeholder'
    try:
        class Reply:
            def __init__(self,status,value):self.status=status;self.headers={};self.data=json.dumps(value).encode()
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read1(self,n):value=self.data[:n];self.data=self.data[n:];return value
        class Opener:
            def __init__(self,statuses,reason='stop'):self.statuses=list(statuses);self.calls=0;self.reason=reason
            def open(self,*args,**kwargs):
                status=self.statuses[min(self.calls,len(self.statuses)-1)];self.calls+=1
                if status=='body504':return Reply(200,{'error':{'message':'Provider timed out after 301575ms','code':504}})
                return Reply(status,{'id':'fixture-'+str(self.calls),'provider':'DigitalOcean','model':CANONICAL,'usage':{'cost':0,'prompt_tokens':1,'completion_tokens':1},'choices':[{'finish_reason':self.reason,'message':{'content':'' if self.reason=='length' else 'A'}}]})
        def mock(statuses,reason='stop'):
            c=OpenRouter();c.last_balance=time.time();c.remaining=100;c.opener=Opener(statuses,reason);return c
        c=mock([429,200]);r=c.call('t/baseline/retry','solve',{'messages':[{'role':'user','content':'x'}]},time.time()+30)
        check('finite-retry-then-success',c.opener.calls==2 and r['provider']=='DigitalOcean')
        c.call('t/baseline/retry','solve',{'messages':[{'role':'user','content':'x'}]},time.time()+30);check('completed-cache-no-redispatch',c.opener.calls==2)
        c=mock(['body504',200]);r=c.call('t/baseline/body504','solve',{'messages':[{'role':'user','content':'x'}]},time.time()+30)
        check('http200-body504-retries-once',c.opener.calls==2 and r['provider']=='DigitalOcean')
        c=mock([503]);failed=False
        try:c.call('t/baseline/exhaust','solve',{'messages':[{'role':'user','content':'x'}]},time.time()+30)
        except Fault:failed=True
        check('three-total-attempts',failed and c.opener.calls==3)
        c=mock([200],'length');r=c.call('t/baseline/length','solve',{'messages':[{'role':'user','content':'x'}]},time.time()+30)
        check('length-empty-is-delivery',c.opener.calls==1 and r['choices'][0]['finish_reason']=='length')
        path=runtime.OUT/'calls/solve/t/baseline/unresolved/attempt-0/dispatch.json';save(path,{'fixture':True},True)
        c=mock([200]);failed=False
        try:c.call('t/baseline/unresolved','solve',{'messages':[{'role':'user','content':'x'}]},time.time()+30)
        except Fault:failed=True
        check('unresolved-no-redispatch',failed and c.opener.calls==0)
    finally:
        runtime.OUT=original_out
        if oldkey is None:os.environ.pop('OPENROUTER_API_KEY',None)
        else:os.environ['OPENROUTER_API_KEY']=oldkey
    book['native-fixture']={'id':'native-fixture','target':'B','unsure':'E','choiceCount':5,'permutationSha256':'fixture'}
    judge=Judge(book)
    class NoModel:
        def call(self,*args,**kwargs):raise AssertionError('ZeroModelAttemptedActualGeneration')
    token=secrets.token_hex(32);server=broker(NoModel(),judge,token)
    try:
        with futures.ThreadPoolExecutor(max_workers=16) as pool:keys=list(pool.map(lambda _:judge.enqueue('native-fixture','B'),range(16)))
        check('concurrent-grade-dedup',len(set(keys))==1)
        d=OUT/'controls/native-fixture'
        result=native({'id':'native-fixture','prompt':'Synthetic non-biological parser check. First verify A, then submit B.','choiceCount':5},d,server,token,True)
        for name,value in read(d/'fixture-assertions.json').items():check('real-engine-'+name,value)
        db=sqlite3.connect('file:'+str(d/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
        check('native-budgets',db.execute('select solve_seconds,max_branches from task').fetchone()==(600,4))
        check('tool-isolation',{r[0] for r in db.execute('select name from tool where usable=1')}==set(CFG['toolPolicy']))
        check('real-submit-and-cycle',result['candidateHow']=='submitted' and result['nativeModelRequests']==3)
        feedback=read(d/'feedback.json');check('reject-then-pass',any(x['node']=='correct' and x['exposed']['value'] is False for x in feedback) and any(x['node']=='correct' and x['exposed']['value'] is True for x in feedback))
        db.close()
        check('zero-real-dispatches',not list((OUT/'calls').glob('**/dispatch.json')))
        frozen(True)
    finally:server.shutdown();judge.pool.shutdown(wait=True)
    result={'allPassed':all(x['passed'] for x in checks),'checks':checks,'failures':[x for x in checks if not x['passed']],'modelCalls':0,'protocolSha256':PROTOCOL_SHA,'atEpoch':time.time()}
    save(OUT/'controls.json',result,True)
    print(json.dumps({'allPassed':result['allPassed'],'checks':len(checks),'failures':result['failures'],'modelCalls':0}))
    if not result['allPassed']:raise SystemExit(1)


if __name__=='__main__':main()
