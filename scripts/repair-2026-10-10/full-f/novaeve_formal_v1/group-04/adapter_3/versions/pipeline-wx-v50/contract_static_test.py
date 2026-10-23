"""Local synthetic contract fixture only: zero Docker/model/oracle evidence."""
import json,hashlib,copy,ast,base64
from pathlib import Path
from grade_contract import validate_result,EXPECTED
raw=json.dumps({'results':{'tests':[{'name':'test_outputs.py::'+n,'status':'passed'} for n in sorted(EXPECTED)]}}).encode()
r={'protocol':'tb12-private-checker-result-v1','taskId':'torch-pipeline-parallelism','invocationId':'local-fixture','checkerSourceSha256':'a'*64,'numericGuestPid':1,'numericParentPid':0,'exitCode':0,'reward':1,'collectOnly':False,'ctrf':json.loads(raw),'ctrfRawSha256':hashlib.sha256(raw).hexdigest(),'ctrfRawBase64':base64.b64encode(raw).decode('ascii'),'privateNamespaces':{n:n+':[synthetic]' for n in ['pid','mnt','net']},'pythonExecutable':'/fixture/python','pythonExecutableSha256':'b'*64,'mountInfoSha256':'c'*64,'procStatus':'synthetic','packages':{'pytest':'fixture'},'wallStart':0,'wallStop':1,'monotonicSeconds':1}
validate_result(r,r['taskId'],'local-fixture','a'*64,raw);rejected=[]
for key,value in [('numericGuestPid',2),('invocationId','wrong'),('checkerSourceSha256','bad'),('reward',0),('ctrfRawSha256','bad')]:
 q=copy.deepcopy(r);q[key]=value
 try:validate_result(q,r['taskId'],'local-fixture','a'*64,raw)
 except AssertionError:rejected.append(key)
 else:raise AssertionError('Invalid fixture accepted: '+key)
runner=Path(__file__).with_name('checker_runner.py').read_text();ast.parse(runner);assert "'numericGuestPid':os.getpid()" in runner and "'numericParentPid':os.getppid()" in runner and "Path('/tmp/ctrf.json').read_bytes()" in runner
grade=Path(__file__).with_name('pipeline_grade.py').read_text();assert "readonly=True,readonly_scratch_bytes=2*1024**3" in grade and "'/opt/pipeline-checker/checker_runner.py'" in grade and "'/tmp/checker_runner.py'" not in grade
print(json.dumps({'syntheticOnly':True,'contractPassed':True,'negativeCasesRejected':rejected,'nativeActions':0,'benchmarkGradingInvocations':0,'modelCalls':0,'newPaidRequests':0}))

from callback_error_contract import candidate_failure
closed={'closeObserved':True,'exitCode':1,'timedOut':False,'overflow':False,'captureFaults':[]}
assert candidate_failure(closed)
for key,value in [('closeObserved',False),('timedOut',True),('overflow',True),('captureFaults',['fixture-capture-fault']),('exitCode',None)]:
 q=dict(closed);q[key]=value;assert not candidate_failure(q)
print(json.dumps({'syntheticOnly':True,'candidateErrorContractPassed':True,'infraFaultCasesRejected':5,'modelCalls':0,'newPaidRequests':0,'nativeActions':0}))
