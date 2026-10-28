"""Full local run and one distinct exception-only reattempt, after main completion."""
import concurrent.futures, copy, hashlib, json, os, re, subprocess, sys, threading, time
from pathlib import Path
import run

ROOT=run.ROOT; PILOT=ROOT/'docs/climaqa/pilot-20261028-v1'; FULL=ROOT/'docs/climaqa/full-20261028-v1'
ARMS=run.ARMS; LOCK=run.LOCK; BASE_MODEL=run.model; BASE_NATIVE=run.native; BASE_GRADE=run.grade

def restore_reasoning(body, files):
    body=copy.deepcopy(body);replies=[]
    for path in files:
        response=run.read(path);m=(response.get('choices') or [{}])[0].get('message') or {}
        if m.get('role')=='assistant':replies.append(m)
    for msg in body.get('messages',[]):
        if msg.get('role')!='assistant' or isinstance(msg.get('reasoning_content'),str):continue
        ids=[x.get('id') for x in (msg.get('tool_calls') or [])]
        if ids:matches=[m for m in replies if ids==[x.get('id') for x in (m.get('tool_calls') or [])]]
        else:matches=[m for m in replies if not m.get('tool_calls') and m.get('content')==msg.get('content')]
        if len(matches)!=1 or not isinstance(matches[0].get('reasoning_content'),str):raise RuntimeError('CannotProveOriginalReasoningField')
        msg['reasoning_content']=matches[0]['reasoning_content']
    return body

def protected_model(tid,arm,index,body,deadline):
    files=list((run.OUT/'calls'/arm/tid).glob('*/response.json'))
    return BASE_MODEL(tid,arm,index,restore_reasoning(body,files) if body.get('tools') else body,deadline)

def journaled_grade(tid,arm,candidate,mode='correct'):
    # Every actual correctness decision is durably journaled before returning to the solver.
    with LOCK:
        result=BASE_GRADE(tid,arm,candidate,mode)
        if mode!='parsed' and result.get('parsed'):
            p=run.OUT/'judgments'/arm/(tid+'.jsonl');p.parent.mkdir(parents=True,exist_ok=True)
            row={'atUtc':run.now(),'answer':run.parse(candidate),'candidateSha256':run.sha(candidate),'passed':result['passed'],'distinctJudged':result['distinctJudged']}
            with p.open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
        return result

def checked_native(task,directory,s):
    n=BASE_NATIVE(task,directory,s)
    if n.get('error'):return n
    tree=run.read(directory/'tree.json') if (directory/'tree.json').exists() else []
    done=any(x.get('cycle')=='submit' and x.get('done')==1 for x in tree)
    verdict=n.get('engineVerdict') or {}
    if n.get('candidateHow')=='submitted' and (not done or n.get('engineState') not in ('done','failed') or verdict.get('valid') is not True):
        n['error']='IncompleteNativeHandin'
    return n

def key_from_env():
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        if line.strip().startswith('DEEPSEEK_API_KEY='):return line.split('=',1)[1].strip().strip('"\'')
    raise RuntimeError('MissingDeepSeekKey')

def pin_sources():
    paths=[ROOT/'scripts/climaqa'/x for x in ('run.py','native.ts','run_full.py','prepare.py','prepare_full.py')]+[FULL/x for x in ('public.json','private.json','source.json')]+[PILOT/x for x in ('public.json','private.json','source.json','summary.json','recovery-271-v1/result.json')]
    files={str(x.relative_to(ROOT)):run.sha(x.read_bytes()) for x in paths}
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    run.save(FULL/'source-pins.json',{'atUtc':run.now(),'gitCommit':commit,'files':files},True)
    return files

def preflight():
    # Reproduce the precise failure from the pilot using real saved, already paid-for responses.
    tid='climaqa-gold-mcq-271';path=PILOT/'tasks/objrun'/tid/'engine-requests.json';requests=run.read(path);assert len(requests)>=3
    files=list((PILOT/'calls/objrun'/tid).glob('*/response.json'));fixed=restore_reasoning(requests[2],files)
    assert all(isinstance(m.get('reasoning_content'),str) for m in fixed['messages'] if m.get('role')=='assistant')
    missing=[m for m in requests[2]['messages'] if m.get('role')=='assistant' and 'reasoning_content' not in m];assert len(missing)==1
    restored=[m for m in fixed['messages'] if m.get('role')=='assistant' and m.get('reasoning_content')==''];assert len(restored)==1
    bad=copy.deepcopy(requests[2]);next(m for m in bad['messages'] if m.get('role')=='assistant' and 'reasoning_content' not in m)['tool_calls'][0]['id']='not-a-real-call'
    try:restore_reasoning(bad,files);raise AssertionError('unexpected tool ID accepted')
    except RuntimeError as e:assert str(e)=='CannotProveOriginalReasoningField'
    p=run.read(FULL/'public.json');q=run.read(FULL/'private.json');old=run.read(PILOT/'public.json')
    assert len(p)==len(q)==225 and len(old)==20 and len({x['id'] for x in p+old})==245
    assert all(set(x)=={'id','source_row','complexity','prompt'} for x in p)
    dummy='CONTROL';run.BOOK[dummy]='A';assert not journal_test_grade(dummy,'B');assert journal_test_grade(dummy,'A')
    try:BASE_GRADE(dummy,'fixture','Answer: C');raise AssertionError('third option accepted')
    except RuntimeError as e:assert str(e)=='DistinctOptionBudgetExceeded'
    run.BOOK.pop(dummy);run.SEEN.pop(('fixture',dummy))
    if not (FULL/'controls.json').exists():run.save(FULL/'controls.json',{'allPassed':True,'atUtc':run.now(),'checks':['pilot failure reproduced and exactly restored','unknown tool ID rejected','225+20 unique validated task IDs','public fields','two distinct options enforced'],'modelCalls':0},True)

def journal_test_grade(tid,letter):return BASE_GRADE(tid,'fixture','Answer: '+letter)['passed']

def observe():
    for endpoint in ('models','user/balance'):
        import urllib.request
        req=urllib.request.Request('https://api.deepseek.com/'+endpoint,headers={'Authorization':'Bearer '+run.KEY})
        with urllib.request.urlopen(req,timeout=30) as r:data=json.load(r)
        if endpoint=='models' and not any(x.get('id')=='deepseek-flash' for x in data.get('data',[])):raise RuntimeError('ModelAliasUnavailable')
        if endpoint=='user/balance' and (not data.get('is_available') or not any(float(x.get('total_balance',0))>0 for x in data.get('balance_infos',[]))):raise RuntimeError('AccountUnavailable')
        run.save(FULL/('observation-'+endpoint.replace('/','-')+'.json'),{'atUtc':run.now(),'endpoint':endpoint,'response':data},True)

def status(stage):
    rows=[run.read(p) for p in (FULL/'results').glob('*/*.json')]
    run.save(FULL/'status.json',{'stage':stage,'atUtc':run.now(),'pid':os.getpid(),'remainingJobs':900-len(rows),'completed':len(rows),'byArm':{a:{'completed':sum(r['arm']==a for r in rows),'valid':sum(r['arm']==a and r['valid'] for r in rows),'passed':sum(r['arm']==a and r['valid'] and r.get('grade',{}).get('passed',False) for r in rows)} for a in ARMS}})

def schedule(jobs,server,capacity=50):
    iterator=iter(jobs);active=set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=capacity) as pool:
        while True:
            while len(active)<capacity and not run.STOP.is_set():
                try:task,arm=next(iterator)
                except StopIteration:break
                active.add(pool.submit(run.solve,task,arm,server))
            if not active:break
            done,active=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED,timeout=5)
            for f in done:f.result()
            status('main')

def recover_exceptions(tasks,server):
    original=[run.read(p) for p in (FULL/'results').glob('*/*.json')]
    exceptions=[r for r in original if not r['valid']]
    recovery=FULL/'exception-recovery-v1';recovery.mkdir()
    run.save(recovery/'scope.json',{'atUtc':run.now(),'onlyOriginalInfrastructureExceptions':True,'count':len(exceptions),'ids':[{'id':r['id'],'arm':r['arm'],'error':r.get('error')} for r in exceptions],'maxAdditionalAttempts':1,'freshTaskClock':True,'originalResultsPreserved':True},True)
    if not exceptions:return
    # Reconstruct the original oracle ledger; the two-distinct-option ceiling spans both attempts.
    for r in exceptions:
        p=FULL/'judgments'/r['arm']/(r['id']+'.jsonl');seen={}
        if p.exists():
            for line in p.read_text(encoding='utf-8').splitlines():
                x=json.loads(line);assert x['passed']==(x['answer']==run.BOOK[r['id']]);seen[x['answer']]=x['passed']
        assert len(seen)<=2;run.SEEN[(r['arm'],r['id'])]=seen
    run.OUT=recovery;run.STOP.clear();lookup={x['id']:x for x in tasks}
    # A dispatch without a receipt could still have been billed; preserve and skip it.
    jobs=[]
    for r in exceptions:
        calls=FULL/'calls'/r['arm']/r['id']
        unsettled=[x for x in calls.glob('*/dispatch.json') if not (x.parent/'receipt.json').exists()]
        if unsettled:continue
        if re.search(r'HTTP40[1234]|ModelIdentityChanged',r.get('error','')):continue
        jobs.append((lookup[r['id']],r['arm']))
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
        for f in concurrent.futures.as_completed([pool.submit(run.solve,t,a,server) for t,a in jobs]):f.result()
    run.OUT=FULL

def main():
    if (FULL/'execution-started.json').exists():raise RuntimeError('ExistingExecutionInspectBeforeRestart')
    run.OUT=FULL;run.KEY=key_from_env();run.BOOK={r['id']:r['answer'] for r in run.read(FULL/'private.json')};run.model=protected_model;run.grade=journaled_grade;run.native=checked_native
    preflight();observe();pins=pin_sources()
    run.save(FULL/'protocol.json',{'atUtc':run.now(),'arms':ARMS,'pilotRowsIncluded':20,'newRows':225,'newJobs':900,'concurrencyMax':50,'api':run.PARAMS,'distinctOptionsPerItemArmAcrossRecovery':2,'baselineAttempts':1,'independentAttempts':2,'binaryAttempts':2,'objrun':{'checks':1,'maxDeadSiblings':0,'maxBranches':4,'units':12,'solveSeconds':600},'exceptionRecovery':'one separate fresh native/solver attempt per settled infrastructure exception after main finishes','automaticFullRun':True},True)
    run.save(FULL/'execution-started.json',{'atUtc':run.now(),'pid':os.getpid()},True)
    public=run.read(FULL/'public.json');jobs=[(t,ARMS[(i+j)%4]) for i,t in enumerate(public) for j in range(4)];s=run.server()
    try:
        status('main');schedule(jobs,s)
        rows=list((FULL/'results').glob('*/*.json'))
        if len(rows)!=900 or run.STOP.is_set():status('needs_attention');return
        status('exception_recovery');recover_exceptions(public,s)
        # Verify frozen sources were not changed while the main batch ran.
        assert all(run.sha((ROOT/p).read_bytes())==v for p,v in pins.items())
        status('finished');run.save(FULL/'finished.json',{'atUtc':run.now(),'mainResults':900,'recoveryScope':str(FULL/'exception-recovery-v1/scope.json')},True)
    finally:s.shutdown()

if __name__=='__main__':main()
