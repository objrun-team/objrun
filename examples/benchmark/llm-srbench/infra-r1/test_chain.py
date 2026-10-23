"""Subprocess-only synthetic full chain. No real model endpoint is reachable."""
import pathlib,sys
fixture=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(fixture/'control'))
from shared import *
import runner as driver,os,subprocess,urllib.request
task=core.CATALOG[0];answer=json.dumps({'expression':'p0*x1','initial':[1]});original=urllib.request.urlopen;count=0;arm_count=0;wire=[]
class Reply:
    status=200
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):
        if current in ['baseline','independent']:message={'role':'assistant','content':answer};finish='stop'
        else:message={'role':'assistant','content':None,'tool_calls':[{'id':'fixture-tool-'+str(count),'type':'function','function':{'name':'verify' if arm_count==1 else 'submit','arguments':json.dumps({'answer':'{}' if arm_count==1 else answer})}}]};finish='tool_calls'
        return json.dumps({'id':'infra-free-'+str(count),'model':common.CFG['model'],'provider':'DigitalOcean','usage':{'cost':.001},'choices':[{'message':message,'finish_reason':finish}]}).encode()
def fake(request,*a,**kw):
    global count,arm_count
    url=request.full_url if hasattr(request,'full_url') else str(request)
    if url.startswith('https://'):
        assert url=='https://openrouter.ai/api/v1/chat/completions';count+=1;arm_count+=1;wire.append(json.loads(request.data));return Reply()
    assert url.startswith('http://127.0.0.1:');return original(request,*a,**kw)
core.FEEDBACK_POOL.shutdown();core.FEEDBACK_POOL=Pool('feedback');common.call=driver.call;common.ACCOUNT_REMAINING=10
port=core.freeport();core.GRADER_URL='http://127.0.0.1:'+str(port);log=(ROOT/'grader-fixture.log').open('ab');env={'PATH':str(ROOT/'runtime/bin')+':/usr/bin:/bin','GRADER_PORT':str(port),'PYTHONUTF8':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'};core.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'fit_service.py')],env=env,stdout=log,stderr=log)
try:
    for _ in range(150):
        try:
            if core.get(core.GRADER_URL+'/health')['ok']:break
        except Exception:time.sleep(.1)
    else:raise RuntimeError('FixtureGraderStartup')
    urllib.request.urlopen=fake
    for e in load(CONTROL/'plan.json')['selected']:
        current=e['arm'];arm_count=0;driver.execute(e);d=OUT/'tasks'/current/task['key'];r=load(d/'result.json')
        assert r['valid'] and r['trainingGrade']['passed'],r.get('error')
        assert r['modelCalls']<=5 and r['unknownCostCount']==0
        if current in ['baseline','independent']:assert r['sampleCount']==1
        else:
            assert r['providerRequestsSettledBeforeFinancialSnapshot'];events=load(d/'feedback.json');assert 2<=len(events)<=5
            if current=='binary':assert all(set(x['exposed'])=={'value'} for x in events)
            assert all((d/'native'/name).exists() for name in ['tree.json','trace.json','engine/data/h2h.sqlite'])
        assert all(p.parent.parent.name.startswith(e['attemptId']+'--') for p in (d/'calls').rglob('dispatch.json'))
        before=ledger(d);time.sleep(.05);assert before==ledger(d)
        for p in (d/'calls').rglob('dispatch.json'):assert load(p)['dispatchAtMs']<=r['completedAtMs']
    assert not (ROOT/'data/private').exists() and all('HIDDEN_OLD_FAILURE' not in json.dumps(w) and 'OLD_ID_OOD_SCORE' not in json.dumps(w) for w in wire)
    assert core.get(core.GRADER_URL+'/concurrency')['capacity']==16 and core.FEEDBACK_POOL.capacity==16
    # Exercise the supplemental auditor and evaluator on synthetic private arrays
    # created only AFTER every mock-provider call and candidate/fee freeze.
    import numpy as np,audit_round,evaluate,csv
    selected=load(CONTROL/'plan.json')['selected'];cases=[];origin=ROOT/'synthetic-origin';(origin/'data/private').mkdir(parents=True)
    x=np.linspace(.2,3,31)
    for split in ['id','ood']:np.savez(origin/'data/private'/(task['key']+'-'+split+'.npz'),X=np.column_stack([x,x*x]),y=2*x*x)
    hashes={}
    for e in selected:
        p=origin/'analysis/outputs/tasks'/e['arm']/e['key']/'final-evaluation.json';common.save(p,{'id':{'passed':False},'ood':{'passed':False}});hashes[str(p)]=sha(p)
        cases.append({'id':task['id'],'key':task['key'],'arm':e['arm'],'originalProtocolVersion':'v1','originalError':'HIDDEN_OLD_FAILURE','originalValid':False,'route':'engine_start_failure','selected':True,'attemptId':e['attemptId'],'originalAccounting':{'actualCostUsd':.001,'accountedUpperBoundUsd':.002}})
    common.save(CONTROL/'plan.json',{'roundId':'synthetic-r1','selected':selected,'cases':cases,'originalAccounting':{'actualCostUsd':.004,'accountedUpperBoundUsd':.008,'unknownReserveUsd':.004}});common.save(CONTROL/'main-freeze.json',{'files':[]});common.save(OUT/'source-pins.json',core.sourcepins());common.save(CONTROL/'source-pins.json',source_pins())
    rows=core.all_results();core.cost_snapshots(rows);common.save(OUT/'candidate-fee-freeze.json',{'idOodAccessed':False,'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for d in [OUT/'tasks',OUT/'fits'] for p in d.rglob('*') if p.is_file()],'accounting':ledger(OUT/'tasks')})
    review=audit_round.audit(True,False);assert review['allPassed'] and review['complete'],review
    before=count;evaluate.MAIN=origin;evaluate.main();assert count==before and all(sha(pathlib.Path(p))==d for p,d in hashes.items())
    summary=load(OUT/'summary.json');assert summary['idSuccess']==summary['oodSuccess']==4 and summary['resultsNeverReplaceMain']
    with (OUT/'original-vs-supplemental.csv').open() as f:comp=list(csv.DictReader(f))
    assert len(comp)==4 and all(r['originalIdPassed']=='False' and r['repairIdPassed']=='True' for r in comp)
    print(json.dumps({'allPassed':True,'realApiCalls':0,'realExecuteNativeGatewayFitter':True,'fourArms':4,'mockProviderCalls':count,'noOriginalFailureOrTestScoresInWire':True,'noPrivateDataDuringSolving':True,'actualRoundAuditAndEvaluationPassed':True,'originalScoresUnchanged':True}))
finally:urllib.request.urlopen=original;core.FEEDBACK_POOL.shutdown();core.GRADER.terminate();core.GRADER.wait(timeout=15);driver.SOLVE.shutdown()
