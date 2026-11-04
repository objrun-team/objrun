"""External owner: starts runner, monitors, enforces fixed clock, then finalizes.
Python parent is outside Bun child-job lifetime. No global WSL/process operations.
"""
from pathlib import Path
import os,sys,json,time,subprocess,psutil,datetime,threading
run=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve();bun=sys.argv[3]
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def dump(p,o):p.write_text(json.dumps(o,indent=2),encoding='utf-8')
def linux(p):return '/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
def event(o):
    with (run/'supervisor.jsonl').open('a') as f:f.write(json.dumps({'utc':now(),**o})+'\n')
assert not (run/'primary-success.json').exists() and not (run/'final/summary.json').exists()
if (run/'supervisor-process.json').exists():
    old=json.loads((run/'supervisor-process.json').read_text())
    try:
        p=psutil.Process(old['pid']);assert abs(p.create_time()-old['created'])>.5,'Another live supervisor exists'
    except psutil.NoSuchProcess:pass
dump(run/'supervisor-process.json',{'pid':os.getpid(),'created':psutil.Process().create_time(),'utc':now()})
def stop_owned(reason):
    # First block paid transport via an absolute stop marker observed by runner.
    dump(run/'stop-request.json',{'utc':now(),'reason':reason})
    actions=[]
    if (run/'process.json').exists():
        info=json.loads((run/'process.json').read_text())
        for name in ('engine','runner'):
            item=info.get(name,{})
            try:
                p=psutil.Process(item['pid'])
                if abs(p.create_time()-item['created'])>.5:continue
                children=p.children(recursive=True);p.kill()
                for c in children:
                    try:c.kill()
                    except psutil.Error:pass
                actions.append({'name':name,'pid':item['pid'],'children':[c.pid for c in children]})
            except (psutil.Error,KeyError):pass
    try:
        out=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_owned.py'),linux(run),'--stop'],capture_output=True,text=True,timeout=30)
        owned=json.loads(out.stdout)
    except Exception as e:owned={'error':str(e)}
    dump(run/'deadline-guard.json',{'utc':now(),'reason':reason,'actions':actions,'linux_stop':owned})
attempt=0;runner=None;guard_done=threading.Event();guard_started=False
def guard(deadline):
    mono=time.monotonic()+max(0,deadline-time.time())
    while time.time()<deadline and time.monotonic()<mono and not (run/'primary-success.json').exists():time.sleep(.2)
    stop_owned('independent_primary_success' if (run/'primary-success.json').exists() else 'immutable_five_hour_deadline')
    guard_done.set()
while not guard_done.is_set():
    if (run/'deadline.json').exists() and not guard_started:
        deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
        threading.Thread(target=guard,args=(deadline,),daemon=True).start();guard_started=True
    if (run/'primary-success.json').exists() or (guard_started and time.time()>=deadline):
        guard_done.wait(.3);continue
    if runner is None or runner.poll() is not None:
        if runner is not None:
            event({'event':'runner_exit','code':runner.returncode,'original_deadline_preserved':True})
            if not guard_started:break
            time.sleep(3)
            if guard_done.is_set():break
        attempt+=1
        out=(run/f'controller-{attempt}.stdout.log').open('w');err=(run/f'controller-{attempt}.stderr.log').open('w')
        runner=subprocess.Popen([bun,'--env-file='+str(root/'.env'),str(root/'examples/research/lj-conjecture-search/run.ts'),str(run)],cwd=root,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        event({'event':'runner_launch','attempt':attempt,'pid':runner.pid});out.close();err.close()
    time.sleep(.2)
if guard_done.is_set():
    with (run/'finalizer.stdout.log').open('w') as out,(run/'finalizer.stderr.log').open('w') as err:
        result=subprocess.run([sys.executable,str(run/'finalize.py'),str(run)],stdout=out,stderr=err)
    event({'event':'finalizer_exit','code':result.returncode})
else:event({'event':'startup_failed_before_paid_request'})
