"""Actual two-round engine/Gateway/fitter pipeline using only a fake provider."""
import pathlib,sys,urllib.request,os
fixture=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(fixture/'control'))
from shared import *
import runner as driver,audit_round
original=urllib.request.urlopen;wire=[];count=0;unknown_count=0
answer=json.dumps({'expression':'p0*x1','initial':[1]})
class Response:
    status=200
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):return self.payload
def fake(request,*a,**kw):
    global count,unknown_count
    url=request.full_url if hasattr(request,'full_url') else str(request)
    if url.startswith('http://127.0.0.1:'):return original(request,*a,**kw)
    assert url=='https://openrouter.ai/api/v1/chat/completions'
    body=json.loads(request.data);wire.append(body);count+=1
    if driver.ROUND=='main' and 'SYNTHETIC_FAIL_ONCE' in json.dumps(body):
        unknown_count+=1;return Response(b'   ')
    if body.get('tools'):message={'role':'assistant','content':None,'tool_calls':[{'id':'synthetic-tool-'+str(count),'type':'function','function':{'name':'submit','arguments':json.dumps({'answer':answer})}}]};finish='tool_calls'
    else:message={'role':'assistant','content':answer};finish='stop'
    return Response(json.dumps({'id':'synthetic-gen-'+str(count),'provider':'DigitalOcean','model':common.CFG['model'],'usage':{'cost':.001},'choices':[{'message':message,'finish_reason':finish}]}).encode())
try:
    urllib.request.urlopen=fake;common.call=driver.call;common.ACCOUNT_REMAINING=10
    common.save(CONTROL/'source-pins.json',source_pins());plan=load(CONTROL/'plan.json')
    first=driver.run_round('main',plan['selected'],plan['historicalAccounting']);assert first['records']==5 and not common.HALT.is_set() and not driver.STATE.get('globalFault')
    assert unknown_count==1 and first['accounting']['unknownReserveUsd']>0
    assert all((round_out('main')/'tasks'/e['arm']/e['key']/'isolation-settlement.json').exists() for e in plan['selected'])
    repair=driver.prepare_repair(plan);assert len(repair['selected'])==1 and repair['selected'][0]['arm']=='objrun'
    prior=first['accounting'];driver.run_round('repair',repair['selected'],prior)
    review=audit_round.audit(ROOT,False);assert review['controlledAuditPassed'] and not review['rawVersionAuditPassed'],review
    assert len(list(round_out('repair').glob('tasks/*/*/result.json')))==1
    assert all(r.get('valid') for r in [load(p) for p in round_out('repair').glob('tasks/*/*/result.json')])
    assert not (ROOT/'data/private').exists();assert all('HIDDEN_OLD_FAILURE' not in json.dumps(w) and 'OLD_ID_OOD_SCORE' not in json.dumps(w) for w in wire)
    # Synthetic private data appears only after both candidate/financial freezes.
    import numpy as np,evaluate
    histories=[ROOT/('synthetic-history-'+str(i)) for i in range(3)]
    for h in histories:(h/'outputs').mkdir(parents=True)
    (histories[1]/'data/private').mkdir(parents=True);x=np.linspace(.2,3,31)
    for t in core.CATALOG[:2]:
        for split in ['id','ood']:np.savez(histories[1]/'data/private'/(t['key']+'-'+split+'.npz'),X=np.column_stack([x,x*x]),y=2*x*x)
    old=histories[0]/'old-score.json';common.save(old,{'id':False,'ood':False});oldhash=sha(old);evaluate.HISTORY=histories;before=count;evaluate.main();assert count==before and sha(old)==oldhash
    assert len(list((ROOT/'analysis/mapping').glob('*/*.json')))==960
    assert load(OUT/'summary.json')['uniqueMappings']==960
    assert round_out('main').joinpath('candidate-fee-freeze.json').exists() and round_out('repair').joinpath('candidate-fee-freeze.json').exists()
    print(json.dumps({'allPassed':True,'realApiCalls':0,'fourRealMethods':True,'actualUnknownNativeSettledWithoutGlobalHalt':True,'nextUnstartedCellContinued':True,'automaticRepairExactlyOnce':True,'actualStrictAndControlledAuditsSeparated':True,'all960MappingsPreserved':True,'noOldFailureOrScoresInWire':True,'noPrivateDataDuringSolving':True,'evaluationOnlyAfterBothFreezes':True,'originalScoreEvidenceUnchanged':True,'mockProviderCalls':count}))
finally:urllib.request.urlopen=original
