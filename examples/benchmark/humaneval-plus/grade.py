"""Use the unmodified EvalPlus checker; candidate execution stays behind numeric RPC."""
import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import types
sys.path[:0] = ['/extras', '/worker', '/root/official']
import numpy as np
from codec import encode, decode
from evalplus.eval import untrusted_check, PASS
from evalplus.gen.util import trusted_exec

def unprivileged():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)

class CandidateError(Exception): pass
class AdapterError(Exception): pass

def grade(request):
    problem = request['problem']
    code = request['code']
    try: ast.parse(code)
    except SyntaxError: return {'valid':True,'passed':False,'errorType':'SyntaxError'}
    path = Path('/tmp/candidate.py')
    path.write_text(code, encoding='utf-8')
    path.chmod(0o644)
    env = {'PATH':'/usr/local/bin:/usr/bin:/bin','MPLCONFIGDIR':'/tmp/matplotlib','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    worker = subprocess.Popen([sys.executable,'-I','/worker/worker.py',str(path)], stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,preexec_fn=unprivileged,env=env)
    saved_kill = os.kill
    def call(*args):
        payload = {'function':problem['entry_point'],'args':encode(args),'kwargs':encode({}),'rng':encode(np.random.get_state())}
        worker.stdin.write(json.dumps(payload)+'\n')
        worker.stdin.flush()
        line = worker.stdout.readline()
        if not line: raise CandidateError('CandidateExited')
        reply = json.loads(line)
        if not reply.get('ok'):
            if reply.get('errorType') == 'UnsupportedScientificObject': raise AdapterError('UnsupportedScientificObject')
            raise CandidateError(reply.get('errorType','ExecutionError'))
        np.random.set_state(decode(reply['rng']))
        return decode(reply['value'])
    try:
        line = worker.stdout.readline()
        if not line: return {'valid':True,'passed':False,'errorType':'CandidateExited'}
        ready = json.loads(line)
        if not ready.get('ready'): return {'valid':True,'passed':False,'errorType':ready.get('errorType')}
        if ready.get('uid') != 65534: raise AdapterError('PrivilegeBoundaryError')
        proxy = types.ModuleType('_grading_proxy')
        proxy.call = call
        sys.modules['_grading_proxy'] = proxy
        wrapper = f"from _grading_proxy import call\ndef {problem['entry_point']}(*args):\n    return call(*args)\n"
        results = {}
        for group in ['base','plus']:
            inputs = problem[group+'_input']
            expected, times = trusted_exec(problem['prompt']+problem['canonical_solution'],inputs,problem['entry_point'],record_time=True)
            status, details = untrusted_check('humaneval',wrapper,inputs,problem['entry_point'],expected,problem['atol'],times,fast_check=False)
            results[group] = {'status':status,'passed':status==PASS,'cases':len(inputs),'checked':len(details),'correct':sum(bool(x) for x in details)}
        return {'valid':True,'passed':all(x['passed'] for x in results.values()),'groups':results}
    finally:
        if worker.poll() is None: saved_kill(worker.pid, signal.SIGKILL)
        worker.wait(timeout=5)

if __name__ == '__main__':
    try: result=grade(json.load(sys.stdin))
    except Exception as error: result={'valid':False,'passed':False,'errorType':type(error).__name__}
    print(json.dumps(result),flush=True)
