"""Local operator for the approved 429 continuation; no frozen package writes."""
import argparse,datetime,hashlib,importlib.util,json,pathlib,re,shutil,subprocess,sys,tarfile
SOURCE=pathlib.Path(__file__).resolve().parent;REPO=SOURCE.parents[3]
spec=importlib.util.spec_from_file_location('v2ops',SOURCE.parent/'v2/local_ops.py');v2=importlib.util.module_from_spec(spec);spec.loader.exec_module(v2)
REMOTE=v2.REMOTE;REMOTE_CONTROL=REMOTE+'/outputs/continuation-429';LOCAL=REPO/'work/llm-srbench-v2-approved429';RESULTS=v2.RESULTS;remote=v2.remote;command=v2.command;SSH=v2.SSH
def prepare():
    LOCAL.mkdir(parents=True,exist_ok=True);old=RESULTS/'full-results';decision=json.loads((RESULTS/'continuation-decision.json').read_text(encoding='utf8'));review=json.loads((RESULTS/'stopped-run-review.json').read_text(encoding='utf8'))
    files={p.relative_to(old).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (old/'outputs/tasks').rglob('*') if p.is_file()}
    cells=[(p.parent.parent.name,p.parent.name) for p in (old/'outputs/tasks').glob('*/*/result.json')]
    calls={a+'/'+k:[p.relative_to(old).as_posix() for p in (old/'outputs/tasks'/a/k/'calls').rglob('*') if p.is_file()] for a,k in cells}
    u=review['unknownRequests'][0];unknown={k:u[k] for k in ['id','arm','key','path','reservedUpperBoundUsd']};unknown['hashes']={name:hashlib.sha256((old/u['path']/name).read_bytes()).hexdigest() for name in ['receipt.json','dispatch.json','response.raw.txt']}
    # Preserve the original approval literal: retain anomalies and resume only the 429 units.
    plan={'authorization':{'humanAnswer':'保留异常，仅续跑429单元','recordedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'terms':'Preserve all 54 records and the unresolved upper bound. No frozen package edits or redispatch. Retain original failed audit; review only the exact approved exception separately.'},'remainingCells':decision['remainingCells'],'protectedCells':cells,'protectedFiles':files,'protectedCallFiles':calls,'approvedUnknown':unknown,'original54ArchiveSha256':review['archive']['sha256'],'originalV2SourceArchiveSha256':'577819d9dbe2f1ff72f6425ce0849538e532808ae3db58a70cc4bd60fe3bcea0','newPaidCanaryCalls':0}
    assert len(cells)==54 and len(plan['remainingCells'])==429
    (LOCAL/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    archive=LOCAL/'controller.tar'
    with tarfile.open(archive,'w') as t:
        for p in SOURCE.iterdir():
            if p.is_file() and p.suffix in ['.py','.md']:t.add(p,arcname='outputs/continuation-429/'+p.name)
        t.add(LOCAL/'plan.json',arcname='outputs/continuation-429/plan.json')
    print(remote(f"from pathlib import Path\nr=Path('{REMOTE_CONTROL}');assert not (r/'source-pins.json').exists(),'ControlFrozen';assert not (r/'launch.json').exists();r.mkdir(parents=True,exist_ok=True)\nprint('Independent control directory verified')"),flush=True)
    v2.old.copy(archive,REMOTE_CONTROL+'/controller.tar')
    print(remote(f"from pathlib import Path\nimport tarfile\nr=Path('{REMOTE}');assert not (r/'outputs/continuation-429/source-pins.json').exists()\nwith tarfile.open(r/'outputs/continuation-429/controller.tar') as t:t.extractall(r,filter='data')\nprint('429 manifest staged; frozen packages untouched')"),flush=True)
def controls():
    print(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE_CONTROL+'/checks.py'],timeout=900),flush=True)
    code=f"import sys,json\nsys.path.insert(0,'{REMOTE_CONTROL}');import runner\nassert json.loads((runner.CONTROL/'free-checks.json').read_text())['allPassed'];runner.protect();assert not (runner.CONTROL/'source-pins.json').exists();runner.durable(runner.CONTROL/'source-pins.json',runner.source_pins())\nprint(json.dumps({{'frozenControlFiles':len(runner.source_pins()),'realApiCalls':0}}))"
    print(remote(code,timeout=180),flush=True)
def launch():
    code=f"import sys,json\nsys.path.insert(0,'{REMOTE_CONTROL}');import runner\nrunner.protect();assert runner.source_pins()==json.loads((runner.CONTROL/'source-pins.json').read_text());assert json.loads((runner.CONTROL/'free-checks.json').read_text())['allPassed'];assert not (runner.CONTROL/'launch.json').exists()\nprint('Approved 429 gates verified before credential transport')"
    print(remote(code,timeout=180),flush=True)
    key=None
    for line in (REPO/'.env').read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',line)
        if m:key=m[1].strip().strip('"\'');break
    assert key,'Missing existing authorized key'
    q={'key':key,'humanAnswer':'保留异常，仅续跑429单元','remainingCells':429,'frozenV2Unchanged':True,'unknownUpperBoundUsd':.0496791}
    r=subprocess.run(SSH+['/usr/bin/python3.11',REMOTE_CONTROL+'/launch.py'],input=json.dumps(q),capture_output=True,text=True,encoding='utf8',errors='replace',timeout=30)
    assert key not in r.stdout and key not in r.stderr,'Credential output suppressed'
    print(r.stdout.strip());assert r.returncode==0,r.stderr[-1000:]
def pull():
    RESULTS.mkdir(parents=True,exist_ok=True)
    state=json.loads(remote(f"from pathlib import Path\nprint(Path('{REMOTE}/outputs/status.json').read_text())"));(RESULTS/'status.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf8');print(json.dumps({k:v for k,v in state.items() if k!='generationIds'}),flush=True)
    local=RESULTS/'continuation-429';local.mkdir(exist_ok=True)
    for name in ['launch.json','source-pins.json','free-checks.json','exception-audit.json','original-v2-audit.json','controller-exit.json','balance-hold.json','plan.json','runner.py','audit_exception.py','checks.py','launch.py','export.py','ops.py','README.md']:
        subprocess.run(['scp','-q','novaeve:'+REMOTE_CONTROL+'/'+name,str(local/name)],capture_output=True,timeout=60)
    if state['stage'] not in ['complete','complete_with_exceptions','needs_attention']:return
    if state.get('executionSegment')!='approved-429':return
    prior=json.loads((RESULTS/'approved429-retrieval.json').read_text(encoding='utf8')) if (RESULTS/'approved429-retrieval.json').exists() else {}
    if prior.get('sha256Verified') and prior.get('stage')==state['stage'] and prior.get('completeRecords')==state['completed']:return
    meta=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE_CONTROL+'/export.py'],timeout=900));archive=RESULTS/pathlib.PurePosixPath(meta['path']).name
    command(['scp','-q','novaeve:'+meta['path'],str(archive)],timeout=1200)
    with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==meta['sha256']
    assert archive.stat().st_size==meta['bytes'];dest=RESULTS/'approved429-full-results'
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
    spec=importlib.util.spec_from_file_location('exception_audit_local',SOURCE/'audit_exception.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    complete=state['stage'] in ['complete','complete_with_exceptions'];audit=m.inspect(dest,complete)
    (RESULTS/'approved429-exception-audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8')
    coverage=False
    if complete:
        a=dest/'analysis/outputs';rows=[json.loads(p.read_text()) for p in (a/'tasks').glob('*/*/result.json')];combined=json.loads((dest/'outputs/combined-analysis-audit.json').read_text())
        assert len(rows)==len({(r['arm'],r['key']) for r in rows})==960
        assert sum(r.get('recordType')=='interrupted' for r in rows)==2 and sum(r.get('protocolVersion','v1')=='v2' for r in rows)==483
        assert combined['v2AuditPassed'] is False and combined['approvedExceptionAuditPassed'] and not combined['allVersionsIntegrityPassed']
        for r in rows:assert (a/'tasks'/r['arm']/r['key']/'final-evaluation.json').exists()
        original=json.loads((dest/'package/continuation-plan.json').read_text())
        for path,sha in original['priorResultHashes'].items():assert hashlib.sha256((a/'tasks'/path/'result.json').read_bytes()).hexdigest()==sha
        approved=json.loads((dest/'outputs/continuation-429/plan.json').read_text())
        for path,sha in approved['protectedFiles'].items():
            if path.endswith('/result.json'):assert hashlib.sha256((dest/'analysis'/path).read_bytes()).hexdigest()==sha
        with (dest/'inherited/v1-frozen-results.tar.gz').open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==original['priorArchiveSha256']
        coverage=True
    rec={**meta,'localArchive':str(archive),'localRoot':str(dest),'sha256Verified':True,'originalOfflineAuditPassed':audit['originalOfflineAuditPassed'],'approvedExceptionAuditPassed':audit['approvedExceptionAuditPassed'],'executionComplete':complete and audit['recordCount']==483,'combinedCoverageVerified':coverage,'allPaidCostsKnown':False}
    (RESULTS/'approved429-retrieval.json').write_text(json.dumps(rec,indent=2)+'\n',encoding='utf8');print(json.dumps(rec))
def monitor():
    v2.monitor()
    code=f"import sys,json\nsys.path.insert(0,'{REMOTE_CONTROL}');import runner\nprint(json.dumps({{'controlSourcePinsMatch':runner.source_pins()==json.loads((runner.CONTROL/'source-pins.json').read_text()),'protected54AndOnlyApprovedException':__import__('audit_exception').inspect(runner.ROOT,False)}}))"
    q=json.loads(remote(code,timeout=180));(RESULTS/'continuation-429/monitor-review.json').write_text(json.dumps(q,indent=2)+'\n',encoding='utf8');print(json.dumps(q))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','controls','launch','pull','monitor']);a=p.parse_args();globals()[a.action]()
