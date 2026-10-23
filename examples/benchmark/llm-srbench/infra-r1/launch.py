"""Single independent round launch; never writes a real API key."""
import os,subprocess
from shared import *
payload=json.load(sys.stdin);key=payload.pop('key');assert key
assert not (CONTROL/'launch.json').exists(),'SupplementalRoundAlreadyLaunched'
import prepare
ok,why=prepare.ready();assert ok,why
verify_sources();verify_originals();assert load(CONTROL/'free-checks.json')['allPassed']
env={'PATH':str(ROOT/'bin')+':'+str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':key,'PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
with (OUT/'controller.stdout.log').open('ab') as out,(OUT/'controller.stderr.log').open('ab') as err:p=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'runner.py')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
v={'pid':p.pid,'entry':str(CONTROL/'runner.py'),'atUtc':utc(),'authorization':payload,'keyWritten':False,'roundId':load(CONTROL/'plan.json')['roundId']};common.durable(CONTROL/'launch.json',v);print(json.dumps(v))
