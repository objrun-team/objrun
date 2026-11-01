"""Independent success/deadline guard; never restarts or kills shared WSL."""
import json,os,sys,time,subprocess
from pathlib import Path
from datetime import datetime,timezone
import psutil
run=Path(sys.argv[1]).resolve();end=json.loads((run/'deadline.json').read_text())['deadline_epoch']
mono=time.monotonic()+max(0,end-time.time())
while time.time()<end and time.monotonic()<mono and not (run/'success-certified.json').exists():time.sleep(.15)
reason='certified_success' if (run/'success-certified.json').exists() else 'original_five_hour_deadline'
receipt={'utc':datetime.now(timezone.utc).isoformat(),'deadline_epoch':end,'reason':reason,'actions':[]}
(run/'stop-requested.json').write_text(json.dumps(receipt));(run/'work/STOP').write_text(reason)
info=json.loads((run/'process.json').read_text())
for name in ['engine','runner']:
    try:
        obj=info[name];p=psutil.Process(obj['pid'])
        if abs(p.create_time()-obj['created'])>.5:continue
        children=p.children(recursive=True);p.kill()
        for c in children:
            if c.pid==os.getpid():continue
            try:c.kill()
            except psutil.Error:pass
        receipt['actions'].append({'name':name,'pid':p.pid,'children':[c.pid for c in children if c.pid!=os.getpid()]})
    except (KeyError,psutil.Error):pass
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
stopped=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_stop.py'),linux(run/'work')],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
receipt['linux']=json.loads(stopped.stdout) if stopped.returncode==0 else {'error':stopped.stderr}
(run/'deadline-guard.json').write_text(json.dumps(receipt,indent=2))
with (run/'finalize.stdout.log').open('w') as out,(run/'finalize.stderr.log').open('w') as err:
    subprocess.run([sys.executable,str(run/'finalize.py'),str(run)],stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
