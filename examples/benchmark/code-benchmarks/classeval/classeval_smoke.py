import json, pathlib, urllib.request, urllib.error, uuid, struct

root=pathlib.Path(__file__).resolve().parent
image=json.loads((root/'classeval-image.json').read_text())['id']
rows=json.loads((root/'classeval/data/ClassEval_data.json').read_text(encoding='utf8'))
endpoint='http://127.0.0.1:18750'
def api(path,data=None,method=None,timeout=30):
    req=urllib.request.Request(endpoint+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=timeout) as response:
        body=response.read()
    return json.loads(body) if body else None
def logs(cid):
    with urllib.request.urlopen(endpoint+'/containers/'+cid+'/logs?stdout=1&stderr=1',timeout=20) as response:body=response.read()
    result=b''
    while len(body)>=8:
        n=struct.unpack('>I',body[4:8])[0];result+=body[8:8+n];body=body[8+n:]
    return result.decode(errors='replace')
results=[]
for kind in ['reference','wrong']:
    row=rows[0]
    code='\n'.join(row['import_statement'])+'\n'+(row['solution_code'] if kind=='reference' else row['skeleton'])+'\n'+row['test']
    worker='''import json,types,sys,unittest,io,os
from func_timeout import func_timeout
os.chdir('/work')
module=types.ModuleType('candidate');sys.modules['candidate']=module
exec(compile(CODE,'candidate.py','exec'),module.__dict__)
out=[]
for name in NAMES:
    suite=unittest.TestLoader().loadTestsFromTestCase(getattr(module,name))
    try:
        r=func_timeout(5,lambda:unittest.TextTestRunner(stream=io.StringIO()).run(suite))
        out.append({'class':name,'tests':r.testsRun,'errors':len(r.errors),'failures':len(r.failures),'passed':r.testsRun>0 and r.wasSuccessful()})
    except BaseException as e:out.append({'class':name,'passed':False,'errorType':type(e).__name__})
print(json.dumps({'passed':all(x['passed'] for x in out),'details':out}))
'''
    worker='CODE='+repr(code)+'\nNAMES='+repr(row['test_classes'])+'\n'+worker
    create={'Image':image,'Cmd':['python','-c',worker],'User':'65534:65534','WorkingDir':'/work','Labels':{'org.objrun.owner':'newbench-20261014','org.objrun.purpose':'preparation-control'},'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],'PidsLimit':128,'Memory':2147483648,'NanoCpus':2000000000,'Tmpfs':{'/work':'rw,nosuid,nodev,size=128m,mode=1777','/tmp':'rw,nosuid,nodev,size=128m,mode=1777'},'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'1'}}}}
    cid=api('/containers/create?name=objrun-newbench-control-'+uuid.uuid4().hex[:12],create,'POST')['Id']
    try:
        api('/containers/'+cid+'/start',{},'POST')
        waited=api('/containers/'+cid+'/wait',{},'POST',timeout=90)
        output=logs(cid)
        result={'kind':kind,'taskId':row['task_id'],'exitCode':waited['StatusCode'],'output':output,'containerId':cid}
        try:result['verdict']=json.loads(output.splitlines()[-1])
        except Exception:pass
        results.append(result);print(json.dumps(result),flush=True)
    finally:
        api('/containers/'+cid+'?force=1',method='DELETE')
report=root.parents[3]/'.scratch/code-benchmarks/classeval-controls.json'; report.parent.mkdir(parents=True,exist_ok=True)
report.write_text(json.dumps({'image':image,'results':results,'allPassed':results[0].get('verdict',{}).get('passed') is True and results[1].get('verdict',{}).get('passed') is False},indent=2),encoding='utf8')
if not(results[0].get('verdict',{}).get('passed') is True and results[1].get('verdict',{}).get('passed') is False):raise SystemExit(1)
