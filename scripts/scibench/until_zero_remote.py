"""Authorized remaining-invalid rounds; immutable history, unique attempts, shared32."""
from pathlib import Path
import fcntl,json,os,shutil,signal,sqlite3,subprocess,sys,time
from infra_retry_policy import ARMS,EXPERIMENT,PROTOCOL,classify,sha
BASE=Path('/var/tmp/tgengin-scibench-20261016');GLOBAL=BASE/'scibench-untilzero-20261016-global'
read=lambda p:json.loads(p.read_text())
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def live(pid,entry):
 p=Path('/proc',str(pid),'cmdline');return p.exists() and str(entry).encode() in p.read_bytes()
def leases(paths):
 result=[]
 for p in dict.fromkeys(paths):
  f=open(p,'a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);result.append(f)
 return result
def require_closed(root):
 o=root/'outputs/canonical';s=read(o/'status.json');launch=read(o/'launch.json')
 assert not s['active'] and not live(s['pid'],root/'package/run.ts'),'HistoryControllerActive'
 assert not (o/'runner-lock.json').exists() and (o/'supervisor-exit.json').exists()
 supervisor=Path('/proc',str(launch['supervisorPid']),'cmdline');assert not supervisor.exists() or str(root/'package').encode() not in supervisor.read_bytes(),'HistorySupervisorActive'
 if (o/'grader-process.json').exists():assert not live(read(o/'grader-process.json')['pid'],root/'package/stand.py')
 for p in (o/'tasks').glob('*/*/engine-process.json'):
  env=Path('/proc',str(read(p)['pid']),'environ')
  try:owned=env.exists() and b'TGENGIN_CONFIG='+str(p.parent/'engine/config.yaml').encode() in env.read_bytes().split(b'\0')
  except FileNotFoundError:owned=False
  assert not owned,'HistoryNativeActive'
 assert all(p.with_name('receipt.json').exists() for p in (o/'calls').rglob('dispatch.json')),'HistoryUnreceiptedDispatch'
 assert all(sha(Path(x['path']).read_bytes())==x['sha256'] for x in read(o/'source-pins.json')['files']),'HistorySourcePinChanged'
 meta=read(root/'package/repair-plan.json') if (root/'package/repair-plan.json').exists() else read(root/'package/continuation.json')
 table='attempts' if (root/'package/repair-plan.json').exists() else 'tasks';db=sqlite3.connect('file:'+meta['registryPath']+'?mode=ro',uri=True)
 clause=' WHERE roundNo='+str(meta['roundNo']) if meta.get('mode')=='until_zero' else ''
 rows=list(db.execute('SELECT arm,id,resultSha256,state FROM '+table+clause));db.close()
 assert rows and all(x[3] in ['complete','inherited'] for x in rows),'HistoryUnfinishedAttempt'
 for arm,tid,digest,_ in rows:assert sha((o/'results'/arm/(tid+'.json')).read_bytes())==digest,'HistoryResultChanged'
 records=[read(p) for p in (o/'results').glob('*/*.json')];assert len(records)==len(rows)
 return meta,records
def history_verified(batches):
 assert len(batches)>=3 and batches[0]['records']==1664 and batches[1]['records']==47 and batches[2]['records']==6
 merged={};original={};prior_meta=[];generations=[]
 for index,b in enumerate(batches):
  root=Path(b['root']).resolve();assert root.parent==BASE and b['finalAuditPassed'] and b['localArchiveVerified']
  assert sha((root/(root.name+'-results.tar.gz')).read_bytes())==b['archiveSha256'],'HistoryArchiveChanged'
  meta,records=require_closed(root);assert len(records)==b['records'];prior_meta.append(meta)
  for r in records:
   k=(r['arm'],r['id'])
   if k in merged:assert not merged[k][0]['grade'].get('valid'),'HistoryOverwroteValidScore'
   if index==0:original[k]=r
   merged[k]=(r,root)
  for p in (root/'outputs/canonical/calls').rglob('receipt.json'):
   g=read(p).get('generationId')
   if g:generations.append(g)
 assert len(original)==len(merged)==1664 and len(generations)==len(set(generations)),'HistoryIdentityOrCostDuplicate'
 return original,merged,prior_meta
def build(proof):
 assert proof['allInvalidExplicitlyAuthorizedUntilZero'] and proof['methodBudgetsUnchanged'] and proof['dollarCap'] is None
 batches=proof['batches'];original,merged,metas=history_verified(batches);pending={k:v for k,v in merged.items() if not v[0]['grade'].get('valid')}
 assert pending,'AlreadyZeroInvalidNoNewBatch'
 assert all(classify(r).startswith(('infra_','native_')) for r,_ in pending.values()),'IntegrityOrUnclassifiedInvalidRequiresReview'
 number=len(batches);assert number>=3;run=f'scibench-untilzero-20261016-r{number:03d}-c32';root=BASE/run;assert not root.exists(),'ExistingRoundNeverOverwrite'
 GLOBAL.mkdir(mode=0o700,exist_ok=True)
 old_locks=[metas[0]['globalLockPath'],metas[1]['globalLockPath'],metas[2]['globalLockPath']];held=leases([*old_locks,str(GLOBAL/'owner.lock')])
 source=Path(batches[0]['root']);tool=Path(__file__).resolve().parent;pins=read(tool/'TOOL_PINS.json');assert all(sha((tool/x['path']).read_bytes())==x['sha256'] for x in pins['files']) and read(tool/'FIXTURE_AUDIT.json')['allPassed']
 db=sqlite3.connect(GLOBAL/'attempts.sqlite');db.executescript('CREATE TABLE IF NOT EXISTS rounds(roundNo INTEGER PRIMARY KEY,root TEXT UNIQUE NOT NULL,planSha256 TEXT NOT NULL); CREATE TABLE IF NOT EXISTS attempts(attemptId TEXT PRIMARY KEY,originalExperiment TEXT NOT NULL,arm TEXT NOT NULL,id TEXT NOT NULL,attemptNo INTEGER NOT NULL CHECK(attemptNo>0),roundNo INTEGER NOT NULL,previousResultSha256 TEXT NOT NULL,originalResultSha256 TEXT NOT NULL,state TEXT NOT NULL,ownerPid INTEGER,claimedAtUtc TEXT,completedAtUtc TEXT,resultSha256 TEXT,UNIQUE(originalExperiment,arm,id,attemptNo));')
 assert not db.execute("SELECT count(*) FROM attempts WHERE state!='complete'").fetchone()[0],'EarlierRoundNotFinished'
 attempts=[]
 for (arm,tid),(r,previous) in sorted(pending.items()):
  ordinal=1+max([int(read(Path(b['root'])/'outputs/canonical/results'/arm/(tid+'.json')).get('attemptNo',0)) for b in batches if (Path(b['root'])/'outputs/canonical/results'/arm/(tid+'.json')).exists()])
  orig=source/'outputs/canonical/results'/arm/(tid+'.json');prev=previous/'outputs/canonical/results'/arm/(tid+'.json')
  attempts.append({'arm':arm,'id':tid,'attemptId':EXPERIMENT+'/'+arm+'/'+tid+f'/authorized-retry-{ordinal}','attemptNo':ordinal,'roundNo':number,'originalExperiment':EXPERIMENT,'eligible':True,'classification':classify(r),'originalPromptSha256':original[(arm,tid)]['promptSha256'],'originalResultPath':str(orig),'originalResultSha256':sha(orig.read_bytes()),'previousResultPath':str(prev),'previousResultSha256':sha(prev.read_bytes()),'previousAttemptId':r.get('attemptId',EXPERIMENT+'/'+arm+'/'+tid+'/original'),'isNewFullAttempt':True})
 old_hashes={m['registryPath']:sha(Path(m['registryPath']).read_bytes()) for m in metas[:3]}
 plan={'schema':3,'mode':'until_zero','roundNo':number,'run':run,'originalExperiment':EXPERIMENT,'sourceRoot':str(source),'sourceArchiveSha256':batches[0]['archiveSha256'],'history':batches,'attempts':attempts,'allInvalidExplicitlyAuthorized':True,'maxNewFullAttemptsPerIdentity':1,'globalSlots':32,'registryPath':str(GLOBAL/'attempts.sqlite'),'globalLockPath':str(GLOBAL/'owner.lock'),'priorGlobalLocks':old_locks,'priorRegistryHashes':old_hashes,'formalVerification':{'originalAuditAllPassed':True,'originalRecords':1664,'localArchiveSha256Verified':True},'mergeRule':'Chronological replacement of current invalid records only. Preserve every existing valid score including valid wrong answers. Never best-of. User authorizes subsequent independent rounds until all1664 have valid scores.','authorization':proof}
 root.mkdir(mode=0o700);shutil.copytree(source/'package',root/'package',ignore=shutil.ignore_patterns('node_modules','__pycache__','.env','continuation.json'));shutil.copytree(source/'data',root/'data');(root/'bin').mkdir();(root/'bin/bun').symlink_to((source/'bin/bun').resolve());(root/'package/engine/app/node_modules').symlink_to((source/'package/engine/app/node_modules').resolve(),target_is_directory=True)
 old=(source/'package/run.ts').read_text();one=old[old.index('async function executeOne('):old.index('\nasync function main()')];template=(tool/'until_zero_runner.ts').read_text();assert template.count('__EXECUTE_ONE__')==1;(root/'package/run.ts').write_text(template.replace('__EXECUTE_ONE__',one))
 for name in ['until_zero_remote.py','infra_retry_policy.py']:shutil.copyfile(tool/name,root/'package'/name)
 cfg=read(source/'package/experiment.json');cfg.update({'run':run,'purpose':'User-authorized fresh attempts for all remaining invalid records until zero','repairAttemptAuthorized':True,'repairRound':number});assert cfg['perQuestionDollarCap'] is None and cfg['pilotBudgetUsd'] is None and cfg['concurrency']==32
 (root/'package/experiment.json').write_text(json.dumps(cfg,indent=2)+'\n');save(root/'package/repair-plan.json',plan)
 save(root/'outputs/canonical/controls.json',{'allPassed':True,'originalControls':read(source/'outputs/canonical/controls.json'),'untilZeroFixture':read(tool/'FIXTURE_AUDIT.json')})
 save(root/'provenance/original-executeOne.json',{'preservedVerbatim':True,'sha256':sha(one),'sourceRoot':str(source)})
 paths=[p for p in (source/'package').rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts and p.name not in ['run.ts','experiment.json','continuation.json'] and p.suffix in ['.ts','.py','.json','.lock']]
 save(root/'provenance/solver-source-pins.json',{'files':[{'path':p.relative_to(source).as_posix(),'sha256':sha(p.read_bytes())} for p in paths]})
 db.execute('INSERT INTO rounds VALUES(?,?,?)',(number,str(root),sha((root/'package/repair-plan.json').read_bytes())))
 db.executemany('INSERT INTO attempts(attemptId,originalExperiment,arm,id,attemptNo,roundNo,previousResultSha256,originalResultSha256,state) VALUES(?,?,?,?,?,?,?,?,?)',[(x['attemptId'],EXPERIMENT,x['arm'],x['id'],x['attemptNo'],number,x['previousResultSha256'],x['originalResultSha256'],'pending') for x in attempts]);db.commit();db.close()
 assert all(sha(Path(p).read_bytes())==h for p,h in old_hashes.items()),'PriorRegistryChanged'
 for f in held:f.close()
 print(json.dumps({'allPassed':True,'run':run,'root':str(root),'roundNo':number,'attempts':len(attempts),'priorRegistriesUnchanged':True}))
def launch(payload,supervise=False):
 root=Path(__file__).resolve().parents[1];out=root/'outputs/canonical';plan=read(root/'package/repair-plan.json')
 if not supervise:
  assert not (out/'launch.json').exists() and not (out/'supervisor-launch.json').exists(),'ExistingLaunchNeverRepeat'
  with (out/'supervisor.stdout.log').open('ab') as so,(out/'supervisor.stderr.log').open('ab') as se:
   child=subprocess.Popen(['/usr/bin/python3.11',str(Path(__file__).resolve()),'--supervise'],cwd=root,env={'PATH':str(root/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1'},stdin=subprocess.PIPE,stdout=so,stderr=se,start_new_session=True);child.stdin.write(json.dumps(payload).encode());child.stdin.close()
  save(out/'supervisor-launch.json',{'pid':child.pid,'root':str(root)});until=time.monotonic()+25
  while not (out/'launch.json').exists():
   assert child.poll() is None,(out/'supervisor.stderr.log').read_text();assert time.monotonic()<until,'LaunchTimeout';time.sleep(.1)
  print((out/'launch.json').read_text());return
 key=payload.pop('key');assert isinstance(key,str) and key
 history_verified(plan['history']);held=leases([*plan['priorGlobalLocks'],plan['globalLockPath']])
 assert all(sha(Path(p).read_bytes())==h for p,h in plan['priorRegistryHashes'].items())
 assert all(read(Path(plan['sourceRoot'])/'package/experiment.json')[k]==read(root/'package/experiment.json')[k] for k in PROTOCOL)
 assert all(sha((root/x['path']).read_bytes())==x['sha256'] for x in read(root/'provenance/solver-source-pins.json')['files'])
 db=sqlite3.connect('file:'+plan['registryPath']+'?mode=ro',uri=True);rows=list(db.execute('SELECT attemptId,state FROM attempts WHERE roundNo=?',(plan['roundNo'],)));assert {x[0] for x in rows}=={x['attemptId'] for x in plan['attempts']} and all(x[1]=='pending' for x in rows);db.close()
 env={'PATH':str(root/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENROUTER_API_KEY':key}
 with (out/'controller.stdout.log').open('ab') as so,(out/'controller.stderr.log').open('ab') as se:child=subprocess.Popen([str(root/'bin/bun'),str(root/'package/run.ts')],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=so,stderr=se)
 record={'pid':child.pid,'supervisorPid':os.getpid(),'root':str(root),'entry':'package/run.ts','atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'credentialWritten':False,'metadata':payload,'globalSlots':32,'attemptCount':len(rows),'roundNo':plan['roundNo']};save(out/'launch.json',record);save(GLOBAL/'owner.json',record)
 def drain(*_):
  if child.poll() is None:child.send_signal(signal.SIGTERM)
 signal.signal(signal.SIGTERM,drain);signal.signal(signal.SIGINT,drain);code=child.wait();save(out/'supervisor-exit.json',{'controllerPid':child.pid,'returncode':code,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())});raise SystemExit(code)
def inspect(root,final=False):
 o=root/'outputs/canonical';plan=read(root/'package/repair-plan.json');s=read(o/'status.json');launch=read(o/'launch.json');running=live(s['pid'],root/'package/run.ts');supervising=live(launch['supervisorPid'],root/'package/until_zero_remote.py')
 assert launch['root']==str(root) and launch['pid']==s['pid'] and all(sha(Path(x['path']).read_bytes())==x['sha256'] for x in read(o/'source-pins.json')['files'])
 assert all(sha(Path(p).read_bytes())==h for p,h in plan['priorRegistryHashes'].items())
 history_verified(plan['history'])
 db=sqlite3.connect('file:'+plan['registryPath']+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;rows=[dict(x) for x in db.execute('SELECT * FROM attempts WHERE roundNo=?',(plan['roundNo'],))];assert len(rows)==len(plan['attempts'])
 started=[x for x in rows if x['state']=='started'];assert len(started)<=32 and all(x['ownerPid']==s['pid'] for x in started)
 for row in rows:
  attempt=next(a for a in plan['attempts'] if a['attemptId']==row['attemptId']);assert row['attemptNo']==attempt['attemptNo'] and row['previousResultSha256']==attempt['previousResultSha256']
  if row['state']=='complete':assert sha((o/'results'/row['arm']/(row['id']+'.json')).read_bytes())==row['resultSha256']
 fs=[]
 for path in [*plan['priorGlobalLocks'],plan['globalLockPath']]:
  f=open(path,'a+');fs.append(f)
  if running:
   try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);raise AssertionError('OwnerLeaseMissing')
   except BlockingIOError:pass
  else:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 unreceipted=[str(p.relative_to(root)) for p in (o/'calls').rglob('dispatch.json') if not p.with_name('receipt.json').exists()]
 same=len(started)==len(s['active']) and {(x['arm'],x['id']) for x in started}=={(x['arm'],x['id']) for x in s['active']}
 if same and started and not (root/'ops/REAL_CONCURRENCY.json').exists():save(root/'ops/REAL_CONCURRENCY.json',{'sameIdentitySet':True,'observed':len(started),'sharedSlotLimit':32,'pid':s['pid'],'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
 if final:
  assert not running and not supervising and not started and not unreceipted and all(x['state']=='complete' for x in rows)
  require_closed(root);dest=root/'provenance/attempts-final.sqlite'
  if dest.exists():
   b=sqlite3.connect('file:'+str(dest)+'?mode=ro',uri=True);assert [tuple(x) for x in b.execute('SELECT * FROM attempts WHERE roundNo=? ORDER BY attemptId',(plan['roundNo'],))]==[tuple(x) for x in db.execute('SELECT * FROM attempts WHERE roundNo=? ORDER BY attemptId',(plan['roundNo'],))];b.close()
  else:b=sqlite3.connect(dest);db.backup(b);b.close()
 archive=root/(root.name+'-results.tar.gz');v={'allPassed':True,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'final':final,'run':root.name,'pid':s['pid'],'supervisorPid':launch['supervisorPid'],'controllerLive':running,'supervisorLive':supervising,'priorRegistriesUnchanged':True,'priorArchivesUnchanged':True,'states':{k:sum(x['state']==k for x in rows) for k in sorted({x['state'] for x in rows})},'unreceiptedDispatches':unreceipted,'status':s,'existingArchive':{'sha256':sha(archive.read_bytes()),'bytes':archive.stat().st_size} if archive.exists() else None}
 if not archive.exists():save(root/'ops/ATTEMPT_AUDIT.json',v)
 print(json.dumps(v))
if __name__=='__main__':
 if '--build' in sys.argv:build(json.load(sys.stdin))
 elif '--inspect' in sys.argv:inspect(Path(sys.argv[sys.argv.index('--inspect')+1]),'--final' in sys.argv)
 else:launch(json.load(sys.stdin),'--supervise' in sys.argv)
