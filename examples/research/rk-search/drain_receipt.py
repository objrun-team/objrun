"""After a proved optimum, drain the current paid request and end idle engine.

This introduces no monetary/token/iteration budget. The research target has
already been attained and independently certified; the original end-of-window
guard and finalization remain unchanged. No new model call is made here.
"""
import json,time,sys
from pathlib import Path
from datetime import datetime,timezone
import psutil
run=Path(sys.argv[1]);state=json.loads((run/'research-complete.json').read_text())
deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
while True:
    rows=[]
    for line in (run/'calls.jsonl').read_text().splitlines():
        try:rows.append(json.loads(line))
        except ValueError:pass
    finished={r['id'] for r in rows if r['event'] in ['response','fault']}
    pending=[r['id'] for r in rows if r['event']=='dispatch' and r['id'] not in finished]
    if not pending or time.time()>=deadline:break
    time.sleep(min(1,max(.01,deadline-time.time())))
info=json.loads((run/'process.json').read_text());stops=[]
for name in ['engine']:
    item=info[name]
    try:
        p=psutil.Process(item['pid'])
        if abs(p.create_time()-item['created'])<.5:
            p.kill();stops.append(item['pid'])
    except psutil.Error:pass
state.update(state='research_complete_waiting_original_finalization',receipt_drain_completed_utc=datetime.now(timezone.utc).isoformat(),pending_requests=pending,stopped_engine_pids=stops)
(run/'research-complete.json').write_text(json.dumps(state,indent=2))
print(json.dumps(state))
