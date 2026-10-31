"""Independent host deadline enforcement; original window can never be renewed."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import psutil

run=Path(sys.argv[1]).resolve()
deadline=json.loads((run/'deadline.json').read_text())
end=time.monotonic()+max(0,deadline['deadline_epoch']-time.time())
while time.time()<deadline['deadline_epoch'] and time.monotonic()<end:
    time.sleep(min(1,max(.01,end-time.monotonic())))
receipt={'time':datetime.now(timezone.utc).isoformat(),'reason':'original_five_hour_deadline','actions':[]}
# The separate Linux timeout outside every sandbox also kills that sandbox at
# this deadline, even if both host processes die or the chat is offline.
for name in ['supervisor-process.json','process.json']:
    try:
        info=json.loads((run/name).read_text())
        items=[info] if 'pid' in info else [info.get('engine',{}),info.get('runner',{})]
        for item in items:
            try:
                proc=psutil.Process(item['pid'])
                if abs(proc.create_time()-item['created'])<.5:
                    for child in proc.children(recursive=True):
                        if child.pid == os.getpid():
                            continue  # The independent guard is also a supervisor child.
                        try: child.kill()
                        except psutil.Error: pass
                    proc.kill()
                    receipt['actions'].append({'pid':item['pid'],'killed':True,'identity_checked':True})
            except (psutil.Error,KeyError): pass
    except (OSError,ValueError): pass
(run/'deadline-guard.json').write_text(json.dumps(receipt,indent=2))
# Verification happens after stopping paid calls/computation; it cannot renew
# the search window. Only trusted code reads the frozen incumbent.
if (run/'finalize.py').exists():
    subprocess.run([sys.executable,str(run/'finalize.py'),str(run)],check=False)
