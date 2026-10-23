"""Root-side function RPC; candidate worker runs as UID65534 with no network or oracle."""
import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
sys.path.insert(0,'/worker')
import numpy as np
from codec import encode, decode

class CandidateError(Exception): pass
class AdapterError(Exception): pass

def drop_privileges():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)

class FunctionProxy:
    def __init__(self, code, seconds=90):
        ast.parse(code)
        path=Path('/tmp/candidate.py')
        path.write_text(code,encoding='utf-8')
        path.chmod(0o644)
        self.worker=subprocess.Popen([sys.executable,'-I','/worker/worker.py',str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',preexec_fn=drop_privileges,env={'PATH':'/usr/local/bin:/usr/bin:/bin','MPLCONFIGDIR':'/tmp/matplotlib','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
        self.previous_handler=signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(CandidateError('CandidateTimeout')))
        signal.alarm(seconds)
        self.ready=None
    def __enter__(self):
        try:
            line=self.worker.stdout.readline()
            if not line: raise CandidateError('CandidateExited')
            hello=json.loads(line)
            if not hello.get('ready'): raise CandidateError(hello.get('errorType','ExecutionError'))
            if hello.get('uid')!=65534: raise AdapterError('PrivilegeBoundaryError')
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise
    def call(self,name,*args):
        self.worker.stdin.write(json.dumps({'function':name,'args':encode(args),'kwargs':encode({}),'rng':encode(np.random.get_state())})+'\n')
        self.worker.stdin.flush()
        line=self.worker.stdout.readline()
        if not line: raise CandidateError('CandidateExited')
        reply=json.loads(line)
        if not reply.get('ok'):
            if reply.get('errorType')=='UnsupportedScientificObject': raise AdapterError('UnsupportedScientificObject')
            raise CandidateError(reply.get('errorType','ExecutionError'))
        np.random.set_state(decode(reply['rng']))
        return decode(reply['value'])
    def __exit__(self,*_):
        signal.alarm(0)
        signal.signal(signal.SIGALRM,self.previous_handler)
        if self.worker.poll() is None: self.worker.kill()
        self.worker.wait(timeout=5)
