"""Twenty-question four-arm local pilot. Never starts the remaining benchmark."""
import concurrent.futures, datetime, hashlib, json, os, re, secrets, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/climaqa/pilot-20261028-v1'
ARMS=['baseline','independent','binary','objrun']
PARAMS={'model':'deepseek-flash','thinking':{'type':'enabled'},'reasoning_effort':'high','max_tokens':16384,'stream':False}
SYSTEM='You are a helpful assistant.'
LOCK=threading.RLock(); STOP=threading.Event(); BOOK={}; SEEN={}; TOKEN=secrets.token_hex(24); KEY=''; FIXTURE=False
def sha(s):return hashlib.sha256(s if isinstance(s,bytes) else s.encode()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(p,o,exclusive=False):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True); raw=json.dumps(o,ensure_ascii=False,indent=2)+'\n'
 if exclusive:
  with p.open('x',encoding='utf-8') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 else:
  t=p.with_name(p.name+'.'+str(threading.get_ident())+'.tmp');t.write_text(raw,encoding='utf-8');os.replace(t,p)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def parse(answer):
 matches=re.findall(r'(?im)^\s*Answer:\s*\(?([A-D])\)?\s*$',answer)
 return matches[0].upper() if len(matches)==1 else None
def grade(tid,arm,candidate,mode='correct'):
 letter=parse(candidate)
 if mode=='parsed':return {'parsed':bool(letter)}
 if not letter:return {'valid':True,'parsed':False,'passed':False,'kind':'invalid_format'}
 with LOCK:
  seen=SEEN.setdefault((arm,tid),{})
  if letter not in seen:
   if len(seen)>=2:raise RuntimeError('DistinctOptionBudgetExceeded')
   seen[letter]=letter==BOOK[tid]
  return {'valid':True,'parsed':True,'passed':seen[letter],'kind':'correct' if seen[letter] else 'wrong','distinctJudged':len(seen)}
def estimate(usage):
 if not isinstance(usage,dict) or not isinstance(usage.get('prompt_tokens'),int) or not isinstance(usage.get('completion_tokens'),int):return None
 p=usage['prompt_tokens'];o=usage['completion_tokens'];hit=usage.get('prompt_cache_hit_tokens');miss=usage.get('prompt_cache_miss_tokens')
 if isinstance(hit,int) and isinstance(miss,int): low=(hit*.003+miss*.15+o*.6)/1e6;high=(hit*.006+miss*.3+o*1.2)/1e6
 else:low=(p*.003+o*.6)/1e6;high=(p*.3+o*1.2)/1e6
 return {'lowerUsd':low,'upperUsd':high,'note':'official off-peak to peak tariff range, not actual bill'}
def model(tid,arm,index,body,deadline):
 if FIXTURE:
  return {'id':'fixture','object':'chat.completion','created':1,'model':'deepseek-flash','choices':[{'index':0,'message':{'role':'assistant','content':None,'reasoning_content':'fixture reasoning','tool_calls':[{'id':'fixture-'+str(index),'type':'function','function':{'name':'verify' if index==1 else 'submit','arguments':json.dumps({'answer':'Answer: B' if index==1 else 'Answer: A'})}}]},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
 if STOP.is_set():raise RuntimeError('AdmissionStopped')
 wire={k:body[k] for k in ('messages','tools') if k in body};wire.update(PARAMS)
 selected=body.get('tool_choice')
 named=selected.get('function',{}).get('name') if isinstance(selected,dict) and selected.get('type')=='function' else None
 if named:
  if named!='submit' or not any(t.get('function',{}).get('name')==named for t in wire.get('tools',[])):raise RuntimeError('InvalidRequiredTool:'+str(named))
  # DeepSeek supports forced tool selection only with thinking disabled.
  wire['tools']=[t for t in wire['tools'] if t.get('function',{}).get('name')==named]
  wire['thinking']={'type':'disabled'};wire.pop('reasoning_effort',None);wire['tool_choice']=selected
 elif wire.get('tools'):wire['tool_choice']='auto'
 for m in wire['messages']:
  if m.get('role')=='assistant' and wire.get('tools') and not isinstance(m.get('reasoning_content'),str):
   # This is the actual history provided by the engine; missing reasoning cannot be reconstructed.
   raise RuntimeError('MissingReasoningContentInToolHistory')
 dest=OUT/'calls'/arm/tid/('call-'+str(index).zfill(3));dest.mkdir(parents=True,exist_ok=False)
 save(dest/'request.json',wire,True);save(dest/'dispatch.json',{'atUtc':now(),'endpoint':'https://api.deepseek.com/chat/completions','deadlineEpoch':deadline},True)
 start=time.time();status=0;response=None;error=None
 try:
  if start>=deadline:raise TimeoutError('SolveDeadline')
  req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(wire,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'},method='POST')
  try:r=urllib.request.urlopen(req,timeout=max(1,deadline-time.time()))
  except urllib.error.HTTPError as e:r=e
  with r:
   status=r.status;raw=r.read();(dest/'response.raw').write_bytes(raw);response=json.loads(raw)
  if status!=200:raise RuntimeError('DeepSeekHTTP'+str(status))
  if not response.get('id') or not response.get('usage') or not response.get('choices'):raise RuntimeError('InvalidProviderResponse')
  if 'flash' not in response.get('model','').lower():raise RuntimeError('ModelIdentityChanged')
  save(dest/'response.json',response,True)
  if named:
   calls=(response['choices'][0].get('message') or {}).get('tool_calls') or []
   if len(calls)!=1 or calls[0].get('function',{}).get('name')!=named:raise RuntimeError('RequiredSubmitNotReturned')
 except Exception as e:error=(type(e).__name__+':'+str(e)).replace(KEY,'[REDACTED]')
 receipt={'atUtc':now(),'httpStatus':status,'seconds':time.time()-start,'responseModel':response.get('model') if isinstance(response,dict) else None,'generationId':response.get('id') if isinstance(response,dict) else None,'systemFingerprint':response.get('system_fingerprint') if isinstance(response,dict) else None,'usage':response.get('usage') if isinstance(response,dict) else None,'estimate':estimate(response.get('usage')) if isinstance(response,dict) else None,'actualUsd':None,'error':error}
 save(dest/'receipt.json',receipt,True)
 if error:
  if status in (400,401,402,403,404) or 'ModelIdentityChanged' in error or 'MissingReasoning' in error:STOP.set()
  raise RuntimeError(error)
 return response
def server():
 class H(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   try:
    if self.headers.get('x-token')!=TOKEN:raise ValueError('Unauthorized')
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<5_000_000:raise ValueError('BodySize')
    x=json.loads(self.rfile.read(size))
    if self.path=='/grade':v=grade(x['id'],x['arm'],x['candidate'],x['mode'])
    elif self.path=='/model':v=model(x['id'],x['arm'],x['index'],x['body'],x['deadline'])
    else:raise ValueError('NotFound')
    code=200
   except Exception as e:v={'error':str(e)};code=503
   b=json.dumps(v,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers()
   try:self.wfile.write(b)
   except (BrokenPipeError,ConnectionResetError):pass
 s=ThreadingHTTPServer(('127.0.0.1',0),H);s.daemon_threads=True;threading.Thread(target=s.serve_forever,daemon=True).start();return s
def native(task,directory,s):
 spec={'task':task,'directory':str(directory),'broker':'http://127.0.0.1:'+str(s.server_port)};save(directory/'input.json',spec,True)
 env={k:v for k,v in os.environ.items() if not re.search(r'(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)',k,re.I)}
 env['CLIMAQA_BROKER_TOKEN']=TOKEN;env['DEEPSEEK_API_KEY']='local-broker-placeholder'
 # Resolve bun through its Windows executable, not the PowerShell shim.
 bun=Path(os.environ['USERPROFILE'])/'.bun/bin/bun.exe'
 if not bun.exists():
  import shutil
  bun=shutil.which('bun.exe') or shutil.which('bun')
 if not bun:raise RuntimeError('BunUnavailable')
 with (directory/'worker.stdout.log').open('w',encoding='utf-8') as stdout,(directory/'worker.stderr.log').open('w',encoding='utf-8') as stderr:
  p=subprocess.Popen([str(bun),str(ROOT/'scripts/climaqa/native.ts'),str(directory/'input.json')],cwd=directory,env=env,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  save(directory/'worker-process.json',{'pid':p.pid,'atUtc':now()},True)
  try:p.wait(timeout=650)
  except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10);raise RuntimeError('NativeWorkerTimeout')
 if not (directory/'native-result.json').exists():raise RuntimeError('NativeWorkerMissingResult:'+str(p.returncode))
 return read(directory/'native-result.json')
def solve(task,arm,s):
 tid=task['id'];directory=OUT/'tasks'/arm/tid;directory.mkdir(parents=True,exist_ok=False);start=time.time();deadline=start+600
 save(directory/'started.json',{'atUtc':now(),'id':tid,'arm':arm,'promptSha256':sha(task['prompt'])},True)
 result={'id':tid,'arm':arm,'complexity':task['complexity'],'startedAtUtc':now()};answer='';samples=[]
 try:
  if arm=='objrun':
   n=native(task,directory,s);answer=n.pop('answer');result.update(n)
   if n.get('error'):raise RuntimeError('Native:'+n['error'])
   if n.get('candidateHow')!='submitted':answer=''
  else:
   for i in range(1 if arm=='baseline' else 2):
    messages=[{'role':'system','content':SYSTEM},{'role':'user','content':task['prompt']}]
    if arm=='binary':
     for sample in samples:messages.extend([{'role':'assistant','content':sample['answer']},{'role':'user','content':'passed' if sample['grade']['passed'] else 'failed'}])
    response=model(tid,arm,i+1,{'messages':messages},deadline);choice=response['choices'][0];answer=choice['message'].get('content') or ''
    g=grade(tid,arm,answer);samples.append({'answer':answer,'grade':g,'finishReason':choice.get('finish_reason')});save(directory/'samples.json',samples)
    if g['passed']:break
   result['samples']=samples
  result['grade']=grade(tid,arm,answer);result['valid']=True
 except Exception as e:result['valid']=False;result['error']=(type(e).__name__+':'+str(e)).replace(KEY,'[REDACTED]')
 result.update(answer=answer,answerSha256=sha(answer),seconds=time.time()-start,completedAtUtc=now(),distinctJudgments=len(SEEN.get((arm,tid),{})))
 save(OUT/'results'/arm/(tid+'.json'),result,True)
 print(json.dumps({'arm':arm,'id':tid,'valid':result['valid'],'passed':result.get('grade',{}).get('passed'),'seconds':round(result['seconds'],1),'error':result.get('error')}),flush=True)
 return result
def main():
 global BOOK,KEY,FIXTURE
 FIXTURE='--fixture' in sys.argv
 public=read(OUT/'public.json'); BOOK={r['id']:r['answer'] for r in read(OUT/'private.json')}
 assert len(public)==20 and len(BOOK)==20
 if FIXTURE:
  assert parse('reason\nAnswer: (A)')=='A' and parse('Answer: A\nAnswer: B') is None and parse('') is None
  tid='fixture';BOOK[tid]='A';assert not grade(tid,'fixture','Answer: B')['passed'];assert grade(tid,'fixture','Answer: A')['passed']
  try:grade(tid,'fixture','Answer: C');raise AssertionError('cap failed')
  except RuntimeError as e:assert str(e)=='DistinctOptionBudgetExceeded'
  task={'id':'fixture','prompt':'Choose A. End with Answer: X.'};d=OUT/('fixture-native-'+str(int(time.time())));d.mkdir(exist_ok=False);s=server()
  try:r=native(task,d,s)
  finally:s.shutdown()
  feedback=read(d/'feedback.json') if (d/'feedback.json').exists() else []
  print(json.dumps({'fixtureNative':r,'feedback':feedback},ensure_ascii=False))
  assert not r.get('error') and r.get('candidateHow')=='submitted' and parse(r['answer'])=='A' and r['modelRequests']>=2 and any(x['node']=='/correct' and x['exposed']['value'] is False for x in feedback)
  return
 for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
  if line.strip().startswith('DEEPSEEK_API_KEY='):KEY=line.split('=',1)[1].strip().strip('"\'');break
 if not KEY:raise RuntimeError('MissingDeepSeekKey')
 sources=[ROOT/'scripts/climaqa/prepare.py',ROOT/'scripts/climaqa/run.py',ROOT/'scripts/climaqa/native.ts',OUT/'public.json',OUT/'private.json',OUT/'source.json']
 pins={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sources}
 git_commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
 save(OUT/'source-pins.json',{'atUtc':now(),'gitCommit':git_commit,'files':pins},True)
 save(OUT/'execution-started.json',{'atUtc':now(),'pid':os.getpid(),'scope':'20 questions x 4 only'},True)
 save(OUT/'protocol.json',{'run':'climaqa-pilot-20261028-v1','arms':ARMS,'items':20,'attempts':{'baseline':1,'independent':2,'binary':2},'distinctOptionJudgmentsMax':2,'objrun':{'checks':1,'maxDeadSiblings':0,'maxBranches':4,'units':12,'solveSeconds':600},'model':PARAMS,'concurrency':4,'temperature':'omitted: ineffective in thinking mode','apiRetries':0,'automaticFullRun':False,'source':read(OUT/'source.json')},True)
 s=server();jobs=[(t,ARMS[(i+j)%4]) for i,t in enumerate(public) for j in range(4)];results=[]
 try:
  # A single four-arm canary validates the actual native bridge before other work is admitted.
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
   for task,arm in jobs[:4]:results.append(pool.submit(solve,task,arm,s))
   canary=[f.result() for f in results];results=[]
   if any(not r['valid'] for r in canary) or not any(r['arm']=='objrun' and r.get('candidateHow')=='submitted' for r in canary):
    save(OUT/'status.json',{'stage':'canary_failed','records':len(canary),'atUtc':now()},True);return
   pending=set();remaining=iter(jobs[4:])
   while True:
    while len(pending)<4 and not STOP.is_set():
     try:task,arm=next(remaining)
     except StopIteration:break
     pending.add(pool.submit(solve,task,arm,s))
    if not pending:break
    done,pending=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
    for f in done:f.result()
 finally:s.shutdown()
 summary()
def summary():
 rows=[read(p) for p in (OUT/'results').glob('*/*.json')];calls=[read(p) for p in (OUT/'calls').glob('*/*/*/receipt.json')]
 out={}
 for arm in ARMS:
  group=[r for r in rows if r['arm']==arm];receipts=[read(p) for p in (OUT/'calls'/arm).glob('*/*/receipt.json')]
  good=[r for r in group if r['valid']];passed=sum(r.get('grade',{}).get('passed',False) for r in good)
  out[arm]={'completed':len(group),'valid':len(good),'passed':passed,'unknown':len(group)-len(good),'accuracyFixed20':passed/20,'accuracyUpperBound':(passed+len(group)-len(good)+(20-len(group)))/20,'requests':len(receipts),'promptTokens':sum((r['usage'] or {}).get('prompt_tokens',0) for r in receipts),'completionTokens':sum((r['usage'] or {}).get('completion_tokens',0) for r in receipts),'estimateLowerUsd':sum((r['estimate'] or {}).get('lowerUsd',0) for r in receipts),'estimateUpperUsd':sum((r['estimate'] or {}).get('upperUsd',0) for r in receipts),'unknownCostRequests':sum(r['estimate'] is None for r in receipts),'actualUsd':None,'secondsSum':sum(r['seconds'] for r in group)}
 result={'stage':'complete' if len(rows)==80 and all(r['valid'] for r in rows) else 'complete_with_exceptions','atUtc':now(),'byArm':out,'totalCompleted':len(rows),'totalRequests':len(calls),'fullRunStarted':False}
 save(OUT/'summary.json',result,True);print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
