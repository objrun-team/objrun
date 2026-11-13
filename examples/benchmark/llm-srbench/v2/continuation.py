"""Separate v2 scope, acceptance gate, and explicitly versioned offline analysis."""
import collections,hashlib,json,os,pathlib,shutil,subprocess,threading,time,traceback
import common
from common import ROOT,OUT,CFG,save,durable,digest,accounting
def load_plan():return json.loads((ROOT/'package/continuation-plan.json').read_text())
def verify_plan():
    p=load_plan();prior=pathlib.Path(p['priorRoot'])
    stop=json.loads((prior/'outputs/operator-stop.json').read_text());assert stop['automaticRecoveryForbidden']
    status=json.loads((prior/'outputs/status.json').read_text());assert status['operatorStopped'] and status['completed']==475
    for name,entry in [('pid','run.py'),('graderPid','grader.py')]:
        cmd=pathlib.Path('/proc')/str(status[name])/'cmdline'
        assert not cmd.exists() or str(prior/'package'/entry).encode() not in cmd.read_bytes(),'V1ProcessActive'
    meta=json.loads((prior/'archive.json').read_text());assert meta['sha256']==p['priorArchiveSha256']
    with pathlib.Path(meta['path']).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==meta['sha256']
    started={(d.parent.name,d.name) for d in (prior/'outputs/tasks').glob('*/*') if d.is_dir() and any(d.iterdir())}
    assert started=={(e['arm'],e['key']) for e in p['startedV1Cells']}
    rows=list((prior/'outputs/tasks').glob('*/*/result.json'));assert len(rows)==475
    for r in rows:
        k=r.parent.parent.name+'/'+r.parent.name
        assert hashlib.sha256(r.read_bytes()).hexdigest()==p['priorResultHashes'][k],'V1RawResultChanged'
    a=accounting(prior/'outputs/tasks')
    for k,v in p['priorAccounting'].items():assert abs(a[k]-v)<1e-7,('V1LedgerChanged',k)
    catalog=json.loads((ROOT/'data/public/catalog.json').read_text());allcells={(a,t['key']) for t in catalog for a in CFG['arms']}
    allowed={(e['arm'],e['key']) for e in p['allowedCells']}
    assert len(allowed)==483 and not allowed&started and allowed|started==allcells and len(allcells)==960
    assert len(set(p['canaryIds']))==10
    canary=[e for e in p['allowedCells'] if e['id'] in p['canaryIds']];assert len(canary)==40
    return p
def acceptance():
    for name in ['summary.json','dispatch-free-checks.json','continuation-free-checks.json','end-to-end-free-checks.json','combined-free-checks.json']:
        q=json.loads((OUT/'controls'/name).read_text());assert q['allPassed'],name
        assert q.get('paidCalls',q.get('realApiCalls',0))==0
    q=json.loads((OUT/'controls/report-control.json').read_text())
    assert q['allPassed'] and q['reportCodeSha256']==hashlib.sha256((ROOT/'package/report.py').read_bytes()).hexdigest()
def supervise(r):
    OUT.mkdir(parents=True,exist_ok=True);lock=OUT/'runner.lock.json'
    if lock.exists():
        old=json.loads(lock.read_text());cmd=pathlib.Path('/proc')/str(old['pid'])/'cmdline'
        if cmd.exists() and str(ROOT/'package/run.py').encode() in cmd.read_bytes():raise RuntimeError('RunnerAlreadyLive')
    if (OUT/'operator-stop.json').exists():raise RuntimeError('OperatorStopForbidsRecovery')
    save(lock,{'pid':os.getpid(),'atUtc':r.utc(),'protocolVersion':'v2'})
    try:
        plan=verify_plan();acceptance();pins=r.sourcepins()
        frozen=OUT/'source-pins.json'
        if frozen.exists():assert json.loads(frozen.read_text())==pins,'SourceChanged'
        else:save(frozen,pins)
        allowed={(e['arm'],e['key']) for e in plan['allowedCells']}
        for d in (OUT/'tasks').glob('*/*'):
            assert (d.parent.name,d.name) in allowed,'UnexpectedV2Cell'
            assert not (d/'cell-start.json').exists() or (d/'result.json').exists(),'InterruptedV2CellRequiresAudit'
        common.preflight();port=r.freeport();r.GRADER_URL='http://127.0.0.1:'+str(port)
        env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['KEY','TOKEN','SECRET'])};env['GRADER_PORT']=str(port)
        log=(OUT/'grader.log').open('ab');r.GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(ROOT/'package/grader.py')],env=env,stdout=log,stderr=log)
        r.STATE.update(graderPid=r.GRADER.pid,protocolVersion='v2',expectedNewRecords=483,priorCompleted=475,priorInterrupted=2)
        for _ in range(100):
            try:
                if r.get(r.GRADER_URL+'/health')['ok']:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('GraderStartup')
        threading.Thread(target=r.heartbeat,daemon=True).start()
        book={t['key']:t for t in r.CATALOG}
        canary=[(book[e['key']],e['arm']) for e in plan['allowedCells'] if e['id'] in plan['canaryIds']]
        r.STATE['stage']='canary';r.status()
        with r.concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:cr=list(pool.map(lambda j:r.execute(*j),canary))
        if r.STOP.is_set() or not r.audit_canary(cr):
            r.STATE.update(stage='needs_attention',stopReason=r.STATE['stopReason'] or 'V2CanaryAuditFailed');return
        r.STATE['stage']='running';r.status()
        remaining=iter([(book[e['key']],e['arm']) for e in plan['allowedCells'] if e['id'] not in plan['canaryIds']])
        def consumer():
            while not r.STOP.is_set():
                with r.LOCK:
                    try:job=next(remaining)
                    except StopIteration:return
                r.execute(*job)
        with r.concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:consumer(),range(4)))
        if r.STOP.is_set():r.STATE['stage']='needs_attention';return
        rows=r.all_results();assert len(rows)==483
        assert {(t['arm'],t['key']) for t in rows}==allowed
        r.cost_snapshots(rows)
        save(OUT/'all-candidates-frozen.json',{'atUtc':r.utc(),'count':483,'protocolVersion':'v2','records':[{'arm':t['arm'],'key':t['key'],'sha256':t.get('finalCandidateSha256'),'valid':t['valid'],'costCheckpointsSha256':digest(json.loads((OUT/'tasks'/t['arm']/t['key']/'cost-checkpoints.json').read_text()))} for t in rows]})
        r.STATE['stage']='verification';r.status()
        subprocess.run([str(ROOT/'runtime/bin/python'),str(ROOT/'package/audit.py'),'--root',str(ROOT),'--require-complete'],check=True,env=env)
        r.STATE['stage']='final_evaluation';r.status();finalize(r)
        r.STATE['stage']='complete_with_exceptions' if any(not t['valid'] for t in rows) else 'complete'
    except Exception as e:
        r.STATE.update(stage='needs_attention',stopReason=type(e).__name__+':'+str(e));traceback.print_exc()
    finally:
        r.STOP.set()
        if r.GRADER is not None:r.GRADER.terminate();r.GRADER.wait(timeout=15)
        r.status()
        if lock.exists() and json.loads(lock.read_text())['pid']==os.getpid():lock.unlink()
def finalize(r):
    """Analysis copies retain raw results. Interrupted rows are explicit new exception entries."""
    p=verify_plan();analysis=ROOT/'analysis';ao=analysis/'outputs';ao.mkdir(parents=True,exist_ok=True)
    assert len(r.all_results())==483 and (OUT/'all-candidates-frozen.json').exists()
    shutil.copytree(ROOT/'package',analysis/'package',dirs_exist_ok=True,ignore=shutil.ignore_patterns('node_modules','__pycache__','.env'))
    for name in ['runtime','bin','data']:
        if not (analysis/name).exists():(analysis/name).symlink_to(ROOT/name,target_is_directory=True)
    prior=pathlib.Path(p['priorRoot']);shutil.copytree(prior/'outputs/tasks',ao/'tasks',dirs_exist_ok=True)
    shutil.copytree(OUT/'tasks',ao/'tasks',dirs_exist_ok=True)
    for root in [prior,ROOT]:
        for src in (root/'outputs/fits').glob('*/fit.json'):
            dst=ao/'fits'/src.parent.name/'fit.json'
            if dst.exists():
                x=json.loads(dst.read_text());y=json.loads(src.read_text())
                for field in ['expression','parameters','passed','nmse']:assert x.get(field)==y.get(field),('FitFreezeConflict',src.parent.name,field)
            else:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for e in p['priorInterrupted']:
        d=ao/'tasks'/e['arm']/e['key'];rp=d/'result.json'
        t=next(t for t in r.CATALOG if t['key']==e['key'])
        v={**e,'subset':t['subset'],'publicInputSha256':t['publicSha256'],'protocolVersion':'v1','recordType':'interrupted','valid':False,'answer':'','error':'V1InterruptedAtIntegrityStop; never resumed or resampled',**accounting(d)}
        if not rp.exists():durable(rp,v)
        else:assert json.loads(rp.read_text())==v
    # Raw v1 result bytes remain identical; version metadata is carried by defaults/provenance.
    for key,sha in p['priorResultHashes'].items():assert hashlib.sha256((ao/'tasks'/key/'result.json').read_bytes()).hexdigest()==sha
    oldout=r.OUT;r.OUT=ao
    try:
        rows=r.all_results();assert len(rows)==960;r.cost_snapshots(rows)
        freeze={'atUtc':r.utc(),'count':960,'completedSolverRecords':958,'interruptedRecords':2,'inheritedV1IntegrityFailure':True,'records':[{'arm':t['arm'],'key':t['key'],'sha256':t.get('finalCandidateSha256'),'valid':t['valid'],'costCheckpointsSha256':digest(json.loads((ao/'tasks'/t['arm']/t['key']/'cost-checkpoints.json').read_text()))} for t in rows]}
        save(ao/'all-candidates-frozen.json',freeze)
    finally:r.OUT=oldout
    save(ao/'provenance.json',{'v1ArchiveSha256':p['priorArchiveSha256'],'v1AuditPassed':False,'v1Completed':475,'v2Completed':483,'v1Interrupted':2,'rawV1ResultHashesPreserved':True,'originalV1RowCostMismatchPreserved':True,'feesUseCompleteJournals':True})
    shutil.copytree(OUT/'controls',ao/'controls',dirs_exist_ok=True)
    subprocess.run([str(ROOT/'runtime/bin/python'),str(analysis/'package/report.py')],check=True,env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ['KEY','TOKEN','SECRET'])})
    versions=collections.Counter(json.loads(q.read_text()).get('protocolVersion','v1') for q in (ao/'tasks').glob('*/*/result.json'))
    assert versions=={'v1':477,'v2':483}
    save(OUT/'combined-analysis-audit.json',{'coveragePassed':True,'mapping':960,'completedSolverRecords':958,'interrupted':2,'versions':dict(versions),'v1AuditPassed':False,'v2AuditPassed':True,'inheritedIntegrityFailure':True,'allVersionsIntegrityPassed':False})
    text=(ao/'REPORT.md').read_text()
    text+='\n\nv1 and v2 use different protocol versions and task cohorts, so this does not establish a pure-v2 result on all 240 tasks. Preserve v1 original cost-row discrepancies, 11 infrastructure anomalies, 2 interruptions, and original audit failures. See protocolVersions in summary.json for version-specific statistics.\n'
    (OUT/'REPORT.md').write_text(text,encoding='utf8')
    shutil.copy2(ao/'summary.json',OUT/'summary.json');shutil.copy2(ao/'results.csv',OUT/'results.csv')
