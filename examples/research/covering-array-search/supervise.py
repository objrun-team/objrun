"""Autonomous infrastructure restarts inside ONE immutable five-hour window."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
import psutil

run=Path(sys.argv[1]).resolve()
bun=sys.argv[2]
root=run.parents[2]
deadline_path=run/'deadline.json'
if not deadline_path.exists():
    now=time.time()
    deadline_path.write_text(json.dumps({'started_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
        'deadline_utc':datetime.fromtimestamp(now+18000,timezone.utc).isoformat(),'deadline_epoch':now+18000,
        'duration_seconds':18000,'model':'deepseek/deepseek-v4.1-flash','only_campaign_budget':'elapsed time'},indent=2))
deadline=json.loads(deadline_path.read_text())
if time.time()>=deadline['deadline_epoch']: raise SystemExit('Original deadline expired')
(run/'supervisor-process.json').write_text(json.dumps({'pid':os.getpid(),'created':psutil.Process().create_time()}))
guard_alive=False
try:
    g=json.loads((run/'guard-process.json').read_text())
    guard_alive=abs(psutil.Process(g['pid']).create_time()-g['created'])<.5
except (OSError,ValueError,KeyError,psutil.Error): pass
if not guard_alive:
    guard=subprocess.Popen([sys.executable,str(run/'guard.py'),str(run)],stdin=subprocess.DEVNULL,
        stdout=open(run/'guard.stdout.log','a'),stderr=open(run/'guard.stderr.log','a'),creationflags=subprocess.CREATE_NO_WINDOW)
    (run/'guard-process.json').write_text(json.dumps({'pid':guard.pid,'created':psutil.Process(guard.pid).create_time()}))

def prepare_recovery():
    # Only executables carrying this run's exact entrypoint may be stopped.
    targets={str(run/'run.ts').replace('\\','/').lower(),str(run/'runtime/src/main.ts').replace('\\','/').lower()}
    stopped=[]
    for p in psutil.process_iter(['pid','name','cmdline','create_time']):
        args=p.info.get('cmdline') or []
        if (p.info.get('name') or '').lower()=='bun.exe' and any(a.replace('\\','/').lower() in targets for a in args):
            try:
                for c in p.children(recursive=True):
                    try:c.kill()
                    except psutil.Error:pass
                p.kill();p.wait(timeout=5);stopped.append({'pid':p.pid,'created':p.info['create_time']})
            except psutil.Error:pass
    old=(run/'engine').resolve()
    if (old/'data/h2h.sqlite').exists():
        parent=(run/'engine-history').resolve();parent.mkdir(exist_ok=True)
        destination=parent/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        assert old.parent==run and parent.parent==run and destination.parent==parent and not destination.exists()
        old.rename(destination)
        with open(run/'supervisor-events.jsonl','a') as f:
            f.write(json.dumps({'event':'preserved_prior_engine','directory':str(destination),'stopped_owned_processes':stopped,'utc':datetime.now(timezone.utc).isoformat()})+'\n')
    # Recovered tasks get fresh context; the entire prior engine/database stays
    # in engine-history, and all programs/checkpoints/receipts stay in this run.

while time.time()<deadline['deadline_epoch']:
    prepare_recovery()
    with open(run/'supervisor-events.jsonl','a') as f: f.write(json.dumps({'event':'start_runner','utc':datetime.now(timezone.utc).isoformat()})+'\n')
    child=subprocess.Popen([bun,'--smol','--env-file='+str(root/'.env'),str(run/'run.ts'),str(run)],cwd=root,
        stdin=subprocess.DEVNULL,stdout=open(run/'runner.stdout.log','a'),stderr=open(run/'runner.stderr.log','a'),creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ,'CA_PROJECT_ROOT':str(root)})
    try: code=child.wait(timeout=max(.01,deadline['deadline_epoch']-time.time()))
    except subprocess.TimeoutExpired:
        child.kill(); break
    with open(run/'supervisor-events.jsonl','a') as f: f.write(json.dumps({'event':'runner_exit','code':code,'utc':datetime.now(timezone.utc).isoformat()})+'\n')
    if time.time()>=deadline['deadline_epoch']: break
    time.sleep(min(10,max(0,deadline['deadline_epoch']-time.time())))
