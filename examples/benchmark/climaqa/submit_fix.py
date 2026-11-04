"""Run six targeted ObjRun retries with DeepSeek's required hand-in tool contract."""
import concurrent.futures, copy, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path
import run, run_full

ROOT=run.ROOT; ORIGINAL=ROOT/'docs/climaqa/full-20261028-v1'; OUT=ROOT/'docs/climaqa/submit-fix-retry-20261028-v1'
IDS=['climaqa-gold-mcq-'+x for x in ('014','090','113','119','198','260')]
MOCK=False

def wire_body(body):
    body=copy.deepcopy(body);tools=body.get('tools') or []
    selected=body.get('tool_choice');named=selected.get('function',{}).get('name') if isinstance(selected,dict) and selected.get('type')=='function' else None
    if named and named!='submit':raise RuntimeError('UnexpectedRequiredTool:'+str(named))
    if named and not any(x.get('function',{}).get('name')==named for x in tools):raise RuntimeError('RequiredToolNotAvailable')
    wire={k:body[k] for k in ('messages','tools') if k in body};wire.update(run.PARAMS)
    if named:
        wire['tools']=[x for x in tools if x.get('function',{}).get('name')==named]
        wire['thinking']={'type':'disabled'};wire.pop('reasoning_effort',None);wire['tool_choice']=selected
    elif tools:wire['tool_choice']='auto'
    return wire,named

def model(tid,arm,index,body,deadline):
    if run.STOP.is_set():raise RuntimeError('AdmissionStopped')
    files=list((run.OUT/'calls'/arm/tid).glob('*/response.json'))
    # A tool-history assistant message must reproduce the provider's own reasoning.
    if body.get('tools') and files:body=run_full.restore_reasoning(body,files)
    wire,named=wire_body(body)
    dest=run.OUT/'calls'/arm/tid/('call-'+str(index).zfill(3));dest.mkdir(parents=True,exist_ok=False)
    run.save(dest/'request.json',wire,True)
    if MOCK:
        # First reply is plain text, mimicking the six observed failures. The
        # actual engine must then request the named hand-in call.
        if named:
            message={'role':'assistant','content':None,'tool_calls':[{'id':'fixture-submit','type':'function','function':{'name':'submit','arguments':json.dumps({'answer':'Answer: A'})}}]};finish='tool_calls'
        else:message={'role':'assistant','content':'Answer: A','reasoning_content':'fixture'};finish='stop'
        response={'id':'fixture-'+str(index),'object':'chat.completion','created':1,'model':'deepseek-flash','choices':[{'index':0,'message':message,'finish_reason':finish}],'usage':{'prompt_tokens':0,'completion_tokens':0}}
        run.save(dest/'response.json',response,True);return response
    run.save(dest/'dispatch.json',{'atUtc':run.now(),'endpoint':'https://api.deepseek.com/chat/completions','deadlineEpoch':deadline,'requiredTool':named},True)
    start=time.time();status=0;response=None;error=None
    try:
        if start>=deadline:raise TimeoutError('SolveDeadline')
        req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(wire,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+run.KEY,'Content-Type':'application/json'},method='POST')
        try:r=urllib.request.urlopen(req,timeout=max(1,deadline-time.time()))
        except urllib.error.HTTPError as e:r=e
        with r:status=r.status;raw=r.read();(dest/'response.raw').write_bytes(raw);response=json.loads(raw)
        if status!=200:raise RuntimeError('DeepSeekHTTP'+str(status))
        if not response.get('id') or not isinstance(response.get('usage'),dict) or not response.get('choices'):raise RuntimeError('InvalidProviderResponse')
        if 'flash' not in response.get('model','').lower():raise RuntimeError('ModelIdentityChanged')
        run.save(dest/'response.json',response,True)
        msg=response['choices'][0].get('message') or {};calls=msg.get('tool_calls') or []
        if named and not (len(calls)==1 and calls[0].get('function',{}).get('name')==named):raise RuntimeError('RequiredSubmitNotReturned')
    except Exception as e:error=(type(e).__name__+':'+str(e)).replace(run.KEY,'[REDACTED]')
    usage=response.get('usage') if isinstance(response,dict) else None
    receipt={'atUtc':run.now(),'httpStatus':status,'seconds':time.time()-start,'responseModel':response.get('model') if isinstance(response,dict) else None,'generationId':response.get('id') if isinstance(response,dict) else None,'usage':usage,'estimate':run.estimate(usage),'actualUsd':None,'requiredTool':named,'error':error}
    run.save(dest/'receipt.json',receipt,True)
    if error:
        if status in (400,401,402,403,404) or 'ModelIdentityChanged' in error:run.STOP.set()
        raise RuntimeError(error)
    return response

def controls():
    global MOCK
    MOCK=True;run.OUT=OUT/'fixture';run.BOOK={'fixture':'A'};run.SEEN={};run.model=model
    d=run.OUT/'native';d.mkdir(parents=True,exist_ok=False);server=run.server()
    try:n=run.native({'id':'fixture','prompt':'Choose A. End with Answer: X.'},d,server)
    finally:server.shutdown()
    tree=run.read(d/'tree.json');reqs=[run.read(p) for p in sorted((run.OUT/'calls/objrun/fixture').glob('*/request.json'))]
    assert not n.get('error') and n.get('engineState')=='done' and n.get('candidateHow')=='submitted' and run.parse(n['answer'])=='A'
    assert any(x.get('cycle')=='submit' and x.get('done')==1 for x in tree)
    assert any(x.get('tool_choice',{}).get('function',{}).get('name')=='submit' and x.get('thinking')=={'type':'disabled'} for x in reqs if isinstance(x.get('tool_choice'),dict))
    assert all([t.get('function',{}).get('name') for t in x.get('tools',[])]==['submit'] for x in reqs if isinstance(x.get('tool_choice'),dict))
    # The non-forced response still uses thinking.
    assert reqs[0].get('thinking')=={'type':'enabled'} and reqs[0].get('tool_choice')=='auto'
    run.save(OUT/'controls.json',{'atUtc':run.now(),'allPassed':True,'nativeFixture':'plain text -> hand-in -> actual submit -> passed','modelCalls':0},True)
    MOCK=False;run.SEEN={}

def main():
    if OUT.exists():raise RuntimeError('ExistingRetryDirectoryInspectFirst')
    OUT.mkdir(parents=True);controls();run.OUT=OUT;run.KEY=run_full.key_from_env()
    public=[x for x in run.read(ORIGINAL/'public.json') if x['id'] in IDS];run.BOOK={x['id']:x['answer'] for x in run.read(ORIGINAL/'private.json') if x['id'] in IDS}
    assert len(public)==len(run.BOOK)==len(IDS) and set(x['id'] for x in public)==set(IDS)
    for tid in IDS:
        old=run.read(ORIGINAL/'results/objrun'/(tid+'.json'));assert (old.get('engineVerdict') or {}).get('outcome')=='no_candidate'
    files=[ROOT/'examples/benchmark/climaqa'/x for x in ('submit_fix.py','run.py','run_full.py','native.ts')]+[ORIGINAL/x for x in ('public.json','private.json','source.json')]
    run.save(OUT/'source-pins.json',{'files':{str(p.relative_to(ROOT)):run.sha(p.read_bytes()) for p in files}},True)
    run.save(OUT/'protocol.json',{'atUtc':run.now(),'ids':IDS,'independentFreshAttempts':True,'maxDistinctOptionsPerAttempt':2,'checksPerAttempt':1,'maxDeadSiblings':0,'maxBranches':4,'units':12,'seconds':600,'ordinaryCalls':run.PARAMS,'requiredSubmit':{'thinking':{'type':'disabled'},'tool_choice':'named submit'},'originalRunUnchanged':True,'maxTaskConcurrency':6},True)
    run.save(OUT/'execution-started.json',{'atUtc':run.now(),'pid':os.getpid()},True)
    run.model=model;run.native=run_full.checked_native;run.grade=run_full.journaled_grade
    server=run.server()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=[f.result() for f in concurrent.futures.as_completed([pool.submit(run.solve,t,'objrun',server) for t in public])]
    finally:server.shutdown()
    run.save(OUT/'completed.json',{'atUtc':run.now(),'results':len(results),'valid':sum(x['valid'] for x in results),'passed':sum(x.get('grade',{}).get('passed',False) for x in results if x['valid'])},True)
    print(json.dumps(run.read(OUT/'completed.json')),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--recovery-113']:
        IDS=['climaqa-gold-mcq-113'];OUT=ROOT/'docs/climaqa/submit-fix-recovery-113-20261028-v1'
    elif sys.argv[1:]:raise RuntimeError('UnknownArguments')
    main()
