"""Verify pipe limits and timeout closure without Docker or models."""
import json
import os
from pathlib import Path
import sys
import time
import uuid
from bounded_child import run
from prepare import HOME,public,save,utc

def main():
    home=HOME/'capture-bound-controls'/uuid.uuid4().hex;home.mkdir(parents=True)
    env={k:v for k,v in os.environ.items() if k in ('SystemRoot','WINDIR','PATH','PATHEXT')}
    cases=[]
    def check(name,code,cap,timeout,stdin=None):
        out=home/(name+'.stdout');err=home/(name+'.stderr')
        before=time.monotonic();result=run([sys.executable,'-I','-B','-c',code],env,out,err,timeout,stdin,stdout_limit=cap,stderr_limit=65536)
        assert result['directChildClosed'] and result['pipeReadersClosed'] and out.stat().st_size<=cap and err.stat().st_size<=65536
        result.update(name=name,wallSeconds=time.monotonic()-before,stdoutPin=public.pin(out),stderrPin=public.pin(err));cases.append(result)
        return result
    ordinary=check('ordinary','print("hello")',1024,5);assert ordinary['exitCode']==0 and not ordinary['faults']
    overflow=check('oversized','import sys;sys.stdout.buffer.write(b"x"*1048576)',65536,5);assert 'stdout_limit' in overflow['faults']
    blocked=check('unread_stdin','import time;time.sleep(20)',1024,0.5,b'x'*1048576);assert 'timeout' in blocked['faults'] and blocked['wallSeconds']<10
    result={'protocol':'skillsbench-full-f-bounded-capture-controls-v1','createdAtUtc':utc(),'cases':cases,
            'sourcePin':public.pin(Path(__file__).with_name('bounded_child.py')),'verified':True,'modelCalls':0,'DockerOperations':0,'scoreCertificate':False}
    pin=save(home/'result.json',result,True);save(HOME/'capture-bound-controls/latest.json',{'resultPin':pin})
    print(json.dumps({'resultPin':pin,'verified':True,'cases':len(cases),'modelCalls':0}))

if __name__=='__main__':main()
