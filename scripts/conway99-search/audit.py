"""Host-only audit. Model cannot write this file, reports, freeze, or success gate."""
import json,sys,hashlib,subprocess,time,os
from pathlib import Path
from datetime import datetime,timezone

def put(p,obj):
    q=p.with_suffix(p.suffix+'.tmp');q.write_text(json.dumps(obj,indent=2));q.replace(p)
def frozen(run):
    f=json.loads((run/'frozen-g.json').read_text())
    for name,h in f['files'].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest()!=h:raise RuntimeError('Frozen checker/goal changed: '+name)
def audit(run,source):
    frozen(run); raw=source.read_bytes();h=hashlib.sha256(raw).hexdigest();d=run/'verified'/h
    if (d/'report.json').exists():return json.loads((d/'report.json').read_text())
    # Reject partial or unrelated JSON; never execute any submitted file.
    obj=json.loads(raw); a=obj.get('matrix') if isinstance(obj,dict) else obj
    if not isinstance(a,list):return None
    d.mkdir(exist_ok=True);(d/'matrix.json').write_bytes(raw)
    reports=[]
    for name in ('check_pairs.py','check_matrix.py'):
        r=subprocess.run([sys.executable,str(run/'checker'/name),str(d/'matrix.json')],capture_output=True,text=True,check=True)
        result=json.loads(r.stdout);put(d/(name+'.json'),result);reports.append(result)
    pair,matrix=reports
    r={'sha256':h,'source':str(source),'artifact':str(d/'matrix.json'),'checked_utc':datetime.now(timezone.utc).isoformat(),'valid':pair['valid'] and matrix['valid'],'pair_checker_valid':pair['valid'],'matrix_checker_valid':matrix['valid'],**{key:pair.get(key) for key in ('constraint_violations','degree_violations','adjacent_pair_violations','nonadjacent_pair_violations','pair_l1','pair_l2','loops','asymmetric_pairs')}}
    if pair.get('binary') and pair.get('shape'):
        edges=[[i,j] for i in range(len(a)) for j in range(i+1,len(a)) if a[i][j]]
        put(d/'edges.json',{'n':len(a),'edges':edges});(d/'edges.txt').write_text(''.join(f'{i} {j}\n' for i,j in edges))
    put(d/'report.json',r)
    with (run/'verifier-events.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
    old=json.loads((run/'best-verified.json').read_text())
    if r['constraint_violations'] is not None and (old.get('constraint_violations') is None or (r['constraint_violations'],r['pair_l2'])<(old['constraint_violations'],old['pair_l2'])):
        put(run/'best-verified.json',r)
    if r['valid']:
        # Independent final replay from two saved formats, not model success text.
        edge_data=json.loads((d/'edges.json').read_text());b=[[0]*99 for _ in range(99)]
        assert edge_data['n']==99 and len(edge_data['edges'])==693
        for u,v in edge_data['edges']:assert 0<=u<v<99 and b[u][v]==0;b[u][v]=b[v][u]=1
        put(d/'edge-reconstructed.json',{'matrix':b});final=[]
        for artifact in ('matrix.json','edge-reconstructed.json'):
            for checker in ('check_pairs.py','check_matrix.py'):
                rr=json.loads(subprocess.check_output([sys.executable,str(run/'checker'/checker),str(d/artifact)],text=True));assert rr['valid'];final.append({'artifact':artifact,'checker':checker,'valid':True})
        frozen(run);put(d/'final-replay.json',final)
        put(run/'success.json',{'main_goal_solved':True,'kind':'existence','sha256':h,'artifact':str(d),'final_replays':final,'utc':datetime.now(timezone.utc).isoformat()})
        (run/'control/STOP').write_text('independently_verified_main_success')
    return r

def scan(run):
    files=list((run/'work/candidates').glob('*.json'))
    if (run/'work/candidate.json').exists():files.append(run/'work/candidate.json')
    for p in sorted(files,key=lambda p:p.stat().st_mtime):
        try:
            if not p.resolve().is_relative_to((run/'work').resolve()):continue
            audit(run,p)
        except (ValueError,OSError) as e:
            with (run/'audit-errors.jsonl').open('a') as f:f.write(json.dumps({'path':str(p),'error':str(e),'time':time.time()})+'\n')
        if (run/'success.json').exists():break

if __name__=='__main__':
    run=Path(sys.argv[1]).resolve()
    # Two host callers (submission and periodic scan) share one audit lock.
    import msvcrt
    lock=(run/'audit.lock').open('a+b');lock.write(b'0');lock.flush()
    def acquire():
        while True:
            try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);return
            except OSError:time.sleep(.1)
    def release():lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    if len(sys.argv)>2 and sys.argv[2]!='--loop':
        acquire()
        try:print(json.dumps(audit(run,Path(sys.argv[2]))))
        finally:release()
        sys.exit(0)
    while True:
        acquire()
        try:scan(run)
        finally:release()
        if '--loop' not in sys.argv or (run/'control/STOP').exists():break
        if (run/'deadline.json').exists() and time.time()>=json.loads((run/'deadline.json').read_text())['deadline_epoch']:break
        time.sleep(10)
