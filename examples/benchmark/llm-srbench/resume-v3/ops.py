"""Local setup, free checks, one launch, read-only monitoring and full retrieval."""
import argparse,difflib,hashlib,importlib.util,json,pathlib,subprocess,sys,tarfile
SOURCE=pathlib.Path(__file__).resolve().parent;REPO=SOURCE.parents[3]
sp=importlib.util.spec_from_file_location('historical_ops',SOURCE.parent/'infra-r1/ops.py');old=importlib.util.module_from_spec(sp);sp.loader.exec_module(old)
REMOTE=old.REMOTE.replace('-infra-r1','-resume-v3');RC=REMOTE+'/control';RESULTS=REPO/'runs/llm-srbench-release240-20261019-resume-v3';SSH=old.SSH;remote=old.remote;command=old.command

def stage():
    RESULTS.mkdir(parents=True,exist_ok=True);archive=RESULTS/'control-staging.tar'
    print(remote(f"from pathlib import Path\nc=Path('{RC}');c.mkdir(parents=True,exist_ok=True);assert not (c/'source-pins.json').exists();assert not (c/'launch-intent.json').exists();print('independent version open for preparation')"),flush=True)
    with tarfile.open(archive,'w') as t:
        for p in SOURCE.iterdir():
            if p.suffix in ['.py','.md','.patch']:t.add(p,arcname='control/'+p.name)
    old.main.previous.v2.old.copy(archive,REMOTE+'/control-staging.tar')
    code=f'''import pathlib,tarfile,shutil,json,hashlib,difflib
r=pathlib.Path('{REMOTE}');base=pathlib.Path('{old.main.REMOTE}');c=r/'control';assert not (c/'source-pins.json').exists()
with tarfile.open(r/'control-staging.tar') as t:t.extractall(r,filter='data')
if not (r/'package').exists():shutil.copytree(base/'package',r/'package',ignore=shutil.ignore_patterns('__pycache__','node_modules','.env'))
original=(base/'package/run.py').read_text();needle='isinstance(e,(AccountStop,common.UnknownDispatch))';assert original.count(needle)==2
patched=original.replace(needle,'isinstance(e,AccountStop)');(r/'package/run.py').write_text(patched)
(c/'backend.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),patched.splitlines(True),fromfile='frozen-v2/run.py',tofile='independent-v3/package/run.py')))
(c/'backend-patch.json').write_text(json.dumps({{'baseSha256':hashlib.sha256((base/'package/run.py').read_bytes()).hexdigest(),'newSha256':hashlib.sha256((r/'package/run.py').read_bytes()).hexdigest(),'onlyBehaviorChange':'UnknownDispatch pauses admission and is reviewed after local calls/native exit instead of unconditional global halt; AccountStop still global','replacements':2,'fitterAndEngineUnchanged':True}},indent=2)+'\\n')
if not (r/'package/engine/app/node_modules').exists():(r/'package/engine/app/node_modules').symlink_to((base/'package/engine/app/node_modules').resolve(),target_is_directory=True)
for name in ['runtime','bin']:
 if not (r/name).exists():(r/name).symlink_to(base/name,target_is_directory=True)
(r/'data').mkdir(exist_ok=True)
if not (r/'data/public').exists():(r/'data/public').symlink_to(base/'data/public',target_is_directory=True)
shutil.copy2(base/'data/manifest.json',r/'data/manifest.json');(r/'outputs').mkdir(exist_ok=True)
shutil.copy2(base/'outputs/source-pins.json',c/'base-source-pins.json');shutil.copy2(base/'package/experiment.json',c/'base-experiment.json')
for e in json.loads((c/'base-source-pins.json').read_text()):
 if e['path'] not in ['package/run.py','package/experiment.json','package/continuation-plan.json']:assert hashlib.sha256((r/e['path']).read_bytes()).hexdigest()==e['sha256']
assert not (r/'data/private').exists();print(json.dumps({{'unchangedBackendFiles':76,'globalUnknownStopsReplaced':2,'oldPackagesUntouched':True,'noPrivateDataLink':True}}))
'''
    print(remote(code,timeout=300),flush=True)

def prepare():print(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/prepare.py'],timeout=1800),flush=True)
def checks():
    value=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/checks.py'],timeout=900));print(json.dumps({k:v for k,v in value.items() if k!='sourceFingerprints'}),flush=True)

def freeze():
    code=f'''import sys,json,tarfile,hashlib
sys.path.insert(0,'{RC}');import shared as s
proof=s.load(s.CONTROL/'free-checks.json');assert proof['allPassed'] and proof['realApiCalls']==0 and proof['sourceFingerprints']==s.source_pins()
assert not (s.CONTROL/'launch-intent.json').exists();s.common.durable(s.CONTROL/'source-pins.json',s.source_pins())
target=s.CONTROL/'frozen-source.tar.gz'
with tarfile.open(target,'w:gz') as t:
 for e in s.source_pins():t.add(s.ROOT/e['path'],arcname=e['path'])
 for name in ['source-pins.json','free-checks.json','chain-free-checks.json']:t.add(s.CONTROL/name,arcname='control/'+name)
 for name in ['data/manifest.json','data/public/catalog.json']:t.add(s.ROOT/name,arcname=name)
with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
q={{'path':str(target),'sha256':digest,'bytes':target.stat().st_size,'sourceFiles':len(s.source_pins()),'freeChecks':len(proof['checks']),'realApiCalls':0}};s.common.save(s.CONTROL/'source-archive.json',q);print(json.dumps(q))
'''
    q=json.loads(remote(code,timeout=300));archive=RESULTS/'frozen-source.tar.gz';command(['scp','-q','novaeve:'+q['path'],str(archive)],timeout=300)
    with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==q['sha256']
    dest=RESULTS/'frozen-source'
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
    for e in json.loads((dest/'control/source-pins.json').read_text()):assert hashlib.sha256((dest/e['path']).read_bytes()).hexdigest()==e['sha256']
    q.update(sha256Verified=True,allSourcePinsVerified=True);(RESULTS/'source-retrieval.json').write_text(json.dumps(q,indent=2)+'\n',encoding='utf8');print(json.dumps(q),flush=True)

def launch():
    key=old._key();r=subprocess.run(SSH+[REMOTE+'/runtime/bin/python',RC+'/launch.py'],input=json.dumps({'key':key,'authorization':'Human authorized 258 never-started continuation plus one new infrastructure round, isolated bounded unknowns, cumulative $78, 2026-10-19'}),capture_output=True,text=True,encoding='utf8',errors='replace',timeout=300)
    assert key not in r.stdout and key not in r.stderr;assert r.returncode==0,r.stderr[-3000:];print(r.stdout,flush=True)

def monitor():
    code=f'''import sys,json
sys.path.insert(0,'{RC}');import shared as s
launch=s.load(s.CONTROL/'launch.json')
if not (s.OUT/'status.json').exists():print(json.dumps({{'stage':'initial_history_verification','pid':launch['pid'],'entry':launch['entry'],'pidVerifiedLive':s.live(launch['pid'],launch['entry'])}}));raise SystemExit
q=s.load(s.OUT/'status.json');q['pidVerifiedLive']=s.live(q['pid'],q['controllerEntry']);q['graderPidVerifiedLive']=s.live(q.get('graderPid',0),q['graderEntry']);s.verify_sources();q['sourcePinsMatch']=True
q['concurrencyObserved']=s.load(s.OUT/'concurrency.json') if (s.OUT/'concurrency.json').exists() else None
q['boundedSettledUnknownCells']=[];q['unknownWithoutProof']=[]
active={{(a['arm'],next(t['key'] for t in s.core.CATALOG if t['id']==a['id'])) for a in q['active']}}
for name in ['main','repair']:
 for d in s.round_out(name).glob('tasks/*/*'):
  m=s.ledger(d)
  if not m['unknownRequests']:continue
  pair=(d.parent.name,d.name)
  if (d/'isolation-settlement.json').exists():q['boundedSettledUnknownCells'].append([name,*pair])
  elif name==q['round'] and pair in active and q['pidVerifiedLive']:continue
  else:q['unknownWithoutProof'].append([name,*pair])
print(json.dumps(q))
'''
    q=json.loads(remote(code,timeout=180));RESULTS.mkdir(exist_ok=True);(RESULTS/'monitor-latest.json').write_text(json.dumps(q,indent=2)+'\n',encoding='utf8')
    with (RESULTS/'monitor-checks.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(q)+'\n')
    print(json.dumps(q),flush=True)

def pull():
    RESULTS.mkdir(parents=True,exist_ok=True)
    q=json.loads(remote(f"import pathlib,json\nr=pathlib.Path('{REMOTE}');print(json.dumps([p.relative_to(r).as_posix() for folder in ['control','outputs'] for p in (r/folder).glob('*') if p.is_file() and p.suffix in ['.py','.patch','.json','.jsonl','.md']]))"))
    # One metadata bundle avoids many SSH/scp round trips.
    target=REMOTE+'/metadata.tar.gz';names=json.dumps(q)
    remote(f"import pathlib,tarfile,json\nr=pathlib.Path('{REMOTE}');names=json.loads({names!r})\nwith tarfile.open('{target}','w:gz') as t:\n for n in names:t.add(r/n,arcname=n)",timeout=120)
    meta=RESULTS/'metadata.tar.gz';command(['scp','-q','novaeve:'+target,str(meta)],timeout=300)
    with tarfile.open(meta) as t:t.extractall(RESULTS,filter='data')
    if not (RESULTS/'outputs/status.json').exists():return
    state=json.loads((RESULTS/'outputs/status.json').read_text())
    if state['stage'] not in ['complete','needs_attention']:return
    previous=json.loads((RESULTS/'retrieval.json').read_text()) if (RESULTS/'retrieval.json').exists() else {}
    if previous.get('sha256Verified') and previous.get('stage')==state['stage'] and previous.get('completedByRound')==state['completedByRound']:return
    live=json.loads(remote(f"from pathlib import Path\nimport json\np=Path('/proc/{state['pid']}/cmdline');print(json.dumps(p.exists() and {state['controllerEntry']!r}.encode() in p.read_bytes().split(bytes([0]))))"))
    if live:return
    info=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/export.py'],timeout=900));archive=RESULTS/pathlib.PurePosixPath(info['path']).name;command(['scp','-q','novaeve:'+info['path'],str(archive)],timeout=1200)
    with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==info['sha256']
    assert archive.stat().st_size==info['bytes'];dest=RESULTS/'full-results'
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
    script="import sys,json;sys.path.insert(0,sys.argv[1]);import audit_round;print(json.dumps(audit_round.audit()))"
    audit=json.loads(command([sys.executable,'-X','utf8','-c',script,str(dest/'control')],timeout=600));(RESULTS/'offline-audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8')
    verify_historical_files(dest)
    coverage=False
    if state['stage']=='complete':
        import csv
        with (dest/'outputs/original-vs-continuation-vs-repair.csv').open(encoding='utf8',newline='') as f:rows=list(csv.DictReader(f))
        assert len(rows)==len({(r['arm'],r['key']) for r in rows})==960
        assert len(list((dest/'analysis/mapping').glob('*/*.json')))==960;coverage=True
    rec={**info,'sha256Verified':True,'controlledOfflineAuditPassed':audit['controlledAuditPassed'],'rawVersionAuditPassed':audit['rawVersionAuditPassed'],'historicalEvidenceVerified':True,'combinedCoverageVerified':coverage,'executionComplete':state['stage']=='complete' and coverage and audit['controlledAuditPassed'],'allVersionsIntegrityPassed':False,'historicalAuditsPassed':False,'localArchive':str(archive),'localRoot':str(dest)}
    (RESULTS/'retrieval.json').write_text(json.dumps(rec,indent=2)+'\n',encoding='utf8');print(json.dumps(rec),flush=True)

def verify_historical_files(dest):
    roots={old.main.REMOTE.replace('-v2','-v1'):REPO/'runs/llm-srbench-release240-20261019/full-results',old.main.REMOTE:old.main.RESULTS/'concurrency16-full-results',old.REMOTE:old.RESULTS/'full-results'}
    discrepancies=[]
    for e in json.loads((dest/'control/history-freeze.json').read_text())['files']:
        server=next(k for k in roots if e['path'].startswith(k+'/'));p=roots[server]/e['path'][len(server)+1:]
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256']:continue
        # Preserve old archives/extractions; fetch exact frozen bytes to a sidecar.
        target=RESULTS/'historical-evidence-sidecars'/pathlib.PurePosixPath(server).name/e['path'][len(server)+1:];target.parent.mkdir(parents=True,exist_ok=True)
        command(['scp','-q','novaeve:'+e['path'],str(target)],timeout=120)
        assert hashlib.sha256(target.read_bytes()).hexdigest()==e['sha256'],'HistoricalFrozenEvidenceChanged'
        discrepancies.append({**e,'verifiedSidecar':str(target),'oldLocalCopyNotOverwritten':True})
    (RESULTS/'historical-evidence-review.json').write_text(json.dumps({'allFrozenFilesVerified':True,'sidecars':discrepancies,'oldArchivesUntouched':True},indent=2)+'\n',encoding='utf8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','prepare','checks','freeze','launch','monitor','pull']);globals()[p.parse_args().action]()
