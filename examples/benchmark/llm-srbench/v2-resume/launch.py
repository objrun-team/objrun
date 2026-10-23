"""Once-only stdin credential transport for the independently frozen controller."""
import json,os,pathlib,subprocess,sys,time
CONTROL=pathlib.Path(__file__).resolve().parent;ROOT=CONTROL.parents[1]
q=json.load(sys.stdin);key=q.pop('key');assert isinstance(key,str) and key.strip()
assert not (CONTROL/'launch.json').exists(),'ContinuationLaunchAlreadyAttempted'
env={'PATH':str(ROOT/'bin')+':'+str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':key,'PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
with (CONTROL/'controller.stdout.log').open('ab') as out,(CONTROL/'controller.stderr.log').open('ab') as err:
    p=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(CONTROL/'runner.py')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
v={'pid':p.pid,'root':str(ROOT),'entry':str(CONTROL/'runner.py'),'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'credentialWritten':False,'authorization':q}
(CONTROL/'launch.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
