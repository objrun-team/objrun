"""Actual checker exit/mailbox lifecycle race; no checker or benchmark is executed."""
import argparse,http.server,json,os,sys,threading,pathlib,traceback,urllib.request,urllib.error,time
from concurrent.futures import ThreadPoolExecutor
import _bench_original_owned_guard as guard
from docker_owned import OwnedDocker
from mailbox_transport import capture_request,deliver_response
p=argparse.ArgumentParser();p.add_argument('--base-proof',required=True);p.add_argument('--output',required=True);a=p.parse_args();plan=json.loads(pathlib.Path(a.base_proof).read_bytes())['plan'];token=os.environ['OBJRUN_TB12_STAND_TOKEN']
def verify():
 import contextlib,copy,io,importlib.metadata
 from native_process import pin
 from pytest_case_witness import run_with_witness,validate_case_identity,_digest,stage_checker_witness
 out=pathlib.Path(plan['nativeOutput']);out.mkdir(parents=True);guard.guard();_bench_authorized_history('torch-pipeline-parallelism')
 os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
 if plan.get('reusedPytestEvidence'):
  evidence=plan['reusedPytestEvidence']
  for key,name in [('witnessPin','witness.json'),('ctrfPin','ctrf.json'),('stdoutPin','pytest.stdout'),('stderrPin','pytest.stderr')]:
   source=pathlib.Path(evidence[key]['path']);assert pin(source)==evidence[key];(out/name).write_bytes(source.read_bytes())
  value=json.loads((out/'witness.json').read_bytes());witness=value['pytestCaseWitness'];code=value['exitCode'];expected={'test_alpha','test_beta','test_pair[1]','test_pair[2]'}
  validate_case_identity(value,expected);rejected=['missing-case','duplicate-case','reward-tamper','ctrf-case-tamper']
 else:
  for wheel in reversed(plan['pytestWheelPins']):
   assert pin(pathlib.Path(wheel['path']))==wheel;sys.path.insert(0,wheel['path'])
  fixture=out/'test_neutral_cases.py';fixture.write_text("import pytest\ndef test_alpha(): assert False\ndef test_beta(): assert False\n@pytest.mark.parametrize('number',[1,2])\ndef test_pair(number): assert False\n")
  stdout=io.StringIO();stderr=io.StringIO()
  with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
   code,witness=run_with_witness(['-p','ctrf.main','--ctrf',str(out/'ctrf.json'),str(fixture),'-rA','-o','cache_dir='+str(out/'pytest-cache')])
  (out/'pytest.stdout').write_text(stdout.getvalue());(out/'pytest.stderr').write_text(stderr.getvalue())
  raw=(out/'ctrf.json').read_bytes();value={'ctrf':json.loads(raw),'packages':{'pytest':importlib.metadata.version('pytest'),'pytest-json-ctrf':importlib.metadata.version('pytest-json-ctrf')},'exitCode':code,'reward':int(code==0),'pytestCaseWitness':witness}
  expected={'test_alpha','test_beta','test_pair[1]','test_pair[2]'};assert code==1 and len(value['ctrf']['results']['tests'])==3
  validate_case_identity(value,expected);rejected=[]
  for kind in ['missing-case','duplicate-case','reward-tamper','ctrf-case-tamper']:
   wrong=copy.deepcopy(value)
   if kind=='missing-case':wrong['pytestCaseWitness']['collected'].pop()
   if kind=='duplicate-case':wrong['pytestCaseWitness']['reports'].append(wrong['pytestCaseWitness']['reports'][-1])
   if kind=='reward-tamper':wrong['reward']=1
   if kind=='ctrf-case-tamper':wrong['ctrf']['results']['tests'][0]['name']='unexpected'
   wrong['pytestCaseWitness']['sha256']=_digest({k:v for k,v in wrong['pytestCaseWitness'].items() if k!='sha256'})
   try:validate_case_identity(wrong,expected)
   except (AssertionError,KeyError):rejected.append(kind)
  assert len(rejected)==4;payload=out/'witness.json';payload.write_text(json.dumps(value,indent=2)+'\n')
 payload=out/'witness.json'
 native=OwnedDocker(out/'owned');cid=None;result={'complete':False,'modelCalls':0,'gradeCalls':0,'referenceCalls':0}
 try:
  cid,initial,created=native.create('neutral-pytest-case-witness',plan['baseImageId'],'/bin/sh',['-c','sleep 180'],network='none',memory_mb=8192,cpus=1,readonly=False,readonly_scratch_bytes=2*1024**3);native.start(cid)
  native.execute(cid,['mkdir','-p','/opt/pipeline-checker/router'])
  derived_dir=out/'derived';derived_dir.mkdir();derived=stage_checker_witness(native,cid,pathlib.Path(plan['neutralOriginalRunnerPin']['path']),derived_dir)
  source_proof=json.loads((derived_dir/'case-witness-source.json').read_bytes());assert source_proof['exactReplacements']==2
  compile(derived.read_bytes(),str(derived),'exec')
  native.upload(derived,cid,'/opt/pipeline-checker/checker_runner.py');guest_sources={}
  for source,destination in [(derived,'/opt/pipeline-checker/checker_runner.py'),(derived_dir/'pytest_case_witness.py','/opt/pipeline-checker/router/pytest_case_witness.py')]:
   receipt=native.execute(cid,['sha256sum',destination]);assert native.text(receipt).split()[0]==pin(source)['sha256'];guest_sources[destination]={'sourcePin':pin(source),'receipt':receipt}
  native.upload(payload,cid,'/tmp/witness.json');proof=native.execute(cid,['sha256sum','/tmp/witness.json']);assert native.text(proof).split()[0]==pin(payload)['sha256']
  result.update(complete=True,cid=cid,derivedSourceProof=source_proof,guestDerivedSources=guest_sources,actualPytestExitCode=code,actualPytestVersion=value['packages']['pytest'],actualCtrfPlugin=value['packages']['pytest-json-ctrf'],actualCollected=witness['collected'],actualReports=witness['reports'],actualCtrfRows=3,rawCtrfPin=pin(out/'ctrf.json'),stdoutPin=pin(out/'pytest.stdout'),stderrPin=pin(out/'pytest.stderr'),witnessPin=pin(payload),negativeCasesRejected=rejected,actualContainerHash=proof,reusedPytestEvidence=plan.get('reusedPytestEvidence'),scope='Actual derived runner/helper staging and guest full SHA; host hook/validation reuses exact prior real pytest evidence; no container PID1 pytest claim')
 finally:
  if cid:
   native.remove(cid)
   try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/containers/'+cid+'/json',timeout=5);raise AssertionError('actor_still_present')
   except urllib.error.HTTPError as error:assert error.code==404
   result.update(actorClosed=True,currentActorStatus=404)
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 return result
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  assert self.headers.get('X-ObjRun-Grader-Token')==token;self.rfile.read(int(self.headers.get('Content-Length','0')))
  try:
   value=verify() if self.path=='/up' else {'ownedContainersRemaining':0,'allExactOwnedActorsAbsent':True};assert self.path in ('/up','/close');self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode());self.wfile.flush()
   if self.path=='/close':threading.Thread(target=self.server.shutdown,daemon=True).start()
  except BaseException as error:traceback.print_exc(file=sys.stderr);self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':str(error)}).encode())
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'protocol':'tb12-stand-ready-v1','pid':os.getpid(),'port':server.server_port,'modelCalls':0}),flush=True);server.serve_forever();server.server_close()
