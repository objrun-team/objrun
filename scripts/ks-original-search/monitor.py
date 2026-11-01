"""Read-only health/actual computation/candidates/receipts, with saved snapshots."""
import json,sys,time,hashlib,sqlite3,subprocess
from pathlib import Path
from datetime import datetime,timezone
import psutil
root=Path(__file__).resolve().parents[2];run=Path(sys.argv[1]) if len(sys.argv)>1 else Path((root/'data/ks-original-search/latest-run.txt').read_text().strip())
out={'run':str(run),'utc':datetime.now(timezone.utc).isoformat()}
for name in ['deadline','status','best-verified','audit-status','success-certified','deadline-guard','completion']:
    p=run/(name+'.json')
    if p.exists():
        try:out[name]=json.loads(p.read_text())
        except ValueError:out[name]={'error':'incomplete JSON'}
if (run/'final/summary.json').exists():out['final']=json.loads((run/'final/summary.json').read_text())
out['processes']={}
for name in ['guard-process','auditor-process']:
    if (run/(name+'.json')).exists():
        v=json.loads((run/(name+'.json')).read_text())
        try:
            p=psutil.Process(v['pid']);out['processes'][name]={'alive':abs(p.create_time()-v.get('created',p.create_time()))<.5,'pid':p.pid,'cpu_seconds':sum(p.cpu_times()[:2])}
        except psutil.Error:out['processes'][name]={'alive':False}
if (run/'process.json').exists():
    for n,v in json.loads((run/'process.json').read_text()).items():
        if isinstance(v,dict) and 'pid' in v:
            try:
                p=psutil.Process(v['pid']);out['processes'][n]={'alive':abs(p.create_time()-v['created'])<.5,'cpu_seconds':sum(p.cpu_times()[:2]),'pid':p.pid,'children':[c.pid for c in p.children(recursive=True)]}
            except psutil.Error:out['processes'][n]={'alive':False}
out['frozen_integrity']={n:hashlib.sha256((run/n).read_bytes()).hexdigest()==h for n,h in json.loads((run/'frozen-g.json').read_text())['files'].items()}
out['candidate_files']=len(list((run/'work/candidates').glob('*.json')))
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
try:
    r=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_cpu_snapshot.py'),linux(run/'work')],capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));out['linux_actual_cpu']=json.loads(r.stdout)
except Exception as e:out['linux_cpu_error']=str(e)
out['progress_files']=[]
for p in sorted((run/'work').rglob('*progress*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:8]:
    try:out['progress_files'].append({'file':str(p.relative_to(run)),'age_seconds':time.time()-p.stat().st_mtime,'content':json.loads(p.read_text())})
    except ValueError:pass
calls=[]
if (run/'calls.jsonl').exists():
    for l in (run/'calls.jsonl').read_text().splitlines():
        try:calls.append(json.loads(l))
        except ValueError:pass
dispatch=[c for c in calls if c['event']=='dispatch'];responses=[c for c in calls if c['event']=='response']
out['usage']={'requests':len(dispatch),'responses':len(responses),'receipt_cost_usd':sum((c.get('usage') or {}).get('cost') or 0 for c in responses),'without_receipt':[c['id'] for c in dispatch if c['id'] not in {r['id'] for r in responses if (r.get('usage') or {}).get('cost') is not None}],'last_response':responses[-1] if responses else None}
if (run/'events.jsonl').exists():out['last_events']=[json.loads(l) for l in (run/'events.jsonl').read_text().splitlines()[-5:]]
if (run/'endpoints.json').exists():
    db=Path(json.loads((run/'endpoints.json').read_text())['database'])
    try:
        c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2);c.row_factory=sqlite3.Row
        out['tasks']=[dict(r) for r in c.execute('select id,state from task order by created_at')]
        out['last_messages']=[dict(r) for r in c.execute('select kind,substr(body,1,1200) as body from agent_kssearch_msg order by rowid desc limit 2')];c.close()
    except Exception as e:out['db_error']=str(e)
with (run/'monitor-history.jsonl').open('a') as f:f.write(json.dumps(out)+'\n')
print(json.dumps(out,indent=2,ensure_ascii=False))
