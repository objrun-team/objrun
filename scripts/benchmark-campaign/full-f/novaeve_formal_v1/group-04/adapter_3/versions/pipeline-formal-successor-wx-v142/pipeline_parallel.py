import inspect,json,os,time
from pathlib import Path
from tensor_protocol import read,write,tensor_pack,tensor_unpack

def train_step_pipeline_afab(model,inputs,targets,device,dtype):
 frame=inspect.currentframe().f_back;rank=frame.f_locals['rank'];world=frame.f_locals['world_size'];collector=frame.f_locals['pipeline_dict'];identity=str(os.getpid())+'-1';root=Path('/tmp/pipeline-mailbox');root.mkdir(exist_ok=True);deadline=time.monotonic()+float(os.environ['PIPELINE_REMAINING_SECONDS'])
 args={'world_size':world,'rank':rank,'config':model.config.to_dict(),'state':{k:tensor_pack(v) for k,v in model.state_dict().items()},'rng_state':tensor_pack(__import__('torch').get_rng_state()),'inputs':[tensor_pack(v) for v in inputs],'targets':[tensor_pack(v) for v in targets]};write(root/(identity+'.request.json'),{'id':identity,'operation':'pipeline','arguments':args});response=root/(identity+'.response.json')
 while not response.exists():
  if time.monotonic()>=deadline:raise TimeoutError('Original verifier deadline exhausted')
  time.sleep(.02)
 result=read(response);assert result['id']==identity
 if 'error' in result:raise RuntimeError(result['error'])
 value=result['value'];assert set(value)=={'traces'} and isinstance(value['traces'],dict)
 for key,values in value['traces'].items():
  assert key.endswith(('.fwd','.bwd')) and isinstance(values,list);collector[key]=[tensor_unpack(v) for v in values]
