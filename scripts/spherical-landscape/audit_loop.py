import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import hashlib,json,sys,time
from pathlib import Path
from datetime import datetime,timezone
from checker import check
run=Path(sys.argv[1]).resolve();seen=set()
frozen=json.loads((run/'frozen-g.json').read_text())
def integrity():
    for n,h in frozen['files'].items():
        assert hashlib.sha256((run/n).read_bytes()).hexdigest()==h,'Frozen checker changed: '+n
def atomic(p,obj):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(obj,indent=2));tmp.replace(p)
def scan():
    integrity();paths=list((run/'work/candidates').glob('*.json'))+[run/'work/candidate.json']
    for p in paths:
        if p.name.endswith(('.initial.json','.trace.json')) or not p.exists():continue
        try:
            data=p.read_bytes();key=hashlib.sha256(data).hexdigest()
            if key in seen:continue
            obj=json.loads(data)
            if not isinstance(obj,dict) or 'vectors' not in obj:continue
            dest=run/'verified'/(key+'.candidate.json');reportpath=run/'verified'/(key+'.json')
            if not dest.exists():dest.write_bytes(data)
            try:r=json.loads(reportpath.read_text())
            except (OSError,ValueError):r=check(dest,reportpath,run/'baseline-audit.json')
            seen.add(key)
            summary={k:v for k,v in r.items() if k not in ['gram','perturbations','full_tangent_spectrum','quotient_spectrum']}
            summary.update(source=str(p),artifact=str(dest),report=str(reportpath),min_quotient_eigenvalue=r['quotient_spectrum'][0],checked_utc=datetime.now(timezone.utc).isoformat())
            with (run/'audit-events.jsonl').open('a') as f:f.write(json.dumps(summary)+'\n')
            if r['energy']>1e-8 and r['gradient_norm']<1e-7:
                target=run/'best-interesting.json';prior=json.loads(target.read_text()) if target.exists() else {}
                if r['quotient_spectrum'][0]>prior.get('min_quotient_eigenvalue',-1e100):atomic(target,summary)
            if r['strict_numerical_candidate']:
                atomic(run/'best-numerical.json',summary)
            atomic(run/'audit-status.json',{'checked_utc':summary['checked_utc'],'unique_checked':len(seen),'last':summary})
        except Exception as e:
            with (run/'audit-errors.jsonl').open('a') as f:f.write(json.dumps({'file':str(p),'time':time.time(),'error':str(e)})+'\n')
if __name__=='__main__':
    if '--once' in sys.argv:scan()
    else:
        while True:
            if (run/'deadline.json').exists() and time.time()>=json.loads((run/'deadline.json').read_text())['deadline_epoch']:break
            scan();time.sleep(3)
