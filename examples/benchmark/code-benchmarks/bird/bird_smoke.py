import json,pathlib,urllib.request,uuid,struct
base=pathlib.Path(r'F:\git\TgEngin-handoff-2026-10-07\TgEngin\scripts\code-benchmarks\bird')
row=json.loads((base/'dev_20251106.json').read_text(encoding='utf8'))[0]
db=json.loads((base/'database-manifest.json').read_text(encoding='utf8'))[row['db_id']]
endpoint='http://127.0.0.1:18750'
def api(path,data=None,method=None,timeout=30):
    req=urllib.request.Request(endpoint+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=timeout) as response:body=response.read()
    return json.loads(body) if body else None
worker='''import sqlite3,json,time
c=sqlite3.connect('file:/db.sqlite?mode=ro&immutable=1',uri=True)
start=time.monotonic();c.set_progress_handler(lambda:int(time.monotonic()-start>30),10000)
gold=set(c.execute(GOLD).fetchall())
same=set(c.execute(GOLD).fetchall())
wrong=set(c.execute('SELECT NULL').fetchall())
readonly=False
try:c.execute('CREATE TABLE __objrun_readonly_probe(x)')
except sqlite3.OperationalError:readonly=True
print(json.dumps({'referencePassed':same==gold,'wrongRejected':wrong!=gold,'readonlyEnforced':readonly,'referenceRows':len(gold),'sqliteVersion':sqlite3.sqlite_version}))
'''
worker='GOLD='+repr(row['SQL'])+'\n'+worker
create={'Image':'sha256:541096ae9b05d3b850341b78790e2ed31e94d5aa0ea086933c6ff0c09ffa2e63','Cmd':['python','-c',worker],'User':'65534:65534','Labels':{'org.objrun.owner':'newbench-20261014','org.objrun.purpose':'bird-preparation-control'},'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges'],'PidsLimit':64,'Memory':2147483648,'NanoCpus':2000000000,'Binds':[db+':/db.sqlite:ro'],'Tmpfs':{'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'1'}}}}
cid=api('/containers/create?name=objrun-bird-control-'+uuid.uuid4().hex[:12],create,'POST')['Id']
try:
    api('/containers/'+cid+'/start',{},'POST')
    wait=api('/containers/'+cid+'/wait',{},'POST',timeout=90)
    with urllib.request.urlopen(endpoint+'/containers/'+cid+'/logs?stdout=1&stderr=1',timeout=20) as response:body=response.read()
    output=b''
    while len(body)>=8:
        n=struct.unpack('>I',body[4:8])[0];output+=body[8:8+n];body=body[8+n:]
    result={'taskId':row['question_id'],'exitCode':wait['StatusCode'],'output':output.decode(errors='replace'),'containerId':cid}
    try:result['verdict']=json.loads(result['output'].splitlines()[-1])
    except Exception:pass
    (base/'preparation-controls.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
finally:api('/containers/'+cid+'?force=1',method='DELETE')
if not all(result.get('verdict',{}).get(k) is True for k in ['referencePassed','wrongRejected','readonlyEnforced']):raise SystemExit(1)
