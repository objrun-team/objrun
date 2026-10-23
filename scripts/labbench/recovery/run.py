"""Retry only original infrastructure identities, stop at their first valid trial."""
from pathlib import Path
import fcntl
import os
import subprocess
import sys
import time
from core import *

def alive(pid,home):
    p=Path('/proc')/str(pid)/'cmdline'
    return p.exists() and str(home).encode() in p.read_bytes() and b'worker.py' in p.read_bytes()

def main():
    root=Path(sys.argv[1]).resolve();cfg=read(root/'recovery.json');jobs=cfg['jobs']
    lock=(root/'controller.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert read(root/'controls.json')['allPassed'] and read(root/'authorization.json')['retryUntilFirstValid']
    for rel,h in read(root/'operations-pins.json').items():assert sha(root/rel)==h
    selected={};processed=set();active={};failures={key(j):0 for j in jobs};next_at={key(j):0 for j in jobs};consecutive=0;concurrency=2;blocked=None
    save(root/'control/admission.json',{'modelSlots':2})
    def history(job):
        return sorted((root/'attempts'/job['arm']/job['id']).glob('attempt-*'))
    def reconcile():
        nonlocal concurrency,consecutive,blocked
        for job in jobs:
            k=key(job)
            for home in history(job):
                if (home/'terminal.json').exists() and home.as_posix() not in processed:
                    t=read(home/'terminal.json');processed.add(home.as_posix());active.pop(k,None)
                    if t['valid']:
                        assert k not in selected
                        selected[k]={'home':home.relative_to(root).as_posix(),'terminal':t,'resultSha256':t['resultSha256']};consecutive=0
                        save(root/'first-valid.json',selected)
                    else:
                        failures[k]+=1;consecutive+=1
                        if consecutive>=2:concurrency=1
                        next_at[k]=t['endedEpoch']+cooldown(failures[k],concurrency==1)
                        resume=read(root/'control/account-unblocked.json').get('atEpoch',0) if (root/'control/account-unblocked.json').exists() else 0
                        if t.get('requiresUser') and t['endedEpoch']>resume:blocked=t
                    save(root/'control/admission.json',{'modelSlots':concurrency})
                elif not (home/'terminal.json').exists():
                    meta=read(home/'attempt.json');proc=read(home/'worker-process.json') if (home/'worker-process.json').exists() else {}
                    if not alive(proc.get('pid',0),home) and (time.time()>meta['createdEpoch']+900 or not list((home/'outputs/canonical/calls').glob('**/dispatch.json'))):
                        save(home/'terminal.json',{'number':meta['number'],'identity':meta['identity'],'arm':job['arm'],'id':job['id'],'valid':False,'result':None,'error':'WorkerExitedWithoutTerminal','requiresUser':False,'endedEpoch':time.time(),'classification':'infrastructure-retry'},True)
                    else:active[k]={'home':home,'pid':proc.get('pid'),'startedEpoch':meta['createdEpoch']}
    def status(stage):
        homes=[p.parent for p in (root/'attempts').glob('*/*/attempt-*/attempt.json')]
        save(root/'status.json',{'stage':stage,'pid':os.getpid(),'atUtc':now(),'selectedCount':len(selected),'targetCount':len(jobs),'attemptCount':len(homes),'firstValid':selected,
            'active':[{'identity':k,'home':v['home'].relative_to(root).as_posix(),'pid':v['pid']} for k,v in active.items()],
            'nextEligibleEpoch':{k:v for k,v in next_at.items() if k not in selected},'workerConcurrency':concurrency,'blocked':blocked,'accounting':ledger(homes)})
    while True:
        reconcile()
        if blocked:
            status('blocked_needs_user')
            if not active:return
        if len(selected)==len(jobs):break
        if not blocked:
            for job in jobs:
                k=key(job)
                if len(active)>=concurrency:break
                if k in selected or k in active or time.time()<next_at[k]:continue
                number=len(history(job))+1;home=attempt_home(root,job,number);home.mkdir(parents=True,exist_ok=False)
                meta={**job,'number':number,'identity':NAME+'/'+k+'/attempt-%04d'%number,'createdEpoch':time.time(),'createdAtUtc':now(),'fullSolveBudgetSeconds':600,'oldTimeOrCandidateReused':False}
                save(home/'attempt.json',meta,True)
                env={**os.environ,'PATH':str(root/'frozen/bin')+':/usr/bin:/bin','HOME':str(root/'frozen/runtime-home'),'PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'127.0.0.1,localhost'}
                with (home/'worker.stdout.log').open('ab') as out,(home/'worker.stderr.log').open('ab') as err:
                    child=subprocess.Popen([str(root/'frozen/venv/bin/python'),str(root/'operations/worker.py'),str(root),str(home)],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
                save(home/'worker-process.json',{'pid':child.pid,'atUtc':now()},True);active[k]={'home':home,'pid':child.pid,'startedEpoch':meta['createdEpoch']}
        status('running' if not blocked else 'blocked_needs_user');time.sleep(5)
    status('finalizing')
    import report_recovery
    report_recovery.generate(root)
    status('complete' if read(root/'AUDIT.json')['allPassed'] else 'needs_attention')
    save(root/'final-freeze.json',{'atUtc':now(),'selected':len(selected),'auditPassed':read(root/'AUDIT.json')['allPassed']},True)

if __name__=='__main__':main()
