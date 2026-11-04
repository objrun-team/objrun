"""Host-side deadline enforcement independent of chat and ObjRun event loop."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import psutil

run=Path(sys.argv[1]).resolve()
deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
stop=time.monotonic()+max(0,deadline-time.time())
while time.time()<deadline and time.monotonic()<stop:
    time.sleep(min(.5,max(.001,deadline-time.time()),max(.001,stop-time.monotonic())))
receipt={'utc':datetime.now(timezone.utc).isoformat(),'reason':'original_five_hour_deadline','actions':[]}
info=json.loads((run/'process.json').read_text())
for name in ('engine','runner'):
    item=info.get(name,{})
    try:
        process=psutil.Process(item['pid'])
        if abs(process.create_time()-item['created'])>=.5: continue
        # Only this run's verified process tree; never terminate a shared WSL host.
        protected={psutil.Process().pid} | {p.pid for p in psutil.Process().children(recursive=True)}
        children=[p for p in process.children(recursive=True) if p.pid not in protected]
        process.kill()
        for child in children:
            try: child.kill()
            except psutil.Error: pass
        receipt['actions'].append({'name':name,'pid':item['pid'],'killed':True,'child_pids':[p.pid for p in children]})
    except (psutil.Error,KeyError): pass
receipt['linux_enforcement']='Each bwrap PID namespace has an independent subprocess timeout at the same absolute deadline; exiting its supervisor destroys the namespace.'
(run/'deadline-guard.json').write_text(json.dumps(receipt,indent=2))

if (run/"finalize.py").exists():
    import subprocess
    time.sleep(2)
    with (run/"finalize.stdout.log").open("w") as out,(run/"finalize.stderr.log").open("w") as err:
        subprocess.run([sys.executable,str(run/"finalize.py"),str(run)],stdout=out,stderr=err)
