import argparse,importlib,json,os,sys,shutil
from pathlib import Path
from tensor_protocol import read,write,tensor_pack,tensor_unpack
def pipeline_rank(rank, world_size, request, output):
    import torch
    import torch.distributed as dist
    import torch.nn as nn
    from transformers import LlamaConfig, LlamaForCausalLM, LlamaModel
    os.environ['MASTER_ADDR'] = 'localhost'
    os.environ['MASTER_PORT'] = '12355'
    dist.init_process_group('gloo', rank=rank, world_size=world_size)
    try:
        model = LlamaForCausalLM(LlamaConfig(**request['config']))
        model.load_state_dict({key: tensor_unpack(value) for key, value in request['state'].items()})
        traces = {}
        def hooks(module, prefix=''):
            for name, child in module.named_children():
                full = prefix + '.' + name if prefix else name
                if isinstance(child, (nn.ModuleList, LlamaModel)):
                    hooks(child, full)
                    continue
                def forward(module, inputs, result, key=full):
                    if isinstance(result, (tuple, list)):
                        result = result[0]
                    traces.setdefault(key + '.fwd', []).append(tensor_pack(result))
                def backward(module, inputs, result, key=full):
                    if isinstance(result, (tuple, list)):
                        result = result[0]
                    traces.setdefault(key + '.bwd', []).append(tensor_pack(result))
                child.register_forward_hook(forward)
                child.register_full_backward_hook(backward)
        hooks(model)
        torch.set_rng_state(tensor_unpack(request['rng_state']))
        sys.path.insert(0, '/app')
        function = importlib.import_module('pipeline_parallel').train_step_pipeline_afab
        function(model, [tensor_unpack(v) for v in request['inputs']],
                 [tensor_unpack(v) for v in request['targets']], torch.device('cpu'), torch.float32)
        write(Path(output) / f'rank-{rank}.json', {'traces': traces})
        dist.barrier()
    finally:
        dist.destroy_process_group()
def main():
 p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--response',required=True);a=p.parse_args();request=read(a.request);args=request['arguments'];assert request['operation']=='pipeline' and args['world_size'] in (1,2)
 import torch.multiprocessing as mp
 output=Path('/tmp/pipeline-ranks');shutil.rmtree(output,ignore_errors=True);output.mkdir();mp.spawn(pipeline_rank,args=(args['world_size'],args,str(output)),nprocs=args['world_size'],join=True);write(a.response,{'id':request['id'],'value':[read(output/('rank-'+str(i)+'.json')) for i in range(args['world_size'])]})
if __name__=='__main__':main()
