"""Private original weighted driver; candidate code only runs through input RPC."""
import contextlib,hashlib,importlib.util,importlib.machinery,io,json,re,runpy,sys,types
from pathlib import Path
from bridge import unpack

def evaluate(trusted,session,callback,collect):
 source='/verifier/test_outputs.py'
 module=runpy.run_path(source)
 names=[name for name in module if name.startswith('test_')]
 if collect:return {'taskId':'debug-trl-grpo','mode':'collect','nodeIds':names,'complete':True,'reward':None,'pytestExitCode':0,'callbackCount':0,'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'originalWeightedScript':True}
 serial=0;fault=None
 def invoke(payload):
  nonlocal serial,fault
  request={'session':session,'serial':serial,'taskId':'debug-trl-grpo','commandIndex':0,'payload':payload}
  try:
   response=callback(request)
   digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   assert response['session']==session and response['serial']==serial and response['requestSha256']==digest
   assert response['exception'] is None and type(response['returncode']) is int
   serial+=1
   if response['returncode']!=0:raise CandidateError('candidate callable process failed: '+str(response['returncode']))
   result=json.loads(unpack(response['stdout']))
   assert set(result)=={'result','error'}
   if result['error'] is not None:raise CandidateError(str(result['error']))
   return result['result']
  except CandidateError:raise
  except Exception as error:fault=repr(error);raise
 class CandidateError(Exception):pass
 def selective(logits,index):
  import torch
  result=invoke({'op':'selective_log_softmax','logits':logits.tolist(),'index':index.tolist()})
  assert result['kind']=='tensor' and result['dtype']=='torch.float32'
  return torch.tensor(result['value'],dtype=torch.float32)
 def decode(input_ids,tokenizer):
  result=invoke({'op':'decode_and_strip_padding','input_ids':input_ids.tolist(),'tokenizer':tokenizer.name_or_path})
  assert result['kind']=='strings' and type(result['value']) is list and all(type(v) is str for v in result['value'])
  return result['value']
 trl=types.ModuleType('trl');trl.__file__='/app/trl/trl/__init__.py';trl.__path__=[]
 trainer=types.ModuleType('trl.trainer');trainer.__path__=[]
 utils=types.ModuleType('trl.trainer.utils');utils.__file__='/app/trl/trl/trainer/utils.py'
 utils.selective_log_softmax=selective;utils.decode_and_strip_padding=decode
 trl.trainer=trainer;trainer.utils=utils
 spec=importlib.util.spec_from_file_location('reward_fn','/opt/objrun-nonsecurity/reward_original.py');reward=importlib.util.module_from_spec(spec);spec.loader.exec_module(reward)
 replacements={'trl':trl,'trl.trainer':trainer,'trl.trainer.utils':utils,'reward_fn':reward}
 for name,value in replacements.items():
  if value.__spec__ is None:value.__spec__=importlib.machinery.ModuleSpec(name,loader=None,is_package=hasattr(value,'__path__'))
 old={k:sys.modules.get(k) for k in replacements};sys.modules.update(replacements)
 scores=[];original=module['compute_reward'];scope=module['main'].__globals__
 def score(*args):value=original(*args);scores.append(value);return value
 scope['compute_reward']=score;output=io.StringIO();code=0
 try:
  with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
   try:module['main']()
   except SystemExit as error:code=error.code
 finally:
  for key,value in old.items():
   if value is None:sys.modules.pop(key,None)
   else:sys.modules[key]=value
 assert fault is None,'trusted_grpo_callback_fault:'+str(fault)
 assert len(scores)==1 and 0<=scores[0]<=1 and code in (0,1)
 assert re.findall(r'^REWARD=([0-9.]+)$',output.getvalue(),re.M)==[f'{scores[0]:.4f}']
 return {'taskId':'debug-trl-grpo','mode':'grade','nodeIds':names,'complete':True,'reward':scores[0],'pytestExitCode':code,'callbackCount':serial,'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'originalWeightedScript':True,'rawPytestOutput':output.getvalue()}
