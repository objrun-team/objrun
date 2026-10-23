"""One fresh, isolated attempt using the byte-identical frozen solver."""
from pathlib import Path
import os
import sys
import time
import urllib.error
from core import read,save,sha,now,valid,Lease,namespaced

def main():
    root=Path(sys.argv[1]).resolve();home=Path(sys.argv[2]).resolve();meta=read(home/'attempt.json');frozen=root/'frozen'
    sys.path.insert(0,str(frozen/'package'))
    import runtime as rt
    import controller as c
    rt.OUT=home/'outputs/canonical';c.OUT=rt.OUT;rt.OUT.mkdir(parents=True,exist_ok=True)
    # This is the sole method-clock override: fresh trials never resume v1/v2 time.
    rt.CFG.pop('canaryTransportRecovery',None)
    assert c.CFG is rt.CFG and rt.CFG['solveSeconds']==600 and rt.CFG['logicalCallMaxAttempts']==3
    save(home/'effective-config.json',rt.CFG,True)
    c.status=lambda:None
    class Router(rt.OpenRouter):
        def __init__(self):super().__init__();self.total=Lease(root)
        def get(self,path):
            for n in range(3):
                try:return super().get(path)
                except (urllib.error.URLError,TimeoutError):
                    if n==2:raise
                    time.sleep(n+1)
        def call(self,logical,category,body,deadline):return super().call(namespaced(logical,meta['number']),category,body,deadline)
    server=None;judge=None;client=None;result=None;error=None;start=time.time()
    try:
        c.frozen(True)
        client=Router();client.observe();c.client=client;judge=rt.Judge(c.book)
        import secrets
        token=secrets.token_hex(32);server=rt.broker(client,judge,token)
        task=next(t for t in c.public if t['id']==meta['id'])
        assert rt.digest(task['prompt'])==meta['promptSha256']
        result=c.solve(task,meta['arm'],judge,server,token)
    except Exception as e:error=(type(e).__name__+':'+str(e)).replace(os.environ.get('OPENROUTER_API_KEY','\0'),'[REDACTED]')[:1500]
    finally:
        if server:server.shutdown()
        if judge:judge.pool.shutdown(wait=True)
    resultpath=rt.OUT/'results'/meta['arm']/(meta['id']+'.json')
    # Candidate stays frozen. Settle already-dispatched receipts before validity audit.
    end_wait=time.time()+15
    while client and client.metrics()['apiConcurrency'] and time.time()<end_wait:time.sleep(.1)
    incomplete=[]
    for d in (rt.OUT/'calls').glob('**/dispatch.json'):
        if not (d.parent.parent/'complete.json').exists() and (not d.with_name('receipt.json').exists() or read(d.with_name('receipt.json')).get('error')):incomplete.append(d.relative_to(home).as_posix())
    if result and result['solverValid'] and incomplete:
        save(home/'late-transport-observation.json',{'frozenOriginalResultSha256':sha(resultpath),'incompleteDispatches':incomplete,'atUtc':now()},True)
        result={**result,'solverValid':False,'transportIncomplete':True,'lateTransportObservation':'candidate and grade unchanged; unsettled or failed transmission after frozen solver result'}
        resultpath=home/'adjudicated-result.json';save(resultpath,result,True)
    stop=client.stop if client else None
    combined_error=error or (result or {}).get('error')
    account_block=bool(stop and any(x in stop for x in ['AccountOrKey','Fault:401','Fault:402','Fault:403'])) or bool(combined_error and any(x in combined_error for x in ['HTTP Error 401','HTTP Error 402','HTTP Error 403']))
    save(home/'terminal.json',{'number':meta['number'],'identity':meta['identity'],'arm':meta['arm'],'id':meta['id'],'valid':valid(result),
        'result':str(resultpath.relative_to(home)) if resultpath.exists() else None,'resultSha256':sha(resultpath) if resultpath.exists() else None,
        'error':error or (result or {}).get('error'),'stopReason':stop,'requiresUser':account_block,'startedEpoch':start,'endedEpoch':time.time(),'atUtc':now(),
        'fullSolveBudgetSeconds':600,'oldTimeOrCandidateReused':False,'classification':'first-valid-stop' if valid(result) else 'infrastructure-retry'},True)

if __name__=='__main__':main()
