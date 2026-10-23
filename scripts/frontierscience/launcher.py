"""Read one credential via SSH stdin; never write it to a file or child engine."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
from protocol import BASE
import urllib.request

root=Path(__file__).resolve().parents[1];out=root/'outputs/canonical';out.mkdir(parents=True,exist_ok=True)
payload=json.load(sys.stdin);key=payload['key']
if not isinstance(key,str) or not key.strip():raise RuntimeError('MissingDeepSeekCredential')
observed={}
for path in ['/models','/user/balance']:
    req=urllib.request.Request(BASE+path,headers={'Authorization':'Bearer '+key})
    with urllib.request.urlopen(req,timeout=30) as r:observed[path]=json.load(r)
if not observed['/user/balance'].get('is_available'):raise RuntimeError('DeepSeekBalanceUnavailable')
if 'deepseek-flash' not in [x['id'] for x in observed['/models']['data']]:raise RuntimeError('DeepSeekFlashAliasUnavailable')
(out/'prelaunch-account.json').write_text(json.dumps({'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'observations':observed},indent=2)+'\n')
if payload.get('action')=='observe':print(json.dumps({'credentialAvailable':True,'observations':observed}));sys.exit(0)
if (out/'launch.json').exists():raise RuntimeError('ExistingLaunchMustInspectNoDuplicate')
env={'DEEPSEEK_API_KEY':key,'PATH':str(root/'bin')+':/usr/bin:/bin','HOME':str(root/'runtime-home'),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost'}
(root/'runtime-home').mkdir(exist_ok=True)
with (out/'controller.stdout.log').open('ab') as stdout,(out/'controller.stderr.log').open('ab') as stderr:
    cmd=['/usr/bin/python3.11',str(root/'package/controller.py')]
    child=subprocess.Popen(cmd,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
record={'pid':child.pid,'root':str(root),'cmdline':cmd,'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'credentialWritten':False}
with (out/'launch.json').open('x') as f:f.write(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
