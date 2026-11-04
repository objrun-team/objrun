"""Pinned OpenRouter transport and deterministic private rule grader."""
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
from protocol import BASE, MODEL, CANONICAL, PARAMETERS, PROTOCOL_SHA, TOOLS, digest, grade, parse

ROOT = (Path(__file__).resolve().parents[4] / 'scripts')
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

TRANSIENT={408,409,425,429,500,502,503,504}

def provider_error_code(response):
    error=response.get('error') if isinstance(response,dict) else None
    code=error.get('code') if isinstance(error,dict) else None
    try:return int(code) if code is not None else None
    except (TypeError,ValueError):return None

def retry_receipt(directory,receipt):
    if receipt.get('retryable'):return True
    # Preserve original v1 receipts; recognize their previously missed body-level 504.
    response=directory/'response.json'
    return receipt.get('httpStatus')==200 and response.exists() and provider_error_code(read(response)) in TRANSIENT


def wire(body):
    result={k:v for k,v in body.items() if k in {'messages','tools','tool_choice'}}
    result=json.loads(json.dumps(result));result.update(PARAMETERS)
    if not isinstance(result.get('messages'),list) or not result['messages']:raise Fault('InvalidMessages')
    if result.get('tools'):
        if any(t['function']['name'] not in TOOLS for t in result['tools']):raise Fault('UnexpectedTool')
        if isinstance(result.get('tool_choice'),dict):
            name=result['tool_choice']['function']['name'];result['tools']=[t for t in result['tools'] if t['function']['name']==name]
        result['tool_choice']='auto'
    return result


class OpenRouter:
    def __init__(self):
        self.key=os.environ['OPENROUTER_API_KEY']
        self.total=threading.BoundedSemaphore(CFG['modelConcurrency']);self.active={};self.peak=0;self.stop=None
        proxy=os.environ.get('LABBENCH_PROXY')
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy} if proxy else {}))
        self.last_balance=0;self.remaining=0.;self.held=0.
    def get(self,path):
        request=urllib.request.Request(BASE+path,headers={'Authorization':'Bearer '+self.key})
        with self.opener.open(request,timeout=30) as r:return json.load(r)
    def observe(self):
        credits=self.get('/credits')['data'];key=self.get('/key')['data'];endpoints=self.get('/models/'+PARAMETERS['model']+'/endpoints')['data']
        endpoint=next((e for e in endpoints['endpoints'] if e.get('tag')=='digitalocean'),None)
        if endpoint is None or CANONICAL not in endpoint['name']:self.stop='PinnedEndpointChanged';raise Fault(self.stop)
        if not set(['tools','tool_choice','reasoning','temperature','max_tokens'])<=set(endpoint['supported_parameters']):raise Fault('MissingProviderParameters')
        rates=endpoint['pricing'];self.rates={k:float(rates.get(k,0)) for k in ['prompt','completion','input_cache_read']}
        if self.rates['prompt']>.3/1e6 or self.rates['completion']>1.2/1e6:self.stop='ProviderTariffExceeded';raise Fault(self.stop)
        values=[float(credits['total_credits'])-float(credits['total_usage'])]
        for value in [key.get('limit_remaining'),(key.get('effective_budget') or {}).get('remaining_usd')]:
            if value is not None:values.append(float(value))
        values.extend(float(v['remaining_usd']) for v in key.get('budgets',[]) if v.get('remaining_usd') is not None)
        self.remaining=min(values);self.last_balance=time.time()
        if self.remaining<=0:self.stop='AccountOrKeyLimit';raise Fault(self.stop)
        save(OUT/'account-observation.json',{'atUtc':now(),'remainingUsd':self.remaining,'keyLimitRemaining':key.get('limit_remaining')})
        save(OUT/'model-observation.json',{'atUtc':now(),'model':PARAMETERS['model'],'canonical':CANONICAL,'endpoint':endpoint,'fullModel':endpoints})
        return self.remaining
    def metrics(self):
        with LOCK:return {'activeApiRequests':list(self.active.values()),'apiConcurrency':len(self.active),'peakApiConcurrency':self.peak,'stopReason':self.stop,'remainingUsd':self.remaining,'heldUsd':self.held}
    def call(self,logical,category,body,deadline):
        if not re.fullmatch(r'[A-Za-z0-9_./-]+',logical) or '..' in Path(logical).parts:raise Fault('InvalidCallIdentity')
        home=OUT/'calls'/category/logical;request=wire(body);completed=home/'complete.json'
        if completed.exists():
            c=read(completed)
            if c['requestSha256']!=digest(request):raise Fault('ExistingCallIdentityMismatch')
            return read(home/c['responsePath'])
        for attempt in range(CFG['logicalCallMaxAttempts']):
            directory=home/('attempt-'+str(attempt));reserve=(len(json.dumps(request,ensure_ascii=False).encode())*.3+16384*1.2)/1e6
            if (directory/'receipt.json').exists():
                if not retry_receipt(directory,read(directory/'receipt.json')):raise Fault('ExistingFailedCallNoRedispatch')
                continue
            if (directory/'dispatch.json').exists():raise Fault('UnresolvedDispatchNoRedispatch')
            if self.stop:raise Fault('AdmissionStopped:'+self.stop)
            if not self.total.acquire(timeout=max(.001,deadline-time.time())):raise BudgetEnded('ApiQueueDeadline')
            held=False
            try:
                if time.time()>=deadline:raise BudgetEnded('OriginalDeadlineExhausted')
                with LOCK:
                    if time.time()-self.last_balance>300:self.observe()
                    if self.remaining-self.held<reserve:self.stop='AccountOrKeyReserve';raise Fault(self.stop)
                    self.held+=reserve;held=True
                started=time.time();save(directory/'request.json',request,True)
                save(directory/'dispatch.json',{'atUtc':now(),'startedEpoch':started,'deadlineEpoch':deadline,'requestSha256':digest(request),'category':category,'attempt':attempt,'endpoint':BASE+'/chat/completions','reserveUsd':reserve},True)
                with LOCK:self.active[str(directory)]={'logical':logical,'startedAtUtc':now()};self.peak=max(self.peak,len(self.active))
                status=0;response=None;error=None;headers={};first=None
                try:
                    req=urllib.request.Request(BASE+'/chat/completions',data=json.dumps(request,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','X-OpenRouter-Title':'ObjRun LAB-Bench 20261019'},method='POST')
                    try:remote=self.opener.open(req,timeout=max(.01,deadline-time.time()))
                    except urllib.error.HTTPError as e:remote=e
                    status=remote.status;headers={k:v for k,v in remote.headers.items() if k.lower() in {'date','content-type','x-request-id','x-generation-id'}}
                    with remote,(directory/'response.raw').open('xb') as f:
                        while True:
                            if time.time()>=deadline:raise TimeoutError('OriginalDeadlineExhausted')
                            try:remote.fp.raw._sock.settimeout(max(.01,deadline-time.time()))
                            except AttributeError:pass
                            chunk=remote.read1(65536)
                            if not chunk:break
                            if first is None:first=time.time()
                            f.write(chunk);f.flush()
                        os.fsync(f.fileno())
                    response=json.loads((directory/'response.raw').read_bytes());save(directory/'response.json',response,True)
                    if status!=200 or response.get('error'):raise Fault('ProviderHTTP'+str(status)+':'+str(response.get('error',''))[:200])
                    if response.get('provider')!='DigitalOcean':self.stop='UnexpectedProvider';raise Fault(self.stop)
                    if response.get('model') not in [MODEL,CANONICAL]:self.stop='UnexpectedModel';raise Fault(self.stop)
                    if not response.get('id') or not isinstance(response.get('usage'),dict):raise Fault('IncompleteResponseMetadata')
                    choice=response['choices'][0];msg=choice['message']
                    if choice.get('finish_reason') not in {'stop','length','tool_calls','content_filter'}:raise Fault('IncompleteFinishReason')
                    if not isinstance(msg.get('content'),(str,type(None))):raise Fault('InvalidContent')
                except Exception as e:error=(type(e).__name__+':'+str(e)).replace(self.key,'[REDACTED]')[:600]
                ended=time.time();usage=response.get('usage') if isinstance(response,dict) else None
                amount=usage.get('cost') if isinstance(usage,dict) else None
                actual=float(amount) if isinstance(amount,(int,float)) and amount>=0 else None
                code=provider_error_code(response)
                retryable=bool(error) and (status==0 or status in TRANSIENT or code in TRANSIENT or 'JSONDecodeError' in error or 'Incomplete' in error)
                receipt={'atUtc':now(),'httpStatus':status,'responseModel':response.get('model') if isinstance(response,dict) else None,
                    'provider':response.get('provider') if isinstance(response,dict) else None,'requestModel':MODEL,
                    'generationId':response.get('id') if isinstance(response,dict) else None,'headers':headers,'usage':usage,
                    'startedEpoch':started,'endedEpoch':ended,'seconds':ended-started,'firstByteSeconds':first-started if first else None,
                    'finishReason':response.get('choices',[{}])[0].get('finish_reason') if isinstance(response,dict) and response.get('choices') else None,
                    'error':error,'providerErrorCode':code,'retryable':retryable,'requestSha256':digest(request),'actualCostUsd':actual,'unknownCost':actual is None,'reserveUsd':reserve}
                save(directory/'receipt.json',receipt,True)
                with LOCK:self.remaining-=actual if actual is not None else reserve
                if status in {400,401,402,403,404} or code in {400,401,402,403,404}:self.stop='ProviderProtocolOrAccountFault:'+str(code or status)
                if not error:
                    save(completed,{'requestSha256':digest(request),'responsePath':str((directory/'response.json').relative_to(home))},True)
                    return response
                if not retryable or attempt==CFG['logicalCallMaxAttempts']-1:raise Fault(error)
            finally:
                with LOCK:
                    self.active.pop(str(directory),None)
                    if held:self.held-=reserve
                self.total.release()
            time.sleep(min(2**attempt,max(0,deadline-time.time())))
        raise Fault('FiniteRetryChainExhausted')

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
                    decision=grade(candidate,row)
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
        def authorized(self):return self.headers.get('X-Labbench-Token')==token
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
                if self.path=='/parse':return self.send({'parsed':parse(b['candidate'],b['choiceCount']) is not None})
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
        relative=p.relative_to(OUT/'calls');arm=relative.parts[2]
        g=groups.setdefault(arm,{'requests':0,'promptTokens':0,'completionTokens':0,'cacheHitTokens':0,'modelSeconds':0,'knownActualCostUsd':0.,'unknownCostRequests':0,'unknownReserveUsd':0.,'failedRequests':0,'unsettledRequests':0})
        g['requests']+=1;dispatch=read(p);rp=p.with_name('receipt.json')
        if not rp.exists():g['unknownCostRequests']+=1;g['unsettledRequests']+=1;g['unknownReserveUsd']+=dispatch['reserveUsd'];continue
        r=read(rp);u=r.get('usage') or {};g['promptTokens']+=u.get('prompt_tokens',0);g['completionTokens']+=u.get('completion_tokens',0)
        g['cacheHitTokens']+=(u.get('prompt_tokens_details') or {}).get('cached_tokens',0);g['modelSeconds']+=r['seconds'];g['failedRequests']+=bool(r.get('error'))
        if r['actualCostUsd'] is None:g['unknownCostRequests']+=1;g['unknownReserveUsd']+=r['reserveUsd']
        else:g['knownActualCostUsd']+=r['actualCostUsd']
        events.extend([(r['startedEpoch'],1),(r['endedEpoch'],-1)])
    active=peak=0
    for _,delta in sorted(events,key=lambda x:(x[0],x[1])):active+=delta;peak=max(peak,active)
    return {'byArm':groups,'peakApiConcurrencyObserved':peak,'costLabel':'OpenRouter usage.cost actual charge; missing cost remains unknown','atUtc':now()}
