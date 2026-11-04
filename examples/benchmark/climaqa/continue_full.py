"""Continue only never-started jobs after the main controller has exited."""
import concurrent.futures, json, os, sys
from pathlib import Path
import run_full as f
import run

def alive(pid):
    # Windows: Python process liveness check without signals or process mutation.
    import ctypes
    handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
    if not handle:return False
    code=ctypes.c_ulong();ok=ctypes.windll.kernel32.GetExitCodeProcess(handle,ctypes.byref(code));ctypes.windll.kernel32.CloseHandle(handle)
    return bool(ok and code.value==259)

def snapshot(stage):
    rows=[]
    for p in (f.FULL/'results').glob('*/*.json'):
        try:rows.append(run.read(p))
        except (json.JSONDecodeError,OSError):continue
    try:run.save(f.FULL/'status-continuation.json',{'atUtc':run.now(),'stage':stage,'pid':os.getpid(),'completedReadable':len(rows),'byArm':{a:sum(x['arm']==a for x in rows) for a in f.ARMS}})
    except OSError:pass  # A Windows reader can briefly hold the old status file open.

def main():
    if not (f.FULL/'execution-started.json').exists() or (f.FULL/'finished.json').exists():raise RuntimeError('IncorrectContinuationState')
    previous=run.read(f.FULL/'execution-started.json')['pid'];assert not alive(previous),'OriginalControllerStillAlive'
    if (f.FULL/'continuation-started.json').exists():raise RuntimeError('ContinuationAlreadyStarted')
    pins=run.read(f.FULL/'source-pins.json')['files'];assert all(run.sha((f.ROOT/p).read_bytes())==v for p,v in pins.items())
    run.OUT=f.FULL;run.KEY=f.key_from_env();run.BOOK={r['id']:r['answer'] for r in run.read(f.FULL/'private.json')};run.model=f.protected_model;run.grade=f.journaled_grade;run.native=f.checked_native
    public=run.read(f.FULL/'public.json');jobs=[];unresolved=[]
    for i,t in enumerate(public):
        for j in range(4):
            arm=f.ARMS[(i+j)%4];result=f.FULL/'results'/arm/(t['id']+'.json');started=f.FULL/'tasks'/arm/t['id']/'started.json'
            if result.exists():
                r=run.read(result);assert r['arm']==arm and r['id']==t['id'];continue
            if started.exists():unresolved.append({'id':t['id'],'arm':arm});continue
            jobs.append((t,arm))
    if unresolved:raise RuntimeError('StartedWithoutResultRequiresInspection:'+json.dumps(unresolved))
    unsettled=[str(p) for p in (f.FULL/'calls').glob('*/*/*/dispatch.json') if not p.with_name('receipt.json').exists()]
    if unsettled:raise RuntimeError('UnsettledCallsRequireInspection:'+json.dumps(unsettled))
    run.save(f.FULL/'continuation-started.json',{'atUtc':run.now(),'priorPid':previous,'pid':os.getpid(),'neverStartedJobs':len(jobs),'originalResultsRetained':900-len(jobs),'capacity':32},True)
    s=run.server();f.status=snapshot
    try:
        f.schedule(jobs,s,capacity=32)
        if len(list((f.FULL/'results').glob('*/*.json')))!=900 or run.STOP.is_set():snapshot('needs_attention');return
        snapshot('exception_recovery');f.recover_exceptions(public,s)
        assert all(run.sha((f.ROOT/p).read_bytes())==v for p,v in pins.items())
        run.save(f.FULL/'finished.json',{'atUtc':run.now(),'mainResults':900,'continuation':True,'recoveryScope':str(f.FULL/'exception-recovery-v1/scope.json')},True)
        snapshot('finished')
    finally:s.shutdown()
if __name__=='__main__':main()
