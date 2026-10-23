"""Owned novaeve deployment, launch, compact pulls and verified full retrieval."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from protocol import NAME,digest

REPO=Path(__file__).resolve().parents[2];STAGE=REPO.parent/'tmp'/NAME
LOCAL=REPO/'docs/labbench'/NAME;LOCAL.mkdir(parents=True,exist_ok=True)
REMOTE='/data/tgengin-labbench-20261019/'+NAME
NAS='/mnt/aliyunsb/pingxingwang/tgengin-bench/labbench-20261019'
SSH=['ssh','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-o','ConnectTimeout=15','novaeve']

def remote(code,timeout=180):
    p=subprocess.run(SSH+['/usr/bin/python3.11','-'],input=code,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stderr[-3000:]+p.stdout[-1000:])
    return p.stdout

def scp(source,destination,timeout=240):
    subprocess.run(['scp','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-q',str(source),str(destination)],check=True,timeout=timeout)

def deploy():
    if (LOCAL/'deployment.json').exists():raise RuntimeError('ExistingDeploymentInspectNoOverwrite')
    # Synchronize the new adapter files once before making any frozen source manifest.
    for p in Path(__file__).parent.iterdir():
        if p.suffix in {'.py','.ts'} and p.name!='ops.py':
            (STAGE/'package'/p.name).write_bytes(p.read_bytes())
    archive=STAGE/'source-package.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name in ['package','data','provenance']:
            tar.add(STAGE/name,arcname=name,filter=lambda x:None if any(v in Path(x.name).parts for v in ['__pycache__','node_modules','.env']) else x)
    sha=digest(archive.read_bytes())
    print(remote(f"""from pathlib import Path
import os,shutil,json
r=Path({REMOTE!r})
if r.exists():raise RuntimeError('OwnedRootExistsInspectNoRedeploy')
disk=shutil.disk_usage('/data').free;mem=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
if disk<8*1024**3 or mem<8*1024**3:raise RuntimeError('InsufficientHeadroom')
r.mkdir(parents=True,mode=0o700)
(r/'deployment-created.json').write_text(json.dumps({{'diskFreeBytes':disk,'memAvailableBytes':mem,'pid':os.getpid()}}))
print(json.dumps({{'created':str(r),'diskFreeBytes':disk}}))
"""),flush=True)
    scp(archive,'novaeve:'+REMOTE+'/source-package.tar.gz')
    code=f"""from pathlib import Path
import os,shutil,subprocess,tarfile,json,hashlib,time
r=Path({REMOTE!r});a=r/'source-package.tar.gz'
assert hashlib.sha256(a.read_bytes()).hexdigest()=={sha!r}
with tarfile.open(a) as t:t.extractall(r,filter='data')
origin=Path('/data/tgengin-labbench-20261019/labbench-formal-20261019-v1-openrouter-c16')
(r/'bin').mkdir();shutil.copy2(origin/'bin/bun',r/'bin/bun')
shutil.copytree(origin/'package/engine/app/node_modules',r/'package/engine/app/node_modules',symlinks=False)
subprocess.run(['/usr/bin/python3.11','-m','venv',str(r/'venv')],check=True)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
deps={{p.relative_to(r).as_posix():sha(p) for top in ['bin','venv','package/engine/app/node_modules'] for p in (r/top).rglob('*') if p.is_file()}}
canonical=json.dumps(deps,sort_keys=True,ensure_ascii=False).encode()
metadata={{'bun':subprocess.check_output([str(r/'bin/bun'),'--version'],text=True).strip(),'python':subprocess.check_output([str(r/'venv/bin/python'),'--version'],text=True).strip(),'files':deps,'manifestSha256':hashlib.sha256(canonical).hexdigest()}}
(r/'provenance/dependencies.json').write_text(json.dumps(metadata,indent=2)+'\\n')
source={{p.relative_to(r).as_posix():sha(p) for top in ['package','data','provenance'] for p in (r/top).rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts and p.name!='source-pins.json'}}
(r/'provenance/source-pins.json').write_text(json.dumps({{'files':source,'atEpoch':time.time()}},indent=2)+'\\n')
(r/'runtime-home').mkdir();out=r/'outputs/canonical';out.mkdir(parents=True)
env={{'PATH':str(r/'bin')+':/usr/bin:/bin','HOME':str(r/'runtime-home'),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost'}}
with (out/'controls.stdout.log').open('ab') as stdout,(out/'controls.stderr.log').open('ab') as stderr:
 child=subprocess.Popen([str(r/'venv/bin/python'),str(r/'package/controls.py')],cwd=r,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
record={{'root':str(r),'controlsPid':child.pid,'sourcePackageSha256':{sha!r},'dependencyFiles':len(deps),'sourceFiles':len(source),'atEpoch':time.time()}}
(r/'deployment.json').write_text(json.dumps(record,indent=2)+'\\n');print(json.dumps(record))
"""
    result=json.loads(remote(code,300));(LOCAL/'deployment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)

def launch():
    text=(REPO/'.env').read_text(encoding='utf-8-sig');m=re.search(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',text,re.M)
    if not m:raise RuntimeError('MissingExistingOpenRouterCredential')
    key=m[1].strip().strip('\"\'')
    p=subprocess.run(SSH+['/usr/bin/python3.11',REMOTE+'/package/launcher.py'],input=json.dumps({'key':key}),text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=60)
    if key in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
    if p.returncode:raise RuntimeError(p.stderr[-2000:])
    record=json.loads(p.stdout);(LOCAL/'launch.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))

def pull():
    names=['status.json','controls.json','controls-progress.json','canary.json','SUMMARY.json','AUDIT.json','FINAL_RESULTS.csv','REPORT.md','launch.json','final-freeze.json','model-observation.json','formal-started.json']
    result=json.loads(remote(f"""from pathlib import Path
import json
r=Path({REMOTE!r});out=r/'outputs/canonical';result={{}}
for name in {names!r}:
 p=out/name
 if p.exists():result[name]=p.read_text()
for name in ['controls.stderr.log','controller.stderr.log','continuation.stderr.log']:
 p=out/name
 if p.exists():result[name]=p.read_text()[-6000:]
print(json.dumps(result))
"""))
    for name,value in result.items():(LOCAL/name).write_text(value,encoding='utf-8')
    for name in ['status.json','controls-progress.json']:
        if name in result:print(json.dumps({name:json.loads(result[name])},ensure_ascii=True))

def retrieve():
    receipt=json.loads(remote(f"""from pathlib import Path
import hashlib,json,tarfile,time
r=Path({REMOTE!r});out=r/'outputs/canonical';s=json.loads((out/'status.json').read_text())
if s['stage'] not in ['complete','complete_with_exceptions']:raise RuntimeError('NotFinished')
if not json.loads((out/'AUDIT.json').read_text())['allPassed']:raise RuntimeError('AuditNotPassed')
owner=json.loads((out/'launch.json').read_text())['pid'];proc=Path('/proc')/str(owner)/'cmdline'
for _ in range(50):
 if not proc.exists() or str(r).encode() not in proc.read_bytes():break
 time.sleep(.1)
else:raise RuntimeError('OwnedControllerStillDraining')
archive=Path({NAS!r})/({NAME!r}+'-full-results.tar.gz');archive.parent.mkdir(parents=True,exist_ok=True)
if not archive.exists():
 inventory={{p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='file-inventory.json'}}
 (out/'file-inventory.json').write_text(json.dumps(inventory,indent=2)+'\\n')
 temp=archive.with_suffix('.partial')
 if temp.exists():raise RuntimeError('ExistingArchivePartialInspectNoRepeat')
 with tarfile.open(temp,'w:gz',dereference=True) as t:
  for name in ['package','data','provenance','bin','venv','wheels','outputs','dependency-install.log','deployment.json']:
   p=r/name
   if p.exists():t.add(p,arcname=name,filter=lambda x:None if '.env' in Path(x.name).parts else x)
 temp.rename(archive)
h=hashlib.sha256()
with archive.open('rb') as f:
 for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
print(json.dumps({{'remoteArchive':str(archive),'bytes':archive.stat().st_size,'sha256':h.hexdigest(),'stage':s['stage']}}))
""",600))
    archive=LOCAL/Path(receipt['remoteArchive']).name
    if not archive.exists():
        partial=archive.with_name(archive.name+'.download.partial')
        if partial.exists():raise RuntimeError('ExistingDownloadPartialInspectBeforeRetry')
        scp('novaeve:'+receipt['remoteArchive'],partial,600)
        if partial.stat().st_size!=receipt['bytes'] or digest(partial.read_bytes())!=receipt['sha256']:raise RuntimeError('DownloadedPartialMismatch')
        partial.rename(archive)
    if archive.stat().st_size!=receipt['bytes'] or digest(archive.read_bytes())!=receipt['sha256']:raise RuntimeError('ArchiveTransferMismatch')
    root=LOCAL/'full-results'
    if not root.exists():
        extracting=LOCAL/'full-results.extracting'
        if extracting.exists():raise RuntimeError('ExistingExtractionPartialInspectBeforeRetry')
        extracting.mkdir()
        with tarfile.open(archive) as tar:tar.extractall(extracting,filter='data')
        extracting.rename(root)
    receipt.update(archive=str(archive),fullResults=str(root),twoEndsSha256Verified=True)
    (LOCAL/'retrieval.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

if __name__=='__main__':
    {'deploy':deploy,'launch':launch,'pull':pull,'retrieve':retrieve}[sys.argv[1]]()
