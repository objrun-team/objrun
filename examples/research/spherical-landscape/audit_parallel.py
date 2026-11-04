"""Same frozen checker, bounded parallel CPU verification; no search/model work.
Workers write private files then atomically install complete reports and arrays.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import concurrent.futures as cf,json,hashlib,sys,time,re,threading
from pathlib import Path
from datetime import datetime,timezone
import psutil
from checker import check

def atom(path,obj):
    tmp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp');tmp.write_text(json.dumps(obj,indent=2));os.replace(tmp,path)
def worker(runstr,key):
    run=Path(runstr);artifact=run/'verified'/(key+'.candidate.json');out=run/'verified'/(key+'.json')
    try:
        if out.exists():
            r=json.loads(out.read_text())
            if r.get('input_sha256')!=key or len(r.get('quotient_spectrum',[]))<1:raise ValueError('incomplete report')
        else:raise ValueError('missing')
    except (ValueError,OSError):
        tmp=run/'verified'/(key+f'.worker-{os.getpid()}.json');r=check(artifact,tmp,run/'baseline-audit.json')
        os.replace(tmp.with_suffix('.npz'),out.with_suffix('.npz'));os.replace(tmp,out)
    summary={k:v for k,v in r.items() if k not in ['gram','perturbations','full_tangent_spectrum','quotient_spectrum']}
    summary.update(artifact=str(artifact),report=str(out),min_quotient_eigenvalue=r['quotient_spectrum'][0],checked_utc=datetime.now(timezone.utc).isoformat())
    return summary

def main(run):
    run=run.resolve();end=json.loads((run/'deadline.json').read_text())['deadline_epoch'];frozen=json.loads((run/'frozen-g.json').read_text())
    def stop():
        time.sleep(max(0,end-time.time()))
        for p in psutil.Process().children(recursive=True):
            try:p.kill()
            except psutil.Error:pass
        os._exit(124)
    threading.Thread(target=stop,daemon=True).start()
    try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except (AttributeError,psutil.Error):pass
    done={p.stem for p in (run/'verified').glob('*.json') if re.fullmatch('[a-f0-9]{64}',p.stem)}
    # Repair any interrupted last writes before trusting the previous auditor.
    recent=sorted((run/'verified').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]
    for p in recent:
        if p.stem in done:
            try:json.loads(p.read_text())
            except ValueError:done.discard(p.stem)
    seenfiles={};waiting={};inflight={};lastscan=0;last=None;best={}
    if (run/'best-interesting.json').exists():best=json.loads((run/'best-interesting.json').read_text())
    with cf.ProcessPoolExecutor(max_workers=4) as pool:
        while time.time()<end:
            if time.time()-lastscan>10:
                lastscan=time.time()
                for n,h in frozen['files'].items():assert hashlib.sha256((run/n).read_bytes()).hexdigest()==h,'Frozen checker changed'
                for p in list((run/'work/candidates').glob('*.json'))+[run/'work/candidate.json']:
                    if p.name.endswith(('.initial.json','.trace.json')) or not p.exists():continue
                    st=p.stat();finger=(st.st_size,st.st_mtime_ns)
                    if seenfiles.get(str(p))==finger:continue
                    try:
                        data=p.read_bytes();obj=json.loads(data)
                        if not isinstance(obj,dict) or 'vectors' not in obj:seenfiles[str(p)]=finger;continue
                        key=hashlib.sha256(data).hexdigest();seenfiles[str(p)]=finger
                        if key in done or key in waiting or key in inflight.values():continue
                        dest=run/'verified'/(key+'.candidate.json')
                        if not dest.exists():dest.write_bytes(data)
                        waiting[key]=str(p)
                    except (OSError,ValueError):continue
            while waiting and len(inflight)<8:
                key=next(iter(waiting));waiting.pop(key);inflight[pool.submit(worker,str(run),key)]=key
            if inflight:
                ready,_=cf.wait(inflight,timeout=.3,return_when=cf.FIRST_COMPLETED)
                for future in ready:
                    key=inflight.pop(future)
                    try:
                        r=future.result();done.add(key);last=r
                        with (run/'audit-parallel-events.jsonl').open('a') as out:out.write(json.dumps(r)+'\n')
                        if r['energy']>1e-8 and r['gradient_norm']<1e-7 and r['min_quotient_eigenvalue']>best.get('min_quotient_eigenvalue',-1e100):best=r;atom(run/'best-interesting.json',r)
                        if r['strict_numerical_candidate']:atom(run/'best-numerical.json',r)
                    except Exception as exc:
                        with (run/'audit-parallel-errors.jsonl').open('a') as out:out.write(json.dumps({'key':key,'error':str(exc),'time':time.time()})+'\n')
            else:time.sleep(.3)
            atom(run/'audit-status.json',{'checked_utc':datetime.now(timezone.utc).isoformat(),'unique_checked':len(done),'queued':len(waiting),'inflight':len(inflight),'workers':4,'last':last})

if __name__=='__main__':main(Path(sys.argv[1]))
