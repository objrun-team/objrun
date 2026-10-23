"""Owned official DeepSeek transport and deterministic private rule grader."""
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import concurrent.futures as futures
import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
import urllib.error
import subprocess
import sys
from protocol import BASE, PARAMETERS, PROTOCOL_SHA, digest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/canonical'
CFG = json.loads((ROOT/'package/experiment.json').read_text())
LOCK = threading.RLock()

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p, value, exclusive=False):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if exclusive:
        with p.open('x',encoding='utf-8') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    else:
        temp=p.with_name(p.name+'.'+str(threading.get_ident())+'.tmp')
        with temp.open('w',encoding='utf-8') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        temp.replace(p)

class Fault(Exception): pass
class BudgetEnded(Fault): pass

def wire(body):
    # Deliberate official API adapter. Never forward SDK/vendor-specific options.
    allowed={'messages','tools'}
    result={k:v for k,v in body.items() if k in allowed}
    result.update(PARAMETERS)
    if not isinstance(result.get('messages'),list) or not result['messages']:raise Fault('InvalidMessages')
    if result.get('tools'):
        result['tool_choice']='auto'
        for m in result['messages']:
            if m.get('role')=='assistant' and 'reasoning_content' not in m: m['reasoning_content']=''
    return result

def estimate(usage, started, ended):
    if not isinstance(usage,dict):return {'kind':'unknown','estimatedUsd':None,'reason':'no complete usage'}
    prompt=usage.get('prompt_tokens'); completion=usage.get('completion_tokens')
    if not isinstance(prompt,int) or not isinstance(completion,int):return {'kind':'unknown','estimatedUsd':None,'reason':'missing token counts'}
    hit=usage.get('prompt_cache_hit_tokens',usage.get('prompt_tokens_details',{}).get('cached_tokens'))
    miss=usage.get('prompt_cache_miss_tokens')
    periods=[]
    # Boundaries/holidays make billing attribution uncertain: retain range.
    for timestamp in [started,ended]:
        d=dt.datetime.fromtimestamp(timestamp,dt.timezone.utc)
        peak=d.weekday()<5 and any(a<=d.hour<b for a,b in CFG['peakHoursUtc'])
        periods.append('peak' if peak else 'offpeak')
    rates=CFG['priceUsdPerMillion']
    def cost(period):
        r=rates[period]
        if not isinstance(hit,int):return ((prompt*r['hit']+completion*r['output'])/1e6,(prompt*r['miss']+completion*r['output'])/1e6)
        missed=miss if isinstance(miss,int) else max(0,prompt-hit)
        v=(hit*r['hit']+missed*r['miss']+completion*r['output'])/1e6
        return v,v
    a,b=cost(periods[0]),cost(periods[-1]);lo=min(a[0],b[0]);hi=max(a[1],b[1])
    return {'kind':'estimate','actualUsd':None,'estimatedUsd':lo if abs(lo-hi)<1e-12 else None,
            'lowerUsd':lo,'upperUsd':hi,'periodAtDispatch':periods[0],'periodAtCompletion':periods[-1],
            'cacheHitTokens':hit,'cacheMissTokens':miss,'tariffDate':CFG['priceObservedDate'],
            'note':'token tariff estimate, not an actual bill; crossing a tariff boundary gives a range'}

class DeepSeek:
    def __init__(self):
        self.key=os.environ['DEEPSEEK_API_KEY']
        self.total=threading.BoundedSemaphore(CFG["modelConcurrency"]);self.solve=threading.BoundedSemaphore(CFG["modelConcurrency"]);self.grader=threading.BoundedSemaphore(1)
        self.active={};self.peak=0;self.stop=None;self.last_balance=0
    def get(self,path):
        req=urllib.request.Request(BASE+path,headers={'Authorization':'Bearer '+self.key})
        with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
    def observe(self):
        balance=self.get('/user/balance'); models=self.get('/models')
        save(OUT/'account-observation.json',{'atUtc':now(),'balance':balance,'models':models})
        if not balance.get('is_available') or not any(float(x.get('total_balance',0))>0 for x in balance.get('balance_infos',[])):raise Fault('AccountUnavailableOrEmpty')
        if 'deepseek-flash' not in [x.get('id') for x in models.get('data',[])]:raise Fault('OfficialFlashAliasUnavailable')
        page=urllib.request.urlopen('https://api-docs.deepseek.com/quick_start/pricing/',timeout=30).read()
        if CFG['expectedModelMapping'].encode() not in page:raise Fault('OfficialModelMappingChanged')
        save(OUT/'model-observation.json',{'atUtc':now(),'expectedMapping':CFG['expectedModelMapping'],'pricingPageSha256':digest(page),'rollingAlias':True})
        (OUT/'pricing-observed.html').write_bytes(page)
        self.last_balance=time.time();return balance
    def metrics(self):
        with LOCK:return {'activeApiRequests':list(self.active.values()),'apiConcurrency':len(self.active),'peakApiConcurrency':self.peak,'stopReason':self.stop}
    def call(self,logical,category,body,deadline):
        logical=re.sub(r'[^A-Za-z0-9_./-]','_',logical)
        if '..' in Path(logical).parts:raise Fault('InvalidCallPath')
        home=OUT/'calls'/category/logical
        request=wire(body)
        completed=home/'complete.json'
        if completed.exists():
            c=read(completed)
            if c['requestSha256']!=digest(request):raise Fault('ExistingCallIdentityMismatch')
            return read(home/c['responsePath'])
        home.mkdir(parents=True,exist_ok=True)
        sem=self.solve if category=='solve' else self.grader
        for attempt in range(3):
            directory=home/('attempt-'+str(attempt))
            if (directory/'receipt.json').exists():
                receipt=read(directory/'receipt.json')
                if not receipt.get('retryable'):raise Fault('CompletedFailedCall:'+logical)
                continue
            if (directory/'dispatch.json').exists():raise Fault('UnresolvedDispatch:'+logical)
            if self.stop:raise Fault('AdmissionStopped:'+self.stop)
            remaining=deadline-time.time()
            if remaining<=0:raise BudgetEnded('OriginalDeadlineExhausted')
            if not sem.acquire(timeout=remaining):raise BudgetEnded('ApiQueueDeadline')
            acquired=False
            try:
                if not self.total.acquire(timeout=max(.001,deadline-time.time())):raise BudgetEnded('TotalApiQueueDeadline')
                acquired=True
                if time.time()>=deadline:raise BudgetEnded('OriginalDeadlineExhausted')
                if time.time()-self.last_balance>300:
                    with LOCK:
                        if time.time()-self.last_balance>300:
                            b=self.observe();save(OUT/'balance-latest.json',{'atUtc':now(),'data':b});self.last_balance=time.time()
                            if not b.get('is_available'):self.stop='AccountUnavailable';raise Fault(self.stop)
                started=time.time()
                save(directory/'request.json',request,True)
                save(directory/'dispatch.json',{'atUtc':now(),'startedEpoch':started,'deadlineEpoch':deadline,'requestSha256':digest(request),'category':category,'attempt':attempt,'endpoint':BASE+'/chat/completions'},True)
                with LOCK:
                    self.active[str(directory)]={'logical':logical,'category':category,'startedAtUtc':now()};self.peak=max(self.peak,len(self.active))
                status=0;raw=b'';response=None;error=None;headers={};first_byte=None
                try:
                    req=urllib.request.Request(BASE+'/chat/completions',data=json.dumps(request,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
                    try: remote=urllib.request.urlopen(req,timeout=max(.01,deadline-time.time()))
                    except urllib.error.HTTPError as e:remote=e
                    status=remote.status;headers={k:v for k,v in remote.headers.items() if k.lower() in {'date','content-type','x-request-id','x-ds-request-id'}}
                    with remote, (directory/'response.raw').open('xb') as target:
                        while True:
                            if time.time()>=deadline:raise TimeoutError('OriginalDeadlineExhausted')
                            try:remote.fp.raw._sock.settimeout(max(.01,deadline-time.time()))
                            except AttributeError:pass
                            chunk=remote.read1(65536)
                            if not chunk:break
                            if first_byte is None:first_byte=time.time()
                            target.write(chunk);target.flush()
                        os.fsync(target.fileno())
                    raw=(directory/'response.raw').read_bytes()
                    response=json.loads(raw)
                    save(directory/'response.json',response,True)
                    if status!=200:raise Fault('HTTP'+str(status))
                    if not isinstance(response.get('model'),str) or 'flash' not in response['model'].lower():raise Fault('UnexpectedResponseModel')
                    choice=response['choices'][0];msg=choice['message']
                    if choice.get('finish_reason') not in {'stop','length','tool_calls','content_filter'}:raise Fault('IncompleteResponseFinishReason')
                    if not isinstance(msg.get('reasoning_content'),str):raise Fault('MissingThinkingContentField')
                    if not isinstance(msg.get('content'),(str,type(None))):raise Fault('InvalidContent')
                    if not response.get('id') or not isinstance(response.get('usage'),dict):raise Fault('IncompleteResponseMetadata')
                except Exception as e:error=(type(e).__name__+':'+str(e)).replace(self.key,'[REDACTED]')[:500]
                ended=time.time();usage=response.get('usage') if isinstance(response,dict) else None
                retryable=bool(error) and (status in {0,408,409,425,429,500,502,503,504} or 'JSONDecodeError' in error or 'IncompleteResponse' in error)
                receipt={'atUtc':now(),'httpStatus':status,'responseModel':response.get('model') if isinstance(response,dict) else None,
                         'requestModel':'deepseek-flash','generationId':response.get('id') if isinstance(response,dict) else None,
                         'systemFingerprint':response.get('system_fingerprint') if isinstance(response,dict) else None,'responseCreated':response.get('created') if isinstance(response,dict) else None,'headers':headers,'usage':usage,
                         'startedEpoch':started,'endedEpoch':ended,'seconds':ended-started,'firstByteSeconds':first_byte-started if first_byte else None,
                         'finishReason':response.get('choices',[{}])[0].get('finish_reason') if isinstance(response,dict) and response.get('choices') else None,
                         'error':error,'retryable':retryable,'requestSha256':digest(request),'cost':estimate(usage,started,ended)}
                save(directory/'receipt.json',receipt,True)
                if not error:
                    save(completed,{'requestSha256':digest(request),'responsePath':str((directory/'response.json').relative_to(home))},True)
                    return response
                if status in {400,401,402,403,404} or 'UnexpectedResponseModel' in error or 'MissingThinking' in error:
                    self.stop='DeepSeekProtocolOrAccountFault:'+error
                if not retryable or attempt==2:raise Fault(error)
            finally:
                with LOCK:self.active.pop(str(directory),None)
                if acquired:self.total.release()
                sem.release()
            delay=min(2**attempt,max(0,deadline-time.time()))
            if delay:time.sleep(delay)
        raise Fault('FiniteAttemptChainExhausted')

class Judge:
    def __init__(self, book):
        self.book=book;self.jobs={};self.pool=futures.ThreadPoolExecutor(max_workers=CFG['graderConcurrency'])
        self.sourceSha=digest((ROOT/'data/private-tasks.json').read_bytes())
    def enqueue(self,tid,candidate):
        row=self.book[tid]
        key=digest({'id':tid,'candidateSha256':digest(candidate),'dataRevision':CFG['dataRevision'],
                    'dataSha256':self.sourceSha,'protocolSha256':PROTOCOL_SHA,'dependencySha256':read(ROOT/'provenance/dependencies.json')['manifestSha256']})
        with LOCK:
            if key in self.jobs:return key
            result=OUT/'judgments'/(key+'.json')
            if result.exists():self.jobs[key]={'result':read(result)};return key
            def work():
                begin=time.time()
                try:
                    # No provider credential, broker token or ambient proxy is inherited.
                    child=subprocess.run([str(ROOT/'venv/bin/python'),str(ROOT/'package/grade.py')],
                        input=json.dumps({'candidate':candidate,'row':row},ensure_ascii=False),text=True,encoding='utf-8',
                        capture_output=True,timeout=30,env={'PATH':'/usr/bin:/bin','PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})
                    if child.returncode:raise Fault('GraderWorkerExit:'+str(child.returncode)+':'+child.stderr[-300:])
                    decision=json.loads(child.stdout)
                    if decision.get('valid') is not True or type(decision.get('passed')) is not bool:raise Fault('GraderWorkerInvalid:'+str(decision))
                except Exception as e:decision={'valid':False,'outcome':'grader_error','errorType':type(e).__name__,'error':str(e)[:600]}
                decision.update(candidateSha256=digest(candidate),taskId=tid,protocolSha256=PROTOCOL_SHA,jobKey=key,atUtc=now(),seconds=time.time()-begin)
                save(result,decision,True);return decision
            save(OUT/'jobs'/(key+'.json'),{'key':key,'id':tid,'candidate':candidate,'candidateSha256':digest(candidate),'atUtc':now()},True)
            self.jobs[key]={'future':self.pool.submit(work)}
        return key
    def poll(self,key):
        with LOCK:
            job=self.jobs[key]
            if 'result' in job:return {'state':'complete','result':job['result']}
            if not job['future'].done():return {'state':'pending'}
            return {'state':'complete','result':job['future'].result()}
    def wait(self,key,deadline=None):
        begin=time.time()
        while True:
            value=self.poll(key)
            if value['state']=='complete':return value['result'],time.time()-begin
            if deadline and time.time()>=deadline:raise BudgetEnded('JudgeWaitExceededOriginalSolveDeadline')
            time.sleep(.05)

def broker(client,judge,token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,obj,status=200):
            raw=json.dumps(obj,ensure_ascii=False).encode()
            try:self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
        def authorized(self):return self.headers.get('X-Olympiad-Token')==token
        def do_GET(self):
            if not self.authorized():return self.send({'error':'Unauthorized'},403)
            try:
                if self.path.startswith('/jobs/'):return self.send(judge.poll(self.path.split('/')[-1]))
                self.send({'error':'NotFound'},404)
            except Exception as e:self.send({'errorType':type(e).__name__,'error':str(e)},503)
        def do_POST(self):
            if not self.authorized():return self.send({'error':'Unauthorized'},403)
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<8*1024*1024:raise Fault('InvalidBodySize')
                b=json.loads(self.rfile.read(n))
                if self.path=='/model':return self.send(client.call(b['logical'],'solve',b['body'],b['deadline']))
                if self.path=='/jobs':return self.send({'key':judge.enqueue(b['id'],b['candidate'])})
                self.send({'error':'NotFound'},404)
            except Exception as e:self.send({'errorType':type(e).__name__,'error':str(e)},503)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server

def accounting():
    groups={};events=[]
    for p in (OUT/'calls').glob('**/dispatch.json'):
        relative=p.relative_to(OUT/'calls');arm=relative.parts[2] if len(relative.parts)>2 else 'unknown'
        g=groups.setdefault(arm,{'requests':0,'promptTokens':0,'completionTokens':0,'cacheHitTokens':0,'modelSeconds':0,
            'estimateLowerUsd':0,'estimateUpperUsd':0,'unknownCostRequests':0,'actualCostUsd':None,'failedRequests':0,'unsettledRequests':0})
        g['requests']+=1
        rp=p.with_name('receipt.json')
        if not rp.exists():g['unknownCostRequests']+=1;g['unsettledRequests']+=1;continue
        r=read(rp);u=r.get('usage') or {};g['promptTokens']+=u.get('prompt_tokens',0);g['completionTokens']+=u.get('completion_tokens',0)
        g['cacheHitTokens']+=u.get('prompt_cache_hit_tokens',0);g['modelSeconds']+=r['seconds'];g['failedRequests']+=bool(r.get('error'))
        c=r['cost']
        if c['kind']=='unknown':g['unknownCostRequests']+=1
        else:g['estimateLowerUsd']+=c['lowerUsd'];g['estimateUpperUsd']+=c['upperUsd']
        events.extend([(r['startedEpoch'],1),(r['endedEpoch'],-1)])
    active=peak=0
    for _,delta in sorted(events,key=lambda x:(x[0],x[1])):active+=delta;peak=max(peak,active)
    return {'byArm':groups,'peakApiConcurrencyObserved':peak,'costLabel':'official token tariff estimate; per-request actual bill unavailable','atUtc':now()}
