"""Separate one-attempt infrastructure round; never imports original analysis results."""
import concurrent.futures,hashlib,json,pathlib,sys,threading,time
CONTROL=pathlib.Path(__file__).resolve().parent;ROOT=CONTROL.parent;OUT=ROOT/'outputs'
MAIN=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/llm-srbench-20261019-v2');V1=MAIN.with_name('llm-srbench-20261019-v1')
sys.path.insert(0,str(ROOT/'package'))
sys.path.insert(0,str(CONTROL))
import common,run as core
load=lambda p:json.loads(pathlib.Path(p).read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def utc():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def live(pid,entry):
    p=pathlib.Path('/proc')/str(pid)/'cmdline';return p.exists() and str(entry).encode() in p.read_bytes().split(b'\0')
def ledger(directory):
    actual=upper=0.;unknown=[];calls=0
    for p in pathlib.Path(directory).rglob('dispatch.json'):
        d=load(p);rp=p.parent/'receipt.json';r=load(rp) if rp.exists() else {};v=r.get('actualCostUsd');actual+=v or 0;upper+=v if v is not None else d['reservedUpperBoundUsd'];calls+=1
        if v is None:unknown.append({'path':str(p.parent),'reserveUsd':d['reservedUpperBoundUsd'],'dispatchAtMs':d['dispatchAtMs'],'receiptPresent':rp.exists(),'generationId':r.get('generationId'),'fault':r.get('fault')})
    return {'actualCostUsd':actual,'accountedUpperBoundUsd':upper,'unknownReserveUsd':sum(x['reserveUsd'] for x in unknown),'unknownRequests':unknown,'modelCalls':calls}
def source_pins():
    files=[p for p in (ROOT/'package').rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'node_modules' not in p.parts]
    files += [p for p in CONTROL.iterdir() if p.suffix in ['.py','.md'] or p.name in ['plan.json','main-freeze.json','base-source-pins.json','base-experiment.json']]
    return [{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in sorted(files)]
def verify_sources():assert source_pins()==load(CONTROL/'source-pins.json'),'InfrastructureRoundSourceChanged'
def verify_originals():
    f=load(CONTROL/'main-freeze.json')
    for x in f['files']:assert sha(pathlib.Path(x['path']))==x['sha256'],('OriginalEvidenceChanged',x['path'])
    return f
class Pool:
    def __init__(self,name,n=16):self.name=name;self.capacity=n;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=n,thread_name_prefix=name);self.lock=threading.Lock();self.active=self.peak=self.submitted=self.completed=0
    def submit(self,fn,*args,**kw):
        with self.lock:self.submitted+=1
        def work():
            with self.lock:self.active+=1;self.peak=max(self.peak,self.active)
            try:return fn(*args,**kw)
            finally:
                with self.lock:self.active-=1;self.completed+=1
        return self.pool.submit(work)
    def shutdown(self,wait=True):self.pool.shutdown(wait=wait)
    def metrics(self):
        with self.lock:return {'capacity':self.capacity,'active':self.active,'peak':self.peak,'submitted':self.submitted,'completed':self.completed}
