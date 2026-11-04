"""Independent absolute deadline, only PID+creation-time owned processes."""
import json,os,sys,time,subprocess
from pathlib import Path
from datetime import datetime,timezone
import psutil
run=Path(sys.argv[1]).resolve();end=json.loads((run/'deadline.json').read_text())['deadline_epoch']
mono=time.monotonic()+max(0,end-time.time())
while time.time()<end and time.monotonic()<mono:time.sleep(min(.2,max(.001,end-time.time()),max(.001,mono-time.monotonic())))
info=json.loads((run/'process.json').read_text());actions=[]
for name in ['engine','runner']:
    try:
        obj=info[name];p=psutil.Process(obj['pid'])
        if abs(p.create_time()-obj['created'])>.5:continue
        children=p.children(recursive=True);p.kill()
        for c in children:
            if c.pid==os.getpid():continue
            try:c.kill()
            except psutil.Error:pass
        actions.append({'name':name,'pid':p.pid,'children':[c.pid for c in children if c.pid!=os.getpid()]})
    except (KeyError,psutil.Error):pass
(run/'deadline-guard.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'deadline_epoch':end,'actions':actions,'linux_enforcement':'Each owned bubblewrap namespace has a supervisor timeout at the same absolute deadline; no shared WSL service is stopped.'},indent=2))
with (run/'finalize.stdout.log').open('w') as out,(run/'finalize.stderr.log').open('w') as err:
    subprocess.run([sys.executable,str(run/'finalize.py'),str(run)],stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
