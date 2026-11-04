"""Auditable recovery of a completed transport failure in this private run only.
Preserve the failed unit and all messages; append a new ask unit as ObjRun's
own #reopen does. Never alter the clock, scientific checker or old responses.
"""
import json,sqlite3,sys,time,re
from pathlib import Path
from urllib.request import Request,urlopen
root=Path(__file__).resolve().parents[3];run=Path((root/'data/spherical-landscape/latest-run.txt').read_text().strip())
clock=json.loads((run/'deadline.json').read_text());assert time.time()<clock['deadline_epoch']
ep=json.loads((run/'endpoints.json').read_text());status=json.loads((run/'status.json').read_text());task=status['task']['id']
calls=[json.loads(x) for x in (run/'calls.jsonl').read_text().splitlines()]
assert {x['id'] for x in calls if x['event']=='dispatch'}<={x['id'] for x in calls if x['event'] in ('response','fault')},'Do not recover an in-flight model request'
con=sqlite3.connect(ep['database'],timeout=10);con.row_factory=sqlite3.Row
u=dict(con.execute('select * from task_spherical_landscape_search where task=? and done=0 order by unit desc limit 1',(task,)).fetchone())
msgs=[dict(x) for x in con.execute('select * from agent_landscape_msg where instance=? and unit=? order by seq',(u['instance'],u['unit']))]
assert any('"stuck"' in x['body'] for x in msgs),'Only explicitly stalled units may be recovered'
t=dict(con.execute('select * from task where id=?',(task,)).fetchone());stamp=str(int(time.time()))
(run/f'recovery-{stamp}-before.json').write_text(json.dumps({'task':t,'unit':u,'messages':msgs},indent=2))
known=[{'package':p.name,'energy':json.loads((p/'independent-check.json').read_text())['energy']} for p in run.glob('proof*') if (p/'manifest.json').exists()]
note='''HOST CONTINUATION OBJECTIVE (the fixed mathematical definition and frozen checker below remain unchanged):
The following different energy classes are ALREADY rigorously proved with independently checked protected exact KKT witnesses: '''+json.dumps(known)+'''. Do NOT repeat submissions of these same points. Continue substantive research until original deadline1793392762.755.
Your cascade found basinD atF~0.296786738223609; the host has now executed the saved model-adapted Cholesky certificate and independently verified it at220 digits. Your contributions are recorded distinctly. Remaining work may examine another positive-gap energy class, exact symmetry/structure or independent mathematical audits. Use research-progress.md cumulatively. Do not call approximate Gram-pattern symmetries or a finite sample exhaustive proofs. Preserve every coordinate, seed and trace. Prioritize independent verification and substantive analysis over redundant restarts.
Host retired superseded baseline job21 and initial structured/hopping/extreme jobs227/233/238 to let the unchanged four-worker independent checker drain its queue and preserve CPU headroom. Model-guided cascade, deflated and orbit searches remain; do not restart duplicate families. This is adaptive prioritization after four proofs, not a new time/count/fee budget.
The original deadline and fixed model remain unchanged. Long tool jobs use background=true with foreground command (no nohup or shell '&'). A prior submit step returned text without the required function call; this ask unit is an auditable recovery, not a new experiment/window. Do not invoke submit again merely to resubmit an already accepted coordinate file.
'''
newunit=int(con.execute('select max(unit)+1 from task_spherical_landscape_search where task=?',(task,)).fetchone()[0]);newnode=int(con.execute('select max(node)+1 from task_spherical_landscape_search where task=?',(task,)).fetchone()[0]);now=int(time.time()*1000)
with con:
    con.execute('update task set description=? where id=?',(note+'\n\n'+t['description'],task))
    con.execute("update task_spherical_landscape_search set done=1,status='dead_service' where task=? and unit=? and done=0",(task,u['unit']))
    con.execute('update agent_landscape_ctx set done=1 where instance=? and unit=?',(u['instance'],u['unit']))
    con.execute('insert into task_spherical_landscape_search(task,cycle,unit,node,from_cycle,from_unit,agent,instance,place,at,done) values(?,?,?,?,?,?,?,?,?,?,0)',(task,'ask',newunit,newnode,u['cycle'],u['unit'],u['agent'],u['instance'],u['place'],now))
    con.execute('insert into agent_landscape_ctx(instance,task,unit,place,done) values(?,?,?,?,0)',(u['instance'],task,newunit,u['place']))
con.close()
token=re.search(r'token: ([a-f0-9]+)',(run/'engine/config.yaml').read_text()).group(1)
req=Request(ep['engine']+'/tasks/'+task+'/messages',method='POST',headers={'content-type':'application/json','Authorization':'Bearer '+token},data=json.dumps({'unit':newunit,'body':'[Automated host recovery] Resume from the new focused continuation objective in task.description; prior failed transport is preserved. No clock reset.'}).encode())
with urlopen(req,timeout=20) as response:result=json.load(response)
report={'timestamp':time.time(),'task':task,'old_unit':u['unit'],'new_unit':newunit,'new_node':newnode,'original_deadline':clock['deadline_utc'],'wake':result,'note':note}
(run/f'recovery-{stamp}.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='note'}))
