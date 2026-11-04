"""No model calls: real classifier, prepare gates and second-round attempt registry."""
from pathlib import Path
import copy,json,sqlite3,sys,tempfile
sys.path.insert(0,sys.argv[1])
from infra_retry2_build import closed
from infra_retry2_policy import make_plan,AUTHORIZED_IDS
from infra_retry_policy import classify
BASE=Path('/var/tmp/tgengin-scibench-20261016');source=BASE/'scibench-formal-20261016-v4-c32';previous=BASE/'scibench-infra-retry-20261016-v1-c32';read=lambda p:json.loads(p.read_text())
orig=[read(p) for p in (source/'outputs/canonical/results').glob('*/*.json')];prior=[read(p) for p in (previous/'outputs/canonical/results').glob('*/*.json')];pm=read(previous/'package/repair-plan.json')
plan=make_plan(orig,prior,pm,str(source),str(previous),{'original':'mock-sha','previous':'mock-sha'})
assert len(plan['attempts'])==6 and {a['id'] for a in plan['attempts']}==AUTHORIZED_IDS and sum(a['nativeRetryExplicitlyAuthorized'] for a in plan['attempts'])==2
assert len({a['attemptId'] for a in plan['attempts']})==6 and not ({a['attemptId'] for a in plan['attempts']} & {r['attemptId'] for r in prior})
assert all(not r['grade'].get('valid') for r in prior if r['id'] in AUTHORIZED_IDS and r['arm']=='objrun')
bad=copy.deepcopy(prior);next(r for r in bad if r['id']=='scibench-atkins-011' and r['arm']=='objrun')['grade']={'valid':True,'passed':False}
try:make_plan(orig,bad,pm,str(source),str(previous),{'original':'','previous':''});raise AssertionError('ValidFailureAccepted')
except AssertionError as e:assert str(e)!='ValidFailureAccepted'
fixture=Path(tempfile.mkdtemp(prefix='infra-retry2-safety-',dir=BASE/'fixtures'));o=fixture/'outputs/canonical';o.mkdir(parents=True)
save=lambda p,v:p.write_text(json.dumps(v))
save(o/'status.json',{'pid':999999999,'active':[{'arm':'objrun','id':'fixture'}]});save(o/'launch.json',{'root':str(fixture),'pid':999999999,'supervisorPid':999999998})
try:closed(fixture,47,True);raise AssertionError('ActiveAccepted')
except AssertionError as e:assert str(e)=='PriorControllerActive'
save(o/'status.json',{'pid':999999999,'active':[]});save(o/'grader-process.json',{'pid':999999997});save(o/'supervisor-exit.json',{});save(o/'source-pins.json',{'files':[]});(o/'calls/fixture').mkdir(parents=True);save(o/'calls/fixture/dispatch.json',{})
try:closed(fixture,47,True);raise AssertionError('UnreceiptedAccepted')
except AssertionError as e:assert str(e)=='PriorUnreceiptedDispatch'
db=sqlite3.connect(fixture/'attempts.sqlite');db.executescript('CREATE TABLE attempts(attemptId TEXT PRIMARY KEY,attemptNo INTEGER CHECK(attemptNo=2),state TEXT);');row=plan['attempts'][0];db.execute('INSERT INTO attempts VALUES(?,?,?)',(row['attemptId'],2,'pending'));db.commit()
assert db.execute("UPDATE attempts SET state='started' WHERE attemptId=? AND state='pending'",(row['attemptId'],)).rowcount==1
assert db.execute("UPDATE attempts SET state='started' WHERE attemptId=? AND state='pending'",(row['attemptId'],)).rowcount==0
for no in [1,3]:
 try:db.execute('INSERT INTO attempts VALUES(?,?,?)',(str(no),no,'pending'));raise AssertionError('WrongRoundAccepted')
 except sqlite3.IntegrityError:pass
db.close()
v={'allPassed':True,'realProviderCalls':0,'fixtureRoot':str(fixture),'planned':6,'infra':4,'nativeExplicitlyAuthorized':2,'checks':['all six selected by latest authorization','all existing valid scores excluded','original seven native excluded by first-round membership','second identities disjoint from first','active previous controller refused','unreceipted previous dispatch refused','atomic pending-only claim prevents repeat','attemptNo1 and3 refused']};(fixture/'AUDIT.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
