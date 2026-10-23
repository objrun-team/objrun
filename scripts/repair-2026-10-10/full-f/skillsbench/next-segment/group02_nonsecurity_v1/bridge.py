"""Exact original subprocess API calls, private assertions stay in pytest."""
import base64,hashlib,json,subprocess,sys,os,math
from pathlib import Path
from policy import COMMANDS

def pack(body):
 return {'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()}

def unpack(value,limit=64*1024**2):
 assert type(value) is dict and set(value)=={'base64','sha256'}
 assert type(value['base64']) is str and len(value['base64']) <= (limit+2)//3*4
 body=base64.b64decode(value['base64'],validate=True)
 assert len(body)<=limit and hashlib.sha256(body).hexdigest()==value['sha256']
 return body

class Bridge:
 def __init__(self,task,callback,session):
  self.task=task;self.callback=callback;self.session=session;self.serial=0;self.original=None;self.failed=None
 def run(self,args,*pos,**kwargs):
  try:return self._run(args,*pos,**kwargs)
  except subprocess.TimeoutExpired:raise
  except Exception as error:
   self.failed=type(error).__name__+':'+str(error);raise
 def _run(self,args,*pos,**kwargs):
  assert not pos
  lookup=args
  if self.task=='simpo-code-reproduction':
   assert args==[sys.executable,'/root/SimPO/unit_test/unit_test_1.py']
   lookup=['python-verifier-3.10','/root/SimPO/unit_test/unit_test_1.py']
  match=[c for c in COMMANDS.get(self.task,[]) if lookup==c[0]]
  assert len(match)==1,'unreviewed_original_command'
  command,cwd,timeout,text=match[0]
  if self.task=='fix-build-agentops':
   assert set(kwargs)=={'stdout','stderr','shell','cwd','env'}
   assert kwargs['stdout']==subprocess.PIPE and kwargs['stderr']==subprocess.DEVNULL and kwargs['shell'] is True
   assert kwargs['env'].get('PIP_INDEX_URL')=='https://pypi.org/simple' and 'PIP_EXTRA_INDEX_URL' not in kwargs['env']
  else:
   expected={'capture_output':True,'text':True}
   if isinstance(command,str):expected['shell']=True
   if cwd is not None:expected['cwd']=cwd
   if timeout is not None:expected['timeout']=timeout
   if self.task=='simpo-code-reproduction':
    assert type(kwargs.get('env')) is dict and kwargs['env']['PYTHONPATH']=='/root/SimPO'
    assert {k:v for k,v in kwargs.items() if k!='env'}==expected,'original_call_options_changed'
   else:assert kwargs==expected,'original_call_options_changed'
  assert kwargs.get('cwd')==cwd and kwargs.get('timeout')==timeout
  request={'session':self.session,'serial':self.serial,'taskId':self.task,'commandIndex':COMMANDS[self.task].index(match[0])}
  response=self.callback(request)
  digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  assert set(response)=={'session','serial','requestSha256','returncode','stdout','stderr','outputs','exception'}
  assert response['session']==self.session and type(response['serial']) is int and response['serial']==self.serial and response['requestSha256']==digest
  self.serial+=1
  stdout=unpack(response['stdout']);stderr=unpack(response['stderr'])
  if response['exception']=='TimeoutExpired':raise subprocess.TimeoutExpired(args,timeout,stdout,stderr)
  assert response['exception'] is None and type(response['returncode']) is int
  assert set(response['outputs']) <= ({'/root/loss.npz'} if self.task=='simpo-code-reproduction' else set())
  for path,value in response['outputs'].items():
   assert set(value)=={'base64','sha256','mtime'} and type(value['mtime']) in (int,float) and math.isfinite(value['mtime'])
   target=Path(path);assert not target.is_symlink();target.write_bytes(unpack({k:value[k] for k in ('base64','sha256')}));os.utime(target,(value['mtime'],value['mtime']))
  def decode(body):return body.decode().replace('\r\n','\n').replace('\r','\n')
  return subprocess.CompletedProcess(args,response['returncode'],decode(stdout) if text else stdout,None if self.task=='fix-build-agentops' else decode(stderr) if text else stderr)
 def __enter__(self):
  self.original=subprocess.run;subprocess.run=self.run;return self
 def __exit__(self,*error):
  subprocess.run=self.original;self.original=None

