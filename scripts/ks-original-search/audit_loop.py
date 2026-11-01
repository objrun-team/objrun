"""Host-only continuous verifier. Successful final replay triggers immediate stop."""
import hashlib,json,sys,time
from pathlib import Path
from datetime import datetime,timezone
from checker import check
run=Path(sys.argv[1]).resolve();seen=set();frozen=json.loads((run/'frozen-g.json').read_text())
def atomic(p,obj):
    tmp=Path(str(p)+'.tmp');tmp.write_text(json.dumps(obj,indent=2));tmp.replace(p)
def integrity():
    for n,h in frozen['files'].items():assert hashlib.sha256((run/n).read_bytes()).hexdigest()==h,'Frozen checker changed: '+n
def scan():
    integrity()
    paths=list((run/'work/candidates').glob('*.json'))+[run/'work/candidate.json']
    for p in paths:
        try:
            data=p.read_bytes();key=hashlib.sha256(data).hexdigest()
            if key in seen:continue
            obj=json.loads(data)
            if not isinstance(obj,dict) or 'vectors' not in obj:continue
            dest=run/'verified'/(key+'.candidate.json');reportpath=run/'verified'/(key+'.json')
            if not dest.exists():dest.write_bytes(data)
            # Each verifier owns a separate destination, avoiding racing engine requests.
            reportpath=run/'verified'/(key+'.audit.json')
            r=check(dest,reportpath,frozen['baseline_n']);seen.add(key)
            summary={**r,'artifact':str(dest),'source':str(p),'checked_utc':datetime.now(timezone.utc).isoformat()}
            with (run/'audit-events.jsonl').open('a') as f:f.write(json.dumps(summary)+'\n')
            prior=json.loads((run/'best-verified.json').read_text())
            if r['valid'] and r['n']<prior.get('n',10**9):atomic(run/'best-verified.json',summary)
            atomic(run/'audit-status.json',{'unique_checked':len(seen),'last':summary})
            if r['strict_success']:
                finalcheck=check(dest,run/'success-final-replay.json',frozen['baseline_n'])
                if finalcheck['strict_success']:
                    atomic(run/'success-certified.json',{'certified_utc':datetime.now(timezone.utc).isoformat(),'artifact':str(dest),'report':finalcheck,'authorization':'user requested immediate stop after complete independent final verification'})
                    (run/'work/STOP').write_text('Certified success: stop all searching immediately')
                    return True
        except FileNotFoundError:pass
        except Exception as e:
            with (run/'audit-errors.jsonl').open('a') as f:f.write(json.dumps({'file':str(p),'epoch':time.time(),'error':str(e)})+'\n')
    return False
if __name__=='__main__':
    if '--once' in sys.argv:scan()
    else:
        while not (run/'stop-requested.json').exists():
            if (run/'deadline.json').exists() and time.time()>=json.loads((run/'deadline.json').read_text())['deadline_epoch']:break
            if scan():break
            time.sleep(2)
