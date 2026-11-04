"""Deploy isolated recovery, pass credentials in memory, and retrieve all trials."""
from pathlib import Path
import hashlib
import json
import re
import shlex
import subprocess
import sys
import tarfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops import remote,scp,REPO,LOCAL as ORIGINAL_LOCAL,REMOTE as ORIGINAL_REMOTE,NAS,SSH
from core import NAME,read,save,sha

LOCAL=REPO/'docs/labbench'/NAME;LOCAL.mkdir(parents=True,exist_ok=True)
REMOTE='/data/tgengin-labbench-20261019/'+NAME

def deploy():
    assert read(ORIGINAL_LOCAL/'LOCAL_VERIFICATION.json')['allPassed'] and read(ORIGINAL_LOCAL/'DELIVERY.json')['verified']
    authorization={'retryUntilFirstValid':True,'paidRetriesAuthorized':True,'supersedesOldNoRetryRestriction':True,'scope':'Only original eight infrastructure arm+question identities; includes initial three canary exceptions; every new trial gets fresh600 seconds; stop immediately on first solverValid and grade.valid regardless of correctness; preserve all failures; DigitalOcean only; no best-answer selection','source':'explicit human instruction in current chat','atLocalOriginalArchiveSha256':read(ORIGINAL_LOCAL/'retrieval.json')['sha256']}
    save(LOCAL/'authorization.json',authorization)
    record=json.loads(remote(f'''from pathlib import Path
import shutil,json,time,hashlib
o=Path({ORIGINAL_REMOTE!r});r=Path({REMOTE!r});assert not r.exists()
assert json.loads((o/'outputs/canonical/AUDIT.json').read_text())['allPassed']
rows=[json.loads(p.read_text()) for p in (o/'outputs/canonical/results').glob('*/*.json')]
bad=[v for v in rows if not (v['solverValid'] and v['grade'].get('valid'))]
assert len(rows)==1416 and len(bad)==8 and sum(v['arm']=='baseline' for v in bad)==1
r.mkdir(mode=0o700);f=r/'frozen';f.mkdir()
for name in ['package','data','provenance','bin','venv']:shutil.copytree(o/name,f/name,symlinks=False)
(f/'runtime-home').mkdir();(r/'operations').mkdir();(r/'control').mkdir();ref=r/'original-reference';ref.mkdir()
shutil.copytree(o/'outputs/canonical/results',ref/'results')
for name in ['SUMMARY.json','AUDIT.json','file-inventory.json']:shutil.copy2(o/'outputs/canonical'/name,ref/name)
(ref/'records.json').write_bytes((json.dumps(rows,ensure_ascii=False,indent=2)+'\\n').encode())
jobs=[{{'arm':v['arm'],'id':v['id'],'originalResultSha256':hashlib.sha256((o/'outputs/canonical/results'/v['arm']/(v['id']+'.json')).read_bytes()).hexdigest(),'promptSha256':v['promptSha256']}} for v in sorted(bad,key=lambda v:(v['arm'],v['id']))]
cfg={{'name':{NAME!r},'originalRoot':str(o),'jobs':jobs,'initialWorkerConcurrency':2,'minWorkerConcurrency':1,'initialBackoffSeconds':60,'maxBackoffSeconds':1800,'freshSolveSeconds':600,'logicalCallMaxAttempts':3,'selection':'first valid, not best','originalArchiveSha256':{authorization['atLocalOriginalArchiveSha256']!r}}}
(r/'recovery.json').write_bytes((json.dumps(cfg,indent=2)+'\\n').encode());print(json.dumps(cfg))
''',300))
    save(LOCAL/'recovery.json',record)
    scp(LOCAL/'authorization.json','novaeve:'+REMOTE+'/authorization.json')
    files=list(Path(__file__).parent.glob('*.py'));pins={}
    for p in files:scp(p,'novaeve:'+REMOTE+'/operations/'+p.name);pins['operations/'+p.name]=sha(p)
    save(LOCAL/'operations-pins.json',pins);scp(LOCAL/'operations-pins.json','novaeve:'+REMOTE+'/operations-pins.json')
    receipt=json.loads(remote(f'''from pathlib import Path
import subprocess,json,os,time
r=Path({REMOTE!r});env={{'PATH':str(r/'frozen/bin')+':/usr/bin:/bin','HOME':str(r/'frozen/runtime-home'),'PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost'}}
with (r/'controls.stdout.log').open('ab') as out,(r/'controls.stderr.log').open('ab') as err:
 p=subprocess.Popen([str(r/'frozen/venv/bin/python'),str(r/'operations/controls.py'),str(r)],cwd=r,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
v={{'root':str(r),'controlsPid':p.pid,'createdEpoch':time.time()}};(r/'deployment.json').write_text(json.dumps(v));print(json.dumps(v))
'''))
    save(LOCAL/'deployment.json',receipt);print(json.dumps(receipt))

def launch():
    credential=(REPO/'.env').read_text(encoding='utf-8-sig');match=re.search(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',credential,re.M);assert match
    key=match[1].strip().strip('\"\'')
    code=f'''from pathlib import Path
import json,sys,os,fcntl,subprocess,time
r=Path({REMOTE!r});key=json.load(sys.stdin)['key'];assert json.loads((r/'controls.json').read_text())['allPassed']
lock=(r/'launch.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert not (r/'final-freeze.json').exists(),'AlreadyFinished'
if (r/'launch.json').exists():
 old=json.loads((r/'launch.json').read_text());p=Path('/proc')/str(old['pid'])/'cmdline'
 if p.exists() and str(r/'operations/run.py').encode() in p.read_bytes():print(json.dumps(old));sys.exit(0)
env={{'OPENROUTER_API_KEY':key,'LABBENCH_PROXY':'http://127.0.0.1:19219','PATH':str(r/'frozen/bin')+':/usr/bin:/bin','HOME':str(r/'frozen/runtime-home'),'PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost','PYTHONUTF8':'1'}}
with (r/'controller.stdout.log').open('ab') as out,(r/'controller.stderr.log').open('ab') as err:
 child=subprocess.Popen([str(r/'frozen/venv/bin/python'),str(r/'operations/run.py'),str(r)],cwd=r,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
v={{'pid':child.pid,'root':str(r),'atEpoch':time.time(),'credentialWritten':False}};h=r/'launch-history';h.mkdir(exist_ok=True);(h/(str(child.pid)+'.json')).write_text(json.dumps(v));(r/'launch.json').write_text(json.dumps(v));print(json.dumps(v))
'''
    p=subprocess.run(SSH+['/usr/bin/python3.11','-c',shlex.quote(code)],input=json.dumps({'key':key}),capture_output=True,text=True,encoding='utf-8',timeout=60)
    if key in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
    if p.returncode:raise RuntimeError(p.stderr[-3000:])
    receipt=json.loads(p.stdout);save(LOCAL/'launch.json',receipt);print(json.dumps(receipt))

def pull():
    result=json.loads(remote(f'''from pathlib import Path
import json,time
r=Path({REMOTE!r});result={{}}
for name in ['status.json','controls.json','first-valid.json','SUMMARY.json','AUDIT.json','final-freeze.json','launch.json']:
 p=r/name
 if p.exists():result[name]=p.read_text()
for name in ['controller.stderr.log','controls.stderr.log']:
 p=r/name
 if p.exists():result[name]=p.read_text()[-8000:]
print(json.dumps(result))
'''))
    for name,value in result.items():(LOCAL/name).write_bytes(value.encode())
    for name in ['status.json','controls.json']:
        if name in result:
            v=json.loads(result[name]);print(json.dumps({name:({k:v.get(k) for k in ['stage','pid','atUtc','selectedCount','targetCount','attemptCount','active','workerConcurrency','blocked','accounting']} if name=='status.json' else v)}))

def retrieve():
    receipt=json.loads(remote(f'''from pathlib import Path
import json,hashlib,tarfile,time
r=Path({REMOTE!r});assert json.loads((r/'status.json').read_text())['stage']=='complete';assert json.loads((r/'AUDIT.json').read_text())['allPassed'];owner=json.loads((r/'launch.json').read_text())['pid'];p=Path('/proc')/str(owner)/'cmdline'
assert not p.exists() or str(r/'operations/run.py').encode() not in p.read_bytes(),'ControllerStillWriting'
a=Path({NAS!r})/({NAME!r}+'-full-results.tar.gz')
if not a.exists():
 inventory={{x.relative_to(r).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in r.rglob('*') if x.is_file() and x.name!='file-inventory-recovery.json'}}
 (r/'file-inventory-recovery.json').write_bytes((json.dumps(inventory,indent=2)+'\\n').encode());temp=a.with_suffix('.partial');assert not temp.exists(),'ExistingArchivePartial'
 with tarfile.open(temp,'w:gz',dereference=True) as tar:
  for x in sorted(r.iterdir()):tar.add(x,arcname=x.name,filter=lambda v:None if '.env' in Path(v.name).parts else v)
 temp.rename(a)
h=hashlib.sha256()
with a.open('rb') as stream:
 for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
print(json.dumps({{'remoteArchive':str(a),'sha256':h.hexdigest(),'bytes':a.stat().st_size}}))
''',600))
    a=LOCAL/Path(receipt['remoteArchive']).name
    if not a.exists():
        temp=a.with_name(a.name+'.download.partial');assert not temp.exists(),'ExistingDownloadPartial';scp('novaeve:'+receipt['remoteArchive'],temp,600);assert sha(temp)==receipt['sha256'];temp.rename(a)
    assert sha(a)==receipt['sha256'] and a.stat().st_size==receipt['bytes']
    out=LOCAL/'full-results'
    if not out.exists():
        temp=LOCAL/'full-results.extracting';assert not temp.exists(),'ExistingExtractionPartial';temp.mkdir()
        with tarfile.open(a) as tar:tar.extractall(temp,filter='data')
        temp.rename(out)
    receipt.update(archive=str(a),fullResults=str(out),twoEndsSha256Verified=True);save(LOCAL/'retrieval.json',receipt);print(json.dumps(receipt))

if __name__=='__main__':{'deploy':deploy,'launch':launch,'pull':pull,'retrieve':retrieve}[sys.argv[1]]()
