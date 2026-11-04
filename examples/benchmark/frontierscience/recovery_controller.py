"""Exactly one independently budgeted recovery round; original package is read-only."""
from pathlib import Path
import concurrent.futures as futures
import fcntl
import json
import os
import secrets
import subprocess
import threading
import time
from protocol import PROTOCOL_SHA, PARAMETERS, digest
from runtime import ROOT,OUT,CFG,LOCK,DeepSeek,Judge,Fault,broker,read,save,now,accounting,wire,parse_grade
from recovery_guard import guard

stage='starting';active={};fatal=None;client=None

def pins():
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for top in ['package','data'] for p in (ROOT/top).rglob('*')
            if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts}

def frozen():
    for rel,sha in read(OUT/'source-pins.json')['files'].items():
        if digest((ROOT/rel).read_bytes())!=sha:raise Fault('RecoverySourceChanged:'+rel)

def status():
    rows=[read(p) for p in (OUT/'results').glob('*/*.json')]
    finals=[read(p) for p in (OUT/'final-results').glob('*/*.json')]
    save(OUT/'status.json',{'stage':stage,'pid':os.getpid(),'root':str(ROOT),'atUtc':now(),'active':list(active.values()),'fatal':fatal,
                          'completed':len(rows),'finalCompleted':len(finals),'finalValid':sum(x['solverValid'] and x['grade'].get('valid',False) for x in finals),
                          'remainingExceptions':[{'arm':x['arm'],'id':x['id']} for x in finals if not x['solverValid'] or not x['grade'].get('valid')],
                          **client.metrics(),'accounting':accounting()})

def heartbeat():
    while stage not in {'complete','complete_with_exceptions','needs_attention'}:
        try:status()
        except Exception:pass
        time.sleep(10)

def native(task,directory,deadline,server,token,fixture=False):
    directory.mkdir(parents=True,exist_ok=True)
    # This is the entire solver-visible spec: no original answers, grades or private fields.
    spec={'task':{'id':task['id'],'problem':task['problem']},'directory':str(directory),'deadlineEpoch':deadline,'fixture':fixture,'run':CFG['run']}
    save(directory/'input.json',spec,True)
    env={'PATH':str(ROOT/'bin')+':/usr/bin:/bin','HOME':str(ROOT/'runtime-home'),'NO_PROXY':'127.0.0.1,localhost',
         'FRONTIER_BROKER_URL':'http://127.0.0.1:'+str(server.server_port),'FRONTIER_BROKER_TOKEN':token}
    with (directory/'worker.stdout.log').open('ab') as stdout,(directory/'worker.stderr.log').open('ab') as stderr:
        cmd=[str(ROOT/'bin/bun'),str(ROOT/'package/native.ts'),str(directory/'input.json')]
        child=subprocess.Popen(cmd,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
        save(directory/'worker-process.json',{'pid':child.pid,'cmdline':cmd,'atUtc':now()},True)
        try:child.wait(timeout=max(1,deadline-time.time())+15)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            p=directory/'engine-process.json'
            if p.exists():
                info=read(p);cmdfile=Path('/proc')/str(info['pid'])/'cmdline'
                if cmdfile.exists() and str(ROOT/'package/engine/app/src/main.ts').encode() in cmdfile.read_bytes():os.kill(info['pid'],15)
    if not (directory/'native-result.json').exists():raise Fault('NativeWorkerMissingResult:'+str(child.returncode))
    return read(directory/'native-result.json')

def main():
    global stage,fatal,client
    OUT.mkdir(parents=True,exist_ok=True)
    lock=(OUT/'controller.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    manifest=read(ROOT/'data/recovery-manifest.json');original=Path(CFG['originalRoot'])
    client=DeepSeek();book={r['task_group_id']:dict(r,id=r['task_group_id']) for r in map(json.loads,(ROOT/'data/test.jsonl').read_text().splitlines())}
    judge=Judge(client,book);token=secrets.token_hex(32);server=broker(client,judge,token)
    try:
        if (OUT/'source-pins.json').exists():raise Fault('RecoveryRoundAlreadyStartedNoAutomaticSecondRound')
        assert manifest['round']==1 and manifest['protocolSha256']==PROTOCOL_SHA==CFG['protocolSha256']
        assert CFG['parameters']==PARAMETERS
        save(OUT/'source-pins.json',{'atUtc':now(),'files':pins()},True)
        save(OUT/'original-freeze.json',guard(original,manifest['originalArchiveSha256']),True)
        stage='controls';status();threading.Thread(target=heartbeat,daemon=True).start();client.observe()
        fixture=native({'id':'recovery-fixture','problem':'What is 2+2? First verify FINAL ANSWER: 5, then submit FINAL ANSWER: 4.'},OUT/'controls/native-fixture',time.time()+60,server,token,True)
        assertions=read(OUT/'controls/native-fixture/fixture-assertions.json')
        checks=manifest['controls']+[{'name':'real-engine-'+k,'passed':v} for k,v in assertions.items()]
        checks.append({'name':'frozen-official-protocol-and-parameters','passed':CFG['parameters']==PARAMETERS and PROTOCOL_SHA==manifest['protocolSha256']})
        probe=OUT/'controls/exclusive-lock-test.json';save(probe,{'round':1},True)
        try:save(probe,{'round':2},True);exclusive=False
        except FileExistsError:exclusive=read(probe)=={'round':1}
        checks.append({'name':'durable-exclusive-lock-rejects-second-round','passed':exclusive})
        checks.append({'name':'official-thinking-cannot-be-disabled','passed':wire({'messages':[{'role':'user','content':'x'}],'thinking':{'type':'disabled'},'temperature':0})==dict(PARAMETERS,messages=[{'role':'user','content':'x'}])})
        for label,response in [('length',{'choices':[{'finish_reason':'length','message':{'content':'GRADE: C'}}]}),('bad-format',{'choices':[{'finish_reason':'stop','message':{'content':'yes'}}]})]:
            try:parse_grade(response);rejected=False
            except Fault:rejected=True
            checks.append({'name':'grading-fault-is-not-wrong-'+label,'passed':rejected})
        checks.append({'name':'original-control-acceptance-inherited','passed':read(original/'outputs/canonical/controls.json')['allPassed']})
        save(OUT/'controls.json',{'allPassed':all(x['passed'] for x in checks),'checks':checks,'originalControlsInherited':read(original/'outputs/canonical/controls.json')['allPassed']},True)
        if not all(x['passed'] for x in checks):raise Fault('RecoveryControlAcceptanceFailed')
        entries=[x for x in manifest['entries'] if x['action'] in {'objrun_once','score_once'}]
        save(OUT/'recovery-locks/round-1.json',{'manifestSha256':digest((ROOT/'data/recovery-manifest.json').read_bytes()),'identities':[x['arm']+'/'+x['id'] for x in entries],'atUtc':now()},True)
        stage='running';status()
        def run(entry):
            arm,tid=entry['arm'],entry['id'];ident=arm+'/'+tid;directory=OUT/'tasks'/arm/tid
            save(OUT/'recovery-locks'/arm/(tid+'.json'),{'round':1,'action':entry['action'],'atUtc':now()},True)
            frozen();start=time.time();deadline=start+entry['extraSolveSeconds']
            with LOCK:active[ident]={'arm':arm,'id':tid,'action':entry['action'],'startedEpoch':start,'deadlineEpoch':deadline,'extraSolveSeconds':entry['extraSolveSeconds']}
            r={'arm':arm,'id':tid,'subject':entry['subject'],'round':1,'action':entry['action'],'extraSolveSeconds':entry['extraSolveSeconds'],
               'startedEpoch':start,'deadlineEpoch':deadline,'originalCandidateSha256':entry['originalCandidateSha256'],'solverValid':True}
            answer=''
            try:
                if entry['action']=='score_once':
                    original_record=read(original/'outputs/canonical/results'/arm/(tid+'.json'))
                    assert original_record['candidateSha256']==entry['originalCandidateSha256']
                    answer=original_record['answer'];r['reusedOriginalCandidate']=True
                    directory.mkdir(parents=True,exist_ok=True)
                    save(directory/'started.json',r,True)
                else:
                    directory.mkdir(parents=True,exist_ok=True);save(directory/'started.json',r,True)
                    n=native(book[tid],directory,deadline,server,token);answer=n.pop('answer');r.update(n)
                    error=n.get('error') or ''
                    boundary_errors=[read(p) for p in (OUT/'calls/solve'/tid/'objrun').glob('*/attempt-*/receipt.json') if read(p).get('error')]
                    boundary=bool(time.time()>=deadline and boundary_errors and all(abs(z['endedEpoch']-deadline)<2 for z in boundary_errors))
                    r['solverValid']=not error or any(x in error for x in ['OriginalSolveDeadline','OriginalDeadlineExhausted','BudgetEnded','JudgeWaitExceededOriginalSolveDeadline']) or boundary
                    r['budgetBoundaryAudited']=boundary
                r['solverEndedEpoch']=time.time()
            except Exception as e:
                r['solverEndedEpoch']=time.time();r['solverValid']=False;r['error']=type(e).__name__+':'+str(e)
            r.update(answer=answer,candidateSha256=digest(answer),frozenAtUtc=now(),solverWallSeconds=r['solverEndedEpoch']-start)
            (directory/'final-answer.txt').write_text(answer,encoding='utf-8')
            save(directory/'frozen-candidate.json',{'arm':arm,'id':tid,'answer':answer,'candidateSha256':digest(answer),'atUtc':now()},True)
            save(OUT/'results'/arm/(tid+'.json'),r,True)
            if not r['solverValid']:save(OUT/'exceptions/recovery'/arm/(tid+'.json'),r,True)
            with LOCK:active.pop(ident,None)
            return r
        with futures.ThreadPoolExecutor(max_workers=32) as pool:records=list(pool.map(run,entries))
        # All recovery candidates are immutable before any blind final request begins.
        save(OUT/'final-freeze.json',{'atUtc':now(),'candidates':[{'arm':r['arm'],'id':r['id'],'sha256':r['candidateSha256']} for r in records]},True)
        stage='final_regrade';status()
        def regrade(r):
            arm,tid=r['arm'],r['id'];f=read(OUT/'tasks'/arm/tid/'frozen-candidate.json')
            assert f['candidateSha256']==r['candidateSha256']==digest(f['answer'])
            key=judge.enqueue(tid,f['answer'],'final','recovery-round-1/'+arm+'/'+tid)
            g,wait=judge.wait(key)
            final={'arm':arm,'id':tid,'subject':r['subject'],'round':1,'action':r['action'],'extraSolveSeconds':r['extraSolveSeconds'],
                   'solverValid':r['solverValid'],'candidateSha256':f['candidateSha256'],'grade':g,'seconds':wait,'atUtc':now()}
            save(OUT/'final-results'/arm/(tid+'.json'),final,True)
            if not g.get('valid'):save(OUT/'exceptions/recovery-grading'/arm/(tid+'.json'),final,True)
            return final
        with futures.ThreadPoolExecutor(max_workers=8) as pool:finals=list(pool.map(regrade,records))
        frozen();judge.pool.shutdown(wait=True)
        save(OUT/'SUMMARY.json',{'originalArchiveSha256':manifest['originalArchiveSha256'],'recovery':finals,'accounting':accounting(),
                                'applyingRule':manifest['selectionRule'],'originalNotOverwritten':True},True)
        stage='complete' if all(r['solverValid'] and r['grade'].get('valid') for r in finals) else 'complete_with_exceptions'
    except Exception as e:
        stage='needs_attention';fatal=type(e).__name__+':'+str(e);save(OUT/'fatal.json',{'atUtc':now(),'error':fatal},True)
    finally:
        judge.pool.shutdown(wait=True);status();server.shutdown();fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=='__main__':main()
