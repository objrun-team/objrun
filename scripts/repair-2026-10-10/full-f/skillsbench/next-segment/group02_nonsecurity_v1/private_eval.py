"""Unmodified original private tests, real separate execution and original score."""
import contextlib,hashlib,importlib.metadata,io,json,os,runpy,shutil,sys,time
from pathlib import Path
sys.path.insert(0,'/opt/objrun-nonsecurity')
from artifacts import install
from bridge import Bridge
from policy import COMMANDS

def main():
 assert sys.flags.isolated and sys.dont_write_bytecode and os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']=='1'
 trusted=json.loads(Path('/opt/objrun-nonsecurity/trusted.json').read_bytes());task=trusted['taskId']
 assert os.getcwd()==trusted['workingDirectory']
 for copy in trusted['fixtureCopies']:shutil.copytree(copy['source'],copy['destination'],dirs_exist_ok=True,symlinks=True)
 maximum=trusted['maximumInputBytes'];raw=sys.stdin.buffer.readline(maximum+1)
 assert len(raw)<=maximum and raw.endswith(b'\n')
 incoming=json.loads(raw);assert set(incoming)=={'artifacts','session'}
 assert type(incoming['session']) is str and incoming['session'].isalnum()
 install(task,incoming['artifacts'],trusted['originalResources'])
 def checked():
  for p in trusted['files']:assert hashlib.sha256(Path(p['path']).read_bytes()).hexdigest()==p['sha256']
 checked()
 for key in ('PYTHONPATH','PYTHONHOME','PYTEST_ADDOPTS','PYTEST_PLUGINS','OUTPUT_DIR','OUTPUT_PATH','EXPECTED_PATH','REWARD_PATH','WRITES_PATH','ABORTS_PATH'):os.environ.pop(key,None)
 import pytest
 class Witness:
  def __init__(self):self.nodes=[];self.reports=[];self.errors=[]
  def pytest_collection_finish(self,session):self.nodes=[x.nodeid for x in session.items]
  def pytest_collectreport(self,report):
   if report.failed or report.skipped:self.errors.append({'nodeId':report.nodeid,'outcome':report.outcome})
  def pytest_runtest_logreport(self,report):self.reports.append({'nodeId':report.nodeid,'phase':report.when,'outcome':report.outcome,'wasXfail':getattr(report,'wasxfail',None)})
 witness=Witness();captured=io.StringIO();collect='--collect' in sys.argv;began=time.monotonic()
 def callback(request):
  sys.__stdout__.write(json.dumps({'kind':'nonsecurity_callback','request':request})+'\n');sys.__stdout__.flush()
  reply=sys.stdin.buffer.readline(180*1024**2+1);assert len(reply)<=180*1024**2 and reply.endswith(b'\n');return json.loads(reply)
 bridge=Bridge(task,callback,incoming['session'])
 if task=='debug-trl-grpo':
  from grpo_private import evaluate
  result=evaluate(trusted,incoming['session'],callback,collect)
  checked();print(json.dumps(result));return
 entries=[e for e in importlib.metadata.distribution('pytest-json-ctrf').entry_points if e.group=='pytest11'];assert len(entries)==1
 args=['-c','/opt/objrun-nonsecurity/empty.ini','--confcutdir=/verifier','--ctrf','/logs/verifier/ctrf.json','/verifier/test_outputs.py','-rA','-v']
 if collect:args+=['--collect-only','-q']
 with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured),bridge:
  code=int(pytest.main(args,plugins=[entries[0].load(),witness]))
  reward=None if collect else int(code==0)
  if not collect and code==0 and task=='tictoc-unnecessary-abort-detection':
   runpy.run_path('/verifier/score_outputs.py',run_name='__main__')
   reward=float(Path('/logs/verifier/reward.txt').read_text());assert 0<=reward<=1
 assert bridge.failed is None,'trusted_callback_infrastructure_fault:'+str(bridge.failed)
 checked();phases={n:{} for n in witness.nodes};issues=[]
 for r in witness.reports:
  if r['nodeId'] not in phases or r['phase'] in phases[r['nodeId']]:issues.append('duplicate_or_foreign_report');continue
  phases[r['nodeId']][r['phase']]=r
  if r['wasXfail'] is not None:issues.append('xfail_or_xpass')
 if witness.errors:issues.append('collection_errors')
 if not collect:
  for values in phases.values():
   ordinary=set(values)=={'setup','call','teardown'} and values['setup']['outcome']=='passed' and values['call']['outcome'] in ('passed','failed') and values['teardown']['outcome']=='passed'
   failed_setup=set(values)=={'setup','teardown'} and values['setup']['outcome']=='failed' and values['teardown']['outcome']=='passed'
   if not(ordinary or failed_setup):issues.append('incomplete_or_skipped_test')
 complete=bool(witness.nodes) and len(set(witness.nodes))==len(witness.nodes) and not issues and code in (0,1)
 result={'protocol':'skillsbench-nonsecurity-private-v1','taskId':task,'mode':'collect' if collect else 'grade','nodeIds':witness.nodes,'reports':witness.reports,'collectionErrors':witness.errors,'pytestExitCode':code,'complete':complete,'validationIssues':issues,'reward':reward if complete else None,'passedTests':sum(r['phase']=='call' and r['outcome']=='passed' for r in witness.reports),'failedTests':sum(r['phase']=='call' and r['outcome']=='failed' for r in witness.reports),'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'separateExecutionSandbox':task in COMMANDS,'callbackCount':bridge.serial,'elapsedSeconds':time.monotonic()-began,'rawPytestOutput':captured.getvalue(),'originalScoringScriptUsed':task=='tictoc-unnecessary-abort-detection' and code==0 and not collect,'network':'none','hostBinds':False}
 print(json.dumps(result))

if __name__=='__main__':main()

