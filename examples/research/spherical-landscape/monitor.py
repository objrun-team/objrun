"""Read-only compact health + actual CPU/artifact progress and verifier integrity."""
import json,sys,time,hashlib,sqlite3,subprocess
from pathlib import Path
from datetime import datetime,timezone
import psutil
root=Path(__file__).resolve().parents[3];run=Path(sys.argv[1]) if len(sys.argv)>1 else Path((root/'data/spherical-landscape/latest-run.txt').read_text().strip())
out={'run':str(run),'utc':datetime.now(timezone.utc).isoformat()}
for name in ['deadline','status','best-interesting','best-numerical','audit-status','deadline-guard','completion']:
    p=run/(name+'.json')
    if p.exists():
        try:out[name]=json.loads(p.read_text())
        except Exception as e:out[name]={'error':str(e)}
if (run/'final/summary.json').exists():out['final']=json.loads((run/'final/summary.json').read_text())
if (run/'proof/independent-check.json').exists():
    c=json.loads((run/'proof/independent-check.json').read_text());out['rigorous_certificate']={k:c[k] for k in ['independently_verified','precision_digits','tests','energy','positive_margin']}
for name in ['host-certify-process','host-reopt-process']:
    if (run/(name+'.json')).exists():
        v=json.loads((run/(name+'.json')).read_text())
        try:p=psutil.Process(v['pid']);out[name]={'alive':abs(p.create_time()-v['created'])<.5,'cpu_seconds':sum(p.cpu_times()[:2])}
        except psutil.Error:out[name]={'alive':False}
if (run/'process.json').exists():
    out['processes']={}
    for n,v in json.loads((run/'process.json').read_text()).items():
        if isinstance(v,dict) and 'pid' in v:
            try:
                p=psutil.Process(v['pid']);out['processes'][n]={'alive':abs(p.create_time()-v['created'])<.5,'cpu_seconds':sum(p.cpu_times()[:2]),'pid':p.pid,'children':[c.pid for c in p.children(recursive=True)]}
            except psutil.Error:out['processes'][n]={'alive':False}
out['frozen_integrity']={n:hashlib.sha256((run/n).read_bytes()).hexdigest()==h for n,h in json.loads((run/'frozen-g.json').read_text())['files'].items()}
out['candidate_files']=len([p for p in (run/'work/candidates').glob('*.json') if not p.name.endswith(('.initial.json','.trace.json'))])
try:
    linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
    script=Path(__file__).resolve().parent/'linux_cpu_snapshot.py'
    if not script.exists():script=run/'linux_cpu_snapshot.py'
    observed=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(script),linux(run/'work')],capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    out['linux_actual_cpu']=json.loads(observed.stdout)
except Exception as e:out['linux_cpu_error']=str(e)
archive=run/'sources/real_equal_norm.tar.gz'
if archive.exists():
    out['source_archive']={'bytes':archive.stat().st_size,'expected_bytes':235698328}
    if archive.stat().st_size==235698328 and not (run/'sources/archive-integrity.json').exists():
        dig=hashlib.md5(archive.read_bytes()).hexdigest();proof={'md5':dig,'expected_md5':'ed823ebfc00e0c180b6a5529aa96a509','matches':dig=='ed823ebfc00e0c180b6a5529aa96a509'}
        (run/'sources/archive-integrity.json').write_text(json.dumps(proof,indent=2))
    if (run/'sources/archive-integrity.json').exists():out['source_archive']['integrity']=json.loads((run/'sources/archive-integrity.json').read_text())
out['recent_artifacts']=[{'name':str(p.relative_to(run)),'bytes':p.stat().st_size,'age_seconds':time.time()-p.stat().st_mtime} for p in sorted((run/'work').rglob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:5]]
if (run/'work/progress.json').exists():out['search_progress']=json.loads((run/'work/progress.json').read_text())
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
        con=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2);con.row_factory=sqlite3.Row
        out['tasks']=[dict(r) for r in con.execute('select id,state from task order by created_at')]
        out['last_messages']=[dict(r) for r in con.execute('select kind,substr(body,1,1800) as body from agent_landscape_msg order by rowid desc limit 2')];con.close()
    except Exception as e:out['db_error']=str(e)
with (run/'monitor-history.jsonl').open('a') as f:f.write(json.dumps(out)+'\n')
print(json.dumps(out,indent=2,ensure_ascii=False))
