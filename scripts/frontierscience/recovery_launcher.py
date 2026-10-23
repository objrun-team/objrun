"""One durable recovery launch. Credential arrives only through SSH stdin."""
from pathlib import Path
import fcntl
import json
import os
import subprocess
import sys
from recovery_guard import guard, resources
from runtime import ROOT,OUT,read,save,now,DeepSeek

OUT.mkdir(parents=True,exist_ok=True)
payload=json.load(sys.stdin);key=payload['key']
assert isinstance(key,str) and key.strip()
lock=(OUT/'launch.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX)
existing=OUT/'launch.json'
if existing.exists():
    print(json.dumps({'reusedLaunch':True,**read(existing)}));sys.exit(0)
manifest=read(ROOT/'data/recovery-manifest.json');cfg=read(ROOT/'package/experiment.json')
preflight={'atUtc':now(),'original':guard(cfg['originalRoot'],manifest['originalArchiveSha256']),'resources':resources()}
os.environ['DEEPSEEK_API_KEY']=key
client=DeepSeek();preflight['account']=client.observe()
save(OUT/'prelaunch.json',preflight,True)
env={'DEEPSEEK_API_KEY':key,'PATH':str(ROOT/'bin')+':/usr/bin:/bin','HOME':str(ROOT/'runtime-home'),
     'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost'}
(ROOT/'runtime-home').mkdir(exist_ok=True)
cmd=['/usr/bin/python3.11',str(ROOT/'package/recovery_controller.py')]
# Persist intent before process creation. An uncertain launch is inspected, never duplicated.
save(existing,{'state':'launch_intent','round':1,'cmdline':cmd,'atUtc':now()},True)
with (OUT/'controller.stdout.log').open('ab') as stdout,(OUT/'controller.stderr.log').open('ab') as stderr:
    child=subprocess.Popen(cmd,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
record={'state':'launched','round':1,'pid':child.pid,'cmdline':cmd,'root':str(ROOT),'atUtc':now(),'credentialWritten':False}
save(existing,record);print(json.dumps(record))
