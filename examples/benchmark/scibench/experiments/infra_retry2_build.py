"""Second-round isolated storage. Prior registries, results and archives are read-only."""
from pathlib import Path
import fcntl,json,shutil,sqlite3,sys,time
from infra_retry_policy import ARMS,PROTOCOL,sha
from infra_retry2_policy import REPAIR2,PREVIOUS,make_plan
BASE=Path('/var/tmp/tgengin-scibench-20261016')
read=lambda p:json.loads(p.read_text())

def live(pid,entry):
 p=Path('/proc',str(pid),'cmdline');return p.exists() and str(entry).encode() in p.read_bytes()

def closed(root,expected,repair=False):
 o=root/'outputs/canonical';s=read(o/'status.json');launch=read(o/'launch.json')
 assert launch['root']==str(root) and launch['pid']==s['pid'] and not s['active'] and not live(s['pid'],root/'package/run.ts'),'PriorControllerActive'
 assert not (o/'runner-lock.json').exists(),'PriorRunnerLockPresent'
 assert not live(read(o/'grader-process.json')['pid'],root/'package/stand.py'),'PriorGraderActive'
 assert not live(launch['supervisorPid'],root/'package'/('infra_retry_launcher.py' if repair else 'continuation_launcher.py')),'PriorSupervisorActive'
 assert (o/'supervisor-exit.json').exists(),'MissingSupervisorExit'
 assert all(sha(Path(x['path']).read_bytes())==x['sha256'] for x in read(o/'source-pins.json')['files']),'PriorSourcePinChanged'
 for p in (o/'tasks').glob('*/*/engine-process.json'):
  e=Path('/proc',str(read(p)['pid']),'environ')
  if e.exists():assert b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() not in e.read_bytes().split(b'\0'),'PriorNativeActive'
 assert all(p.with_name('receipt.json').exists() for p in (o/'calls').rglob('dispatch.json')),'PriorUnreceiptedDispatch'
 meta=read(root/'package'/('repair-plan.json' if repair else 'continuation.json'));db=sqlite3.connect('file:'+meta['registryPath']+'?mode=ro',uri=True);table='attempts' if repair else 'tasks'
 assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==expected
 assert not db.execute("SELECT count(*) FROM "+table+" WHERE state NOT IN ('complete','inherited')").fetchone()[0],'PriorUnfinishedRegistry'
 for arm,tid,digest in db.execute('SELECT arm,id,resultSha256 FROM '+table):assert sha((o/'results'/arm/(tid+'.json')).read_bytes())==digest,'PriorResultChanged'
 db.close();records=[read(p) for p in (o/'results').glob('*/*.json')];assert len(records)==expected
 return meta,records

def build(proof):
 source=Path(proof['sourceRoot']).resolve();previous=Path(proof['previousRoot']).resolve()
 assert source.parent==previous.parent==BASE and source.name.startswith('scibench-formal-20261016-v') and previous.name==PREVIOUS
 assert proof['originalFinalAuditPassed'] and proof['previousFinalAuditPassed'] and proof['localArchivesVerified']
 m,originals=closed(source,1664);pm,prior=closed(previous,47,True)
 leases=[]
 for path in [m['globalLockPath'],pm['globalLockPath']]:
  f=open(path,'a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);leases.append(f)
 old_hashes={p:sha(Path(p).read_bytes()) for p in [m['registryPath'],pm['registryPath']]}
 for root,digest in [(source,proof['originalArchiveSha256']),(previous,proof['previousArchiveSha256'])]:assert sha((root/(root.name+'-results.tar.gz')).read_bytes())==digest,'PriorArchiveChanged'
 assert read(previous/'ops/ATTEMPT_AUDIT.json')['final'] and read(previous/'ops/ATTEMPT_AUDIT.json')['allPassed']
 root=BASE/REPAIR2;global_root=BASE/'scibench-infra-retry2-20261016-global';assert not root.exists() and not global_root.exists(),'SecondRoundAlreadyExistsNeverRebuild'
 tooling=Path(__file__).resolve().parent;pins=read(tooling/'TOOL_PINS.json')
 assert all(sha((tooling/x['path']).read_bytes())==x['sha256'] for x in pins['files']) and read(tooling/'FIXTURE_AUDIT.json')['allPassed']
 plan=make_plan(originals,prior,pm,str(source),str(previous),{'original':proof['originalArchiveSha256'],'previous':proof['previousArchiveSha256']})
 for a in plan['attempts']:
  assert sha(Path(a['originalResultPath']).read_bytes())==a['originalResultSha256']
  a['previousResultSha256']=sha(Path(a['previousResultPath']).read_bytes())
 plan.update({'formalVerification':{'originalAuditAllPassed':True,'originalRecords':1664,'localArchiveSha256Verified':True},'previousVerification':proof,'registryPath':str(global_root/'attempts.sqlite'),'globalLockPath':str(global_root/'owner.lock'),'priorRegistryHashes':old_hashes,'priorGlobalLocks':[m['globalLockPath'],pm['globalLockPath']],'toolPinsSha256':sha((tooling/'TOOL_PINS.json').read_bytes())})
 root.mkdir(mode=0o700);global_root.mkdir(mode=0o700)
 shutil.copytree(source/'package',root/'package',ignore=shutil.ignore_patterns('node_modules','__pycache__','.env','continuation.json'))
 shutil.copytree(source/'data',root/'data');(root/'bin').mkdir();(root/'bin/bun').symlink_to((source/'bin/bun').resolve());(root/'package/engine/app/node_modules').symlink_to((source/'package/engine/app/node_modules').resolve(),target_is_directory=True)
 old=(source/'package/run.ts').read_text();one=old[old.index('async function executeOne('):old.index('\nasync function main()')]
 template=(tooling/'infra_retry2_runner.ts').read_text();assert template.count('__EXECUTE_ONE__')==1;(root/'package/run.ts').write_text(template.replace('__EXECUTE_ONE__',one))
 for name in ['infra_retry2_build.py','infra_retry2_launcher.py','infra_retry2_policy.py','infra_retry_policy.py']:shutil.copyfile(tooling/name,root/'package'/name)
 cfg=read(source/'package/experiment.json');cfg.update({'run':REPAIR2,'purpose':'User-authorized second fresh attempt for all six remaining first-round invalid ObjRun outcomes','repairAttemptAuthorized':True,'repairRound':2,'originalExperiment':plan['originalExperiment']})
 assert cfg['perQuestionDollarCap'] is None and cfg['pilotBudgetUsd'] is None
 assert all(cfg[k]==read(source/'package/experiment.json')[k] for k in PROTOCOL)
 (root/'package/experiment.json').write_text(json.dumps(cfg,indent=2)+'\n');(root/'package/repair-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
 out=root/'outputs/canonical';out.mkdir(parents=True);(out/'controls.json').write_text(json.dumps({'allPassed':True,'originalControls':read(source/'outputs/canonical/controls.json'),'repair2Fixture':read(tooling/'FIXTURE_AUDIT.json')})+'\n')
 (root/'provenance').mkdir();(root/'provenance/original-executeOne.json').write_text(json.dumps({'sha256':sha(one),'preservedVerbatim':True,'sourceRoot':str(source)})+'\n')
 (root/'provenance/authorization.json').write_text(json.dumps(proof,indent=2)+'\n')
 paths=[p for p in (source/'package').rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts and p.name not in ['run.ts','experiment.json','continuation.json'] and p.suffix in ['.ts','.py','.json','.lock']]
 (root/'provenance/solver-source-pins.json').write_text(json.dumps({'files':[{'path':p.relative_to(source).as_posix(),'sha256':sha(p.read_bytes())} for p in paths]},indent=2)+'\n')
 db=sqlite3.connect(global_root/'attempts.sqlite');db.executescript('CREATE TABLE attempts(attemptId TEXT PRIMARY KEY,originalExperiment TEXT NOT NULL,arm TEXT NOT NULL,id TEXT NOT NULL,attemptNo INTEGER NOT NULL CHECK(attemptNo=2),originalResultSha256 TEXT NOT NULL,previousAttemptId TEXT NOT NULL,previousResultSha256 TEXT NOT NULL,state TEXT NOT NULL,ownerPid INTEGER,claimedAtUtc TEXT,completedAtUtc TEXT,resultSha256 TEXT,UNIQUE(originalExperiment,arm,id,attemptNo));')
 db.executemany('INSERT INTO attempts(attemptId,originalExperiment,arm,id,attemptNo,originalResultSha256,previousAttemptId,previousResultSha256,state) VALUES(?,?,?,?,?,?,?,?,?)',[(a['attemptId'],a['originalExperiment'],a['arm'],a['id'],2,a['originalResultSha256'],a['previousAttemptId'],a['previousResultSha256'],'pending') for a in plan['attempts']]);db.commit();db.close()
 assert all(sha(Path(p).read_bytes())==h for p,h in old_hashes.items()),'PriorRegistryChanged'
 for f in leases:f.close()
 print(json.dumps({'allPassed':True,'run':REPAIR2,'root':str(root),'attempts':len(plan['attempts']),'priorRegistriesUnchanged':True,'attemptNo':2,'originalSevenNativeExcluded':True}))

if __name__=='__main__':build(json.load(sys.stdin))
