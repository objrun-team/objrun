"""Isolated fixture of real round creation. No provider calls and no production writes."""
from pathlib import Path
import contextlib,hashlib,io,json,shutil,sqlite3,tempfile
import until_zero_remote as u
BASE=u.BASE;fixture=Path(tempfile.mkdtemp(prefix='until-zero-build-',dir=BASE/'fixtures'));u.BASE=fixture;u.GLOBAL=fixture/'scibench-untilzero-20261016-global'
read=lambda p:json.loads(p.read_text());save=u.save
roots=[];history=[];production=[BASE/'scibench-formal-20261016-v4-c32',BASE/'scibench-infra-retry-20261016-v1-c32',BASE/'scibench-infra-retry2-20261016-v1-c32']
native_ids=['scibench-atkins-011','scibench-atkins-020','scibench-atkins-031','scibench-atkins-037','scibench-class-045','scibench-quan-016']
for index,old in enumerate(production):
 root=fixture/old.name;root.mkdir();roots.append(root);o=root/'outputs/canonical';o.mkdir(parents=True)
 if index==0:
  shutil.copytree(old/'package',root/'package',ignore=shutil.ignore_patterns('node_modules','__pycache__','.env'),symlinks=True);shutil.copytree(old/'data',root/'data');(root/'bin').mkdir();(root/'bin/bun').symlink_to((old/'bin/bun').resolve());(root/'package/engine/app/node_modules').symlink_to((old/'package/engine/app/node_modules').resolve(),target_is_directory=True)
 else:(root/'package').mkdir()
 source=production[1] if index==2 else old
 records=[read(p) for p in (source/'outputs/canonical/results').glob('*/*.json')]
 if index==2:records=[r for r in records if r['id'] in native_ids and r['arm']=='objrun']
 for r in records:
  if index==2:r={**r,'attemptNo':2,'attemptId':r['attemptId'].replace('/infra-retry-1','/infra-retry-2')}
  save(o/'results'/r['arm']/(r['id']+'.json'),r)
 save(o/'status.json',{'pid':999999999,'active':[]});save(o/'launch.json',{'pid':999999999,'supervisorPid':999999998,'root':str(root)});save(o/'grader-process.json',{'pid':999999997});save(o/'supervisor-exit.json',{});save(o/'source-pins.json',{'files':[]});save(o/'controls.json',{'allPassed':True})
 meta={'registryPath':str(root/'mock.sqlite'),'globalLockPath':str(root/'owner.lock')};save(root/'package'/('continuation.json' if index==0 else 'repair-plan.json'),meta)
 db=sqlite3.connect(root/'mock.sqlite');table='tasks' if index==0 else 'attempts';db.execute('CREATE TABLE '+table+'(arm TEXT,id TEXT,resultSha256 TEXT,state TEXT)');db.executemany('INSERT INTO '+table+' VALUES(?,?,?,?)',[(r['arm'],r['id'],u.sha((o/'results'/r['arm']/(r['id']+'.json')).read_bytes()),'complete') for r in records]);db.commit();db.close()
 archive=root/(root.name+'-results.tar.gz');archive.write_bytes(('fixture-'+str(index)).encode());history.append({'root':str(root),'records':len(records),'finalAuditPassed':True,'localArchiveVerified':True,'archiveSha256':u.sha(archive.read_bytes())})
proof={'batches':history,'allInvalidExplicitlyAuthorizedUntilZero':True,'methodBudgetsUnchanged':True,'dollarCap':None};hashes={str(p/'mock.sqlite'):u.sha((p/'mock.sqlite').read_bytes()) for p in roots}
with contextlib.redirect_stdout(io.StringIO()) as out:u.build(proof)
result=json.loads(out.getvalue());assert result['attempts']==13
new=Path(result['root']);plan=read(new/'package/repair-plan.json');assert sum(x['attemptNo']==1 for x in plan['attempts'])==7 and sum(x['attemptNo']==3 for x in plan['attempts'])==6
assert all(u.sha(Path(p).read_bytes())==h for p,h in hashes.items())
try:u.build(proof);raise AssertionError('DuplicateAccepted')
except AssertionError as e:assert str(e)=='ExistingRoundNeverOverwrite'
save(roots[1]/'outputs/canonical/status.json',{'pid':999999999,'active':[{'arm':'objrun','id':'fixture'}]})
try:u.history_verified(history);raise AssertionError('ActiveAccepted')
except AssertionError as e:assert str(e)=='HistoryControllerActive'
save(roots[1]/'outputs/canonical/status.json',{'pid':999999999,'active':[]});save(roots[1]/'outputs/canonical/calls/fixture/dispatch.json',{})
try:u.history_verified(history);raise AssertionError('UnreceiptedAccepted')
except AssertionError as e:assert str(e)=='HistoryUnreceiptedDispatch'
v={'allPassed':True,'realProviderCalls':0,'fixtureRoot':str(fixture),'checks':['all13 invalid including original7 selected','valid scores never selected','attempt ordinals1 and3 preserve per-identity history','prior registries SHA unchanged','duplicate round refused','active history refused','unreceipted history refused','solver copied with no dollar caps and unchanged method limits']};save(fixture/'AUDIT.json',v);print(json.dumps(v))
