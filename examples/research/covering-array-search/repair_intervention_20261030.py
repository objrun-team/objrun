"""Repair the observed call/intervention/result ordering, retaining all evidence."""
import json
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import yaml

root=Path(__file__).resolve().parents[3]
run=root/'data/covering-array-search/run-20261030T094841Z'
out=run/'repairs/message-order-20261030T1029Z';out.mkdir(parents=True,exist_ok=True)
con=sqlite3.connect((run/'engine/data/h2h.sqlite').as_uri()+'?mode=ro',uri=True)
con.row_factory=sqlite3.Row
backup=sqlite3.connect(out/'before.sqlite');con.backup(backup);backup.close()
before=[dict(r) for r in con.execute("select * from agent_ca_msg where instance='ca-search-001#1' order by unit,seq")]
(out/'messages-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')

def scan(rows):
    pending=set();errors=[]
    for r in rows:
        if r['kind'] in ['call','graded']:
            pending.update(c['id'] for c in json.loads(r['body']).get('calls',[]))
        elif r['kind']=='tool': pending.discard(json.loads(r['body'])['id'])
        elif r['role']=='user' and pending:
            errors.append({'unit':r['unit'],'seq':r['seq'],'calls_pending':sorted(pending)})
    return errors

errors=scan(before)
assert errors==[{'unit':34,'seq':2,'calls_pending':['call_3f19bdc48f37457ead610d913e2c82ca']}],errors
assert con.execute("select done from task_ca_search where task='ca-search-001' and unit=35").fetchone()[0]==0
assert con.execute("select count(*) from agent_ca_msg where instance='ca-search-001#1' and unit=35").fetchone()[0]==2
cfg=yaml.safe_load((run/'engine/config.yaml').read_text())
def sql(statement):
    req=urllib.request.Request('http://127.0.0.1:'+str(cfg['server']['port'])+'/api/exec',
        data=json.dumps({'sql':statement}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+cfg['api']['token']},method='POST')
    with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)

# Move only the controller intervention after the completed tool result.
receipts=[sql("update agent_ca_msg set unit=35,seq=3 where instance='ca-search-001#1' and unit=34 and seq=2 and role='user'")]
# Retain old local failure/sent records alongside the preceding closed unit;
# this releases the existing unfinished ask unit for one retry (no tool rerun).
receipts.append(sql("update agent_ca_msg set unit=34,seq=seq+4 where instance='ca-search-001#1' and unit=35 and seq in (1,2) and role='system' and kind='inject'"))
after=[dict(r) for r in con.execute("select * from agent_ca_msg where instance='ca-search-001#1' order by unit,seq")]
(out/'messages-after.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
assert scan(after)==[],scan(after)
record={'utc':datetime.now(timezone.utc).isoformat(),'component':'ObjRun context delivery',
 'reason':'Controller feedback was interposed between call and genuine result; AI SDK rejected it locally.',
 'before_pair_order_errors':errors,'after_pair_order_errors':scan(after),'sql_receipts':receipts,
 'unchanged':'G, model, actual tool-result bytes, candidates, source programs and original deadline.',
 'preserved_before_database':str(out/'before.sqlite'),
 'future_monitor_policy':'Do not inject user messages into an act unit with pending tool calls; deliver only at a safe boundary, or use a file for the model to read.'}
(out/'repair.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
with open(run/'infrastructure-repairs.jsonl','a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
print(json.dumps({'repaired':True,'local_order_check_passed':True,'receipts':receipts,'evidence':str(out)}))
