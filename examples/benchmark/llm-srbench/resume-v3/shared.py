"""Independent continuation and one subsequent repair round; public/train only."""
import concurrent.futures,hashlib,json,math,os,pathlib,sys,threading,time
CONTROL=pathlib.Path(__file__).resolve().parent
ROOT=CONTROL.parent
OUT=ROOT/'outputs'
BASE=pathlib.Path('/mnt/aliyunsb/pingxingwang/tgengin-bench')
HISTORY=[BASE/('llm-srbench-20261019-'+s) for s in ['v1','v2','infra-r1']]
sys.path.insert(0,str(ROOT/'package'));sys.path.insert(0,str(CONTROL))
import common,run as core
load=lambda p:json.loads(pathlib.Path(p).read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def utc():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def live(pid,entry):
    p=pathlib.Path('/proc')/str(pid)/'cmdline'
    return p.exists() and str(entry).encode() in p.read_bytes().split(b'\0')
def pid_in_root(pid,root):
    p=pathlib.Path('/proc')/str(pid)/'cmdline'
    return p.exists() and str(root).encode() in p.read_bytes()
def ledger(d):
    actual=[];upper=[];unknown=[];calls=0
    for p in sorted(pathlib.Path(d).rglob('dispatch.json'),key=lambda p:p.as_posix()):
        dispatch=load(p);rp=p.parent/'receipt.json';r=load(rp) if rp.exists() else {};v=r.get('actualCostUsd');calls+=1
        assert v is None or isinstance(v,(int,float)) and math.isfinite(v) and v>=0
        reserve=dispatch['reservedUpperBoundUsd'];assert isinstance(reserve,(int,float)) and math.isfinite(reserve) and reserve>0
        actual.append(v or 0);upper.append(v if v is not None else reserve)
        if v is None:unknown.append({'path':str(p.parent),'reserveUsd':reserve,'dispatchAtMs':dispatch['dispatchAtMs'],'receiptPresent':rp.exists(),'generationId':r.get('generationId'),'fault':r.get('fault')})
    return {'actualCostUsd':math.fsum(actual),'accountedUpperBoundUsd':math.fsum(upper),'unknownReserveUsd':math.fsum(u['reserveUsd'] for u in unknown),'unknownRequests':unknown,'modelCalls':calls}
def cap(arm):return .025 if arm=='baseline' else .1
def round_out(name):
    assert name in ['main','repair']
    return ROOT/'rounds'/name/'outputs'
def set_round(name,prior):
    d=round_out(name);d.mkdir(parents=True,exist_ok=True)
    common.OUT=core.OUT=d
    common.CFG.update(priorUpperBoundUsd=prior['accountedUpperBoundUsd'],priorUnknownReserveUsd=prior['unknownReserveUsd'])
    return d
def source_pins():
    files=[p for p in (ROOT/'package').rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'node_modules' not in p.parts]
    files += [p for p in CONTROL.iterdir() if p.suffix in ['.py','.md','.patch'] or p.name in ['plan.json','history-freeze.json','base-source-pins.json','base-experiment.json','backend-patch.json']]
    return sorted([{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in files],key=lambda e:e['path'])
def verify_sources():assert source_pins()==load(CONTROL/'source-pins.json'),'ContinuationSourceChanged'
def verify_history():
    for e in load(CONTROL/'history-freeze.json')['files']:assert sha(pathlib.Path(e['path']))==e['sha256'],('HistoricalEvidenceChanged',e['path'])
def processes_exited(root):
    state=load(root/'outputs/status.json')
    for field,default in [('pid','run.py'),('graderPid','grader.py')]:
        entry=state.get('controllerEntry' if field=='pid' else 'graderEntry',str(root/'package'/default))
        if live(state.get(field,0),entry):return False
    for p in (root/'outputs/tasks').glob('*/*/native-process.json'):
        q=load(p)
        if live(q['pid'],root/'package/native.ts'):return False
    for p in (root/'outputs/tasks').glob('*/*/native/engine-process.json'):
        if pid_in_root(load(p)['pid'],root):return False
    return True
class Pool:
    def __init__(self,name,n=16):
        self.capacity=n;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=n,thread_name_prefix=name);self.lock=threading.Lock();self.active=self.peak=self.submitted=self.completed=0
    def submit(self,fn,*a,**kw):
        with self.lock:self.submitted+=1
        def work():
            with self.lock:self.active+=1;self.peak=max(self.peak,self.active)
            try:return fn(*a,**kw)
            finally:
                with self.lock:self.active-=1;self.completed+=1
        return self.pool.submit(work)
    def metrics(self):
        with self.lock:return {'capacity':self.capacity,'active':self.active,'peak':self.peak,'submitted':self.submitted,'completed':self.completed}
    def shutdown(self,wait=True):self.pool.shutdown(wait=wait)
