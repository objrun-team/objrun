"""Isolated recovery deployment, process inspection, and SHA-verified transfer."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tarfile

REPO=Path(__file__).resolve().parents[2]
NAME='frontierscience-recovery-20261016-v1-deepseek-c32'
ORIGINAL='frontierscience-formal-20261016-v1-deepseek-c32'
BASE='/var/tmp/tgengin-frontierscience-20261016/'
REMOTE=BASE+NAME;ORIGIN=BASE+ORIGINAL
LOCAL=REPO/'docs/frontierscience'/NAME;LOCAL.mkdir(parents=True,exist_ok=True)
SSH=['ssh','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-o','ConnectTimeout=15','novaeve']
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda b:hashlib.sha256(b).hexdigest()

def remote(code,timeout=90):
    p=subprocess.run(SSH+['/usr/bin/python3.11','-'],input=code,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=timeout)
    if p.returncode:raise RuntimeError(p.stderr[-2500:]+p.stdout[-1000:])
    return p.stdout

def scp(a,b,timeout=240):
    subprocess.run(['scp','-o','BatchMode=yes','-o','ClearAllForwardings=yes','-q',str(a),str(b)],check=True,timeout=timeout)

def guard_code():
    return f"from pathlib import Path\nimport sys\nsys.path.insert(0,{REMOTE!r}+'/package')\nfrom recovery_guard import guard,resources\n"

def main():
    action=sys.argv[1]
    if action=='deploy':
        original=REPO/'docs/frontierscience'/ORIGINAL
        assert read(original/'LOCAL_VERIFICATION.json')['allPassed']
        manifest=read(LOCAL/'recovery-manifest.json');raw=(LOCAL/'recovery-manifest.json').read_bytes()
        code={p.name:p.read_text(encoding='utf-8') for p in Path(__file__).parent.glob('recovery_*.py')}
        # Copy the immutable original engine, native adapter, transport and protocol.
        result=remote(f"""from pathlib import Path
import json,shutil,hashlib,sys
r=Path({REMOTE!r});o=Path({ORIGIN!r})
if r.exists():raise RuntimeError('ExistingRecoveryRootInspectDoNotOverwrite')
r.mkdir(mode=0o700);(r/'package').mkdir();(r/'outputs/canonical').mkdir(parents=True)
for name,source in {code!r}.items():(r/'package'/name).write_text(source)
sys.path.insert(0,str(r/'package'))
from recovery_guard import guard,resources
preflight={{'original':guard(o,{manifest['originalArchiveSha256']!r}),'resources':resources()}}
for name in ['protocol.py','runtime.py','native.ts','engine-origin.json']:shutil.copy2(o/'package'/name,r/'package'/name)
shutil.copytree(o/'package/engine',r/'package/engine',symlinks=False)
shutil.copytree(o/'bin',r/'bin',symlinks=False);shutil.copytree(o/'data',r/'data');shutil.copytree(o/'provenance',r/'provenance')
(r/'data/recovery-manifest.json').write_bytes({raw!r})
cfg=json.loads((o/'package/experiment.json').read_text());(r/'package/original-experiment.json').write_text(json.dumps(cfg,indent=2)+'\\n')
cfg.update(run={NAME!r},originalRoot={ORIGIN!r},recoveryRound=1,originalArchiveSha256={manifest['originalArchiveSha256']!r},authorization='user authorized exactly one separate recovery round and explicit extra 600-second solver budget')
(r/'package/experiment.json').write_text(json.dumps(cfg,indent=2)+'\\n')
(r/'resource-preflight.json').write_text(json.dumps(preflight,indent=2)+'\\n')
print(json.dumps({{'root':str(r),'manifestSha256':hashlib.sha256((r/'data/recovery-manifest.json').read_bytes()).hexdigest(),'preflight':preflight}}))
""",timeout=180)
        assert json.loads(result)['manifestSha256']==sha(raw)
        (LOCAL/'deployment.json').write_text(result,encoding='utf-8');print(result)
    elif action=='launch':
        text=(REPO/'.env').read_text(encoding='utf-8-sig')
        match=re.search(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$',text,re.M)
        if not match:raise RuntimeError('MissingExistingDeepSeekCredential')
        key=match[1].strip().strip('\"\'')
        p=subprocess.run(SSH+['/usr/bin/python3.11',REMOTE+'/package/recovery_launcher.py'],input=json.dumps({'key':key}),text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=120)
        if key in p.stdout+p.stderr:raise RuntimeError('CredentialOutputSuppressed')
        if p.returncode:raise RuntimeError(p.stderr[-2500:])
        (LOCAL/'connection.json').write_text(p.stdout,encoding='utf-8');print(p.stdout)
    elif action=='sync':
        meta=json.loads(remote(guard_code()+f"""import json,tarfile,hashlib
r=Path({REMOTE!r});out=r/'outputs/canonical';s=json.loads((out/'status.json').read_text())
owned=[]
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  raw=p.read_bytes()
  if str(r).encode() in raw:owned.append({{'pid':int(p.parent.name),'cmdline':raw.replace(b'\\x00',b' ').decode(errors='replace')}})
 except OSError:pass
s['ownedProcesses']=owned
a=r/'recovery-sync.tar.gz'
with tarfile.open(a,'w:gz') as t:
 for top in ['outputs/canonical','data','resource-preflight.json']:
  t.add(r/top,arcname=top,filter=lambda x:None if x.name.endswith(('.sqlite','.sqlite-wal','.sqlite-shm')) else x)
print(json.dumps({{'status':s,'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'bytes':a.stat().st_size}}))
""",timeout=180))
        a=LOCAL/'recovery-sync.tar.gz';scp('novaeve:'+REMOTE+'/'+a.name,a)
        assert sha(a.read_bytes())==meta['sha256']
        with tarfile.open(a) as tar:tar.extractall(LOCAL/'compact-mirror',filter='data')
        (LOCAL/'status.json').write_text(json.dumps(meta['status'],indent=2)+'\n',encoding='utf-8')
        (LOCAL/'sync.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(meta['status']))
    elif action=='retrieve':
        a=LOCAL/(NAME+'-results.tar.gz')
        if a.exists():
            m=read(LOCAL/'retrieval.json');assert sha(a.read_bytes())==m['sha256'];print(json.dumps(m));return
        m=json.loads(remote(guard_code()+f"""import json,tarfile,hashlib
r=Path({REMOTE!r});out=r/'outputs/canonical';s=json.loads((out/'status.json').read_text())
assert s['stage'] in {{'complete','complete_with_exceptions','needs_attention'}} and not s['active'] and not s['activeApiRequests']
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:raw=p.read_bytes()
 except OSError:continue
 assert str(r).encode() not in raw,'RecoveryProcessesStillLive'
assert not [p for p in (out/'calls').glob('**/dispatch.json') if not p.with_name('receipt.json').exists()]
assert not [p for p in (out/'jobs').glob('*/*.json') if not (out/'judgments'/p.parent.name/p.name).exists()]
a=r/{a.name!r}
def allow(x):return None if any(y in {{'.env','__pycache__','runtime-home'}} for y in Path(x.name).parts) or x.issym() else x
with tarfile.open(a,'w:gz') as tar:
 for top in ['package','bin','data','outputs','provenance','resource-preflight.json']:tar.add(r/top,arcname=top,filter=allow)
print(json.dumps({{'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'bytes':a.stat().st_size,'stage':s['stage']}}))
""",timeout=240))
        scp('novaeve:'+REMOTE+'/'+a.name,a)
        assert sha(a.read_bytes())==m['sha256'] and a.stat().st_size==m['bytes']
        with tarfile.open(a) as tar:tar.extractall(LOCAL/'full-results',filter='data')
        m.update(archive=str(a),twoEndsSha256Verified=True)
        (LOCAL/'retrieval.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8');print(json.dumps(m))
    else:raise RuntimeError('UnknownAction')

if __name__=='__main__':main()
