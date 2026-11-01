"""Read-only red/green check for the current real-engine stalled ask unit."""
from pathlib import Path
import json,sqlite3,sys,datetime
ROOT=Path(__file__).resolve().parents[2]
run=Path((ROOT/'data/lj-conjecture-search/latest-run.txt').read_text().strip())
status=json.loads((run/'status.json').read_text(encoding='utf-8'));task=status['task']['id']
ep=json.loads((run/'endpoints.json').read_text());con=sqlite3.connect('file:'+ep['database'].replace('\\','/')+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
row=con.execute('select * from task_lj_conjecture_search where task=? and done=0 order by unit desc limit 1',(task,)).fetchone()
unit=dict(row) if row else None
messages=[dict(x) for x in con.execute('select * from agent_lj_msg where instance=? and unit=? order by seq',(unit['instance'],unit['unit']))] if unit else []
stuck=any('Tool result is missing for tool call' in str(x.get('body','')) for x in messages)
report={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'task':task,'unit':unit,'stalled_tool_adjacency':stuck,'current_unit_messages':messages}
folder=run/'diagnostics';folder.mkdir(exist_ok=True)
(folder/('adjacency-'+str(int(datetime.datetime.now().timestamp()))+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
signal='WAIT_FOR_CURRENT_UNIT' if unit is None else 'RED' if stuck else 'GREEN'
print(json.dumps({'task':task,'unit':unit['unit'] if unit else None,'stalled_tool_adjacency':stuck,'signal':signal}))
sys.exit(2 if unit is None else 1 if stuck else 0)
