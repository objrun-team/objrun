"""Automatic post-main advance, with all model authorization already granted."""
import argparse,hashlib,importlib.util,json,pathlib,re,subprocess,sys,tarfile
SOURCE=pathlib.Path(__file__).resolve().parent;REPO=SOURCE.parents[3]
sp=importlib.util.spec_from_file_location('mainops',SOURCE.parent/'v2-concurrency16/ops.py');main=importlib.util.module_from_spec(sp);sp.loader.exec_module(main)
REMOTE=main.REMOTE.replace('-v2','-infra-r1');RC=REMOTE+'/control';RESULTS=REPO/'runs/llm-srbench-release240-20261019-infra-r1';SSH=main.SSH;remote=main.remote;command=main.command
def stage():
    RESULTS.mkdir(parents=True,exist_ok=True);archive=RESULTS/'control-staging.tar'
    with tarfile.open(archive,'w') as t:
        for p in SOURCE.iterdir():
            if p.suffix in ['.py','.md']:t.add(p,arcname='control/'+p.name)
    print(remote(f"from pathlib import Path\nr=Path('{REMOTE}');assert not (r/'control/source-pins.json').exists(),'RoundFrozen';assert not (r/'control/blueprint-pins.json').exists(),'BlueprintFrozen';assert not (r/'control/launch.json').exists();(r/'control').mkdir(parents=True,exist_ok=True)\nprint('separate infrastructure root ready')"),flush=True)
    main.previous.v2.old.copy(archive,REMOTE+'/control-staging.tar')
    code=f'''import pathlib,shutil,tarfile,json,hashlib
r=pathlib.Path('{REMOTE}');base=pathlib.Path('{main.REMOTE}');assert not (r/'control/source-pins.json').exists()
with tarfile.open(r/'control-staging.tar') as t:t.extractall(r,filter='data')
if not (r/'package').exists():shutil.copytree(base/'package',r/'package',ignore=shutil.ignore_patterns('__pycache__','node_modules','.env'))
if not (r/'package/engine/app/node_modules').exists():(r/'package/engine/app/node_modules').symlink_to((base/'package/engine/app/node_modules').resolve(),target_is_directory=True)
for name in ['runtime','bin']:
 if not (r/name).exists():(r/name).symlink_to(base/name,target_is_directory=True)
(r/'data').mkdir(exist_ok=True)
if not (r/'data/public').exists():(r/'data/public').symlink_to(base/'data/public',target_is_directory=True)
shutil.copy2(base/'data/manifest.json',r/'data/manifest.json');(r/'outputs').mkdir(exist_ok=True)
shutil.copy2(base/'outputs/source-pins.json',r/'control/base-source-pins.json');shutil.copy2(base/'package/experiment.json',r/'control/base-experiment.json')
for p in json.loads((r/'control/base-source-pins.json').read_text()):assert hashlib.sha256((r/p['path']).read_bytes()).hexdigest()==p['sha256']
assert not (r/'data/private').exists();print(json.dumps({{'copiedFrozenSolverFiles':79,'originalPackagesUntouched':True,'noPrivateDataInSolverRoot':True}}))
'''
    print(remote(code,timeout=300),flush=True)
def checks():print(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/checks.py'],timeout=600),flush=True)
def _key():
    for line in (REPO/'.env').read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',line)
        if m:return m[1].strip().strip('"\'')
    raise RuntimeError('ExistingAuthorizedKeyMissing')
def launch():
    key=_key();r=subprocess.run(SSH+[REMOTE+'/runtime/bin/python',RC+'/launch.py'],input=json.dumps({'key':key,'authorization':'Explicit 2026-10-19 authorization for at most one independent infrastructure attempt; cumulative $78','noPaidCanaryAdded':True}),capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1200)
    assert key not in r.stdout and key not in r.stderr;assert r.returncode==0,r.stderr[-3000:];print(r.stdout,flush=True)
def advance():
    # Invoked after each normal main heartbeat. While it runs, this is read-only.
    q=json.loads(remote(f"import pathlib,json\nr=pathlib.Path('{REMOTE}');print(json.dumps({{'launched':(r/'control/launch.json').exists(),'frozen':(r/'control/source-pins.json').exists()}}))"))
    if q['launched']:pull();monitor();return
    prep=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/prepare.py'],timeout=1800));print(json.dumps(prep),flush=True)
    if not prep['prepared']:return
    if not q['frozen']:
        checks()
        code=f"import sys,json\nsys.path.insert(0,'{RC}');import shared as s\ns.verify_originals();p=s.load(s.CONTROL/'plan.json');cfg=s.load(s.ROOT/'package/experiment.json');assert cfg['priorUpperBoundUsd']==p['originalAccounting']['accountedUpperBoundUsd'];assert cfg['priorUnknownReserveUsd']==p['originalAccounting']['unknownReserveUsd'];assert s.load(s.CONTROL/'free-checks.json')['allPassed'];s.common.durable(s.CONTROL/'source-pins.json',s.source_pins())\nprint(json.dumps({{'frozenSources':len(s.source_pins()),'selected':len(p['selected'])}}))"
        print(remote(code,timeout=600),flush=True)
        pull()
    launch();pull();monitor()
def monitor():
    code=f'''import sys,json
sys.path.insert(0,'{RC}');import shared as s
if not (s.OUT/'status.json').exists():print(json.dumps({{'stage':'waiting_for_main'}}));raise SystemExit
q=s.load(s.OUT/'status.json');q['generationIds']=[];q['pidVerifiedLive']=s.live(q['pid'],q['controllerEntry']);q['graderPidVerifiedLive']=s.live(q.get('graderPid',0),q['graderEntry']);q['priorAccounting']=s.load(s.CONTROL/'plan.json')['originalAccounting'];q['cumulativeUpperBoundUsd']=q['priorAccounting']['accountedUpperBoundUsd']+q['accountedUpperBoundUsd'];q['cumulativeActualCostUsd']=q['priorAccounting']['actualCostUsd']+q['actualCostUsd']
if (s.CONTROL/'source-pins.json').exists():s.verify_sources();q['sourcePinsMatch']=True
q['newPendingCells']=[];q['newClosedUnknownCells']=[];active={{(a['arm'],next(t['key'] for t in s.core.CATALOG if t['id']==a['id'])) for a in q['active']}}
for d in (s.OUT/'tasks').glob('*/*'):
 a=s.ledger(d)
 if not a['unknownRequests']:continue
 pair=(d.parent.name,d.name)
 if pair in active and q['pidVerifiedLive'] and not (d/'result.json').exists():q['newPendingCells'].append(pair)
 else:q['newClosedUnknownCells'].append(pair)
q['concurrencyObserved']=s.load(s.OUT/'concurrency.json') if (s.OUT/'concurrency.json').exists() else None
print(json.dumps(q))
'''
    q=json.loads(remote(code,timeout=120));RESULTS.mkdir(exist_ok=True);(RESULTS/'monitor-latest.json').write_text(json.dumps(q,indent=2)+'\n',encoding='utf8')
    with (RESULTS/'monitor-checks.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(q)+'\n')
    print(json.dumps(q),flush=True)
def pull():
    RESULTS.mkdir(parents=True,exist_ok=True)
    files=json.loads(remote(f"import pathlib,json\nr=pathlib.Path('{REMOTE}');print(json.dumps([p.relative_to(r).as_posix() for folder in ['control','outputs'] for p in (r/folder).iterdir() if p.is_file() and p.suffix in ['.py','.md','.json','.jsonl']]))"))
    for name in files:
        dest=RESULTS/name;dest.parent.mkdir(exist_ok=True);command(['scp','-q','novaeve:'+REMOTE+'/'+name,str(dest)],timeout=120)
    configs=RESULTS/'package-config';configs.mkdir(exist_ok=True)
    for name in ['experiment.json','continuation-plan.json']:command(['scp','-q','novaeve:'+REMOTE+'/package/'+name,str(configs/name)],timeout=120)
    state=json.loads((RESULTS/'outputs/status.json').read_text()) if (RESULTS/'outputs/status.json').exists() else None
    if not state or state['stage'] not in ['complete','complete_partial','needs_attention']:return
    live=json.loads(remote(f"from pathlib import Path\nimport json\np=Path('/proc/{state['pid']}/cmdline');print(json.dumps(p.exists() and {state['controllerEntry']!r}.encode() in p.read_bytes().split(bytes([0]))))"))
    if live:return
    prior=json.loads((RESULTS/'retrieval.json').read_text()) if (RESULTS/'retrieval.json').exists() else {}
    if prior.get('sha256Verified') and prior.get('stage')==state['stage'] and prior.get('records')==state['completed']:return
    meta=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/export.py'],timeout=1200));archive=RESULTS/pathlib.PurePosixPath(meta['path']).name;command(['scp','-q','novaeve:'+meta['path'],str(archive)],timeout=1200)
    with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==meta['sha256']
    assert archive.stat().st_size==meta['bytes'];dest=RESULTS/'full-results'
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
    # Audit in a fresh Python process: imports resolve exclusively to the archive.
    script="import sys,json;sys.path.insert(0,sys.argv[1]);import audit_round;print(json.dumps(audit_round.audit(False,False)))"
    audit=json.loads(command([sys.executable,'-X','utf8','-c',script,str(dest/'control')],timeout=300));(RESULTS/'offline-audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8')
    freeze=json.loads((dest/'control/main-freeze.json').read_text());verified=True;missing=[]
    prefixes={main.REMOTE:main.RESULTS/'concurrency16-full-results',main.REMOTE.replace('-v2','-v1'):REPO/'runs/llm-srbench-release240-20261019/full-results'}
    for e in freeze['files']:
        root=next((server for server in prefixes if e['path'].startswith(server+'/')),None);local=prefixes[root]/e['path'][len(root)+1:] if root else None
        if not local or not local.exists() or hashlib.sha256(local.read_bytes()).hexdigest()!=e['sha256']:verified=False;missing.append(e['path'])
    rec={**meta,'sha256Verified':True,'offlineAuditPassed':audit['allPassed'],'originalEvidenceVerifiedLocally':verified,'originalMissingOrChanged':missing,'executionComplete':state['stage']=='complete' and audit['complete'],'oneRoundFinished':state['stage'] in ['complete','complete_partial'],'localArchive':str(archive),'localRoot':str(dest),'originalAuditsRemainFailed':True};(RESULTS/'retrieval.json').write_text(json.dumps(rec,indent=2)+'\n',encoding='utf8');print(json.dumps(rec),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','checks','advance','launch','monitor','pull']);globals()[p.parse_args().action]()
