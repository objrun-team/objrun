"""Seven task-specific boundaries; no readiness or score assertions."""
from pathlib import PurePosixPath

TASKS = {
 'fix-build-agentops': {'roots':['/home/github/build/failed'],'tree':True},
 'simpo-code-reproduction': {'roots':['/root/loss.npz','/root/python_info.txt'],'tree':False},
 'debug-trl-grpo': {'roots':['/app/trl/trl/trainer/utils.py','/app/trl/trl/trainer/grpo_trainer.py','/app/train_grpo.py','/app/reward_fn.py'],'tree':False},
}
COMMANDS = {
 'fix-build-agentops': [('bash run_passed.sh', '/tests', None, False)],
 'simpo-code-reproduction': [(['python-verifier-3.10','/root/SimPO/unit_test/unit_test_1.py'],'/root/SimPO',None,True)],
 'debug-trl-grpo': [(['python','/opt/objrun-grpo-call.py'],'/app',None,False)],
}

def allowed(task,path):
 p=PurePosixPath(path)
 if not p.is_absolute() or str(p)!=path or '..' in p.parts:return False
 cfg=TASKS[task]
 return any(path==root or cfg['tree'] and path.startswith(root+'/') for root in cfg['roots'])

def limits(task,resources):
 # Original storage remains the upper bound, including complete source trees.
 storage=int(resources['environment']['storage_mb'])*1024**2
 maximum=storage if TASKS[task]['tree'] else min(storage,128*1024**2 if task=='quantum-numerical-simulation' else 8*1024**2)
 return {'maximumBytes':maximum,'maximumFiles':100000 if TASKS[task]['tree'] else len(TASKS[task]['roots'])}

