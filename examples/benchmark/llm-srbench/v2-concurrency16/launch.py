"""Single launch; existing key travels on SSH stdin, never written to disk."""
import json,os,subprocess,sys
from support import *
q=json.load(sys.stdin);key=q.pop('key');assert key and isinstance(key,str)
assert not (CONTROL/'launch.json').exists(),'AlreadyLaunched'
p=preserve();h=load(CONTROL/'handoff.json');assert h['drainedAndVerified'] and not live(h['oldPid'],h['oldEntry']) and not live(h['oldGraderPid'],h['oldGraderEntry'])
assert pins()==load(CONTROL/'source-pins.json') and load(CONTROL/'free-checks.json')['allPassed']
env={'PATH':str(ROOT/'bin')+':'+str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':key,'PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
with (CONTROL/'controller.stdout.log').open('ab') as out,(CONTROL/'controller.stderr.log').open('ab') as err:
    proc=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'runner.py')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
value={'pid':proc.pid,'entry':str(CONTROL/'runner.py'),'atUtc':core.utc(),'credentialWritten':False,'authorization':q,'remainingCells':len(p['remainingCells']),'concurrency':[16,16,16]};common.durable(CONTROL/'launch.json',value);print(json.dumps(value))
