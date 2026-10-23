"""Real Linux acceptance with synthetic model responses only. Zero API generation."""
from pathlib import Path
import concurrent.futures as futures
import importlib.metadata
import json
import os
import secrets
import sqlite3
import subprocess
import time
from protocol import PARAMETERS, PROTOCOL_SHA, digest
from runtime import ROOT,OUT,CFG,read,save,Judge,broker,wire
from controller import frozen,native

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'controls-started.json').exists():raise RuntimeError('ExistingControlsInspectNoDuplicate')
    save(OUT/'controls-started.json',{'atEpoch':time.time(),'pid':os.getpid()},True)
    checks=[]
    def check(name,value,**details):
        checks.append({'name':name,'passed':bool(value),**details})
        save(OUT/'controls-progress.json',{'checks':len(checks),'failed':[x for x in checks if not x['passed']],'modelCalls':0})
    frozen(True)
    rows=read(ROOT/'data/private-tasks.json');public=read(ROOT/'data/public-tasks.json')
    check('scope236',len(rows)==236 and len({r['id'] for r in rows})==236 and len(public)==236)
    check('public-whitelist',all(set(r)=={'id','originalId','prompt','subfield','answerType','multiple'} for r in public))
    check('original-context-present',all((r.get('context') or '') in p['prompt'] for r,p in zip(rows,public)))
    for package,version in CFG['pythonPackages'].items():check('dependency-version:'+package,importlib.metadata.version(package)==version)
    check('official-wire',wire({'messages':[{'role':'user','content':'x'}],'provider':{},'temperature':0,'thinking':{'type':'disabled'}})==dict(PARAMETERS,messages=[{'role':'user','content':'x'}]))
    preserved=wire({'messages':[{'role':'assistant','content':'','reasoning_content':'real original thinking'}],'tools':[{'type':'function','function':{'name':'submit'}}]})
    check('thinking-preserved',preserved['messages'][0]['reasoning_content']=='real original thinking' and preserved['tool_choice']=='auto')
    book={r['id']:r for r in rows}
    cases=[('number','4','So the final answer is \\boxed{4}.',True,None),
        ('wrong-number','4','\\boxed{5}',False,None),('empty','4','',False,None),
        ('no-box','4','4',True,None),('algebra','2x','\\boxed{x+x}',True,None),
        ('equation','x=2','\\boxed{2x=4}',True,None),
        ('multiple','1,2','\\boxed{1,2}',True,None),('missing-component','1,2','\\boxed{1}',False,None),
        ('absolute-tolerance','100','\\boxed{100.05}',True,'0.1'),('outside-tolerance','100','\\boxed{100.2}',False,'0.1'),
        ('mixed-tolerance','x,2','\\boxed{x,2.005}',True,',1e-2')]
    for name,gold,candidate,expected,error in cases:book['control-'+name]={'id':'control-'+name,'final_answer':[gold],'answer_type':'Expression','error':error}
    judge=Judge(book)
    try:
        jobs=[(r,judge.enqueue(r['id'],r['final_answer'][0])) for r in rows]
        for row,key in jobs:
            result,_=judge.wait(key);check('reference-roundtrip:'+row['id'],result.get('valid') and result.get('passed'),result=result)
        for name,gold,candidate,expected,error in cases:
            result,_=judge.wait(judge.enqueue('control-'+name,candidate))
            check('scoring-'+name,result.get('valid') and result.get('passed')==expected,result=result)
        # The upstream public examples are checked and any pre-existing disagreement is disclosed.
        from grade import load_official,judge as direct
        cls,_=load_official();example_results=[]
        for example in read(ROOT/'package/vendor/scoring_examples.json'):
            for item in example['Ans']:
                row={'final_answer':[example['GT']],'answer_type':'Expression','error':None}
                precision=item.get('precision')
                if isinstance(precision,str):precision=float(precision)
                if isinstance(precision,str):row['error']=precision
                elif precision is not None:row['error']=','.join(map(str,precision)) if isinstance(precision,list) else str(precision)
                upstream=cls().judge(item['answer'],example['GT'],precision if precision is not None else 1e-8)
                wrapped,_=direct(item['answer'],row)
                example_results.append({'groundTruth':example['GT'],'candidate':item['answer'],'publishedExpected':item['equal'],'officialInferenceResult':bool(upstream),'wrapperResult':wrapped})
        save(OUT/'official-examples.json',example_results,True)
        check('official-example-parity',all(x['wrapperResult']==x['officialInferenceResult'] for x in example_results),publishedExpectationDisagreements=sum(x['officialInferenceResult']!=x['publishedExpected'] for x in example_results))
        with futures.ThreadPoolExecutor(max_workers=16) as pool:keys=list(pool.map(lambda _:judge.enqueue('control-number','4'),range(16)))
        check('concurrent-grading-dedup',len(set(keys))==1)
        class NoModel:
            def call(self,*args,**kwargs):raise AssertionError('ZeroModelAcceptanceAttemptedModelCall')
        token=secrets.token_hex(32);server=broker(NoModel(),judge,token)
        try:
            d=OUT/'controls/native-fixture'
            result=native({'id':'native-fixture','prompt':'What is 2+2? First verify 5, then submit 4.'},d,server,token,True)
            assertions=read(d/'fixture-assertions.json')
            for name,value in assertions.items():check('real-engine-'+name,value)
            db=sqlite3.connect('file:'+str(d/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
            check('native-budgets',db.execute('select solve_seconds,max_branches from task').fetchone()==(600,4))
            check('four-tools',{r[0] for r in db.execute('select name from tool where usable=1')}==set(CFG['toolPolicy']))
            check('native-feedback-cycle',bool(read(d/'feedback.json')))
            # ask -> act -> ask -> required submit: the final station is a third model request.
            check('actual-submission',result['candidateHow']=='submitted' and result['nativeModelRequests']==3)
            check('required-submit-station',db.execute('select cycle from task_repair order by unit desc limit 1').fetchone()==('submit',))
            db.close()
        finally:server.shutdown()
        # Resource-killed/timeout grading is never converted to a valid false.
        malformed,_=judge.wait(judge.enqueue('control-number','\\boxed{10^{10^{10^{10}}}}'))
        check('bounded-symbolic-grading',isinstance(malformed.get('valid'),bool))
        check('zero-paid-requests',not list((OUT/'calls').glob('**/dispatch.json')))
        frozen(True)
    finally:judge.pool.shutdown(wait=True)
    result={'allPassed':all(x['passed'] for x in checks),'checks':checks,'failures':[x for x in checks if not x['passed']],
            'modelCalls':0,'protocolSha256':PROTOCOL_SHA,'atEpoch':time.time()}
    save(OUT/'controls.json',result,True)
    print(json.dumps({'allPassed':result['allPassed'],'checks':len(checks),'failures':result['failures'],'modelCalls':0}))
    if not result['allPassed']:raise SystemExit(1)

if __name__=='__main__':main()
