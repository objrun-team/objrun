"""One owned controller: control acceptance -> formal canary -> 200 tasks -> blind regrade."""
from pathlib import Path
import concurrent.futures as futures
import fcntl
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from protocol import CONTROLS, PARAMETERS, PROTOCOL_SHA, digest, judge_messages
from runtime import ROOT,OUT,CFG,LOCK,DeepSeek,Judge,Fault,BudgetEnded,broker,read,save,now,accounting,parse_grade,wire

OUT.mkdir(parents=True,exist_ok=True)
client=DeepSeek()
official=[json.loads(line) for line in (ROOT/'data/test.jsonl').read_text().splitlines() if line.strip()]
assert len(official)==100 and len({r['task_group_id'] for r in official})==100
book={r['task_group_id']:dict(r,id=r['task_group_id']) for r in official}
for name,problem,answer,candidate,passed in CONTROLS:book['control-'+name]={'id':'control-'+name,'problem':problem,'answer':answer,'subject':'control'}
judge=Judge(client,book);token=secrets.token_hex(32);server=broker(client,judge,token)
stage='starting';active={};fatal=None

def pins():
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for top in ['package','data'] for p in (ROOT/top).rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts and p.name!='source-pins.json'}
def frozen():
    for rel,sha in read(OUT/'source-pins.json')['files'].items():
        if digest((ROOT/rel).read_bytes())!=sha:raise Fault('SourceChanged:'+rel)
def status():
    records=[read(p) for p in (OUT/'results').glob('*/*.json')]
    final=[read(p) for p in (OUT/'final-results').glob('*/*.json')]
    save(OUT/'status.json',{'stage':stage,'pid':os.getpid(),'root':str(ROOT),'atUtc':now(),'active':list(active.values()),'fatal':fatal,
         'arms':{a:{'total':100,'completed':sum(r['arm']==a for r in records),'validOnline':sum(r['arm']==a and r.get('onlineGrade',{}).get('valid',False) for r in records),'onlinePassed':sum(r['arm']==a and r.get('onlineGrade',{}).get('valid',False) and r['onlineGrade'].get('passed',False) for r in records),'finalCompleted':sum(r['arm']==a for r in final),'finalValid':sum(r['arm']==a and r.get('grade',{}).get('valid',False) and r.get('solverValid',False) for r in final),'finalPassed':sum(r['arm']==a and r.get('solverValid',False) and r.get('grade',{}).get('passed',False) for r in final),'exceptions':sum(r['arm']==a and not r.get('solverValid',False) for r in records)} for a in CFG['arms']},
         **client.metrics(),'accounting':accounting()})
def heartbeat():
    while stage not in {'complete','complete_with_exceptions','needs_attention'}:
        try:status()
        except Exception:pass
        time.sleep(10)

def native(task,directory,deadline,fixture=False):
    directory.mkdir(parents=True,exist_ok=True)
    spec={'task':{'id':task['id'],'problem':task['problem']},'directory':str(directory),'deadlineEpoch':deadline,'fixture':fixture,'run':CFG['run']}
    save(directory/'input.json',spec,True)
    env={'PATH':str(ROOT/'bin')+':/usr/bin:/bin','HOME':str(ROOT/'runtime-home'),'NO_PROXY':'127.0.0.1,localhost',
         'FRONTIER_BROKER_URL':'http://127.0.0.1:'+str(server.server_port),'FRONTIER_BROKER_TOKEN':token}
    with (directory/'worker.stdout.log').open('ab') as stdout,(directory/'worker.stderr.log').open('ab') as stderr:
        child=subprocess.Popen([str(ROOT/'bin/bun'),str(ROOT/'package/native.ts'),str(directory/'input.json')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
        save(directory/'worker-process.json',{'pid':child.pid,'cmdline':[str(ROOT/'bin/bun'),str(ROOT/'package/native.ts'),str(directory/'input.json')],'atUtc':now()},True)
        try:child.wait(timeout=max(1,deadline-time.time())+15)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            # Any remaining engine is owned by this task only.
            p=directory/'engine-process.json'
            if p.exists():
                info=read(p);cmd=Path('/proc')/str(info['pid'])/'cmdline'
                if cmd.exists() and str(ROOT/'package/engine/app/src/main.ts').encode() in cmd.read_bytes():os.kill(info['pid'],15)
    if not (directory/'native-result.json').exists():raise Fault('NativeWorkerMissingResult:exit='+str(child.returncode))
    return read(directory/'native-result.json')

def controls():
    result=[]
    def check(name,ok,**extra):result.append({'name':name,'passed':bool(ok),**extra})
    control_jobs=[(case,judge.enqueue('control-'+case[0],case[3],'controls',case[0])) for case in CONTROLS]
    for case,key in control_jobs:
        name,problem,answer,candidate,expected=case
        g,wait=judge.wait(key)
        check('judge-'+name,g.get('valid') and g.get('passed')==expected,decision=g,seconds=wait)
    for bad in [
        {'choices':[{'finish_reason':'stop','message':{'content':'yes','reasoning_content':'GRADE: C'}}]},
        {'choices':[{'finish_reason':'length','message':{'content':'GRADE: C'}}]}]:
        try:parse_grade(bad);ok=False
        except Fault:ok=True
        check('invalid-grader-output-'+str(len(result)),ok)
    check('effective-parameters',wire({'messages':[{'role':'user','content':'x'}],'temperature':0,'provider':{'only':['wrong']},'thinking':{'type':'disabled'}})==dict(PARAMETERS,messages=[{'role':'user','content':'x'}]))
    # Concurrency identity check: all simultaneous calls resolve to the same persistent job.
    with futures.ThreadPoolExecutor(max_workers=16) as pool:
        keys=list(pool.map(lambda _:judge.enqueue('control-algebra',CONTROLS[0][3],'controls','algebra'),range(16)))
    check('concurrent-judge-dedup',len(set(keys))==1)
    tools=[{'type':'function','function':{'name':'control_echo','description':'Return the supplied word.','parameters':{'type':'object','properties':{'word':{'type':'string'}},'required':['word'],'additionalProperties':False}}}]
    messages=[{'role':'user','content':'Call control_echo exactly once with word="frontier-control". After receiving the tool result, reply DONE.'}]
    first=client.call('tool-compat-1','controls',{'messages':messages,'tools':tools},time.time()+600)
    msg=first['choices'][0]['message'];calls=msg.get('tool_calls') or []
    check('official-thinking-tool-call',bool(calls) and bool(msg.get('reasoning_content')))
    if calls:
        messages.append(msg)
        for call in calls:messages.append({'role':'tool','tool_call_id':call['id'],'content':'frontier-control'})
        second=client.call('tool-compat-2','controls',{'messages':messages,'tools':tools},time.time()+600)
        check('official-thinking-tool-history',bool(second['choices'][0]['message'].get('content')) and messages[1].get('reasoning_content')==msg.get('reasoning_content'))
    fixture=native({'id':'native-fixture','problem':'What is 2+2? First verify FINAL ANSWER: 5, then submit FINAL ANSWER: 4.'},OUT/'controls/native-fixture',time.time()+60,True)
    assertions=read(OUT/'controls/native-fixture/fixture-assertions.json')
    for name,ok in assertions.items():check('real-engine-'+name,ok)
    # Auth failures are HTTP errors and never valid False judgments.
    import urllib.request,urllib.error
    try:
        urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/jobs/nonexistent',timeout=5);ok=False
    except urllib.error.HTTPError as e:ok=e.code==403
    check('private-broker-auth',ok)
    save(OUT/'controls.json',{'protocolSha256':PROTOCOL_SHA,'allPassed':all(x['passed'] for x in result),'checks':result,'atUtc':now()},True)
    if not all(x['passed'] for x in result):raise Fault('ControlAcceptanceFailed')

def solve(task,arm):
    tid=task['id'];dest=OUT/'results'/arm/(tid+'.json');directory=OUT/'tasks'/arm/tid
    if dest.exists():return read(dest)
    frozen();start=time.time();deadline=start+600
    directory.mkdir(parents=True,exist_ok=True)
    save(directory/'started.json',{'arm':arm,'id':tid,'startedAtUtc':now(),'startedEpoch':start,'deadlineEpoch':deadline,'promptSha256':digest(task['problem'])},True)
    with LOCK:active[arm+'/'+tid]={'arm':arm,'id':tid,'startedEpoch':start,'deadlineEpoch':deadline}
    record={'arm':arm,'id':tid,'subject':task['subject'],'promptSha256':digest(task['problem']),'startedEpoch':start,'deadlineEpoch':deadline,'solverValid':True}
    answer=''
    try:
        if arm=='baseline':
            response=client.call(tid+'/baseline/sample-0','solve',{'messages':[{'role':'user','content':task['problem']}]},deadline)
            answer=response['choices'][0]['message'].get('content') or ''
            record['finishReason']=response['choices'][0]['finish_reason'];record['nativeModelRequests']=1
        else:
            n=native(task,directory,deadline);answer=n.pop('answer');record.update(n)
            # Reaching the fixed task wall is a budget stop; API/grader faults are exceptions.
            if n.get('error') and not any(x in n['error'] for x in ['OriginalSolveDeadline','OriginalDeadlineExhausted','BudgetEnded','JudgeWaitExceededOriginalSolveDeadline']):record['solverValid']=False
        record['solverEndedEpoch']=time.time()
    except Exception as e:
        record['solverEndedEpoch']=time.time();record['solverValid']=isinstance(e,BudgetEnded);record['error']=type(e).__name__+':'+str(e)
        save(OUT/'exceptions/original'/arm/(tid+'.json'),{'record':record,'atUtc':now()},True)
    record.update(answer=answer,candidateSha256=digest(answer),frozenAtUtc=now(),solverWallSeconds=record['solverEndedEpoch']-start)
    (directory/'final-answer.txt').write_text(answer,encoding='utf-8')
    save(directory/'frozen-candidate.json',{'arm':arm,'id':tid,'candidateSha256':digest(answer),'answer':answer,'atUtc':now()},True)
    try:
        key=judge.enqueue(tid,answer,'online');g,wait=judge.wait(key)
        record['onlineGrade']=g;record['postSolveJudgeWaitSeconds']=wait
    except Exception as e:record['onlineGrade']={'valid':False,'outcome':'grader_error','error':str(e)}
    record['completedAtUtc']=now();record['totalWallSeconds']=time.time()-start
    save(dest,record,True)
    if not record['solverValid'] or not record['onlineGrade'].get('valid'):
        p=OUT/'exceptions/original'/arm/(tid+'.json')
        if not p.exists():save(p,record,True)
    with LOCK:active.pop(arm+'/'+tid,None)
    return record

def final_regrade(record):
    arm,tid=record['arm'],record['id'];p=OUT/'final-results'/arm/(tid+'.json')
    if p.exists():return
    f=read(OUT/'tasks'/arm/tid/'frozen-candidate.json')
    if f['candidateSha256']!=digest(record['answer']) or f['answer']!=record['answer']:raise Fault('FrozenCandidateMismatch')
    key=judge.enqueue(tid,f['answer'],'final',arm+'/'+tid)
    grade,wait=judge.wait(key)
    save(p,{'arm':arm,'id':tid,'subject':record['subject'],'candidateSha256':f['candidateSha256'],'solverValid':record['solverValid'],
            'grade':grade,'onlineGrade':record['onlineGrade'],'onlineFinalDisagree':bool(grade.get('valid') and record['onlineGrade'].get('valid') and grade['passed']!=record['onlineGrade']['passed']),
            'seconds':wait,'atUtc':now()},True)

def main():
    global stage,fatal
    lock=(OUT/'controller.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        if (OUT/'source-pins.json').exists():raise Fault('ExistingRunRequiresExplicitBoundedRecovery')
        save(OUT/'source-pins.json',{'atUtc':now(),'files':pins()},True)
        stage='preflight';status();client.observe()
        threading.Thread(target=heartbeat,daemon=True).start()
        stage='controls';status();controls();frozen()
        ids=read(ROOT/'data/source.json')['canaryIds']
        jobs=[(book[tid],arm) for tid in ids for arm in CFG['arms']]
        stage='formal_canary';status()
        with futures.ThreadPoolExecutor(max_workers=32) as pool:
            canary=list(pool.map(lambda job:solve(*job),jobs))
        save(OUT/'canary.json',canary,True)
        if any(not r['solverValid'] or not r['onlineGrade'].get('valid') for r in canary):raise Fault('FormalCanaryInvalid')
        stage='running';status()
        jobs=[(book[r['task_group_id']],arm) for i,r in enumerate(official) if r['task_group_id'] not in ids for arm in (CFG['arms'] if i%2==0 else list(reversed(CFG['arms'])))]
        def run_job(job):
            if client.stop:return None
            return solve(*job)
        with futures.ThreadPoolExecutor(max_workers=32) as pool:
            for result in pool.map(run_job,jobs):pass
        records=[read(p) for p in (OUT/'results').glob('*/*.json')]
        if len(records)!=200:raise Fault('Incomplete200:'+str(len(records))+':'+str(client.stop))
        frozen();save(OUT/'final-freeze.json',{'atUtc':now(),'count':len(records),'candidates':[{'arm':r['arm'],'id':r['id'],'sha256':r['candidateSha256']} for r in records]},True)
        stage='final_regrade';status()
        with futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(final_regrade,records))
        frozen()
        subprocess.run([sys.executable,str(ROOT/'package/report.py'),str(ROOT)],check=True,timeout=120)
        finals=[read(p) for p in (OUT/'final-results').glob('*/*.json')]
        stage='complete' if len(finals)==200 and all(r['solverValid'] and r['grade'].get('valid') for r in finals) else 'complete_with_exceptions'
    except Exception as e:
        stage='needs_attention';fatal=type(e).__name__+':'+str(e)
        save(OUT/'fatal.json',{'atUtc':now(),'error':fatal},True)
    finally:
        # Do not orphan paid requests: drain the owned judge queue before terminal state.
        judge.pool.shutdown(wait=True);status();server.shutdown()
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=='__main__':main()
