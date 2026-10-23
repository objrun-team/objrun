"""Fast read-only pass/fail signal for this exact private service and fixed Docker pipe."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib,json,os,subprocess,time,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CID='4c334ef1f093e82cf9e26ec06aaf0edd09385212c249e42b9ee7f7b8aae73153'
DOCKER='D:/Program/resources/bin/docker.exe'
def utc():return datetime.now(timezone.utc).isoformat()
def docker():
    command=[DOCKER,'-H','npipe:////./pipe/dockerDesktopLinuxEngine','inspect',CID]
    started=utc();begin=time.monotonic()
    try:
        result=subprocess.run(command,capture_output=True,timeout=5)
        record={'command':command,'startedAtUtc':started,'elapsedSeconds':time.monotonic()-begin,'exitCode':result.returncode,'stdoutSha256':hashlib.sha256(result.stdout).hexdigest(),'stderrSha256':hashlib.sha256(result.stderr).hexdigest(),'timedOut':False}
        if result.returncode==0:
            row=json.loads(result.stdout)[0];record.update(containerId=row['Id'],imageId=row['Image'],running=row['State']['Running'],oomKilled=row['State']['OOMKilled'],networkMode=row['HostConfig']['NetworkMode'])
        record['passed']=result.returncode==0 and record.get('containerId')==CID and record.get('running') is True
    except subprocess.TimeoutExpired:record={'command':command,'startedAtUtc':started,'elapsedSeconds':time.monotonic()-begin,'timedOut':True,'passed':False,'timeoutSeconds':5}
    except Exception as e:record={'command':command,'startedAtUtc':started,'elapsedSeconds':time.monotonic()-begin,'passed':False,'errorType':type(e).__name__}
    return record
def health():
    started=utc();begin=time.monotonic()
    try:
        with urllib.request.urlopen('http://127.0.0.1:17918/health',timeout=3) as response:
            raw=response.read(262145);assert len(raw)<=262144;body=json.loads(raw)
            return {'url':'http://127.0.0.1:17918/health','startedAtUtc':started,'elapsedSeconds':time.monotonic()-begin,'httpStatus':response.status,'responseRawSha256':hashlib.sha256(raw).hexdigest(),'profile':body,'passed':response.status==200 and body.get('items')==816}
    except Exception as e:return {'url':'http://127.0.0.1:17918/health','startedAtUtc':started,'elapsedSeconds':time.monotonic()-begin,'passed':False,'errorType':type(e).__name__,'timeoutSeconds':3}
with ThreadPoolExecutor(max_workers=2) as executor:
    d=executor.submit(docker);h=executor.submit(health);results={'docker':d.result(),'health':h.result()}
value={'protocol':'chemiq-private-health-diagnostic-v2','observedAtUtc':utc(),'modelCalls':0,'gradeCalls':0,'oldContainerMutated':False,'sourceSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'passed':all(v['passed'] for v in results.values()),**results}
out=ROOT/'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/observations';out.mkdir(parents=True,exist_ok=True)
path=out/('private-health-diagnostic-'+uuid.uuid4().hex+'.json');raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
print(json.dumps({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'passed':value['passed'],'dockerPassed':results['docker']['passed'],'healthPassed':results['health']['passed'],'modelCalls':0,'gradeCalls':0}))
raise SystemExit(0 if value['passed'] else 1)
