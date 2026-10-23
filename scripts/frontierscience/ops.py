"""Task-owned deployment and verified result transfer. No unrelated processes are mutated."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tarfile

REPO=Path(__file__).resolve().parents[2]
NAME='frontierscience-formal-20261016-v1-deepseek-c32'
STAGE=REPO.parent/'tmp'/NAME
LOCAL=REPO/'docs/frontierscience'/NAME
REMOTE='/var/tmp/tgengin-frontierscience-20261016/'+NAME
LOCAL.mkdir(parents=True,exist_ok=True)
SSH=['ssh','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-o','ConnectTimeout=15','novaeve']
def remote(code,timeout=60):
    p=subprocess.run(SSH+['/usr/bin/python3.11','-'],input=code,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stderr[-2000:]+p.stdout[-1000:])
    return p.stdout
def scp(source,dest,timeout=120):
    subprocess.run(['scp','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-q',str(source),str(dest)],check=True,timeout=timeout)
def key_payload(action):
    text=(REPO/'.env').read_text(encoding='utf-8-sig')
    m=re.search(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$',text,re.M)
    if not m:raise RuntimeError('MissingExistingDeepSeekCredential')
    return {'key':m[1].strip().strip('\"\''),'action':action}
def invoke(action):
    payload=key_payload(action)
    p=subprocess.run(SSH+['/usr/bin/python3.11',REMOTE+'/package/launcher.py'],input=json.dumps(payload),text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=60)
    if payload['key'] in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
    if p.returncode:raise RuntimeError(p.stderr[-1600:])
    return json.loads(p.stdout)
def allow(info):
    return None if any(p in {'.env','__pycache__','runtime-home'} for p in Path(info.name).parts) or info.issym() else info

action=sys.argv[1]
if action=='deploy':
    source=STAGE/'source-package.tar.gz'
    if (LOCAL/'connection.json').exists():raise RuntimeError('ExistingLaunchNoDeployOverwrite')
    with tarfile.open(source,'w:gz') as tar:tar.add(STAGE/'package',arcname='package',filter=lambda x:None if 'node_modules' in Path(x.name).parts else allow(x))
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    print(remote(f"""from pathlib import Path
import os,json,shutil
r=Path({REMOTE!r})
if r.exists():raise RuntimeError('OwnedDirectoryAlreadyExists')
cpu=os.cpu_count();load=os.getloadavg()[0];mem=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024;disk=shutil.disk_usage('/var/tmp').free
if mem<8*1024**3 or disk<5*1024**3 or load>cpu*.95:raise RuntimeError('InsufficientResourceHeadroom')
r.mkdir(parents=True,mode=0o700)
(r/'resource-preflight.json').write_text(json.dumps({{'cpus':cpu,'load1':load,'availableMemoryBytes':mem,'freeDiskBytes':disk}},indent=2)+'\\n')
print(json.dumps({{'root':str(r),'cpus':cpu,'load1':load,'availableMemoryBytes':mem,'freeDiskBytes':disk}}))
"""))
    scp(source,'novaeve:'+REMOTE+'/source-package.tar.gz')
    result=remote(f"""from pathlib import Path
import hashlib,json,shutil,tarfile,urllib.request,collections,os,subprocess
r=Path({REMOTE!r});a=r/'source-package.tar.gz'
assert hashlib.sha256(a.read_bytes()).hexdigest()=={sha!r}
with tarfile.open(a) as t:t.extractall(r,filter='data')
origin=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/scicode-original-20261015')
(r/'bin').mkdir();shutil.copy2(origin/'bin/bun',r/'bin/bun')
shutil.copytree(origin/'package/engine/app/node_modules',r/'package/engine/app/node_modules',symlinks=False)
data=r/'data';data.mkdir()
revision='25ed67db7da8f4591484e764008ff585544f5a30'
url='https://huggingface.co/datasets/openai/frontierscience/resolve/'+revision+'/olympiad/test.jsonl'
raw=urllib.request.urlopen(url,timeout=60).read();rows=[json.loads(x) for x in raw.splitlines() if x.strip()]
assert len(rows)==100 and len({{x['task_group_id'] for x in rows}})==100
assert set(x['subject'] for x in rows)=={{'physics','chemistry','biology'}}
(data/'test.jsonl').write_bytes(raw)
public=[{{'id':x['task_group_id'],'subject':x['subject'],'problem':x['problem']}} for x in rows]
(data/'public-tasks.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\\n')
canary=[next(x['task_group_id'] for x in rows if x['subject']==s) for s in ['physics','chemistry','biology']]
source={{'revision':revision,'url':url,'fileSha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'count':len(rows),'subjects':dict(collections.Counter(x['subject'] for x in rows)),'ids':[x['task_group_id'] for x in rows],'canaryIds':canary,'canarySelection':'first released question of each subject, selected before any model call; included in formal100'}}
(data/'source.json').write_text(json.dumps(source,indent=2)+'\\n')
provenance=r/'provenance';provenance.mkdir()
for name,url in [('pricing','https://api-docs.deepseek.com/quick_start/pricing/'),('thinking','https://api-docs.deepseek.com/guides/thinking_mode/'),('chat-api','https://api-docs.deepseek.com/api/create-chat-completion/'),('paper','https://arxiv.org/html/2601.21165v1')]:
 try:(provenance/(name+'.html')).write_bytes(urllib.request.urlopen(url,timeout=40).read())
 except Exception as e:(provenance/(name+'-fetch-error.txt')).write_text(type(e).__name__)
deps={{'bun':subprocess.check_output([str(r/'bin/bun'),'--version'],text=True).strip(),'python':subprocess.check_output(['/usr/bin/python3.11','--version'],text=True).strip(),'nodeModulesFiles':sum(1 for p in (r/'package/engine/app/node_modules').rglob('*') if p.is_file())}}
(provenance/'dependencies.json').write_text(json.dumps(deps,indent=2)+'\\n')
print(json.dumps({{'sourceArchiveSha256':{sha!r},'dataset':source,'dependencies':deps}}))
""",timeout=240)
    (LOCAL/'deployment.json').write_text(result,encoding='utf-8');print(result)
    for name in ['source.json','public-tasks.json','test.jsonl']:
        (STAGE/'data').mkdir(exist_ok=True);scp('novaeve:'+REMOTE+'/data/'+name,STAGE/'data'/name)
elif action=='refresh':
    print(remote(f"from pathlib import Path\nr=Path({REMOTE!r})\nassert not (r/'outputs/canonical/launch.json').exists()\nprint('PrelaunchRefreshAllowed')\n"))
    for p in Path(__file__).parent.iterdir():
        if p.suffix in {'.py','.ts'}:
            import shutil
            shutil.copy2(p,STAGE/'package'/p.name);scp(p,'novaeve:'+REMOTE+'/package/'+p.name)
    print(remote(f"""from pathlib import Path
import json,hashlib
r=Path({REMOTE!r});p=r/'package/engine/app/src/llm/index.ts';s=p.read_text();updated=s.replace('maxRetries: RETRIES','maxRetries: 0');p.write_text(updated)
origin=r/'package/engine-origin.json';d=json.loads(origin.read_text())
if updated!=s:d['changes'].append({{'path':'app/src/llm/index.ts','beforeSha256':hashlib.sha256(s.encode()).hexdigest(),'afterSha256':hashlib.sha256(updated.encode()).hexdigest(),'reason':'disable SDK retries; central official transport owns the bounded retry chain'}})
p=r/'package/engine/app/src/main.ts';s=p.read_text();updated=s.replace('["deepseek", "deepseek-v4-flash", "chat,tools"]','["deepseek", "deepseek-flash", "chat,tools"]');p.write_text(updated)
if updated!=s:d['changes'].append({{'path':'app/src/main.ts','beforeSha256':hashlib.sha256(s.encode()).hexdigest(),'afterSha256':hashlib.sha256(updated.encode()).hexdigest(),'reason':'register current official model alias'}})
for entry in d['files']:
 p=r/'package/engine'/entry['path'];entry['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
origin.write_text(json.dumps(d,indent=2)+'\\n')
print('IsolatedSnapshotUpdated')
"""))
elif action in {'observe','launch'}:
    result=invoke(action)
    if action=='launch':(LOCAL/'connection.json').write_text(json.dumps({'server':'novaeve','root':REMOTE,'launch':result},indent=2)+'\n')
    print(json.dumps(result))
elif action=='fixture':
    print(remote(f"""from pathlib import Path
import subprocess,os,json,time
r=Path({REMOTE!r});d=r/('preflight-native-fixture-'+str(time.time_ns()));d.mkdir()
p=d/'input.json';p.write_text(json.dumps({{'task':{{'id':'fixture','problem':'What is 2+2?'}},'directory':str(d),'deadlineEpoch':time.time()+60,'fixture':True,'run':'preflight'}}))
env={{'PATH':str(r/'bin')+':/usr/bin:/bin','HOME':str(d),'NO_PROXY':'127.0.0.1,localhost'}}
x=subprocess.run([str(r/'bin/bun'),str(r/'package/native.ts'),str(p)],cwd=r,env=env,capture_output=True,text=True,timeout=80)
print(x.stdout);print(x.stderr)
print((d/'native-result.json').read_text() if (d/'native-result.json').exists() else 'NO_RESULT')
print((d/'fixture-assertions.json').read_text() if (d/'fixture-assertions.json').exists() else 'NO_ASSERTIONS')
""",timeout=100))
elif action in {'status','sync'}:
    result=remote(f"""from pathlib import Path
import json
r=Path({REMOTE!r});out=r/'outputs/canonical'
s=json.loads((out/'status.json').read_text()) if (out/'status.json').exists() else {{}}
p=Path('/proc')/str(s.get('pid',0))/'cmdline';s['ownedProcessLive']=p.exists() and str(r/'package/controller.py').encode() in p.read_bytes()
print(json.dumps(s))
for name in ['controller.stdout.log','controller.stderr.log','fatal.json']:
 p=out/name
 if p.exists() and p.stat().st_size:print(name+': '+p.read_text()[-1800:])
""")
    print(result);(LOCAL/'status-readback.txt').write_text(result,encoding='utf-8')
    for name in ['status.json','launch.json','controls.json','canary.json','fatal.json','SUMMARY.json','AUDIT.json','REPORT.md','FINAL_RESULTS.csv','source-pins.json']:
        p=subprocess.run(['scp','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-q','novaeve:'+REMOTE+'/outputs/canonical/'+name,str(LOCAL/name)],capture_output=True,timeout=30)
    if action=='sync':
        # Incremental compact results; active SQLite is never claimed to be a frozen backup.
        archive_meta=remote(f"""from pathlib import Path
import tarfile,json,hashlib
r=Path({REMOTE!r});a=r/'compact-sync.tar.gz'
with tarfile.open(a,'w:gz') as t:
 for top in ['outputs/canonical/results','outputs/canonical/final-results','outputs/canonical/exceptions','data','provenance']:
  if (r/top).exists():t.add(r/top,arcname=top)
print(json.dumps({{'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'bytes':a.stat().st_size}}))
""")
        a=LOCAL/'compact-sync.tar.gz';scp('novaeve:'+REMOTE+'/compact-sync.tar.gz',a)
        meta=json.loads(archive_meta);assert hashlib.sha256(a.read_bytes()).hexdigest()==meta['sha256']
        with tarfile.open(a) as t:t.extractall(LOCAL/'compact-mirror',filter='data')
        (LOCAL/'sync.json').write_text(json.dumps(meta,indent=2)+'\n')
elif action=='retrieve':
    archive=LOCAL/(NAME+'-results.tar.gz')
    if archive.exists():raise RuntimeError('ExistingArchiveInspectNoOverwrite')
    metadata=json.loads(remote(f"""from pathlib import Path
import tarfile,hashlib,json
r=Path({REMOTE!r});out=r/'outputs/canonical';s=json.loads((out/'status.json').read_text());p=Path('/proc')/str(s['pid'])/'cmdline'
if s['active'] or p.exists() and str(r/'package/controller.py').encode() in p.read_bytes():raise RuntimeError('ControllerStillRunning')
a=r/{archive.name!r}
def allow(x):return None if any(y in {{'.env','__pycache__','runtime-home'}} for y in Path(x.name).parts) or x.issym() else x
with tarfile.open(a,'w:gz') as t:
 for name in ['package','data','outputs','provenance','resource-preflight.json']+[p.name for p in r.glob('preflight-native-fixture*')]:
  if (r/name).exists():t.add(r/name,arcname=name,filter=allow)
print(json.dumps({{'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'bytes':a.stat().st_size,'stage':s['stage']}}))
""",timeout=240))
    scp('novaeve:'+REMOTE+'/'+archive.name,archive,timeout=240)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==metadata['sha256'] and archive.stat().st_size==metadata['bytes']
    with tarfile.open(archive) as t:t.extractall(LOCAL/'full-results',filter='data')
    (LOCAL/'retrieval.json').write_text(json.dumps({**metadata,'archive':str(archive),'twoEndsSha256Verified':True},indent=2)+'\n')
    print(json.dumps(metadata))
else:raise RuntimeError('UnknownAction')
