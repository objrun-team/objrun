"""Independent watchdog, owns only this run's registered PID incarnations."""
import json,sys,time,os,subprocess,psutil
from pathlib import Path
from datetime import datetime,timezone
run=Path(sys.argv[1]).resolve()
while not (run/'deadline.json').exists():
    if (run/'completion.json').exists():sys.exit(0)
    time.sleep(.1)
deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
mono=time.monotonic()+max(0,deadline-time.time())
while time.time()<deadline and time.monotonic()<mono and not (run/'success.json').exists():time.sleep(.1)
reason='independently_verified_main_success' if (run/'success.json').exists() else 'immutable_five_hour_deadline'
(run/'control/STOP').write_text(reason)
# Namespace supervisors observe this read-only STOP within 100ms and terminate
# their process groups. The Windows processes get a short chance to flush logs.
time.sleep(1)
info=json.loads((run/'process.json').read_text());actions=[]
for name in ('engine','runner','auditor'):
    item=info.get(name,{})
    try:
        p=psutil.Process(item['pid'])
        if abs(p.create_time()-item['created'])>=.5:continue
        descendants=p.children(recursive=True)
        p.kill()
        for child in descendants:
            if child.pid==os.getpid():continue
            try:child.kill()
            except psutil.Error:pass
        actions.append({'name':name,'pid':item['pid'],'children':[p.pid for p in descendants if p.pid!=os.getpid()]})
    except (psutil.Error,KeyError):pass
(run/'deadline-guard.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'reason':reason,'actions':actions,'linux_enforcement':'Every owned bwrap namespace checks shared read-only STOP and absolute deadline; no shared WSL restart.'},indent=2))
with (run/'finalize.stdout.log').open('w') as out,(run/'finalize.stderr.log').open('w') as err:
    subprocess.run([sys.executable,str(run/'finalize.py'),str(run)],stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
