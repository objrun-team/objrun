import json
import subprocess
import sys
import time
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[3]
run=Path((root/'data/covering-array-search/latest-run.txt').read_text())
if not json.loads((run/'preflight/check-result.json').read_text())['passed']:
    raise SystemExit('Integration preflight did not pass')
if not json.loads((run/'tests/isolation.json').read_text())['external_timeout_passed']:
    raise SystemExit('Deadline preflight did not pass')
if (run/'supervisor-process.json').exists():
    item=json.loads((run/'supervisor-process.json').read_text())
    try:
        p=psutil.Process(item['pid'])
        if abs(p.create_time()-item['created'])<.5: raise SystemExit('Supervisor already running')
    except psutil.Error: pass
if (run/'deadline.json').exists() and time.time()>=json.loads((run/'deadline.json').read_text())['deadline_epoch']:
    raise SystemExit('Original deadline expired; cannot restart')
bun=str(Path.home()/'AppData/Roaming/npm/node_modules/bun/bin/bun.exe')
child=subprocess.Popen([sys.executable,str(run/'supervise.py'),str(run),bun],cwd=root,
    stdin=subprocess.DEVNULL,stdout=open(run/'supervisor.stdout.log','a'),stderr=open(run/'supervisor.stderr.log','a'),
    creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'supervisor_pid':child.pid,'run':str(run),'started':True}))
