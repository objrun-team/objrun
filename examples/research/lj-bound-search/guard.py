"""Owned-process absolute deadline + immediate success closeout watchdog."""
import json,sys,time,psutil,subprocess
from pathlib import Path
from datetime import datetime,timezone
run=Path(sys.argv[1]).resolve()
while not (run/'deadline.json').exists():
    if (run/'completion.json').exists():sys.exit(0)
    time.sleep(.2)
deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
stop=time.monotonic()+max(0,deadline-time.time())
while time.time()<deadline and time.monotonic()<stop:
    if (run/'primary-success.json').exists():
        # Let the runner commit report and shut down cleanly, without more calls.
        time.sleep(1);break
    time.sleep(.25)
receipt={'utc':datetime.now(timezone.utc).isoformat(),'reason':'independent_success' if (run/'primary-success.json').exists() else 'immutable_five_hour_deadline','actions':[]}
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
try:
    owned=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_owned.py'),linux(run),'--stop'],capture_output=True,text=True,timeout=20)
    receipt['linux_stop']=json.loads(owned.stdout)
except Exception as e:receipt['linux_stop_error']=str(e)
info=json.loads((run/'process.json').read_text())
for name in ('engine','runner'):
    item=info.get(name,{})
    try:
        p=psutil.Process(item['pid'])
        if abs(p.create_time()-item['created'])>=.5:continue
        children=p.children(recursive=True)
        # The guard is itself an owned child; do not kill ourselves before finalizing.
        children=[c for c in children if c.pid!=__import__('os').getpid()]
        p.kill()
        for child in children:
            try:child.kill()
            except psutil.Error:pass
        receipt['actions'].append({'name':name,'pid':item['pid'],'child_pids':[c.pid for c in children]})
    except (psutil.Error,KeyError):pass
receipt['linux_enforcement']='Private bwrap PID namespaces, die-with-parent and identical absolute subprocess timeout. No shared WSL restart.'
(run/'deadline-guard.json').write_text(json.dumps(receipt,indent=2))
with (run/'finalizer.stdout.log').open('w') as out,(run/'finalizer.stderr.log').open('w') as err:
    subprocess.run([sys.executable,str(run/'finalize.py'),str(run)],stdout=out,stderr=err)
