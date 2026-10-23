"""Durable paid-request journal with atomic task/account reservations."""
import hashlib,json,os,pathlib,threading,time,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'outputs';CFG=json.loads((ROOT/'package/experiment.json').read_text());LOCK=threading.RLock()
KEY=os.environ.get('OPENROUTER_API_KEY','');RESERVED={};ACCOUNT_RESERVED=0.0;ACCOUNT_REMAINING=None;HALT=threading.Event()
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp-'+str(threading.get_ident()));tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(p)
def durable(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def digest(v):return hashlib.sha256((v if isinstance(v,str) else json.dumps(v,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
def receipts(d):return [json.loads(p.read_text()) for p in d.rglob('receipt.json')]
def accounting(d):
    rr=receipts(d);orphans=[p for p in d.rglob('dispatch.json') if not (p.parent/'receipt.json').exists()]
    unknown=sum(1 for r in rr if r.get('unknownCost'))+len(orphans)
    reserve=sum(r.get('actualCostUsd') if r.get('actualCostUsd') is not None else r['reservedUpperBoundUsd'] for r in rr)+sum(json.loads(p.read_text())['reservedUpperBoundUsd'] for p in orphans)
    return {'actualCostUsd':sum(r.get('actualCostUsd') or 0 for r in rr),'accountedUpperBoundUsd':reserve,'unknownCostCount':unknown,'modelCalls':len(rr)+len(orphans),'generationIds':[r['generationId'] for r in rr if r.get('generationId')]}
class TaskBudgetStop(Exception):pass
class AccountStop(Exception):
    def __init__(self,message):HALT.set();super().__init__(message)
class UnknownDispatch(Exception):pass
def public_json(url):
    with urllib.request.urlopen(url,timeout=30) as f:return json.load(f)
def preflight():
    global ACCOUNT_REMAINING
    endpoint=public_json('https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash/endpoints');e=next(x for x in endpoint['data']['endpoints'] if x['tag']=='digitalocean')
    assert float(e['pricing']['prompt'])<=.3/1e6 and float(e['pricing']['completion'])<=1.2/1e6
    required={'reasoning','temperature','max_tokens','tools','tool_choice'};assert required<=set(e['supported_parameters'])
    observed={}
    for part in ['credits','key']:
        request=urllib.request.Request('https://openrouter.ai/api/v1/'+part,headers={'Authorization':'Bearer '+KEY})
        with urllib.request.urlopen(request,timeout=30) as r:observed[part]=json.load(r)['data']
    a=observed['credits'];k=observed['key'];kr=k.get('limit_remaining')
    if kr is None:kr=float('inf') if k.get('limit') is None else k['limit']-k['usage']
    ACCOUNT_REMAINING=min(a['total_credits']-a['total_usage'],kr)
    save(OUT/'provider-preflight.json',{'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'endpoint':e,'remainingUsd':ACCOUNT_REMAINING,'keyLimit':k.get('limit'),'keyRemaining':None if kr==float('inf') else kr})
    if ACCOUNT_REMAINING<=0:raise AccountStop('InsufficientBalance')
def strict_schema(q):
    if isinstance(q,list):return [strict_schema(x) for x in q]
    if not isinstance(q,dict):return q
    q={k:strict_schema(v) for k,v in q.items()}
    if q.get('type')=='object':q['additionalProperties']=False
    return q
def wire(body):
    w=dict(body);w.update(model=CFG['model'],stream=False,temperature=0,max_tokens=16384,provider={'only':['digitalocean'],'allow_fallbacks':False,'max_price':{'prompt':.3,'completion':1.2}},reasoning={'enabled':True,'effort':'high','exclude':False})
    for k in ['seed','thinking','reasoning_effort','max_completion_tokens']:w.pop(k,None)
    if isinstance(w.get('tool_choice'),dict):
        wanted=w['tool_choice'].get('function',{}).get('name');w['tools']=[t for t in w.get('tools',[]) if t.get('function',{}).get('name')==wanted];w['tool_choice']='auto'
    if 'tools' in w:w['tools']=strict_schema(w['tools'])
    return w
def call(taskdir,logical,body,remaining_seconds=600):
    global ACCOUNT_RESERVED,ACCOUNT_REMAINING
    w=wire(body);raw=json.dumps(w,ensure_ascii=False,separators=(',',':')).encode();reserve=len(raw)*.3/1e6+16384*1.2/1e6
    taskid=str(taskdir);arm=taskdir.parent.name;cap=.025 if arm=='baseline' else .1;calls=taskdir/'calls'/logical
    for attempt in range(3):
        if HALT.is_set():raise AccountStop('CampaignStopped')
        d=calls/('attempt-'+str(attempt));rp=d/'receipt.json'
        with LOCK:
            if rp.exists():
                receipt=json.loads(rp.read_text());response=(d/'response.raw.txt').read_text() if (d/'response.raw.txt').exists() else ''
                if (d/'request.json').exists() and digest(json.loads((d/'request.json').read_text()))!=digest(w):raise RuntimeError('LogicalRequestChanged')
                cached=True
            else:
                cached=False
                if (d/'dispatch.json').exists():raise UnknownDispatch('InterruptedPaidDispatch:'+str(d))
                spent=accounting(taskdir)['accountedUpperBoundUsd']
                if spent+RESERVED.get(taskid,0)+reserve>cap+1e-12:raise TaskBudgetStop('TaskDollarCap')
                if ACCOUNT_REMAINING is None or ACCOUNT_REMAINING-ACCOUNT_RESERVED<reserve:raise AccountStop('AccountOrKeyBalance')
                RESERVED[taskid]=RESERVED.get(taskid,0)+reserve;ACCOUNT_RESERVED+=reserve
                durable(d/'request.json',w);durable(d/'dispatch.json',{'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'dispatchAtMs':int(time.time()*1000),'requestSha256':hashlib.sha256(raw).hexdigest(),'reservedUpperBoundUsd':reserve})
        if not cached:
            started=time.monotonic();status=0;response='';value={};fault=None
            req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=raw,headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json','X-OpenRouter-Title':'ObjRun LLM-SRBench release240 20261019'})
            try:
                try:r=urllib.request.urlopen(req,timeout=max(1,min(600,remaining_seconds)))
                except urllib.error.HTTPError as e:r=e
                with r:status=r.status;response=r.read().decode('utf8')
                try:value=json.loads(response)
                except ValueError:fault='NonJSONResponse'
            except Exception as e:fault=type(e).__name__+':'+str(e)
            usd=value.get('usage',{}).get('cost');usd=usd if isinstance(usd,(int,float)) and usd>=0 else None
            rejected=status in [400,401,402,403,404,429] and not value.get('id') and not value.get('usage')
            if rejected:usd=0.0
            receipt={'atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'completedAtMs':int(time.time()*1000),'httpStatus':status,'generationId':value.get('id'),'provider':value.get('provider'),'model':value.get('model'),'usage':value.get('usage'),'actualCostUsd':usd,'unknownCost':usd is None,'reservedUpperBoundUsd':reserve,'requestSha256':hashlib.sha256(raw).hexdigest(),'seconds':time.monotonic()-started,'finishReason':value.get('choices',[{}])[0].get('finish_reason') if value.get('choices') else None,'fault':fault or value.get('error')}
            with LOCK:
                (d/'response.raw.txt').write_text(response,encoding='utf8');durable(rp,receipt)
                RESERVED[taskid]-=reserve;ACCOUNT_RESERVED-=reserve;ACCOUNT_REMAINING-=usd if usd is not None else reserve
            if usd is not None and usd>reserve+1e-7:raise AccountStop('PriceReservationExceeded')
        if receipt['httpStatus']==200:
            value=json.loads(response)
            if value.get('provider')!='DigitalOcean' or not str(value.get('model','')).startswith(CFG['model']):raise AccountStop('UnexpectedProviderOrModel')
            if not value.get('choices') or value.get('error'):raise RuntimeError('ProviderResponseFault')
            return value
        if receipt['httpStatus'] in [401,402,403]:raise AccountStop('ProviderHTTP'+str(receipt['httpStatus']))
        if receipt['unknownCost']:raise UnknownDispatch('UnknownPaidResponse:'+str(d))
        if receipt['httpStatus']!=429 and receipt['httpStatus']<500:raise RuntimeError('ProviderHTTP'+str(receipt['httpStatus']))
        if attempt==2:raise RuntimeError('FiniteProviderRetriesExhausted')
        time.sleep(attempt+1)
    raise RuntimeError('FiniteRequestChainExhausted')
