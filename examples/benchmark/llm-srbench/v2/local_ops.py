"""Only the isolated v2 directory. Credentials travel through SSH stdin."""
import argparse,hashlib,json,pathlib,shutil,subprocess,sys,tarfile
SOURCE=pathlib.Path(__file__).resolve().parent;REPO=SOURCE.parents[3]
# Import v1 by explicit filename to avoid this module's own basename.
import importlib.util
spec=importlib.util.spec_from_file_location('v1_ops',SOURCE.parent/'v1/local_ops.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
REMOTE='/mnt/aliyunsb/pingxingwang/tgengin-bench/llm-srbench-20261019-v2'
LOCAL=REPO/'work/llm-srbench-20261019-v2';RESULTS=REPO/'runs/llm-srbench-release240-20261019-v2';remote=old.remote;command=old.command;SSH=old.SSH
def stage():
    LOCAL.mkdir(parents=True,exist_ok=True);package=LOCAL/'package'
    shutil.copytree(REPO/'runs/llm-srbench-release240-20261019/full-results/package',package,dirs_exist_ok=True)
    for p in SOURCE.iterdir():
        if p.is_file() and p.suffix in ['.py','.ts','.json','.md','.patch']:shutil.copy2(p,package/p.name)
    p=package/'engine/test/_lib.ts';s=p.read_text(encoding='utf8');assert s.count('i < 100;')==1 and s.count('i === 99)')==1
    s=s.replace('i < 100;','i < 600;').replace('i === 99)','i === 599)');p.write_text(s,encoding='utf8')
    archive=LOCAL/'v2-package.tar'
    with tarfile.open(archive,'w') as t:t.add(package,arcname='package',filter=lambda m:None if '__pycache__' in pathlib.PurePosixPath(m.name).parts or 'node_modules' in pathlib.PurePosixPath(m.name).parts else m)
    print(remote(f"import pathlib\nr=pathlib.Path('{REMOTE}');assert not (r/'outputs/source-pins.json').exists(),'V2Frozen';r.mkdir(parents=True,exist_ok=True)\nprint('v2 destination verified')"),flush=True)
    old.copy(archive,REMOTE+'/v2-package.tar')
    code=f'''import pathlib,tarfile,shutil,json
r=pathlib.Path('{REMOTE}');v1=pathlib.Path('{old.REMOTE}')
assert not (r/'outputs/source-pins.json').exists(),'V2Frozen'
assert json.loads((v1/'outputs/operator-stop.json').read_text())['automaticRecoveryForbidden']
with tarfile.open(r/'v2-package.tar') as t:t.extractall(r,filter='data')
for name in ['data','bin']:
    if not (r/name).exists():shutil.copytree(v1/name,r/name)
if not (r/'runtime').exists():(r/'runtime').symlink_to(v1/'runtime',target_is_directory=True)
dependency=v1/'package/engine/app/node_modules'
if not (r/'package/engine/app/node_modules').exists():(r/'package/engine/app/node_modules').symlink_to(dependency.resolve(),target_is_directory=True)
(r/'data/private').chmod(0o700);(r/'outputs').mkdir(exist_ok=True)
(r/'inherited').mkdir(exist_ok=True)
archive=json.loads((v1/'archive.json').read_text())
if not (r/'inherited/v1-frozen-results.tar.gz').exists():shutil.copy2(archive['path'],r/'inherited/v1-frozen-results.tar.gz')
print(json.dumps({{'staged':True,'priorFrozenUntouched':True,'v2Tasks':483}}))
'''
    print(remote(code,timeout=300),flush=True)
def controls():
    print(remote(f"from pathlib import Path\nassert not Path('{REMOTE}/outputs/source-pins.json').exists(),'V2Frozen: controls are prelaunch only'\nprint('unfrozen free acceptance')"),flush=True)
    for name in ['controls.py','dispatch_controls.py','continuation_controls.py','end_to_end_controls.py']:
        print(name,flush=True)
        print(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE+'/package/'+name],timeout=900),flush=True)
    fixture=REPO/'work/llm-srbench-20261019-v1/combined_v2_control.py'
    old.copy(fixture,REMOTE+'/combined_v2_control.py')
    print(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE+'/combined_v2_control.py'],timeout=360),flush=True)
    # Freeze only after all free acceptance gates pass, before obtaining paid credentials.
    code=f"import sys\nsys.path.insert(0,'{REMOTE}/package')\nimport run,continuation\ncontinuation.verify_plan();continuation.acceptance();run.save(run.OUT/'source-pins.json',run.sourcepins())\nprint('All free gates passed; independent v2 frozen')"
    print(remote(code,timeout=120),flush=True)
def launch():
    code=f"import pathlib,json,sys\nr=pathlib.Path('{REMOTE}');sys.path.insert(0,str(r/'package'))\nimport continuation,run\ncontinuation.verify_plan();continuation.acceptance();assert json.loads((r/'outputs/controls/combined-free-checks.json').read_text())['allPassed']\nassert json.loads((r/'outputs/source-pins.json').read_text())==run.sourcepins()\nassert not (r/'outputs/launch.json').exists(),'Launch already attempted; audit before any recovery'\nassert not list((r/'outputs/tasks').glob('*/*/result.json')),'New launch must not replay existing cells'\nprint('All frozen v2 gates verified before credential transport')"
    print(remote(code),flush=True)
    # Reuse the proven stdin credential transport, scoped to the v2 entry.
    old.REMOTE=REMOTE;old.launch()
def pull():
    RESULTS.mkdir(parents=True,exist_ok=True)
    state=json.loads(remote(f"import pathlib,json\np=pathlib.Path('{REMOTE}/outputs/status.json');print(p.read_text() if p.exists() else json.dumps({{'stage':'not_launched'}}))"))
    (RESULTS/'status.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in state.items() if k!='generationIds'},ensure_ascii=False),flush=True)
    for name in ['launch.json','canary-audit.json','controls/summary.json','controls/dispatch-free-checks.json','controls/continuation-free-checks.json','controls/end-to-end-free-checks.json','source-pins.json','REPORT.md','summary.json','results.csv','combined-analysis-audit.json']:
        dst=RESULTS/name;dst.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['scp','-q','novaeve:'+REMOTE+'/outputs/'+name,str(dst)],capture_output=True,timeout=60)
    if state['stage'] not in ['complete','complete_with_exceptions','needs_attention']:return
    prior=json.loads((RESULTS/'retrieval.json').read_text(encoding='utf8')) if (RESULTS/'retrieval.json').exists() else {}
    if prior.get('sha256Verified') and prior.get('stage')==state['stage'] and prior.get('completeRecords')==state['completed']:return
    meta=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE+'/package/export.py'],timeout=600));archive=RESULTS/pathlib.PurePosixPath(meta['path']).name
    command(['scp','-q','novaeve:'+meta['path'],str(archive)],timeout=1200)
    with archive.open('rb') as f:got=hashlib.file_digest(f,'sha256').hexdigest()
    assert got==meta['sha256'] and archive.stat().st_size==meta['bytes'];dest=RESULTS/'full-results'
    with tarfile.open(archive) as t:t.extractall(dest,filter='data')
    assert len(list((dest/'outputs/tasks').glob('*/*/result.json')))==meta['completeRecords']
    spec=importlib.util.spec_from_file_location('audit_v2',SOURCE/'audit.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    audit=m.audit(dest,state['stage'] in ['complete','complete_with_exceptions'])
    (RESULTS/'offline-audit.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf8')
    combined=json.loads((dest/'outputs/combined-analysis-audit.json').read_text()) if (dest/'outputs/combined-analysis-audit.json').exists() else {}
    coverage=False
    if combined.get('coveragePassed'):
        plan=json.loads((dest/'package/continuation-plan.json').read_text());analysis=dest/'analysis/outputs';rows=[json.loads(p.read_text()) for p in (analysis/'tasks').glob('*/*/result.json')]
        assert len(rows)==len({(r['arm'],r['key']) for r in rows})==960
        assert sum(r.get('recordType')=='interrupted' for r in rows)==2
        assert sum(r.get('protocolVersion','v1')=='v2' for r in rows)==483
        for key,sha in plan['priorResultHashes'].items():assert hashlib.sha256((analysis/'tasks'/key/'result.json').read_bytes()).hexdigest()==sha
        for r in rows:assert (analysis/'tasks'/r['arm']/r['key']/'final-evaluation.json').exists()
        with (dest/'inherited/v1-frozen-results.tar.gz').open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==plan['priorArchiveSha256']
        assert combined['v1AuditPassed'] is False and combined['allVersionsIntegrityPassed'] is False
        coverage=True
    retrieved={**meta,'localArchive':str(archive),'localRoot':str(dest),'sha256Verified':True,'offlineAuditPassed':audit['allPassed'],'executionComplete':meta['completeRecords']==483 and state['stage'] in ['complete','complete_with_exceptions'],'combinedCoverageVerified':coverage,'inheritedV1AuditPassed':False}
    (RESULTS/'retrieval.json').write_text(json.dumps(retrieved,indent=2)+'\n',encoding='utf8');print(json.dumps(retrieved))
def monitor():
    code=f'''import pathlib,sys,json,hashlib
r=pathlib.Path('{REMOTE}');sys.path.insert(0,str(r/'package'))
import common
s=json.loads((r/'outputs/status.json').read_text());issues=[];pending=[];closedunknown=[]
for name,entry in [('pid',s.get('controllerEntry','run.py')),('graderPid','grader.py')]:
    p=pathlib.Path('/proc')/str(s.get(name,0))/'cmdline';s[name+'VerifiedLive']=p.exists() and str(r/'package'/entry).encode() in p.read_bytes()
for pin in json.loads((r/'outputs/source-pins.json').read_text()):
    if hashlib.sha256((r/pin['path']).read_bytes()).hexdigest()!=pin['sha256']:issues.append('SourceHash:'+pin['path'])
active={{(e['arm'],next(t['key'] for t in json.loads((r/'data/public/catalog.json').read_text()) if t['id']==e['id'])) for e in s['active']}}
approved={{(e['arm'],e['key']) for e in s.get('approvedUnknownCells',[])}};approvedunresolved=[]
plan=json.loads((r/'package/continuation-plan.json').read_text());allowed={{(e['arm'],e['key']) for e in plan['allowedCells']}}
for d in (r/'outputs/tasks').glob('*/*'):
    pair=(d.parent.name,d.name)
    if pair not in allowed:issues.append('OutsideAllowlist:'+str(pair))
    rp=d/'result.json';row=json.loads(rp.read_text()) if rp.exists() else None;a=common.accounting(d)
    if row and any(abs(a[k]-row[k])>1e-7 for k in ['actualCostUsd','accountedUpperBoundUsd','unknownCostCount','modelCalls']):issues.append('CellAccounting:'+str(pair))
    if a['unknownCostCount']:
        if pair in approved:approvedunresolved.append(pair)
        elif pair in active and s['pidVerifiedLive']:pending.append(pair)
        else:closedunknown.append(pair)
    if row:
        for p in (d/'calls').rglob('dispatch.json'):
            if json.loads(p.read_text())['dispatchAtMs']>row['completedAtMs']:issues.append('DispatchAfterResult:'+str(pair))
s.pop('generationIds',None);s.update(issues=issues,pendingActiveCells=pending,closedUnknownCells=closedunknown,approvedUnresolvedCells=approvedunresolved)
print(json.dumps(s))
'''
    v=json.loads(remote(code,timeout=120));RESULTS.mkdir(parents=True,exist_ok=True)
    (RESULTS/'monitor-latest.json').write_text(json.dumps(v,indent=2)+'\n',encoding='utf8')
    with (RESULTS/'monitor-checks.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(v)+'\n')
    print(json.dumps(v,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','controls','launch','pull','monitor']);a=p.parse_args();globals()[a.action]()
