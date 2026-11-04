"""Independent absolute-deadline guard. No shared WSL host is terminated."""
import json,sys,time,psutil
from pathlib import Path
from datetime import datetime,timezone
run=Path(sys.argv[1]).resolve()
while not (run/'deadline.json').exists():
 if (run/'completion.json').exists():sys.exit(0)
 time.sleep(.2)
deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
stop=time.monotonic()+max(0,deadline-time.time())
while time.time()<deadline and time.monotonic()<stop:time.sleep(min(.3,max(.001,deadline-time.time()),max(.001,stop-time.monotonic())))
receipt={'utc':datetime.now(timezone.utc).isoformat(),'reason':'immutable_first_dispatch_plus_five_hours','actions':[]}
info=json.loads((run/'process.json').read_text())
for name in ('engine','runner'):
 item=info.get(name,{})
 try:
  p=psutil.Process(item['pid'])
  if abs(p.create_time()-item['created'])>=.5:continue
  children=p.children(recursive=True)
  p.kill()
  for child in children:
   try:child.kill()
   except psutil.Error:pass
  receipt['actions'].append({'name':name,'pid':item['pid'],'killed':True,'child_pids':[p.pid for p in children]})
 except (psutil.Error,KeyError):pass
receipt['linux_enforcement']='All model tools and in-run checker processes run in bwrap private PID namespaces with the same absolute timeout; PID namespace destruction kills descendants. No shared WSL restart or termination.'
(run/'deadline-guard.json').write_text(json.dumps(receipt,indent=2))
