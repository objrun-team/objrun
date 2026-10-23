"""Real execute -> native engine -> Gateway -> fake provider -> real grader, no paid calls."""
import json,os,subprocess,threading,time,urllib.request
import common,run
from common import ROOT,OUT,CFG,save,accounting
control=OUT/('controls/end-to-end-'+str(int(time.time()*1000)));control.mkdir(parents=True,exist_ok=True)
plan=json.loads((ROOT/'package/continuation-plan.json').read_text());allowed={e['key'] for e in plan['allowedCells'] if e['id'] in plan['canaryIds']}
refs=json.loads((OUT/'controls/reference-training.json').read_text());ref=next(x for x in refs if x['id'] in plan['canaryIds'] and x['result'].get('passed'))
task=next(t for t in run.CATALOG if t['id']==ref['id']);answer=json.dumps({'expression':ref['expression']})
port=run.freeport();run.GRADER_URL='http://127.0.0.1:'+str(port)
env={'PATH':str(ROOT/'runtime/bin')+':/usr/bin:/bin','GRADER_PORT':str(port),'PYTHONUTF8':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
log=(control/'grader.log').open('ab');run.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(ROOT/'package/grader.py')],env=env,stdout=log,stderr=log)
oldout=run.OUT;run.OUT=control/'outputs';common.OUT=run.OUT;common.ACCOUNT_REMAINING=10;original=urllib.request.urlopen;calls=[];arm_calls=0
class Reply:
    status=200
    def __init__(self,n):self.n=n
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):
        second=self.n>1;name='submit' if second else 'verify';body=answer if second else '{}'
        return json.dumps({'id':'free-e2e-'+str(self.n),'model':CFG['model'],'provider':'DigitalOcean','usage':{'cost':.001},'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'free-tool-'+str(self.n),'type':'function','function':{'name':name,'arguments':json.dumps({'answer':body})}}]},'finish_reason':'tool_calls'}]}).encode()
def fake(request,*a,**kw):
    global arm_calls
    url=request.full_url if hasattr(request,'full_url') else str(request)
    if url.startswith('https://openrouter.ai/'):
        assert url=='https://openrouter.ai/api/v1/chat/completions';calls.append(url);arm_calls+=1;return Reply(arm_calls)
    assert url.startswith('http://127.0.0.1:');return original(request,*a,**kw)
checks=[]
try:
    for _ in range(100):
        try:
            if run.get(run.GRADER_URL+'/health')['ok']:break
        except Exception:time.sleep(.1)
    else:raise RuntimeError('FreeGraderStartup')
    urllib.request.urlopen=fake
    for arm in ['objrun','binary']:
        arm_calls=0
        row=run.execute(task,arm);d=run.OUT/'tasks'/arm/task['key']
        assert row['valid'],row.get('error')
        assert row['providerRequestsSettledBeforeFinancialSnapshot'] and row['trainingGrade']['passed']
        events=json.loads((d/'feedback.json').read_text())
        assert 2<=row['modelCalls']<=4 and 2<=len(events)<=5
        assert not events[0]['grade']['passed'] and all(e['grade']['passed'] for e in events[1:])
        requests='\n'.join(p.read_text() for p in (d/'calls').rglob('request.json'))
        assert ('CandidateFormat' in requests)==(arm=='objrun')
        if arm=='binary':assert all(set(e['exposed'])=={'value'} for e in events)
        assert all((d/'native'/n).exists() for n in ['trace.json','tree.json','task.json','engine/data/h2h.sqlite'])
        before=accounting(d);time.sleep(.1);assert before==accounting(d)
        for dispatch in (d/'calls').rglob('dispatch.json'):assert json.loads(dispatch.read_text())['dispatchAtMs']<=row['completedAtMs']
        checks.append({'name':'real_execute_native_gateway_grader_'+arm,'passed':True,'fakeProviderCalls':arm_calls})
    assert 4<=len(calls)<=8
finally:
    urllib.request.urlopen=original;run.GRADER.terminate();run.GRADER.wait(timeout=15);run.OUT=oldout;common.OUT=OUT
save(OUT/'controls/end-to-end-free-checks.json',{'allPassed':True,'realApiCalls':0,'checks':checks});print(json.dumps({'allPassed':True,'realApiCalls':0,'checks':checks}))
