"""One-shot owned controller launch. Credential is received on stdin, never persisted."""
from pathlib import Path
import fcntl
import json
import os
import subprocess
import sys
import time

root=(Path(__file__).resolve().parents[4] / 'scripts');out=root/'outputs/canonical';out.mkdir(parents=True,exist_ok=True)
payload=json.load(sys.stdin);key=payload['key']
if not isinstance(key,str) or len(key.strip())<8:raise RuntimeError('MissingExistingCredential')
lock=(out/'launcher.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
if (out/'launch.json').exists() or (out/'launch-started.json').exists():raise RuntimeError('ExistingLaunchInspectDoNotRepeat')
controls=json.loads((out/'controls.json').read_text())
if not controls['allPassed'] or controls['modelCalls']!=0:raise RuntimeError('ZeroModelAcceptanceRequired')
with (out/'launch-started.json').open('x') as f:json.dump({'atEpoch':time.time()},f)
env={'DEEPSEEK_API_KEY':key,'PATH':str(root/'bin')+':/usr/bin:/bin','HOME':str(root/'runtime-home'),
    'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost'}
(root/'runtime-home').mkdir(exist_ok=True)
cmd=[str(root/'venv/bin/python'),str(root/'package/controller.py')]
with (out/'controller.stdout.log').open('ab') as stdout,(out/'controller.stderr.log').open('ab') as stderr:
    child=subprocess.Popen(cmd,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
record={'pid':child.pid,'root':str(root),'cmdline':cmd,'atEpoch':time.time(),'credentialWritten':False}
with (out/'launch.json').open('x') as f:json.dump(record,f,indent=2)
print(json.dumps(record))
