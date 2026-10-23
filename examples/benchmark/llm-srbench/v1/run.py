"""Four-arm release240 supervisor: sealed test data, canary gate, durable cells."""
import concurrent.futures,json,os,pathlib,signal,socket,subprocess,threading,time,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import common
from common import ROOT,OUT,CFG,save,durable,digest,accounting,TaskBudgetStop,AccountStop
CATALOG=json.loads((ROOT/'data/public/catalog.json').read_text());MANIFEST=json.loads((ROOT/'data/manifest.json').read_text());ARMS=['baseline','objrun','independent','binary'];LOCK=common.LOCK
STATE={'stage':'starting','pid':os.getpid(),'active':[],'stopReason':None};GRADER=None;GRADER_URL='';STOP=common.HALT
def utc():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def freeport():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def post(url,v):
    import urllib.request
    req=urllib.request.Request(url,data=json.dumps(v).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
def get(url):
    import urllib.request
    with urllib.request.urlopen(url,timeout=10) as r:return json.load(r)
def grade(task,answer):
    job=post(GRADER_URL+'/fit',{'key':task['key'],'answer':answer})['job']
    while True:
        r=get(GRADER_URL+'/job/'+job)
        if r['state']=='done':
            if not r['grade']['valid']:raise RuntimeError('GraderInfrastructure:'+r['grade'].get('errorType','unknown'))
            return r['grade']
        if r['state']=='fault':raise RuntimeError('GraderInfrastructure:'+r['error'])
        if GRADER.poll() is not None:raise RuntimeError('GraderProcessExited')
        time.sleep(.2)
def all_results():return [json.loads(p.read_text()) for p in (OUT/'tasks').glob('*/*/result.json')]
def status():
    with LOCK:
        rr=all_results();STATE['updatedAtUtc']=utc();STATE['completed']=len(rr);STATE['arms']={a:{'completed':sum(r['arm']==a for r in rr),'valid':sum(r['arm']==a and r['valid'] for r in rr)} for a in ARMS};STATE.update(accounting(OUT/'tasks'))
        save(OUT/'status.json',STATE)
        (OUT/'RUNNING.md').write_text('# LLM-SRBench 发布版 240 题\n\n阶段：'+STATE['stage']+'\n\n'+json.dumps({k:STATE[k] for k in ['pid','completed','arms','actualCostUsd','unknownCostCount','stopReason']},ensure_ascii=False,indent=2)+'\n\n服务器 novaeve；入口 package/run.py。四组共960条记录，10题四组技术试跑通过后自动继续。ID/OOD在全部候选冻结后评分。\n')
class Gateway:
    def __init__(self,task,arm,directory):
        self.task=task;self.arm=arm;self.d=directory;self.events=[];self.error=None;self.counter=0;self.guard=threading.RLock();self.pending={}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def reply(self,v,status=200,raw=False):
                b=v.encode() if raw else json.dumps(v,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Length',str(len(b)));self.send_header('Content-Type','application/json');self.end_headers()
                try:self.wfile.write(b)
                except BrokenPipeError:pass
            def do_POST(self):
                try:
                    q=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path=='/model':
                        logical='native-'+digest(common.wire(q['body']))
                        v=common.call(owner.d,logical,q['body'],q.get('remainingSeconds',600));self.reply(v);return
                    if self.path=='/feedback':
                        assert q['key']==task['key'] and q['arm']==arm
                        with owner.guard:
                            if owner.counter>=5:raise TaskBudgetStop('FiveCandidateCeiling')
                            owner.counter+=1;index=owner.counter;token=digest({'index':index,'answer':q['answer']})
                            owner.pending[token]=FEEDBACK_POOL.submit(owner.feedback,index,q['answer'])
                        self.reply({'job':token});return
                    self.reply({'error':'UnknownPath'},404)
                except Exception as e:
                    owner.error=e
                    if isinstance(e,AccountStop):STATE['stopReason']=str(e);STOP.set()
                    self.reply({'error':type(e).__name__+':'+str(e)},402 if isinstance(e,TaskBudgetStop) else 503)
            def do_GET(self):
                token=self.path.rsplit('/',1)[-1];f=owner.pending.get(token)
                if f is None:self.reply({'state':'fault','error':'UnknownJob'},404);return
                if not f.done():self.reply({'state':'pending'});return
                try:self.reply({'state':'done','projected':f.result()})
                except Exception as e:owner.error=e;self.reply({'state':'fault','error':str(e)},503)
        self.service=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.service.daemon_threads=True
        self.thread=threading.Thread(target=self.service.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.service.server_port)
    def feedback(self,index,answer):
        from grader import project
        r=grade(self.task,answer);exposed=project(r,self.arm)
        with self.guard:
            self.events.append({'index':index,'answer':answer,'candidateSha256':digest(answer),'grade':r,'exposed':exposed,'atUtc':utc()});save(self.d/'feedback.json',self.events)
        return exposed
    def close(self):self.service.shutdown();self.service.server_close()
FEEDBACK_POOL=concurrent.futures.ThreadPoolExecutor(max_workers=4)
def execute(task,arm):
    d=OUT/'tasks'/arm/task['key'];rp=d/'result.json'
    if rp.exists():return json.loads(rp.read_text())
    if STOP.is_set():return {'id':task['id'],'key':task['key'],'arm':arm,'valid':False,'modelCalls':0,'accountedUpperBoundUsd':0,'error':'CampaignStoppedBeforeDispatch'}
    with LOCK:STATE['active'].append({'id':task['id'],'arm':arm});status()
    record={'id':task['id'],'key':task['key'],'subset':task['subset'],'arm':arm,'publicInputSha256':task['publicSha256'],'startedAtUtc':utc(),'valid':False,'answer':''};beg=time.monotonic()
    try:
        d.mkdir(parents=True,exist_ok=True)
        if arm in ['objrun','binary']:
            if (d/'native-start.json').exists():raise RuntimeError('InterruptedNativeCellRequiresAuditNoAutomaticRegeneration')
            durable(d/'native-start.json',{'atUtc':utc(),'ownerPid':os.getpid()});gateway=Gateway(task,arm,d)
            env={'PATH':str(ROOT/'bin')+':'+str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':'local-proxy-no-provider-credential','NO_PROXY':'127.0.0.1,localhost','BUN_INSTALL_CACHE_DIR':str(ROOT/'setup/bun-cache')}
            try:
                with (d/'native.stdout.log').open('wb') as out,(d/'native.stderr.log').open('wb') as err:
                    p=subprocess.Popen([str(ROOT/'bin/bun'),str(ROOT/'package/native.ts')],stdin=subprocess.PIPE,stdout=out,stderr=err,env=env,cwd=ROOT,start_new_session=True)
                    save(d/'native-process.json',{'pid':p.pid,'ownerPid':os.getpid(),'entry':str(ROOT/'package/native.ts')})
                    try:p.communicate(json.dumps({'task':task,'arm':arm,'directory':str(d/'native'),'gateway':gateway.url,'model':CFG['model']}).encode(),timeout=720)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=20);raise RuntimeError('NativeControllerTimeout')
                nr=json.loads((d/'native/native-result.json').read_text());record['native']=nr;record['answer']=nr.get('answer','');record['feedbackCount']=len(gateway.events)
                if gateway.error and not isinstance(gateway.error,TaskBudgetStop):raise gateway.error
                if nr.get('error'):raise RuntimeError('NativeEngine:'+nr['error'])
                record['stoppingReason']=str(gateway.error) if gateway.error else nr.get('stopReason') or 'native_finished'
            finally:gateway.close()
            record['trainingGrade']=grade(task,record['answer']);record['valid']=True
        else:
            samples=json.loads((d/'samples.json').read_text()) if (d/'samples.json').exists() else []
            limit=1 if arm=='baseline' else 5
            while len(samples)<limit and not STOP.is_set() and not (samples and samples[-1]['grade']['passed']):
                index=len(samples)
                try:v=common.call(d,'sample-'+str(index),{'messages':[{'role':'user','content':task['prompt']}]})
                except TaskBudgetStop:record['stoppingReason']='task_dollar_cap';break
                msg=v['choices'][0]['message'];answer=msg.get('content') or '';r=grade(task,answer)
                samples.append({'index':index,'answer':answer,'candidateSha256':digest(answer),'grade':r,'cumulativeCost':accounting(d),'finishReason':v['choices'][0].get('finish_reason'),'atUtc':utc()});save(d/'samples.json',samples)
            record['answer']=samples[-1]['answer'] if samples else '';record['sampleCount']=len(samples);record['trainingGrade']=samples[-1]['grade'] if samples else grade(task,'');record['valid']=True
            record.setdefault('stoppingReason','first_training_pass' if samples and samples[-1]['grade']['passed'] else 'candidate_ceiling')
        (d/'final-answer.txt').write_text(record['answer'],encoding='utf8');record['finalCandidateSha256']=digest(record['answer'])
        save(d/'candidate-freeze.json',{'answerSha256':record['finalCandidateSha256'],'atUtc':utc(),'selection':'real finalCandidate' if arm in ['objrun','binary'] else 'first training pass else last','idOodAccessed':False})
    except Exception as e:
        record['error']=type(e).__name__+':'+str(e);record['traceback']=traceback.format_exc()
        if isinstance(e,AccountStop):STATE['stopReason']=str(e);STOP.set()
    record.update(accounting(d));record.update(completedAtUtc=utc(),wallSeconds=time.monotonic()-beg);save(rp,record)
    with LOCK:STATE['active']=[x for x in STATE['active'] if not (x['id']==task['id'] and x['arm']==arm)];status()
    print(json.dumps({k:record.get(k) for k in ['id','arm','valid','actualCostUsd','sampleCount','error']},ensure_ascii=False),flush=True)
    return record
def sourcepins():
    import hashlib
    return [{'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((ROOT/'package').rglob('*')) if p.is_file() and p.name!='.env' and '__pycache__' not in p.parts and 'node_modules' not in p.parts]
def cost_snapshots(records):
    for record in records:
        d=OUT/'tasks'/record['arm']/record['key'];points={}
        for budget in [.025,.05,.1]:
            answer='';how='none'
            if record['valid'] and record['arm'] in ['objrun','binary']:
                dispatches=[]
                for p in (d/'calls').rglob('dispatch.json'):
                    dispatch=json.loads(p.read_text());rp=p.parent/'receipt.json';receipt=json.loads(rp.read_text()) if rp.exists() else {}
                    value=receipt.get('actualCostUsd');value=value if value is not None else dispatch['reservedUpperBoundUsd'];dispatches.append((dispatch['dispatchAtMs'],value))
                spent=0;cutoff=int(time.time()*1000)
                for at,value in sorted(dispatches):
                    if spent+value>budget+1e-12:cutoff=at-1;break
                    spent+=value
                q={'db':str(d/'native/engine/data/h2h.sqlite'),'taskId':'llm-srbench-240/'+record['key'],'cutoffMs':cutoff}
                p=subprocess.run([str(ROOT/'bin/bun'),str(ROOT/'package/snapshot.ts')],input=json.dumps(q),capture_output=True,text=True,timeout=20,env={'PATH':str(ROOT/'bin')+':/usr/bin:/bin'})
                if p.returncode:raise RuntimeError('CostSnapshotSelector:'+p.stderr[-500:])
                selected=json.loads(p.stdout);answer=selected['answer'];how=selected['candidateHow']
            elif record['valid']:
                samples=json.loads((d/'samples.json').read_text()) if (d/'samples.json').exists() else []
                eligible=[s for s in samples if s['cumulativeCost']['accountedUpperBoundUsd']<=budget+1e-12]
                if eligible:answer=eligible[-1]['answer'];how='first_training_pass_else_last'
            points[str(budget)]={'answer':answer,'answerSha256':digest(answer),'candidateHow':how,'solverValid':record['valid'],'idOodAccessed':False}
        save(d/'cost-checkpoints.json',points)
def audit_canary(records):
    problems=[]
    for r in records:
        d=OUT/'tasks'/r['arm']/r['key']
        if not r['valid'] or r['modelCalls']==0:problems.append([r['id'],r['arm'],'invalid_or_no_model_call'])
        if r['accountedUpperBoundUsd']>(.025 if r['arm']=='baseline' else .1)+1e-7:problems.append([r['id'],r['arm'],'cost_cap'])
        for p in (d/'calls').rglob('request.json'):
            w=json.loads(p.read_text())
            if w.get('model')!=CFG['model'] or w.get('temperature')!=0 or w.get('max_tokens')!=16384 or w.get('provider',{}).get('only')!=['digitalocean'] or w.get('provider',{}).get('allow_fallbacks') is not False or w.get('reasoning',{}).get('effort')!='high' or 'seed' in w:problems.append([r['id'],r['arm'],'wire_profile_changed'])
        if r['arm']=='independent':
            for p in (d/'calls').rglob('request.json'):
                w=json.loads(p.read_text())
                if w['messages']!=[{'role':'user','content':next(t['prompt'] for t in CATALOG if t['key']==r['key'])}]:problems.append([r['id'],r['arm'],'history_leak'])
        if r['arm'] in ['objrun','binary']:
            n=d/'native';
            if not all((n/name).exists() for name in ['trace.json','tree.json','task.json','engine/data/h2h.sqlite']):problems.append([r['id'],r['arm'],'missing_native_evidence'])
            events=json.loads((d/'feedback.json').read_text()) if (d/'feedback.json').exists() else []
            if len(events)>5:problems.append([r['id'],r['arm'],'candidate_cap'])
            if len(events)>=5 and r.get('answer') and r['answer'] not in [e['answer'] for e in events]:problems.append([r['id'],r['arm'],'unassessed_sixth_candidate'])
            if r['arm']=='binary' and any(set(e['exposed'])!={'value'} for e in events):problems.append([r['id'],r['arm'],'binary_leak'])
    a={'atUtc':utc(),'problems':problems,'allPassed':len(records)==40 and not problems,'records':len(records),'idOodAccessed':False};save(OUT/'canary-audit.json',a);return a['allPassed']
def heartbeat():
    while not STOP.wait(20):status()
def main():
    global GRADER,GRADER_URL
    OUT.mkdir(parents=True,exist_ok=True);lock=OUT/'runner.lock.json'
    if lock.exists():
        prior=json.loads(lock.read_text());p=pathlib.Path('/proc')/str(prior['pid'])/'cmdline'
        if p.exists() and str(ROOT/'package/run.py').encode() in p.read_bytes():raise RuntimeError('RunnerAlreadyLive')
    save(lock,{'pid':os.getpid(),'atUtc':utc()})
    try:
        assert json.loads((OUT/'controls/summary.json').read_text())['allPassed']
        report_control=json.loads((OUT/'controls/report-control.json').read_text());assert report_control['allPassed'] and report_control['reportCodeSha256']==__import__('hashlib').sha256((ROOT/'package/report.py').read_bytes()).hexdigest(),'ReportControlChanged'
        frozen=sourcepins()
        if (OUT/'source-pins.json').exists():assert json.loads((OUT/'source-pins.json').read_text())==frozen,'SourceChanged'
        else:save(OUT/'source-pins.json',frozen)
        common.preflight();port=freeport();GRADER_URL='http://127.0.0.1:'+str(port)
        env={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ['KEY','TOKEN','SECRET'])};env['GRADER_PORT']=str(port)
        log=(OUT/'grader.log').open('ab');GRADER=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(ROOT/'package/grader.py')],env=env,stdout=log,stderr=log);STATE['graderPid']=GRADER.pid
        for _ in range(100):
            try:
                if get(GRADER_URL+'/health')['ok']:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('GraderStartup')
        threading.Thread(target=heartbeat,daemon=True).start()
        canary=[t for t in CATALOG if t['id'] in MANIFEST['canaryIds']];STATE['stage']='canary';status()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:cr=list(pool.map(lambda j:execute(*j),[(t,a) for t in canary for a in ARMS]))
        if STOP.is_set() or not audit_canary(cr):STATE['stage']='needs_attention';STATE['stopReason']=STATE['stopReason'] or 'CanaryAuditFailed';return
        STATE['stage']='running';status();remaining=[(t,a) for t in CATALOG if t['id'] not in MANIFEST['canaryIds'] for a in ARMS]
        iterator=iter(remaining)
        def consumer():
            while not STOP.is_set():
                with LOCK:
                    try:job=next(iterator)
                    except StopIteration:return
                execute(*job)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:consumer(),range(4)))
        if STOP.is_set():STATE['stage']='needs_attention';return
        rr=all_results()
        if len(rr)!=960:raise RuntimeError('IncompleteTaskMapping')
        cost_snapshots(rr)
        save(OUT/'all-candidates-frozen.json',{'atUtc':utc(),'count':len(rr),'records':[{'arm':r['arm'],'key':r['key'],'sha256':r.get('finalCandidateSha256'),'costCheckpointsSha256':digest(json.loads((OUT/'tasks'/r['arm']/r['key']/'cost-checkpoints.json').read_text())),'valid':r['valid']} for r in rr]})
        STATE['stage']='final_evaluation';status()
        clean={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ['KEY','TOKEN','SECRET'])}
        subprocess.run([str(ROOT/'runtime/bin/python'),str(ROOT/'package/report.py')],check=True,env=clean)
        STATE['stage']='verification';status()
        subprocess.run([str(ROOT/'runtime/bin/python'),str(ROOT/'package/audit.py')],check=True,env=clean)
        STATE['stage']='complete_with_exceptions' if any(not r['valid'] for r in rr) else 'complete'
    except Exception as e:STATE['stage']='needs_attention';STATE['stopReason']=type(e).__name__+':'+str(e);traceback.print_exc()
    finally:
        STOP.set()
        if GRADER is not None:GRADER.terminate();GRADER.wait(timeout=10)
        status()
        if lock.exists() and json.loads(lock.read_text())['pid']==os.getpid():lock.unlink()
if __name__=='__main__':main()
