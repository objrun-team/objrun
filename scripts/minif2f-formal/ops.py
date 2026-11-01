"""Own-project SSH lifecycle; only launch reads the authorized workspace credential."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];WORKSPACE=REPO.parent
STAGE=WORKSPACE/'tmp/minif2f-test244-deepinfra-20261019-v1'
DEST=REPO/'docs/minif2f/test244-deepinfra-20261019-v1'
PILOT_DEST=REPO/'docs/minif2f/valid-deepinfra-pilot-20261019-v1'
PROJECT='/data/ProjectManagement/ICLR2027-TgEngin-miniF2F'
REMOTE=PROJECT+'/pm-runtime/runs/minif2f-deepinfra-test244-20261019-v1'
ENV_FILE=PROJECT+'/pm-runtime/formal-test244.env'
SCP=['scp','-q','-o','ClearAllForwardings=yes']

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def ssh(code,payload=None):
    command='cd '+shlex.quote(PROJECT)+' && /usr/bin/python3.11 -c '+shlex.quote(code)
    result=subprocess.run(['ssh','-o','ClearAllForwardings=yes','-o','BatchMode=yes','-o','ConnectTimeout=10','novaeve',command],
        input=json.dumps(payload).encode() if payload is not None else None,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace')[:4000]+result.stdout.decode(errors='replace')[:4000])
    return result.stdout.decode()

def prepare_remote():
    for name in ['source_stand.py','kimina_models.py','public-lock.json']:
        assert sha(STAGE/'vendor'/name)==sha(WORKSPACE/'tmp/minif2f-valid-deepinfra-20261019-v1/vendor'/name)
    assert sha(HERE/'lean_worker.py')==sha(REPO/'scripts/minif2f-ablation/lean_worker.py')
    assert sha(HERE/'sequence.py')==sha(REPO/'scripts/minif2f-ablation/sequence.py')
    auth=read(REPO/'docs/minif2f/FOLLOWUP.json')
    assert auth['formalAuthorized'] is True and auth['formalRequirements']['modelConcurrency']==16
    save(STAGE/'data/human-authorization.json',{'source':auth['formalAuthorizationSource'],
        'constraints':auth['formalRequirements'],'formalAuthorized':True,
        'pilotGateRequiredBeforeModelCalls':True,'noFurtherConfirmationRequired':True})
    code=r"""
import pathlib,json,hashlib,shutil,subprocess,time
project=pathlib.Path(PROJECT);r=pathlib.Path(REMOTE)
assert r.parent==project/'pm-runtime/runs' and not r.exists(),'Preserve existing run'
subprocess.run(['/data/ProjectManagement/.pm/bin/pm-runtime-env',str(project),r.name,ENV_FILE],check=True,capture_output=True)
base=r.with_name('minif2f-pilot-20261019-v1')
(r/'outputs').mkdir(exist_ok=True);(r/'assets').symlink_to(base/'assets',target_is_directory=True)
env=json.loads((base/'outputs/environment.json').read_text())
for path,field in [('repl-bin','replSha256'),('tools/leantar','leantarSha256')]:
 assert hashlib.sha256((r/'assets'/path).read_bytes()).hexdigest()==env[field]
env.update(isolation='bubblewrap unshare-all, env -i, fresh tmpfs, readonly dependencies',atUtc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
(r/'outputs/environment.json').write_text(json.dumps(env,indent=2)+'\n')
shutil.copy2(base/'dependency-bundle.json',r/'dependency-bundle.json')
fresh={'previousCandidatesReused':False,'previousGradesReused':False,'previousCallsOrLedgerReused':False,
 'baselineReadOnlyAssets':str(base/'assets'),'pilotExpensesIncluded':False,'split':'test','tasks':244,
 'dependencyBundleSha256':env['bundleSha256']}
(r/'outputs/fresh-run.json').write_text(json.dumps(fresh,indent=2)+'\n')
print(json.dumps({'prepared':str(r),'environmentFile':ENV_FILE}))
""".replace('PROJECT',repr(PROJECT)).replace('REMOTE',repr(REMOTE)).replace('ENV_FILE',repr(ENV_FILE))
    print(ssh(code))

def push():
    guard="import pathlib,json; r=pathlib.Path("+repr(REMOTE)+"); assert not (r/'outputs/launch-launch.json').exists(),'Paid source frozen'\nfor p in (r/'outputs').glob('controls*-launch.json'):\n c=pathlib.Path('/proc')/str(json.loads(p.read_text())['pid'])/'cmdline'\n assert not(c.exists() and str(r/'package/controls.py').encode() in c.read_bytes()),'Wait for the owned control process to exit'"
    ssh(guard)
    with tarfile.open(STAGE/'package.tar.gz','w:gz') as tar:
        for p in sorted(HERE.iterdir()):
            if p.is_file() and p.suffix in ['.py','.json','.md']:tar.add(p,arcname='package/'+p.name)
        for name in ['vendor','data']:
            for p in sorted((STAGE/name).iterdir()):
                if p.is_file():tar.add(p,arcname=name+'/'+p.name)
    subprocess.run(SCP+[str(STAGE/'package.tar.gz'),'novaeve:'+REMOTE+'/package.tar.gz'],check=True)
    code=r"""
import pathlib,tarfile,shutil,subprocess,json
project=pathlib.Path(PROJECT);r=pathlib.Path(REMOTE)
assert not (r/'outputs/launch-launch.json').exists(),'Paid source frozen'
for p in (r/'outputs').glob('controls*-launch.json'):
 c=pathlib.Path('/proc')/str(json.loads(p.read_text())['pid'])/'cmdline'
 assert not(c.exists() and str(r/'package/controls.py').encode() in c.read_bytes()),'Controls still active'
with tarfile.open(r/'package.tar.gz') as tar:
 members=tar.getmembers();assert all(m.isfile() and not m.name.startswith('/') and '..' not in pathlib.PurePosixPath(m.name).parts for m in members)
 tar.extractall(r)
for name,target in [('package','formal-src'),('data','formal-data'),('vendor','formal-vendor')]:
 shutil.copytree(r/name,project/target,dirs_exist_ok=True)
subprocess.run(['git','add','--','formal-src','formal-data','formal-vendor'],check=True)
if subprocess.run(['git','diff','--cached','--quiet','--','formal-src','formal-data','formal-vendor']).returncode:
 result=subprocess.run(['git','-c','user.name=objrun','-c','user.email=objrun@local','commit','-m','Add authorized shared-16 miniF2F test244 scheduler and controls','--','formal-src','formal-data','formal-vendor'],capture_output=True,text=True)
 if result.returncode:raise RuntimeError(result.stderr)
record={'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'packageFiles':len(members)}
(r/'outputs/git-source.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
""".replace('PROJECT',repr(PROJECT)).replace('REMOTE',repr(REMOTE))
    print(ssh(code))

def gate():
    verification=read(PILOT_DEST/'local-verification.json');audit=read(PILOT_DEST/'independent-audit.json')
    status=read(PILOT_DEST/'status.json');summary=read(PILOT_DEST/'summary.json')
    integrity=read(PILOT_DEST/'archive-integrity.json');credential=read(PILOT_DEST/'credential-scan.json')
    assert status['completed']==24 and status['stage'] in ['complete','complete_with_exceptions']
    assert verification['completeLogsReturnedLocally'] and verification['archiveSha256Verified'] and verification['credentialsAbsent']
    assert sha(PILOT_DEST/'results.tar.gz')==integrity['sha256']==verification['archiveSha256']
    assert audit['protocolAndIntegrityChecksPassed'] and not credential['hits']
    assert summary['budgetChargedUsd']<=2.40+1e-9
    assert all(e.startswith('InfrastructureException:') for e in read(PILOT_DEST/'audit.json')['errors'])
    follow=read(REPO/'docs/minif2f/FOLLOWUP.json');assert follow['formalAuthorized'] is True
    value={'humanAuthorized':True,'pilotCompleted':True,'fullLogsReturnedToLocal':True,
        'archiveSha256Verified':True,'protocolAndIntegrityChecksPassed':True,'credentialsAbsent':True,
        'unknownExpensesConservativelyReserved':True,'ordinaryProofFailuresBlockLaunch':False,
        'pilotArchiveSha256':integrity['sha256'],'localVerificationSha256':sha(PILOT_DEST/'local-verification.json'),
        'pilotLocalResults':str(PILOT_DEST),'pilotKnownCostUsd':summary['actualCostUsd'],
        'pilotUnknownCostCount':summary['unknownCostCount'],'pilotBudgetExposureUsd':summary['budgetChargedUsd'],
        'pilotExpensesIncludedInFormalLedger':False,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    save(STAGE/'pilot-delivery-gate.json',value)
    print(ssh("import pathlib,json,sys; r=pathlib.Path("+repr(REMOTE)+"); p=r/'outputs/pilot-delivery-gate.json'; assert not (r/'outputs/launch-launch.json').exists(); assert not p.exists(),'Preserve existing gate'; p.write_text(json.dumps(json.load(sys.stdin),indent=2)+'\\n'); print('Pilot delivery gate recorded')",value))

def launch(action,attempt):
    key=None
    if action=='launch':
        assert read(REPO/'docs/minif2f/FOLLOWUP.json')['formalAuthorized'] is True
        assert (STAGE/'pilot-delivery-gate.json').exists(),'Complete verified pilot gate first'
        text=(WORKSPACE/'TgEngin.env').read_text(encoding='utf-8-sig')
        match=re.search(r'^\s*OPENROUTER_API_KEY\s*=\s*(.+?)\s*$',text,re.M)
        assert match,'WorkspaceCredentialMissing';key=match[1].strip().strip('"\'')
    code=r"""
import json,os,pathlib,subprocess,sys,time,hashlib
r=pathlib.Path(REMOTE);env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['KEY','TOKEN','SECRET'])}
for line in pathlib.Path(ENV_FILE).read_text().splitlines():
 if line and not line.startswith('#') and '=' in line:
  k,v=line.split('=',1);env[k]=v
env.update(PATH='/usr/bin:/bin',PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',NO_PROXY='127.0.0.1,localhost')
v=json.load(sys.stdin);action=v['action'];stem=action+('-'+str(v['attempt']) if v['attempt']>1 else '')
lock=r/'outputs'/(stem+'-launch.json');assert not lock.exists(),'Existing launch; inspect first'
assert not (r/'outputs/launch-launch.json').exists(),'Paid launch already exists'
for p in (r/'outputs').glob('controls*-launch.json'):
 c=pathlib.Path('/proc')/str(json.loads(p.read_text())['pid'])/'cmdline'
 assert not(c.exists() and str(r/'package/controls.py').encode() in c.read_bytes()),'Controls still active'
if action=='launch':
 assert (r/'outputs/pilot-delivery-gate.json').exists()
 controls=json.loads((r/'outputs/controls.json').read_text());assert controls['allPassed'] and len(controls['checks'])>=23
 assert all(hashlib.sha256((r/name).read_bytes()).hexdigest()==h for name,h in controls['sourcePins'].items())
 # Atomic across separate SSH callers: only one formal controller may be created.
 (r/'outputs/launch-guard').mkdir()
 env['OPENROUTER_API_KEY']=v['key']
entry='controls.py' if action=='controls' else 'run.py'
with (r/'outputs'/(stem+'.stdout.log')).open('ab') as stdout,(r/'outputs'/(stem+'.stderr.log')).open('ab') as stderr:
 child=subprocess.Popen(['/usr/bin/python3.11','-u',str(r/'package'/entry),str(r)],cwd=r,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
value={'pid':child.pid,'entry':entry,'root':str(r),'credentialWritten':False,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
lock.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))
""".replace('REMOTE',repr(REMOTE)).replace('ENV_FILE',repr(ENV_FILE))
    result=ssh(code,{'action':action,'attempt':attempt,**({'key':key} if key else {})})
    print(result)
    if action=='launch':save(STAGE/'launch-receipt.json',json.loads(result))

def health():
    code=r"""
import pathlib,json,hashlib,time
r=pathlib.Path(REMOTE);out=r/'outputs'
state=json.loads((out/'status.json').read_text()) if (out/'status.json').exists() else None
value={'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'root':str(r),'state':state}
for name in ['controls.stdout.log','controls.stderr.log','launch.stderr.log']:
 p=out/name
 if p.exists():value[name]=p.read_text()[-3000:]
if (out/'controls.json').exists():
 c=json.loads((out/'controls.json').read_text());value['controls']={'allPassed':c['allPassed'],'checks':len(c['checks']),'modelCalls':c['modelCalls']}
if state:
 pid=state['pid'];proc=pathlib.Path('/proc')/str(pid);p=proc/'cmdline'
 cmd=p.read_bytes().replace(b'\0',b' ').decode() if p.exists() else None
 value.update(pid=pid,cmdline=cmd,controllerIdentityMatched=bool(cmd and str(r/'package/run.py') in cmd))
 if state['stage']=='running':assert value['controllerIdentityMatched']
 pins=json.loads((out/'source-pins.json').read_text())
 assert all(hashlib.sha256((r/name).read_bytes()).hexdigest()==h for name,h in pins.items())
 value['sourcePinsMatched']=True
 inodes=set()
 if proc.exists():
  for fd in (proc/'fd').iterdir():
   try:
    target=fd.readlink().as_posix()
    if target.startswith('socket:['):inodes.add(target[8:-1])
   except FileNotFoundError:pass
 sockets=[]
 tcp=proc/'net/tcp'
 if tcp.exists():
  for row in tcp.read_text().splitlines()[1:]:
   fields=row.split()
   if fields[9] in inodes and fields[2].endswith(':4858'):
    sockets.append({'remote':fields[2],'state':fields[3],'inode':fields[9]})
 value['ownedProxyTcpConnections']=sockets
 value['ownedProxyEstablishedCount']=sum(x['state']=='01' for x in sockets)
 if state['actualModelActive']>16 or state['graderActive']>4:raise RuntimeError('ActualConcurrencyExceeded')
 print(json.dumps(value))
 if not (out/'results.tar.gz').exists():
  with (out/'operator-observations.jsonl').open('a') as stream:stream.write(json.dumps(value)+'\n')
else:print(json.dumps(value))
""".replace('REMOTE',repr(REMOTE))
    value=json.loads(ssh(code));save(STAGE/'health-latest.json',value)
    with (STAGE/'health-history.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(value)+'\n')
    print(json.dumps(value,ensure_ascii=False))

def pull():
    DEST.mkdir(parents=True,exist_ok=True)
    print(ssh("import sys;sys.path.insert(0,"+repr(REMOTE+'/package')+");import report;report.finish("+repr(REMOTE)+",archive=True)"))
    for name in ['results.tar.gz','archive-integrity.json','REPORT.md','audit.json','summary.json','status.json','results.csv','paired-comparison.json','budget-curves.json','controls.json','environment.json','git-source.json','pilot-delivery-gate.json']:
        subprocess.run(SCP+['novaeve:'+REMOTE+'/outputs/'+name,str(DEST/name)],check=True)
    assert sha(DEST/'results.tar.gz')==read(DEST/'archive-integrity.json')['sha256']
    full=DEST/'full-results';full.mkdir(exist_ok=True)
    with tarfile.open(DEST/'results.tar.gz') as tar:
        assert all(not m.name.startswith('/') and '..' not in Path(m.name).parts and (m.isfile() or m.isdir()) for m in tar.getmembers())
        tar.extractall(full,filter='data')
    save(DEST/'retrieval.json',{'archiveSha256Verified':True,'completeLogsReturnedLocally':True,'completeLogs':str(full)})
    print(json.dumps({'localResults':str(DEST),'sha256Verified':True}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare-remote','push-code','controls','gate','launch','health','pull'])
    parser.add_argument('--attempt',type=int,default=1);args=parser.parse_args()
    if args.action=='prepare-remote':prepare_remote()
    elif args.action=='push-code':push()
    elif args.action=='gate':gate()
    elif args.action in ['controls','launch']:launch(args.action,args.attempt)
    elif args.action=='health':health()
    elif args.action=='pull':pull()
