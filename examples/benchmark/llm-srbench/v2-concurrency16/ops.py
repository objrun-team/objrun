"""Local operations for the independently hashed concurrency handoff."""
import argparse,hashlib,importlib.util,json,pathlib,re,subprocess,sys,tarfile
SOURCE=pathlib.Path(__file__).resolve().parent;REPO=SOURCE.parents[3]
spec=importlib.util.spec_from_file_location('previous_ops',SOURCE.parent/'v2-resume/ops.py');previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
REMOTE=previous.REMOTE;RC=REMOTE+'/outputs/concurrency16';RESULTS=previous.RESULTS;LOCAL=RESULTS/'concurrency16';SSH=previous.SSH;remote=previous.remote;command=previous.command
def stage():
    LOCAL.mkdir(parents=True,exist_ok=True);archive=LOCAL/'control-staging.tar'
    with tarfile.open(archive,'w') as t:
        for p in SOURCE.iterdir():
            if p.suffix in ['.py','.md']:t.add(p,arcname='outputs/concurrency16/'+p.name)
    print(remote(f"from pathlib import Path\np=Path('{RC}');assert not (p/'source-pins.json').exists();assert not (p/'drain-request.json').exists();p.mkdir(exist_ok=True)\nprint('independent directory ready')"))
    previous.v2.old.copy(archive,RC+'/control-staging.tar')
    print(remote(f"import tarfile,pathlib\nr=pathlib.Path('{REMOTE}');assert not (r/'outputs/concurrency16/source-pins.json').exists()\nwith tarfile.open(r/'outputs/concurrency16/control-staging.tar') as t:t.extractall(r,filter='data')\nprint('independent sources staged; package unchanged')"))
def checks():print(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/checks.py'],timeout=300),flush=True)
def handoff(action):print(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/handoff.py',action],timeout=180),flush=True)
def launch():
    key=None
    for line in (REPO/'.env').read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',line)
        if m:key=m[1].strip().strip('"\'');break
    assert key
    r=subprocess.run(SSH+[REMOTE+'/runtime/bin/python',RC+'/launch.py'],input=json.dumps({'key':key,'authorization':'Explicit user concurrency 16/16/16 and controlled handoff','noPaidCanaryAdded':True}),capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
    assert key not in r.stdout and key not in r.stderr;print(r.stdout);assert r.returncode==0,r.stderr[-2000:]
def monitor():
    code=f'''import sys,json,pathlib
sys.path.insert(0,'{RC}');import support as s
state=s.load(s.OUT/'status.json');review=s.preserve();issues=[]
for name,entry in [('pid',state['controllerEntry']),('graderPid',state['graderEntry'])]:
 state[name+'VerifiedLive']=s.live(state[name],entry)
 if state['stage']=='running' and not state[name+'VerifiedLive']:issues.append(name+'NotLive')
assert s.pins()==s.load(s.CONTROL/'source-pins.json'),'ControlSourceChanged'
claims=[s.load(p) for p in (s.CONTROL/'claims').glob('*/*.json')];pairs=[(p['arm'],p['key']) for p in claims];assert len(pairs)==len(set(pairs))
allowed={{(e['arm'],e['key']) for e in review['remainingCells']}};assert set(pairs)<=allowed
active={{(e['arm'],next(t['key'] for t in s.core.CATALOG if t['id']==e['id'])) for e in state['active']}};pending=[];newunknown=[]
approved=('objrun','aa6d065a7b7d4d4bd2f0c0b2')
for d in (s.OUT/'tasks').glob('*/*'):
 if not d.is_dir():continue
 pair=(d.parent.name,d.name);a=s.common.accounting(d)
 if a['unknownCostCount'] and pair!=approved:
  if pair in active and state['pidVerifiedLive'] and not (d/'result.json').exists():pending.append(pair)
  else:newunknown.append(pair)
if newunknown:issues.append('NewClosedUnknown:'+str(newunknown))
state['generationIds']=[];state.update(issues=issues,pendingActiveCells=pending,newClosedUnknownCells=newunknown,claimedUnique=len(pairs),controlSourcePinsMatch=True,allPredecessorCellHashesMatch=True,approvedExceptionAuditPassed=True,concurrencyObserved=s.load(s.CONTROL/'concurrency-latest.json'))
print(json.dumps(state))
'''
    q=json.loads(remote(code,timeout=180));RESULTS.mkdir(exist_ok=True);LOCAL.mkdir(exist_ok=True)
    for name in ['monitor-latest.json','status.json']:(RESULTS/name).write_text(json.dumps(q,indent=2)+'\n',encoding='utf8')
    (LOCAL/'monitor-latest.json').write_text(json.dumps(q,indent=2)+'\n',encoding='utf8')
    with (LOCAL/'monitor-checks.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(q)+'\n')
    print(json.dumps(q))
def pull():
    LOCAL.mkdir(parents=True,exist_ok=True);state=json.loads(remote(f"from pathlib import Path\nprint(Path('{REMOTE}/outputs/status.json').read_text())"));(RESULTS/'status.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf8');print(json.dumps({k:v for k,v in state.items() if k!='generationIds'}),flush=True)
    names=[p.name for p in SOURCE.iterdir() if p.suffix in ['.py','.md']]+['plan.json','handoff.json','drain-request.json','temporary-drain-plan.json','predecessor-plan.original','free-checks.json','source-pins.json','launch.json','concurrency-latest.json','concurrency-history.jsonl','controller-exit.json','exception-audit.json','balance-hold.json']
    for name in names:subprocess.run(['scp','-q','novaeve:'+RC+'/'+name,str(LOCAL/name)],capture_output=True,timeout=60)
    if state.get('executionSegment')!='concurrency16' or state['stage'] not in ['complete_with_exceptions','needs_attention','drained']:return
    prior=json.loads((RESULTS/'concurrency16-retrieval.json').read_text()) if (RESULTS/'concurrency16-retrieval.json').exists() else {}
    if prior.get('sha256Verified') and prior.get('stage')==state['stage'] and prior.get('completeRecords')==state['completed']:return
    meta=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',RC+'/export.py'],timeout=900));archive=RESULTS/pathlib.PurePosixPath(meta['path']).name;command(['scp','-q','novaeve:'+meta['path'],str(archive)],timeout=1200)
    with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==meta['sha256']
    assert archive.stat().st_size==meta['bytes'];dest=RESULTS/'concurrency16-full-results'
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
    spec=importlib.util.spec_from_file_location('local_exception',SOURCE.parent/'v2-resume/audit_exception.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);complete=state['stage']=='complete_with_exceptions';audit=m.inspect(dest,complete)
    p=json.loads((dest/'outputs/concurrency16/plan.json').read_text());preserved=all(hashlib.sha256((dest/path).read_bytes()).hexdigest()==sha for path,sha in p['protectedFiles'].items());pins=json.loads((dest/'outputs/concurrency16/source-pins.json').read_text());sourceok=all(hashlib.sha256((dest/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in pins)
    coverage=False
    if complete:
        a=dest/'analysis/outputs';rows=[json.loads(q.read_text()) for q in (a/'tasks').glob('*/*/result.json')];c=json.loads((dest/'outputs/combined-analysis-audit.json').read_text());assert len(rows)==len({(r['arm'],r['key']) for r in rows})==960 and sum(r.get('recordType')=='interrupted' for r in rows)==2 and sum(r.get('protocolVersion','v1')=='v2' for r in rows)==483
        assert not c['v2AuditPassed'] and c['approvedExceptionAuditPassed'] and not c['allVersionsIntegrityPassed']
        for r in rows:assert (a/'tasks'/r['arm']/r['key']/'final-evaluation.json').exists()
        original=json.loads((dest/'package/continuation-plan.json').read_text())
        for path,sha in original['priorResultHashes'].items():assert hashlib.sha256((a/'tasks'/path/'result.json').read_bytes()).hexdigest()==sha
        for path,sha in p['protectedFiles'].items():
            if path.endswith('/result.json'):assert hashlib.sha256((dest/'analysis'/path).read_bytes()).hexdigest()==sha
        with (dest/'inherited/v1-frozen-results.tar.gz').open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==original['priorArchiveSha256']
        coverage=True
    rec={**meta,'localArchive':str(archive),'localRoot':str(dest),'sha256Verified':True,'approvedExceptionAuditPassed':audit['approvedExceptionAuditPassed'] and preserved and sourceok,'originalOfflineAuditPassed':audit['originalOfflineAuditPassed'],'executionComplete':complete and audit['recordCount']==483,'combinedCoverageVerified':coverage,'priorEvidencePreserved':preserved,'controlSourcePinsMatch':sourceok,'allPaidCostsKnown':False};(RESULTS/'concurrency16-retrieval.json').write_text(json.dumps(rec,indent=2)+'\n',encoding='utf8');(RESULTS/'concurrency16-exception-audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8');print(json.dumps(rec))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','checks','drain','drain-status','seal','launch','pull','monitor']);a=p.parse_args().action
    if a in ['drain','seal','drain-status']:handoff('status' if a=='drain-status' else a)
    else:globals()[a]()
