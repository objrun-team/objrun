"""Zero-model acceptance -> frozen twenty-question canary -> full 708 x 2."""
from pathlib import Path
import concurrent.futures as futures
import fcntl
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from protocol import digest, SYSTEM
from runtime import ROOT,OUT,CFG,LOCK,OpenRouter,Judge,Fault,BudgetEnded,broker,read,save,now,accounting

book={r['id']:r for r in read(ROOT/'data/private-tasks.json')}
public=read(ROOT/'data/public-tasks.json')
stage='starting';active={};fatal=None;client=None;consecutive_faults=0

def frozen(dependencies=False):
    for rel,sha in read(ROOT/'provenance/source-pins.json')['files'].items():
        if digest((ROOT/rel).read_bytes())!=sha:raise Fault('SourceChanged:'+rel)
    if dependencies:
        for rel,sha in read(ROOT/'provenance/dependencies.json')['files'].items():
            if digest((ROOT/rel).read_bytes())!=sha:raise Fault('DependencyChanged:'+rel)

def status():
    rows=[read(p) for p in (OUT/'results').glob('*/*.json')]
    save(OUT/'status.json',{'stage':stage,'pid':os.getpid(),'root':str(ROOT),'atUtc':now(),'active':list(active.values()),'fatal':fatal,
        'arms':{a:{'total':708,'completed':sum(r['arm']==a for r in rows),
            'valid':sum(r['arm']==a and r['solverValid'] and r['grade']['valid'] for r in rows),
            'passed':sum(r['arm']==a and r['solverValid'] and r['grade'].get('valid') and r['grade'].get('passed',False) for r in rows),
            'exceptions':sum(r['arm']==a and not (r['solverValid'] and r['grade'].get('valid')) for r in rows)} for a in CFG['arms']},
        'api':client.metrics() if client else {},'accounting':accounting()})

def heartbeat():
    while stage not in {'complete','complete_with_exceptions','needs_attention'}:
        try:status()
        except Exception:pass
        time.sleep(15)

def native(task,directory,server,token,fixture=False):
    directory.mkdir(parents=True,exist_ok=True)
    # Startup is bounded separately. native.ts publishes the authoritative task deadline.
    launch_deadline=time.time()+CFG['solveSeconds']+CFG['engineStartupSeconds']
    spec={'task':{'id':task['id'],'problem':task['prompt'],'choiceCount':task.get('choiceCount',5)},'directory':str(directory),
        'deadlineEpoch':launch_deadline,'fixture':fixture,'run':CFG['run']}
    recovery=(CFG.get('canaryTransportRecovery') or {}).get(task['id']) if not fixture else None
    if recovery:
        spec.update(priorSolveSeconds=recovery['consumedSolveSeconds'],replayFirstWire=read(ROOT/recovery['firstWirePath']))
    save(directory/'input.json',spec,True)
    env={'PATH':str(ROOT/'bin')+':/usr/bin:/bin','HOME':str(ROOT/'runtime-home'),'NO_PROXY':'127.0.0.1,localhost',
        'BUN_INSTALL_CACHE_DIR':str(ROOT/'runtime-home/bun-cache'),'PYTHONDONTWRITEBYTECODE':'1',
        'LABBENCH_BROKER_URL':'http://127.0.0.1:'+str(server.server_port),'LABBENCH_BROKER_TOKEN':token}
    with (directory/'worker.stdout.log').open('ab') as stdout,(directory/'worker.stderr.log').open('ab') as stderr:
        child=subprocess.Popen([str(ROOT/'bin/bun'),'--no-install',str(ROOT/'package/native.ts'),str(directory/'input.json')],
            cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
        save(directory/'worker-process.json',{'pid':child.pid,'atUtc':now()},True)
        try:child.wait(timeout=max(1,launch_deadline-time.time())+20)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            info=directory/'engine-process.json'
            if info.exists():
                pid=read(info)['pid'];cmd=Path('/proc')/str(pid)/'cmdline'
                if cmd.exists() and str(ROOT/'package/engine/app/src/main.ts').encode() in cmd.read_bytes():os.kill(pid,15)
    if not (directory/'native-result.json').exists():raise Fault('NativeWorkerMissingResult:exit='+str(child.returncode))
    return read(directory/'native-result.json')

def solve(task,arm,judge,server,token):
    global consecutive_faults,fatal
    tid=task['id'];dest=OUT/'results'/arm/(tid+'.json');directory=OUT/'tasks'/arm/tid
    if dest.exists():raise Fault('ExistingResultCannotRegenerate:'+arm+'/'+tid)
    frozen();start=time.time();deadline=start+CFG['solveSeconds']
    directory.mkdir(parents=True,exist_ok=True)
    save(directory/'started.json',{'arm':arm,'id':tid,'startedAtUtc':now(),'startedEpoch':start,'promptSha256':digest(task['prompt'])},True)
    with LOCK:active[arm+'/'+tid]={'arm':arm,'id':tid,'startedEpoch':start}
    record={'arm':arm,'id':tid,'category':task['category'],'subtask':task['subtask'],'choiceCount':task['choiceCount'],'promptSha256':digest(task['prompt']),
        'startedEpoch':start,'deadlineEpoch':deadline,'solverValid':True}
    answer=''
    try:
        if arm=='baseline':
            response=client.call(tid+'/baseline/sample-0','solve',{'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':task['prompt']}]},deadline)
            answer=response['choices'][0]['message'].get('content') or ''
            record.update(finishReason=response['choices'][0]['finish_reason'],nativeModelRequests=1)
        else:
            n=native(task,directory,server,token);answer=n.pop('answer');record.update(n)
            if n.get('error') and not any(x in n['error'] for x in ['OriginalSolveDeadline','OriginalDeadlineExhausted','BudgetEnded','JudgeWaitExceededOriginalSolveDeadline']):record['solverValid']=False
        record['solverEndedEpoch']=time.time()
    except Exception as e:
        record.update(solverEndedEpoch=time.time(),solverValid=isinstance(e,BudgetEnded),error=type(e).__name__+':'+str(e))
    # A transport/response failure cannot disappear behind the native deadline label.
    callroot=OUT/'calls/solve'/tid/arm
    failedhomes={p.parent.parent for p in callroot.glob('**/dispatch.json') if not (p.parent.parent/'complete.json').exists()}
    if any(any((p.parent/'receipt.json').exists() and read(p.parent/'receipt.json').get('error') for p in h.glob('attempt-*/dispatch.json')) for h in failedhomes):
        record['solverValid']=False
        record['transportIncomplete']=True
    record.update(answer=answer,candidateSha256=digest(answer),frozenAtUtc=now(),solverWallSeconds=record['solverEndedEpoch']-start)
    if arm=='objrun' and tid in CFG.get('canaryTransportRecovery',{}):
        recovery=CFG['canaryTransportRecovery'][tid]
        record.update(transportRecovery=recovery,cumulativeSolveSeconds=record['solverWallSeconds']+recovery['consumedSolveSeconds'],
                      recoveryWallGapSeconds=start-recovery['originalSolverEndedEpoch'])
    (directory/'final-answer.txt').write_text(answer,encoding='utf-8')
    save(directory/'frozen-candidate.json',{'arm':arm,'id':tid,'candidateSha256':digest(answer),'answer':answer,'atUtc':now()},True)
    try:
        key=judge.enqueue(tid,answer);g,wait=judge.wait(key)
        record.update(grade=g,postSolveJudgeWaitSeconds=wait)
    except Exception as e:record['grade']={'valid':False,'outcome':'grader_error','error':str(e)}
    record.update(completedAtUtc=now(),totalWallSeconds=time.time()-start)
    save(dest,record,True)
    with LOCK:
        active.pop(arm+'/'+tid,None)
        if record['solverValid'] and record['grade'].get('valid'):consecutive_faults=0
        else:
            save(OUT/'exceptions'/arm/(tid+'.json'),record,True);consecutive_faults+=1
            if consecutive_faults>=3:fatal='ThreeConsecutiveInfrastructureFailures'
    status()
    print(json.dumps({'arm':arm,'id':tid,'valid':record['solverValid'] and record['grade']['valid'],'passed':record['grade'].get('passed'),'seconds':record['solverWallSeconds']}),flush=True)
    return record

def run_jobs(jobs,judge,server,token):
    # Bounded admission: futures are admitted only as slots become free.
    iterator=iter(jobs)
    with futures.ThreadPoolExecutor(max_workers=CFG['taskConcurrency']) as pool:
        pending=set()
        while True:
            while len(pending)<CFG['taskConcurrency'] and not fatal and not client.stop:
                try:task,arm=next(iterator)
                except StopIteration:break
                dest=OUT/'results'/arm/(task['id']+'.json')
                if dest.exists():
                    existing=read(dest)
                    if not (existing['solverValid'] and existing['grade'].get('valid')):raise Fault('ExistingInvalidResultRequiresInspection')
                    continue
                pending.add(pool.submit(solve,task,arm,judge,server,token))
            if not pending:break
            done,pending=futures.wait(pending,return_when=futures.FIRST_COMPLETED)
            for f in done:f.result()

def main():
    global stage,client,fatal
    OUT.mkdir(parents=True,exist_ok=True)
    lock=(OUT/'controller.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    judge=None;server=None
    try:
        if (OUT/'execution-started.json').exists():raise Fault('ExistingExecutionRequiresInspectionNoRelaunch')
        frozen(True)
        if not read(OUT/'controls.json')['allPassed']:raise Fault('ZeroModelAcceptanceNotPassed')
        save(OUT/'execution-started.json',{'atUtc':now(),'pid':os.getpid()},True)
        client=OpenRouter();client.observe();judge=Judge(book);token=secrets.token_hex(32);server=broker(client,judge,token)
        threading.Thread(target=heartbeat,daemon=True).start()
        canaryIds=read(ROOT/'data/source.json')['canaryIds'];canarySet=set(canaryIds)
        canary=[r for r in public if r['id'] in canarySet]
        stage='canary';status();run_jobs([(r,a) for n,r in enumerate(canary) for a in CFG['arms'][n%2:]+CFG['arms'][:n%2]],judge,server,token)
        records=[read(OUT/'results'/a/(i+'.json')) for i in canaryIds for a in CFG['arms'] if (OUT/'results'/a/(i+'.json')).exists()]
        passed=len(records)==40 and all(r['solverValid'] and r['grade'].get('valid') for r in records)
        nativeRecords=[r for r in records if r['arm']=='objrun']
        submitted=sum(r.get('candidateHow')=='submitted' for r in nativeRecords)
        passed=passed and submitted>0 and all(r.get('nativeModelRequests',0)>0 for r in nativeRecords)
        save(OUT/'canary.json',{'allPassed':passed,'ids':canaryIds,'records':records,'realSubmissions':submitted,'gate':'valid transport/grading/native execution and at least one real submission; answer accuracy is not an acceptance threshold'},True)
        if not passed:raise Fault('TwentyQuestionCanaryAcceptanceFailed')
        frozen(True);stage='formal';save(OUT/'formal-started.json',{'atUtc':now(),'canaryRecords':40},True);status()
        rest=[r for r in public if r['id'] not in canarySet]
        run_jobs([(r,a) for n,r in enumerate(rest) for a in CFG['arms'][n%2:]+CFG['arms'][:n%2]],judge,server,token)
        if fatal or client.stop:raise Fault(fatal or client.stop)
        stage='finalizing';status()
    except Exception as e:fatal=type(e).__name__+':'+str(e);stage='needs_attention'
    finally:
        if server:server.shutdown()
        if judge:judge.pool.shutdown(wait=True)
        status()
    if stage=='finalizing':
        frozen(True)
        subprocess.run([sys.executable,str(ROOT/'package/report.py')],check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        audit=read(OUT/'AUDIT.json');rows=[read(p) for p in (OUT/'results').glob('*/*.json')]
        stage=('complete' if all(r['solverValid'] and r['grade'].get('valid') for r in rows) else 'complete_with_exceptions') if audit['allPassed'] else 'needs_attention'
        save(OUT/'final-freeze.json',{'atUtc':now(),'count':len(rows),'auditPassed':audit['allPassed']},True);status()

if __name__=='__main__':main()
