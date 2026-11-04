"""Owned SSH deployment, launch, status and verified local retrieval for SciBench only."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import tarfile

REPO = Path(__file__).resolve().parents[4]
WORKSPACE = REPO.parent
STAGE = WORKSPACE / 'tmp/scibench-pilot-20261016-v1'
LOCAL = REPO / 'docs/scibench/pilot-20261016-v1'
REMOTE = '/mnt/aliyunsb/pingxingwang/tgengin-bench/scibench-pilot-20261016-v1'
ORIGINAL = '/mnt/aliyunsb/pingxingwang/tgengin-bench/scicode-original-20261015'
SSH_CONFIG = 'C:/Users/y1252/Documents/Codex/2026-10-15/s-c/work/scicode/ssh-config'
IS_NVME = False
IS_REPAIR = False
# Explicit run roots keep prior pilot artifacts immutable.
if len(sys.argv)>2:
    run=sys.argv[2]
    match=re.fullmatch(r'scibench-formal-20261016-v([1-9][0-9]*)-c32',run)
    IS_UNTIL_ZERO=bool(re.fullmatch(r'scibench-untilzero-20261016-r[0-9]{3,}-c32',run))
    IS_REPAIR=IS_UNTIL_ZERO or run in {'scibench-infra-retry-20261016-v1-c32','scibench-infra-retry2-20261016-v1-c32'}
    IS_NVME=IS_REPAIR or bool(match and 3<=int(match[1])<=999)
    if not IS_NVME and run not in {'scibench-recovery-20261016-v1','scibench-recovery-20261016-v2','scibench-formal-20261016-v1','scibench-formal-20261016-v2-c32'}:
        raise RuntimeError('UnknownOwnedRun')
    STAGE=WORKSPACE/'tmp'/run
    LOCAL=REPO/'docs/scibench'/run.removeprefix('scibench-')
    REMOTE='/mnt/aliyunsb/pingxingwang/tgengin-bench/'+run
    if IS_NVME:REMOTE='/var/tmp/tgengin-scibench-20261016/'+run
LOCAL.mkdir(parents=True, exist_ok=True)

def ssh(code, timeout=60, stdin=None):
    argv = ['ssh', '-F', SSH_CONFIG, 'novaeve']
    if stdin is None:
        argv += ['python3.11', '-']
        stdin = code
    else:
        argv += ['python3.11', code]
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr[-3000:] + p.stdout[-2000:])
    return p.stdout

action = sys.argv[1]
if action == 'deploy':
    archive = STAGE / 'source-package.tar.gz'
    def allow(info):
        return None if any(p in {'node_modules', '__pycache__', '.env'} for p in Path(info.name).parts) else info
    with tarfile.open(archive, 'w:gz') as tar:
        for name in ['package', 'data']:
            tar.add(STAGE / name, arcname=name, filter=allow)
    print(ssh(f"""from pathlib import Path
r=Path({REMOTE!r})
if (r/'outputs/canonical/launch.json').exists(): raise RuntimeError('ExistingLaunchNoOverwrite')
r.mkdir(parents=True,exist_ok=True)
print('OwnedRootReady')
"""), end='')
    subprocess.run(['scp', '-F', SSH_CONFIG, '-q', str(archive), 'novaeve:' + REMOTE + '/source-package.tar.gz'], check=True, timeout=60)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(ssh(f"""from pathlib import Path
import hashlib,json,tarfile
r=Path({REMOTE!r});a=r/'source-package.tar.gz'
assert hashlib.sha256(a.read_bytes()).hexdigest()=={expected!r}
with tarfile.open(a) as t:t.extractall(r,filter='data')
(r/'bin').mkdir(exist_ok=True)
for p,target in [(r/'bin/bun',Path({ORIGINAL!r})/'bin/bun'),(r/'package/engine/app/node_modules',Path({ORIGINAL!r})/'package/engine/app/node_modules')]:
 if not p.exists():p.symlink_to(target,target_is_directory=target.is_dir())
print(json.dumps({{'sourceArchiveSha256':{expected!r},'root':str(r)}}))
"""), end='')
elif action == 'controls':
    print(ssh(f"""import subprocess,json
from pathlib import Path
r=Path({REMOTE!r})
for argv in [['/usr/bin/python3.11',str(r/'package/controls.py')],[str(r/'bin/bun'),str(r/'package/controls.ts')]]:
 p=subprocess.run(argv,cwd=r,capture_output=True,text=True,timeout=90)
 print(p.stdout);print(p.stderr)
 if p.returncode:raise RuntimeError('RemoteControlsFailed')
""", timeout=220), end='')
elif action in {'launch','settle'}:
    key = None
    for line in (REPO / '.env').read_text(encoding='utf-8-sig').splitlines():
        m = re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$', line)
        if m:
            key = m[1].strip().strip('\"\'')
            break
    if not key:
        raise RuntimeError('MissingExistingAuthorizedKey')
    config_path=STAGE/'package/experiment.json'
    if not config_path.exists():config_path=LOCAL/'full-results/package/experiment.json'
    if (IS_NVME and action=='launch') or not config_path.exists():
        config=json.loads(ssh(f"from pathlib import Path\nprint(Path({REMOTE!r}).joinpath('package/experiment.json').read_text())\n"))
    else:config=json.loads(config_path.read_text(encoding='utf-8'))
    payload={'key':key,'scope':config['purpose'],'config':config} if action=='launch' else {'key':key,'additionalRuns':['scibench-recovery-20261016-v1'] if config.get('priorRecoveryRoot') else []}
    launcher='until_zero_remote.py' if IS_REPAIR and IS_UNTIL_ZERO else 'infra_retry2_launcher.py' if IS_REPAIR and run=='scibench-infra-retry2-20261016-v1-c32' else 'infra_retry_launcher.py' if IS_REPAIR else 'continuation_launcher.py' if IS_NVME else 'launch_remote.py'
    result = ssh(REMOTE + '/package/' + (launcher if action=='launch' else 'cost_lookup.py'), stdin=json.dumps(payload),timeout=120)
    if key in result:
        raise RuntimeError('CredentialUnexpectedlyInOutputSuppressed')
    if action=='launch':(LOCAL / 'connection.json').write_text(json.dumps({'server': 'novaeve', 'root': REMOTE, 'launch': json.loads(result)}, indent=2) + '\n')
    print(result, end='')
elif action == 'status':
    result = ssh(f"""from pathlib import Path
import json
r=Path({REMOTE!r});s=r/'outputs/canonical/status.json'
if s.exists():
 v=json.loads(s.read_text());p=Path('/proc')/str(v['pid'])/'cmdline'
 v['ownedProcessLive']=p.exists() and str(r/'package/run.ts').encode() in p.read_bytes()
 print(json.dumps(v))
else:print('{{}}')
for n in ['controller.stdout.log','controller.stderr.log']:
 p=r/'outputs/canonical'/n
 if p.exists():print(n+'\\n'+p.read_text()[-2500:])
""")
    print(result)
    for name in ['status.json', 'launch.json', 'canary.json', 'prices.json', 'balance-latest.json']:
        subprocess.run(['scp', '-F', SSH_CONFIG, '-q', 'novaeve:' + REMOTE + '/outputs/canonical/' + name, str(LOCAL / name)], capture_output=True, timeout=30)
elif action == 'retrieve':
    archive_name=Path(REMOTE).name+'-results.tar.gz'
    archive=LOCAL/archive_name
    if archive.exists():raise RuntimeError('ExistingVerifiedArchiveNoOverwrite')
    metadata = json.loads(ssh(f"""from pathlib import Path
import json,hashlib,tarfile
r=Path({REMOTE!r});s=json.loads((r/'outputs/canonical/status.json').read_text())
if s['active']:raise RuntimeError('ActiveTasksRemain')
p=Path('/proc')/str(s['pid'])/'cmdline'
if p.exists() and str(r/'package/run.ts').encode() in p.read_bytes():raise RuntimeError('ControllerStillLive')
a=r/{archive_name!r}
def allow(x):return None if any(p in {{'node_modules','__pycache__','.env'}} for p in Path(x.name).parts) else x
with tarfile.open(a,'w:gz') as t:
 for n in ['package','data','outputs','ops','provenance','control']:
  if (r/n).exists():t.add(r/n,arcname=n,filter=allow)
print(json.dumps({{'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'bytes':a.stat().st_size,'stage':s['stage']}}))
""", timeout=120))
    subprocess.run(['scp', '-F', SSH_CONFIG, '-q', 'novaeve:' + REMOTE + '/' + archive_name, str(archive)], check=True, timeout=120)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == metadata['sha256'] and archive.stat().st_size == metadata['bytes']
    with tarfile.open(archive) as tar:
        tar.extractall(LOCAL / 'full-results', filter='data')
    (LOCAL / 'retrieval.json').write_text(json.dumps({**metadata, 'localArchive': str(archive), 'sha256Verified': True}, indent=2) + '\n')
    print(json.dumps(metadata))
elif action == 'sync':
    # Completed SQLite stores only. Active calls/logs are snapshots, never final evidence.
    mirror=LOCAL/'full-results'
    known={str(p.relative_to(mirror)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in mirror.rglob('*') if p.is_file() and p.suffix not in {'.tmp'} and 'node_modules' not in p.parts} if mirror.exists() else {}
    metadata=json.loads(ssh(f"""from pathlib import Path
import json,hashlib,tarfile
r=Path({REMOTE!r});known={known!r};out=r/'outputs/canonical'
status=json.loads((out/'status.json').read_text());selected=[];manifest={{}}
completed={{(p.parent.name,p.stem) for p in (out/'results').glob('*/*.json')}}
if (r/'package/repair-plan.json').exists():
 import sqlite3
 plan=json.loads((r/'package/repair-plan.json').read_text());db=sqlite3.connect('file:'+plan['registryPath']+'?mode=ro',uri=True)
 completed &= set(db.execute("SELECT arm,id FROM attempts WHERE state='complete'"));db.close()
for top in ['package','data','outputs','ops','provenance','control']:
 for directory,dirs,files in __import__('os').walk(r/top,followlinks=False):
  dirs[:]=[d for d in dirs if d not in {{'node_modules','__pycache__'}}]
  for name in files:
   p=Path(directory)/name;rel=p.relative_to(r).as_posix()
   if name.endswith('.tmp') or name=='.env' or p.is_symlink():continue
   parts=Path(rel).parts
   if rel.startswith('outputs/canonical/results/') and (parts[3],Path(parts[4]).stem) not in completed:continue
   if rel.startswith('outputs/canonical/tasks/') and '/engine/' in rel:
    arm,tid=parts[3:5]
    if (arm,tid) not in completed:continue
   try:raw=p.read_bytes()
   except FileNotFoundError:continue
   digest=hashlib.sha256(raw).hexdigest();manifest[rel]=digest
   if known.get(rel)!=digest:selected.append((p,rel,raw))
# Histories append before dispatch. Refresh them after all call files so a
# captured request never appears with an older prefix of its own history.
by_rel={{rel:(p,rel,raw) for p,rel,raw in selected}}
for p in (out/'tasks').glob('*/*/samples.json'):
 rel=p.relative_to(r).as_posix();raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest();manifest[rel]=digest
 if known.get(rel)!=digest:by_rel[rel]=(p,rel,raw)
selected=list(by_rel.values())
a=r/'progress-snapshot.tar.gz'
with tarfile.open(a,'w:gz') as t:
 import io
 for p,rel,raw in selected:
  info=tarfile.TarInfo(rel);info.size=len(raw);info.mtime=p.stat().st_mtime;t.addfile(info,io.BytesIO(raw))
print(json.dumps({{'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'bytes':a.stat().st_size,'changedFiles':len(selected),'stage':status['stage'],'completedRecordsAtSnapshotStart':len(completed),'manifest':manifest}}))
""",timeout=120))
    archive=LOCAL/'progress-snapshot.tar.gz'
    subprocess.run(['scp','-F',SSH_CONFIG,'-q','novaeve:'+REMOTE+'/progress-snapshot.tar.gz',str(archive)],check=True,timeout=120)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==metadata['sha256']
    with tarfile.open(archive) as tar:tar.extractall(mirror,filter='data')
    (LOCAL/'sync.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in metadata.items() if k!='manifest'}))
else:
    raise RuntimeError('UnknownAction')
