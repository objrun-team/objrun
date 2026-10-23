"""Single durable launch intent and shared campaign admission lease."""
import fcntl,subprocess
from shared import *
payload=json.load(sys.stdin);key=payload.pop('key');assert key
assert not (CONTROL/'launch.json').exists(),'AlreadyLaunched'
assert all(processes_exited(r) for r in HISTORY)
verify_sources();assert load(CONTROL/'free-checks.json')['allPassed']
lease=(BASE/'llm-srbench-20261019-admission.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
common.durable(CONTROL/'launch-intent.json',{'atUtc':utc(),'authorization':payload,'keyWritten':False})
env={'PATH':str(ROOT/'bin')+':'+str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':key,'PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
env['BENCH_ADMISSION_FD']=str(lease.fileno())
with (OUT/'controller.stdout.log').open('ab') as out,(OUT/'controller.stderr.log').open('ab') as err:
    p=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'runner.py')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True,pass_fds=(lease.fileno(),))
v={'pid':p.pid,'entry':str(CONTROL/'runner.py'),'atUtc':utc(),'keyWritten':False,'runId':load(CONTROL/'plan.json')['runId']};common.durable(CONTROL/'launch.json',v)
lease.close();print(json.dumps(v))
