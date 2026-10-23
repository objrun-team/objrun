"""Admission pauses until every unknown call and its native cell have settled."""
from shared import *

class GlobalFault(RuntimeError):pass

class Admission:
    def __init__(self):
        self.condition=threading.Condition(threading.RLock());self.paused=set();self.active={};self.closed=False
    def begin_call(self,d):
        with self.condition:self.active[str(d)]=self.active.get(str(d),0)+1
    def end_call(self,d):
        with self.condition:
            self.active[str(d)]-=1
            common.save(pathlib.Path(d)/'provider-call-state.json',{'ownerPid':os.getpid(),'active':self.active[str(d)],'localCallReturnedAtMs':int(time.time()*1000),'localHttpOperationEnded':self.active[str(d)]==0})
            self.condition.notify_all()
    def unknown(self,d):
        with self.condition:self.paused.add(str(d));self.condition.notify_all()
    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()
    def claim(self,jobs,claim):
        with self.condition:
            self.condition.wait_for(lambda:self.closed or common.HALT.is_set() or not self.paused)
            if self.closed or common.HALT.is_set():return None
            try:e=next(jobs)
            except StopIteration:return None
            claim(e)
            return e
    def settle(self,d,wait_seconds=30):
        d=pathlib.Path(d)
        with self.condition:assert self.active.get(str(d),0)==0,'ProviderCallStillActive'
        end=time.monotonic()+wait_seconds
        while True:
            processes=[]
            for p,entry in [(d/'native-process.json',ROOT/'package/native.ts')]:
                if p.exists() and live(load(p)['pid'],entry):processes.append(load(p)['pid'])
            p=d/'native/engine-process.json'
            if p.exists() and pid_in_root(load(p)['pid'],ROOT):processes.append(load(p)['pid'])
            if not processes:break
            if time.monotonic()>=end:raise GlobalFault('UnknownCellNativeStillLive:'+str(d))
            time.sleep(.1)
        m=ledger(d)
        if m['accountedUpperBoundUsd']>cap(d.parent.name)+1e-7:raise GlobalFault('UnknownCellDollarCap')
        proofs=[]
        for u in m['unknownRequests']:
            p=pathlib.Path(u['path']);dispatch=load(p/'dispatch.json')
            if not (p/'receipt.json').exists():raise GlobalFault('UnknownDispatchWithoutTerminalReceipt')
            receipt=load(p/'receipt.json');request=load(p/'request.json')
            assert request['model']=='deepseek/deepseek-v4.1-flash' and request.get('max_tokens')==16384
            assert request.get('provider',{}).get('only')==['digitalocean'] and request['provider'].get('allow_fallbacks') is False
            assert request['provider']['max_price']=={'prompt':.3,'completion':1.2}
            raw=json.dumps(request,ensure_ascii=False,separators=(',',':')).encode()
            bound=len(raw)*.3/1e6+16384*1.2/1e6
            if hashlib.sha256(raw).hexdigest()!=dispatch['requestSha256']:raise GlobalFault('UnknownRequestDigestChanged')
            if not math.isclose(bound,dispatch['reservedUpperBoundUsd'],abs_tol=1e-10):raise GlobalFault('UntrustworthyUnknownCostBound')
            if not receipt.get('completedAtMs') or receipt['completedAtMs']<dispatch['dispatchAtMs']:raise GlobalFault('UnknownRequestNotTerminal')
            if not math.isclose(receipt['reservedUpperBoundUsd'],bound,abs_tol=1e-10):raise GlobalFault('UnknownReceiptReserveChanged')
            proofs.append({'requestDirectory':str(p),'requestSha256':sha(p/'request.json'),'dispatchSha256':sha(p/'dispatch.json'),'receiptSha256':sha(p/'receipt.json'),'reservedUpperBoundUsd':bound,'localHttpOperationEnded':True,'remoteBillingUnresolved':True,'originalRequestNeverReplayed':True})
        proof={'atUtc':utc(),'ownerPid':os.getpid(),'localCallsActive':0,'nativeExited':True,'accounting':m,'trustedBoundAndFullReserve':True,'unknownRequests':proofs,'noRemoteBillingClaim':True,'safeToContinueOtherUnstartedCells':True}
        common.durable(d/'isolation-settlement.json',proof)
        with self.condition:self.paused.discard(str(d));self.condition.notify_all()
        return proof
