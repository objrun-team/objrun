"""Compact, read-only monitoring. Does not print request bodies or credentials."""
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import psutil

sys.stdout.reconfigure(encoding='utf-8')

base = Path(__file__).resolve().parents[3]/'data/covering-array-search'
run = Path(sys.argv[1]) if len(sys.argv)>1 else Path((base/'latest-run.txt').read_text().strip())
out = {'run': str(run), 'checked_utc': datetime.now(timezone.utc).isoformat()}
for name in ['deadline', 'status', 'best-verified', 'completion', 'deadline-guard', 'final-report']:
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
        'last_events': events[-3:]}
    receipt_ids={e['id'] for e in finished if 'cost' in (e.get('usage') or {})}
    out['model_usage']['cost_unconfirmed_request_ids']=[e['id'] for e in dispatch if e['id'] not in receipt_ids]
    out['model_usage']['preparation_cost_usd']=json.loads((run/'reference/model-probe.receipt.json').read_text())['usage']['cost']
out['process_health']={}
for name in ['process','supervisor-process','guard-process']:
    try:
        data=json.loads((run/(name+'.json')).read_text())
        items={name:data} if 'pid' in data else {k:v for k,v in data.items() if isinstance(v,dict) and 'pid' in v}
        for label,item in items.items():
            try:
                p=psutil.Process(item['pid']); cpu=p.cpu_times()
                out['process_health'][label]={'pid':p.pid,'alive':p.is_running(),
                    'identity_matches':abs(p.create_time()-item.get('created',p.create_time()))<.5,
                    'cpu_seconds':cpu.user+cpu.system,'rss_bytes':p.memory_info().rss}
            except psutil.Error: out['process_health'][label]={'pid':item['pid'],'alive':False}
    except (OSError,ValueError): pass
try:
    raw=subprocess.check_output(['wsl','-d','Ubuntu','--','ps','-ww','-eo','pid=,ppid=,etimes=,time=,pcpu=,args='],text=True,stderr=subprocess.DEVNULL,timeout=10)
    linux_run='/mnt/'+str(run)[0].lower()+str(run)[2:].replace('\\','/')
    processes={}
    for line in raw.splitlines():
        fields=line.strip().split(None,5)
        if len(fields)==6: processes[int(fields[0])]=fields
    selected={pid for pid,f in processes.items() if linux_run in f[5]}
    while True:
        grown=selected|{pid for pid,f in processes.items() if int(f[1]) in selected}
        if grown==selected: break
        selected=grown
    out['linux_compute']=[{'pid':pid,'ppid':int(processes[pid][1]),'elapsed_seconds':int(processes[pid][2]),
        'cpu_time':processes[pid][3],'pcpu':processes[pid][4],'command':processes[pid][5][:240]} for pid in sorted(selected)]
except Exception as e: out['linux_compute_error']=str(e)
out['source_versions_saved']=len(list((run/'code-history').glob('*')))
out['verified_candidate_snapshots']=len(list((run/'verified').glob('*.txt')))
events_path = run/'events.jsonl'
if events_path.exists():
    out['recent_events'] = [json.loads(x) for x in events_path.read_text().splitlines()[-6:]]
db = run/'engine/data/h2h.sqlite'
if db.exists():
    con = sqlite3.connect(db.as_uri()+'?mode=ro', uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    try:
        out['tasks'] = [dict(r) for r in con.execute('select id,state,created_at,solve_seconds from task order by created_at')]
        out['last_messages'] = [dict(r) for r in con.execute('select kind,substr(body,1,1600) as body from agent_ca_msg order by rowid desc limit 3')]
    except sqlite3.Error as e: out['db_note'] = str(e)
    finally: con.close()
print(json.dumps(out, indent=2, ensure_ascii=False))
