"""Independent concurrency control; the frozen solver and fitter stay unchanged."""
import concurrent.futures,hashlib,importlib.util,json,pathlib,sys,threading,time
CONTROL=pathlib.Path(__file__).resolve().parent;ROOT=CONTROL.parents[1];OUT=ROOT/'outputs';OLD=OUT/'continuation-429'
sys.path.insert(0,str(ROOT/'package'));sys.path.insert(0,str(OLD))
import common,run as core,audit_exception
spec=importlib.util.spec_from_file_location('approved429',OLD/'runner.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
load=lambda p:json.loads(pathlib.Path(p).read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def pins():return [{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in sorted(CONTROL.iterdir()) if p.suffix in ['.py','.md'] or p.name=='plan.json']
def live(pid,entry):
    p=pathlib.Path('/proc')/str(pid)/'cmdline'
    return p.exists() and str(entry).encode() in p.read_bytes().split(b'\0')
def preserve():
    p=load(CONTROL/'plan.json');assert core.sourcepins()==load(OUT/'source-pins.json'),'FrozenPackageChanged'
    assert old.source_pins()==load(OLD/'source-pins.json'),'OriginalControlChanged'
    review=audit_exception.inspect(ROOT,False);assert review['approvedExceptionAuditPassed'],review
    for path,digest in p['protectedFiles'].items():assert sha(ROOT/path)==digest,('PriorCellChanged',path)
    for cell,paths in p['protectedCallFiles'].items():assert sorted(x.relative_to(ROOT).as_posix() for x in (OUT/'tasks'/cell/'calls').rglob('*') if x.is_file())==paths,('PriorCallsChanged',cell)
    allowed={(e['arm'],e['key']) for e in p['remainingCells']};protected={tuple(e) for e in p['protectedCells']}
    original={(e['arm'],e['key']) for e in load(ROOT/'package/continuation-plan.json')['allowedCells']}
    assert not allowed&protected and allowed|protected==original and len(original)==483
    return p
class MeteredPool:
    def __init__(self,n,name):
        self.capacity=n;self.name=name;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=n,thread_name_prefix=name);self.lock=threading.RLock();self.active=0;self.peak=0;self.submitted=0;self.completed=0
    def submit(self,fn,*args,**kwargs):
        with self.lock:self.submitted+=1
        def work():
            with self.lock:self.active+=1;self.peak=max(self.peak,self.active)
            try:return fn(*args,**kwargs)
            finally:
                with self.lock:self.active-=1;self.completed+=1
        return self.pool.submit(work)
    def metrics(self):
        with self.lock:return {'capacity':self.capacity,'active':self.active,'peak':self.peak,'submitted':self.submitted,'completed':self.completed,'queued':self.submitted-self.completed-self.active}
    def shutdown(self,wait=True):self.pool.shutdown(wait=wait)
