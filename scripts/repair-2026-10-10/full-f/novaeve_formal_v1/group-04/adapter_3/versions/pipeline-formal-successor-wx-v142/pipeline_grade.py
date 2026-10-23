"""Production Pipeline callback grading. Executed only for future candidate grading."""
import json,time,os,uuid,hashlib,re,base64
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from bootstrap import ROOT
from tensor_protocol import read,write
from portable_framework import install,pin
from grade_contract import validate_result
from artifacts import capture_file
from docker_owned import NativeFault
from callback_error_contract import candidate_failure
from mailbox_transport import capture_request,deliver_response

def grade_snapshot(native,candidate,task,context,context_directory,private_base,output):
 assert task['taskId']=='torch-pipeline-parallelism';output=Path(output);output.mkdir(parents=True,exist_ok=False);deadline=time.monotonic()+task['verifierSeconds'];state={'protocol':'tb12-snapshot-grade-v1','candidateCid':candidate,'invocationId':uuid.uuid4().hex,'taskId':task['taskId'],'callbackMode':'docker-cp-exec-mailbox','hostCallbackRequired':False,'originalPredicatesChanged':False,'modelCalls':0};worker=checker=None
 def remain():
  n=deadline-time.monotonic()
  if n<=0:raise TimeoutError('Original verifier deadline exhausted')
  return n
 try:
  actual=native.assert_actor(candidate)
  if not actual['State']['Paused']:native.pause(candidate)
  image,commit=native.commit(candidate,'pipeline-full-candidate-snapshot');state['snapshotCommit']=commit
  env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
  worker,_,_=native.create('pipeline-candidate-callback',image,'/bin/sh',['-c','sleep 1800'],network='bridge' if task['officialEnvironment']['allow_internet'] else 'none',memory_mb=8192,cpus=1,env_names=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'),environment=env,cwd='/app');native.start(worker);state['worker']={'cid':worker,'fullCandidateSnapshotImage':image,'candidateCid':candidate}
  from runtime_transport import stage_runtime,ship_runtime
  runtime=stage_runtime(output/'worker-runtime');state['workerRuntime']=ship_runtime(native,worker,runtime);prefix,state['portableFramework']=install(native,worker,output/'portable-framework')
  worker_script=output/'pipeline_worker.py';source=Path(__file__).with_name('pipeline_worker.py').read_text().replace('import torch.multiprocessing as mp','import torch.multiprocessing as mp\n mp.set_executable('+repr(prefix+'/run-python')+')');worker_script.write_text(source);native.upload(worker_script,worker,'/tmp/pipeline_worker.py');native.upload(Path(__file__).with_name('tensor_protocol.py'),worker,'/tmp/tensor_protocol.py')
  stager,_,_=native.create('pipeline-original-private-stage',private_base,'/bin/sh',['-c','sleep 1800'],network='none',memory_mb=8192,cpus=1,env_names=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'),environment=env,cwd='/app');native.start(stager);checker=stager
  native.execute(checker,['mkdir','-p','/opt/pipeline-checker/router','/tmp/pipeline-mailbox','/tests']);native.upload(Path(__file__).with_name('pipeline_parallel.py'),checker,'/opt/pipeline-checker/router/pipeline_parallel.py');native.upload(Path(__file__).with_name('tensor_protocol.py'),checker,'/opt/pipeline-checker/router/tensor_protocol.py')
  tests=ROOT/'.phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks/torch-pipeline-parallelism/tests/test_outputs.py';local=output/'original-test_outputs.py';local.write_bytes(tests.read_bytes());assert hashlib.sha256(local.read_bytes()).hexdigest()==task['officialTestHashes']['test_outputs.py'];native.upload(local,checker,'/tests/test_outputs.py');capture=capture_file(native,candidate,'/app/pipeline_parallel.py',task['profile']['artifacts']['/app/pipeline_parallel.py'],output/'candidate-capture');state['candidateArtifactCapture']=capture
  if capture['exists']:
   artifact=Path(capture['stored']);native.upload(artifact,checker,'/app/pipeline_parallel.py');state['candidateArtifactPin']=pin(artifact)
  runner=Path(__file__).with_name('checker_runner.py');configpath=output/'checker-config.json';write(configpath,{'taskId':task['taskId'],'invocationId':state['invocationId'],'checkerSourceSha256':pin(runner)['sha256'],'originalTestSha256':task['officialTestHashes']['test_outputs.py'],'packageNames':['pytest','torch','transformers','numpy','pytest-json-ctrf']});native.upload(runner,checker,'/opt/pipeline-checker/checker_runner.py');native.upload(configpath,checker,'/opt/pipeline-checker/checker-config.json');state['checkerSourcePin']=pin(runner);state['checkerCid']=checker
  native.stop(stager);staged,staging_commit=native.commit(stager,'pipeline-original-private-stage');native.remove(stager);checker,initial,created=native.create('pipeline-original-private-checker',staged,'/opt/checker/bin/python',['/opt/pipeline-checker/checker_runner.py','--config','/opt/pipeline-checker/checker-config.json'],network='none',memory_mb=8192,cpus=1,env_names=('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','PYTHONPATH','PIPELINE_REMAINING_SECONDS'),environment={**env,'PYTHONPATH':'/opt/pipeline-checker/router:/tests:/opt/checker/lib/python3.13/site-packages','PIPELINE_REMAINING_SECONDS':str(remain())},cwd='/app',readonly=True,readonly_scratch_bytes=2*1024**3);assert initial['HostConfig']['ReadonlyRootfs'] is True and initial['HostConfig']['NetworkMode']=='none' and initial['HostConfig']['Memory']==8192*1024**2 and initial['HostConfig']['NanoCpus']==1000000000 and initial['HostConfig']['PidsLimit']==256 and 'ALL' in initial['HostConfig']['CapDrop'];assert initial['HostConfig']['Tmpfs']['/tmp']=='rw,nosuid,nodev,size=2147483648,mode=1777';state['actualPrivateHostConfig']=initial['HostConfig'];state['scratchMemoryBudget']={'tmpfsBytes':2147483648,'accountedInOriginalActorMemoryBytes':8192*1024**2,'writableLayerHardLimitBytes':None};state['checkerCid']=checker;state['initialState']=initial;state['create']=created;state['staging']={'imageId':staged,'commitReceipt':staging_commit,'configPin':pin(configpath),'runnerPin':pin(runner)};cache={};candidate_errors={};handled=set();state['callbackRequests']=[];state['mailboxCaptureReceipts']=[];state['mailboxResponseReceipts']=[]
  with ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(native.start,checker,True,int(remain()))
   while not future.done():
    remain()
    if not native.assert_actor(checker)['State']['Running']:
     time.sleep(.05);continue
    native.guard();listing=native.command(['exec',checker,'find','/tmp/pipeline-mailbox','-maxdepth','1','-type','f','-name','*.request.json','-printf','%f\n'],timeout=min(60,int(remain())))
    if listing['exitCode']!=0:
     if future.done() or native.assert_actor(checker)['State']['Status']=='exited':continue
     raise RuntimeError('Private mailbox listing failed before guest exit')
    names=native.text(listing).splitlines()
    for name in names:
     assert re.fullmatch(r'[0-9]+-1\.request\.json',name)
     if name in handled:continue
     native.guard();native.assert_actor(checker)
     request,capture_receipt=capture_request(native,checker,name,output,remain);state['mailboxCaptureReceipts'].append({'name':name,'missing':request is None,'receipt':capture_receipt})
     if request is None:continue
     handled.add(name);requestpath=output/name;assert request['operation']=='pipeline';args=request['arguments'];rank=args['rank'];assert args['world_size'] in [1,2] and rank in range(args['world_size']);fingerprint=hashlib.sha256(json.dumps({k:v for k,v in args.items() if k!='rank'},sort_keys=True).encode()).hexdigest()
     if fingerprint not in cache and fingerprint not in candidate_errors:
      native.guard();native.assert_actor(worker);native.checked(['cp',str(requestpath),worker+':/tmp/request.json'],timeout=min(180,int(remain())))
      try:
       receipt=native.execute(worker,[prefix+'/run-python','/tmp/pipeline_worker.py','--request','/tmp/request.json','--response','/tmp/response.json'],timeout=int(remain()))
      except NativeFault as fault:
       receipt=fault.receipt
       if not candidate_failure(receipt):raise
       candidate_errors[fingerprint]='Candidate Pipeline program exited with code '+str(receipt['exitCode']);state['callbackRequests'].append({'fingerprint':fingerprint,'worldSize':args['world_size'],'candidateExecutionFailed':True,'actualWorkerExecution':receipt,'returnedErrorToOriginalPrivatePytest':True})
      else:
       responsecapture=capture_file(native,worker,'/tmp/response.json',1024**3,output/('response-'+str(len(cache))));assert responsecapture['exists'];responsepath=Path(responsecapture['stored']);response=read(responsepath);assert response['id']==request['id'] and len(response['value'])==args['world_size'];cache[fingerprint]=response['value'];state['callbackRequests'].append({'fingerprint':fingerprint,'worldSize':args['world_size'],'actualWorkerExecution':receipt})
     answer=output/name.replace('.request.json','.response.json');reply={'id':request['id'],'error':candidate_errors[fingerprint]} if fingerprint in candidate_errors else {'id':request['id'],'value':cache[fingerprint][rank]};write(answer,reply);native.guard();native.assert_actor(checker);response_receipt=deliver_response(native,checker,answer.name,reply,remain);state['mailboxResponseReceipts'].append({'name':answer.name,'receipt':response_receipt})
    time.sleep(.05)
   receipt=future.result();remain();state['originalTestReceipt']=receipt;state['start']=receipt;state['finalState']=native.assert_actor(checker);assert state['finalState']['State']['Status']=='exited' and state['finalState']['State']['ExitCode']==0;assert receipt['closeObserved'] and not receipt.get('timedOut') and receipt['exitCode']==0;line=native.text(receipt).splitlines()[-1];assert line.startswith('TB12_RESULT:');result=json.loads(line[len('TB12_RESULT:'):]);ctrfpath=output/'ctrf.json';resultpath=output/'checker-result.json';raw_ctrf=base64.b64decode(result['ctrfRawBase64'],validate=True);assert len(raw_ctrf)<=2*1024**2;ctrfpath.write_bytes(raw_ctrf);resultpath.write_text(json.dumps(result));state['rawCaptureSource']='Trusted PID1 final frame ctrfRawBase64 contains exact guest-read bytes; tmpfs need not survive guest exit';state['result']=validate_result(result,task['taskId'],state['invocationId'],pin(runner)['sha256'],ctrfpath.read_bytes());state['ctrfPin']=pin(ctrfpath);state['checkerResultPin']=pin(resultpath);state['result']['stdout']=native.text(receipt)
  state['complete']=True
 finally:
  for cid in [checker,worker]:
   if cid and any(r[0]==cid for r in native.open_actors()):
    removal,absence=native.remove(cid)
    if cid==checker:state['removal']=removal;state['absence']=absence
    else:state.setdefault('worker',{})['removal']=removal;state['worker']['absence']=absence
  state['remainingGradeActors']=[];state['capsulePath']=str(output/'capsule.json');write(output/'capsule.json',{'protocol':'tb12-sealed-data-capsule-v1','taskId':task['taskId'],'sourceCid':candidate,'candidateCodeExecutedInPrivateChecker':False,'files':[state['candidateArtifactCapture']] if 'candidateArtifactCapture' in state else []});write(output/'grade.json',state)
 return state
