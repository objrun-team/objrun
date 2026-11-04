"""Remote builder: final archive + host verification required before a repair exists."""
from pathlib import Path
import fcntl,json,os,shutil,sqlite3,sys,time
from infra_retry_policy import ARMS,REPAIR,PROTOCOL,make_plan,sha

BASE=Path('/var/tmp/tgengin-scibench-20261016')
def read(p):return json.loads(p.read_text())
def live(pid,entry):
 p=Path('/proc',str(pid),'cmdline');return p.exists() and str(entry).encode() in p.read_bytes()
def require_closed(source):
 o=source/'outputs/canonical';s=read(o/'status.json');m=read(source/'package/continuation.json')
 assert not s['active'] and not live(s['pid'],source/'package/run.ts'),'OriginalStillActive'
 assert not live(read(o/'grader-process.json')['pid'],source/'package/stand.py'),'OriginalGraderLive'
 if (o/'supervisor-launch.json').exists():assert not live(read(o/'supervisor-launch.json')['pid'],source/'package/continuation_launcher.py'),'OriginalSupervisorLive'
 assert all(sha(Path(x['path']).read_bytes())==x['sha256'] for x in read(o/'source-pins.json')['files']),'OriginalPinMismatch'
 assert all(p.with_name('receipt.json').exists() for p in (o/'calls').rglob('dispatch.json')),'OriginalUnreceiptedDispatch'
 for p in (o/'tasks').glob('*/*/engine-process.json'):
  e=Path('/proc',str(read(p)['pid']),'environ')
  if e.exists():assert b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() not in e.read_bytes().split(b'\0'),'OriginalNativeLive'
 registry=Path(m['registryPath']);db=sqlite3.connect('file:'+str(registry)+'?mode=ro',uri=True)
 assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==1664
 assert db.execute("SELECT count(*) FROM tasks WHERE state NOT IN ('complete','inherited')").fetchone()[0]==0,'OriginalNotFinished'
 db.close();records=[read(p) for p in (o/'results').rglob('*.json')]
 assert len(records)==1664 and len({(r['arm'],r['id']) for r in records})==1664
 return s,m,records

def build(proof):
 source=Path(proof['sourceRoot']).resolve();assert source.parent==BASE and source.name.startswith('scibench-formal-20261016-v')
 assert proof['originalAuditAllPassed'] and proof['originalRecords']==1664 and proof['localArchiveSha256Verified']
 s,m,records=require_closed(source)
 lease=open(m['globalLockPath'],'a+');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
 original_db_sha=sha(Path(m['registryPath']).read_bytes())
 archive=source/(source.name+'-results.tar.gz');assert sha(archive.read_bytes())==proof['sourceArchiveSha256'],'OriginalArchiveHashMismatch'
 root=BASE/REPAIR;assert not root.exists(),'ExistingRepairInspectNeverOverwrite'
 global_root=BASE/'scibench-infra-retry-20261016-global';assert not global_root.exists(),'ExistingAttemptRegistryNeverReset'
 tooling=Path(__file__).resolve().parent
 pins=read(tooling/'TOOL_PINS.json');assert all(sha((tooling/x['path']).read_bytes())==x['sha256'] for x in pins['files'])
 assert read(tooling/'FIXTURE_AUDIT.json')['allPassed'],'RepairFixtureRequired'
 cfg=read(source/'package/experiment.json');assert cfg['concurrency']==32 and cfg['arms']==ARMS and cfg['solveSeconds']==600 and cfg['checks']==5 and cfg['cyclesMaxUnits']==12 and cfg['maxBranches']==4 and cfg['samples']==5
 assert cfg['perQuestionDollarCap'] is None and cfg['pilotBudgetUsd'] is None
 plan=make_plan(records,str(source),proof['sourceArchiveSha256'])
 for row in plan['classification']:
  row['originalResultSha256']=sha(Path(row['originalResultPath']).read_bytes())
 by_id={(x['arm'],x['id']):x for x in plan['classification']}
 for a in plan['attempts']:a.update(by_id[(a['arm'],a['id'])])
 plan.update({'sourcePid':s['pid'],'originalRegistryPath':m['registryPath'],'originalRegistrySha256AtBuild':original_db_sha,'originalGlobalLockPath':m['globalLockPath'],'registryPath':str(global_root/'attempts.sqlite'),'globalLockPath':str(global_root/'owner.lock'),'formalVerification':proof,'toolPinsSha256':sha((tooling/'TOOL_PINS.json').read_bytes())})
 root.mkdir(mode=0o700);global_root.mkdir(mode=0o700)
 shutil.copytree(source/'package',root/'package',ignore=shutil.ignore_patterns('node_modules','__pycache__','.env','continuation.json'))
 shutil.copytree(source/'data',root/'data');(root/'bin').mkdir();(root/'bin/bun').symlink_to((source/'bin/bun').resolve())
 (root/'package/engine/app/node_modules').symlink_to((source/'package/engine/app/node_modules').resolve(),target_is_directory=True)
 old_run=(source/'package/run.ts').read_text();one=old_run[old_run.index('async function executeOne('):old_run.index('\nasync function main()')]
 template=(tooling/'infra_retry_runner.ts').read_text();assert template.count('__EXECUTE_ONE__')==2
 template=template.replace('// New attempt scheduling only; __EXECUTE_ONE__ is copied byte-for-byte from the formal runner.','// One fresh attempt per authorized infrastructure identity; solver body preserved.')
 (root/'package/run.ts').write_text(template.replace('__EXECUTE_ONE__',one))
 for name in ['infra_retry_launcher.py','infra_retry_build.py','infra_retry_policy.py']:
  shutil.copyfile(tooling/name,root/'package'/name)
 cfg.update({'run':REPAIR,'purpose':'User-authorized one fresh attempt for final infrastructure failures only','repairAttemptAuthorized':True,'originalExperiment':plan['originalExperiment']})
 (root/'package/experiment.json').write_text(json.dumps(cfg,indent=2)+'\n')
 (root/'package/repair-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
 out=root/'outputs/canonical';out.mkdir(parents=True);(out/'controls.json').write_text(json.dumps({'allPassed':True,'originalControls':read(source/'outputs/canonical/controls.json'),'repairFixture':read(tooling/'FIXTURE_AUDIT.json')})+'\n')
 (root/'provenance').mkdir();(root/'provenance/formal-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
 (root/'provenance/original-executeOne.json').write_text(json.dumps({'sha256':sha(one),'sourceRoot':str(source),'preservedVerbatim':True})+'\n')
 (root/'provenance/solver-source-pins.json').write_text(json.dumps({'files':[{'path':x.relative_to(source).as_posix(),'sha256':sha(x.read_bytes())} for x in (source/'package').rglob('*') if x.is_file() and 'node_modules' not in x.parts and '__pycache__' not in x.parts and x.name not in ['run.ts','experiment.json','continuation.json'] and x.suffix in ['.ts','.py','.json','.lock']]},indent=2)+'\n')
 assert all(read(source/'package/experiment.json')[k]==cfg[k] for k in PROTOCOL),'ProtocolChanged'
 db=sqlite3.connect(global_root/'attempts.sqlite');db.executescript('CREATE TABLE attempts(attemptId TEXT PRIMARY KEY, originalExperiment TEXT NOT NULL,arm TEXT NOT NULL,id TEXT NOT NULL,attemptNo INTEGER NOT NULL CHECK(attemptNo=1),originalResultSha256 TEXT NOT NULL,state TEXT NOT NULL,ownerPid INTEGER,claimedAtUtc TEXT,completedAtUtc TEXT,resultSha256 TEXT, UNIQUE(originalExperiment,arm,id,attemptNo));')
 db.executemany('INSERT INTO attempts(attemptId,originalExperiment,arm,id,attemptNo,originalResultSha256,state) VALUES(?,?,?,?,?,?,?)',[(a['attemptId'],a['originalExperiment'],a['arm'],a['id'],1,a['originalResultSha256'],'pending') for a in plan['attempts']]);db.commit();db.close()
 assert sha(Path(m['registryPath']).read_bytes())==original_db_sha,'OriginalRegistryChanged'
 lease.close();print(json.dumps({'root':str(root),'run':REPAIR,'attempts':len(plan['attempts']),'excludedNative':sum(x['classification'].startswith('native_') for x in plan['classification']),'classificationCounts':{k:sum(x['classification']==k for x in plan['classification']) for k in sorted({x['classification'] for x in plan['classification']})},'originalRegistryUnchanged':True}))

if __name__=='__main__':build(json.load(sys.stdin))
