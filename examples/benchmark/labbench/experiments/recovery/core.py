"""Independent retry orchestration and provenance; frozen solver stays unchanged."""
from pathlib import Path
import hashlib
import json
import time
import datetime as dt

NAME='labbench-infra-recovery-20261019-v1-digitalocean'

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value,exclusive=False):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    if exclusive:
        with p.open('xb') as f:f.write(raw)
    else:
        tmp=p.with_name(p.name+'.tmp');tmp.write_bytes(raw);tmp.replace(p)
def valid(r):return bool(r and r.get('solverValid') and r.get('grade',{}).get('valid'))
def key(job):return job['arm']+'/'+job['id']
def attempt_home(root,job,n):return Path(root)/'attempts'/job['arm']/job['id']/('attempt-%04d'%n)
def first_valid(attempts):
    found=[a for a in sorted(attempts,key=lambda a:a['number']) if a['valid']]
    return found[0] if found else None
def namespaced(logical,number):
    tid,arm,tail=logical.split('/',2)
    return tid+'/'+arm+'/recovery-%04d/'%number+tail
def cooldown(failures,degraded=False):return min(1800,(120 if degraded else 60)*2**min(max(0,failures-1),5))
def verify_frozen(root):
    root=Path(root)
    for m in ['source-pins.json','dependencies.json']:
        for p,h in read(root/'provenance'/m)['files'].items():
            if sha(root/p)!=h:raise RuntimeError('FrozenMismatch:'+p)
def original_guard(root):
    root=Path(root);out=root/'outputs/canonical'
    assert read(out/'final-freeze.json')['count']==1416 and read(out/'AUDIT.json')['allPassed']
    for p,h in read(out/'file-inventory.json').items():
        if sha(root/p)!=h:raise RuntimeError('OriginalChanged:'+p)
    verify_frozen(root)

class Lease:
    """Cross-process model slots; queue time stays inside the 600-second clock."""
    def __init__(self,root):
        import threading
        self.root=Path(root);self.local=threading.local()
    def acquire(self,timeout):
        import fcntl
        deadline=time.time()+timeout;home=self.root/'control/slots';home.mkdir(parents=True,exist_ok=True)
        while True:
            slots=read(self.root/'control/admission.json')['modelSlots']
            for n in range(slots):
                f=(home/str(n)).open('a+b')
                try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);self.local.handle=f;return True
                except BlockingIOError:f.close()
            if time.time()>=deadline:return False
            time.sleep(min(.05,max(0,deadline-time.time())))
    def release(self):
        import fcntl
        handle=getattr(self.local,'handle',None)
        if handle:fcntl.flock(handle,fcntl.LOCK_UN);handle.close();self.local.handle=None

def ledger(roots):
    groups={};events=[];identities=set()
    for home in roots:
        home=Path(home);meta=read(home/'attempt.json');arm=meta['arm']
        g=groups.setdefault(arm,{'requests':0,'knownActualCostUsd':0.,'unknownCostRequests':0,'unsettledRequests':0,'failedRequests':0,'promptTokens':0,'completionTokens':0,'cacheHitTokens':0,'modelSeconds':0.})
        for p in (home/'outputs/canonical/calls').glob('**/dispatch.json'):
            identity=meta['identity']+'/'+p.relative_to(home).as_posix();assert identity not in identities;identities.add(identity);g['requests']+=1
            d=read(p);q=p.with_name('receipt.json')
            if not q.exists():g['unknownCostRequests']+=1;g['unsettledRequests']+=1;continue
            r=read(q);u=r.get('usage') or {};g['promptTokens']+=u.get('prompt_tokens',0);g['completionTokens']+=u.get('completion_tokens',0);g['cacheHitTokens']+=(u.get('prompt_tokens_details') or {}).get('cached_tokens',0)
            g['modelSeconds']+=r['seconds'];g['failedRequests']+=bool(r.get('error'))
            if r['actualCostUsd'] is None:g['unknownCostRequests']+=1
            else:g['knownActualCostUsd']+=r['actualCostUsd']
            events.extend([(r['startedEpoch'],1),(r['endedEpoch'],-1)])
    active=peak=0
    for _,delta in sorted(events,key=lambda x:(x[0],x[1])):active+=delta;peak=max(peak,active)
    return {'byArm':groups,'peakApiConcurrencyObserved':peak,'costLabel':'OpenRouter usage.cost; absent fees remain unknown; includes every failed and successful recovery attempt only'}
