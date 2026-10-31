"""Compact, read-only monitoring. Does not print request bodies or credentials."""
import json
import sqlite3
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from datetime import datetime, timezone
from pathlib import Path

base = Path(__file__).resolve().parents[2]/'data/rk-search'
run = Path(sys.argv[1]) if len(sys.argv)>1 else Path((base/'latest-run.txt').read_text().strip())
out = {'run': str(run), 'checked_utc': datetime.now(timezone.utc).isoformat()}
for name in ['deadline', 'status', 'best-verified', 'completion', 'deadline-guard', 'research-complete']:
    path = run/(name+'.json')
    if path.exists():
        try: out[name] = json.loads(path.read_text(encoding='utf-8-sig'))
        except Exception as e: out[name] = {'read_error': str(e)}
progress = run/'work/progress.json'
if progress.exists():
    out['self_reported_progress'] = progress.read_text(encoding='utf-8-sig')[-6000:]
calls = run/'calls.jsonl'
if calls.exists():
    events = []
    for line in calls.read_text().splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    dispatch = [e for e in events if e['event']=='dispatch']
    finished = [e for e in events if e['event']=='response']
    completed_ids = {e['id'] for e in events if e['event'] in ['response', 'fault']}
    out['model_usage'] = {'requests': len(dispatch), 'responses': len(finished),
        'in_flight': [e['id'] for e in dispatch if e['id'] not in completed_ids],
        'receipt_cost_usd': sum((e.get('usage') or {}).get('cost') or 0 for e in finished),
        'prompt_tokens': sum((e.get('usage') or {}).get('prompt_tokens') or 0 for e in finished),
        'completion_tokens': sum((e.get('usage') or {}).get('completion_tokens') or 0 for e in finished),
        'unconfirmed_request_ids': [e['id'] for e in dispatch if not any(f['id']==e['id'] and (f.get('usage') or {}).get('cost') is not None for f in finished)],
        'last_events': events[-3:]}
events_path = run/'events.jsonl'
if events_path.exists():
    out['recent_events'] = [json.loads(x) for x in events_path.read_text().splitlines()[-6:]]
endpoint_path=run/'endpoints.json'
endpoints=json.loads(endpoint_path.read_text()) if endpoint_path.exists() else {}
db = Path(endpoints.get('database',str(run/'engine/data/h2h.sqlite')))
out['endpoints']=endpoints
try:
    import psutil
    process_info=json.loads((run/'process.json').read_text())
    out['process_health']={name:bool(psutil.pid_exists(v['pid']) and abs(psutil.Process(v['pid']).create_time()-v['created'])<.5) for name,v in process_info.items() if isinstance(v,dict) and 'pid' in v}
except Exception as e:out['process_health_error']=str(e)
if db.exists():
    con = sqlite3.connect(db.as_uri()+'?mode=ro', uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    try:
        out['tasks'] = [dict(r) for r in con.execute('select id,state,created_at,solve_seconds from task order by created_at')]
        out['last_messages'] = [dict(r) for r in con.execute('select kind,substr(body,1,1600) as body from agent_rk_msg order by rowid desc limit 3')]
    except sqlite3.Error as e: out['db_note'] = str(e)
    finally: con.close()
import hashlib,subprocess,time
frozen=json.loads((run/'frozen-g.json').read_text())
out['frozen_hashes_intact']=all(hashlib.sha256((run/n).read_bytes()).hexdigest()==h for n,h in frozen['files'].items())
linux_run='/mnt/'+str(run)[0].lower()+str(run)[2:].replace(chr(92),'/')
try:
    health=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux_run+'/linux_health.py',linux_run],capture_output=True,text=True,timeout=20)
    out['linux_health']=json.loads(health.stdout)
except Exception as e:out['linux_health_error']=str(e)
out['work_files']=[{'name':str(p.relative_to(run/'work')),'bytes':p.stat().st_size,'modified_epoch':p.stat().st_mtime} for p in (run/'work').rglob('*') if p.is_file() and p.suffix in ['.py','.json','.jsonl','.log']][-40:]
(run/'monitor-snapshots').mkdir(exist_ok=True)
(run/'monitor-snapshots'/('check-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out, indent=2, ensure_ascii=False))
