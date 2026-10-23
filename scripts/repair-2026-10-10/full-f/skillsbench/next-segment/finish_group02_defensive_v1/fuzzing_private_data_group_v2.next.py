"""STAGED fixed-private data/replay grader; real cold controls still required."""
import contextlib,hashlib,importlib.metadata,io,json,os,sys,time
from pathlib import Path
assert sys.flags.isolated and sys.dont_write_bytecode
assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']=='1'
trusted=json.loads(Path('/opt/objrun/trusted.json').read_bytes())
for p in trusted['files']:assert hashlib.sha256(Path(p['path']).read_bytes()).hexdigest()==p['sha256']
libs=('arrow','ujson','black','ipython','minisgl');lib=os.environ.get('LIB')
assert lib is None or lib in libs
# /app must be a fresh private tmpfs. Candidate snapshot layers never supply it.
assert not any(Path('/app').iterdir())
import base64,types
from pathlib import PurePosixPath
payload=json.load(sys.stdin);data=payload['ordinaryCapture'];envelope=payload['executionEnvelope']
assert data['nativeOriginVerified'] is True and not data['denied']
assert data['candidateSnapshotUsedForTrustedGrader'] is False
assert len(data['metadata'])<=65536 and len(data['artifacts'])<=16
def app_path(name):
 p=PurePosixPath(name)
 assert p.is_absolute() and p.parts[:2]==('/','app') and '..' not in p.parts and '\\' not in name
 assert str(p)==name
 return Path(name)
for name,meta in sorted(data['metadata'].items(),key=lambda item:len(PurePosixPath(item[0]).parts)):
 if meta.get('directory') and not meta.get('symlink') and not meta.get('hardlink'):
  app_path(name).mkdir(parents=True,exist_ok=True)
allowed={'/app/libraries.txt',*(f'/app/{l}/{n}' for l in libs for n in ('fuzz.py','fuzz.log','notes_for_testing.txt'))}
seen=set();total=0
for artifact in data['artifacts']:
 name=artifact['path'];assert name in allowed and name not in seen;seen.add(name)
 meta=data['metadata'][name];assert meta['regular'] and not meta['symlink'] and not meta['hardlink']
 body=base64.b64decode(artifact['base64'],validate=True);total+=len(body)
 assert len(body)==artifact['bytes'] and len(body)<=16*1024**2 and total<=64*1024**2
 assert hashlib.sha256(body).hexdigest()==artifact['sha256'];body.decode('utf8',errors='strict')
 p=app_path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
for l in libs:
 # .venv existence comes from daemon metadata only. No candidate interpreter,
 # executable, dependency tree, or activate contents enter the trusted grader.
 name=f'/app/{l}/.venv/bin/activate';meta=data['metadata'].get(name,{})
 if meta.get('regular') and not meta.get('symlink') and not meta.get('hardlink'):
  p=app_path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'')
 root=f'/app/{l}';meta=data['metadata'].get(root,{})
 if meta.get('directory') and meta.get('nonempty') and not any(app_path(root).iterdir()):
  # Preserve an actual immediate daemon child name for original any(iterdir).
  children=[(n,m) for n,m in data['metadata'].items() if PurePosixPath(n).parent==PurePosixPath(root)]
  assert children
  n,m=children[0];p=app_path(n)
  assert m.get('regular') and not m.get('symlink') and not m.get('hardlink') and n not in allowed
  p.write_bytes(b'')
if '/app/libraries.txt' in seen:
 for line in Path('/app/libraries.txt').read_text().splitlines():
  line=line.strip()
  if line:
   p=PurePosixPath(line);assert not p.is_absolute() and '..' not in p.parts and '\\' not in line,'outside_app_discovery_namespace_denied'
assert hashlib.sha256(payload['trustedReplaySource'].encode()).hexdigest()==payload['trustedReplaySourceSha256']
replay=types.ModuleType('trusted_fuzzing_replay');exec(compile(payload['trustedReplaySource'],'<trusted-host-replay>','exec'),replay.__dict__)
sys.path.insert(0,'/verifier');import testing_utils
positions=replay.install_original_execution_replay(testing_utils,envelope)
target='/verifier/test_lib.py' if lib else '/verifier/test_setup.py'
import pytest
entry=[e for e in importlib.metadata.distribution('pytest-json-ctrf').entry_points if e.group=='pytest11'];assert len(entry)==1
class Witness:
 def __init__(self):self.nodes=[];self.reports=[];self.collectionErrors=[]
 def pytest_collection_finish(self,session):self.nodes=[x.nodeid for x in session.items]
 def pytest_collectreport(self,report):
  if report.failed or report.skipped:self.collectionErrors.append({'nodeId':report.nodeid,'outcome':report.outcome})
 def pytest_runtest_logreport(self,report):self.reports.append({'nodeId':report.nodeid,'phase':report.when,'outcome':report.outcome,'wasXfail':getattr(report,'wasxfail',None)})
w=Witness();captured=io.StringIO();began=time.monotonic()
with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
 code=int(pytest.main(['-c','/opt/objrun/empty.ini','--confcutdir=/verifier','--ctrf','/logs/ctrf.json',target,'-rA','-v'],plugins=[entry[0].load(),w]))
phases={}
for r in w.reports:
 d=phases.setdefault(r['nodeId'],{});assert r['phase'] not in d;d[r['phase']]=r
issues=[]
for node in w.nodes:
 p=phases.get(node,{})
 if p.get('teardown',{}).get('outcome')!='passed':issues.append('missing_or_failed_teardown')
 ordinary=p.get('setup',{}).get('outcome')=='passed' and p.get('call',{}).get('outcome') in ('passed','failed')
 failed_setup=p.get('setup',{}).get('outcome')=='failed' and 'call' not in p
 if not (ordinary or failed_setup):issues.append('incomplete_or_skipped_test')
 if any(r['wasXfail'] is not None for r in p.values()):issues.append('xfail')
passed=sum(r['phase']=='call' and r['outcome']=='passed' for r in w.reports)
failed=sum(r['phase']=='call' and r['outcome']=='failed' for r in w.reports)
errors=sum(p.get('setup',{}).get('outcome')=='failed' for p in phases.values())
complete=len(w.nodes)==(4 if lib else 2) and len(set(w.nodes))==len(w.nodes) and not w.collectionErrors and not issues and code in (0,1) and passed+failed+errors==len(w.nodes)
assert all(value==0 for name,value in positions.items() if name!=lib)
assert lib is None or positions[lib]==len(envelope['libraries'][lib])
print(json.dumps({'protocol':'skillsbench-fuzzing-original-private-empty-group-v1','lib':lib,'target':target,'complete':complete,'nodeIds':w.nodes,'reports':w.reports,'collectionErrors':w.collectionErrors,'validationIssues':issues,'exitCode':code,'passedTests':passed,'failedTests':failed,'errorTests':errors,'rawPytestOutput':captured.getvalue(),'ctrf':json.loads(Path('/logs/ctrf.json').read_bytes()),'pythonPath':sys.executable,'pythonVersion':sys.version,'pythonSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),'installedPackages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},'elapsedSeconds':time.monotonic()-began,'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'modelCalls':0,'formalScoreCertified':False}))
