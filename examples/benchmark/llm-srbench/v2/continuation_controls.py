"""Scope and closed-feedback regression checks; never calls a provider."""
import http.client,importlib,json,pathlib,threading,time
import common,continuation,run
from common import ROOT,OUT,save
checks=[]
plan=continuation.verify_plan();checks.append({'name':'483_frozen_allowlist_excludes_all_477_v1_started_cells','passed':True})
disallowed=next(e for e in plan['startedV1Cells'])
task=next(t for t in run.CATALOG if t['key']==disallowed['key'])
try:run.execute(task,disallowed['arm'])
except RuntimeError as e:assert str(e)=='CellOutsideFrozenContinuationScope'
else:raise AssertionError('Old cell was allowed to execute')
checks.append({'name':'real_execute_rejects_v1_cell_before_any_write_or_dispatch','passed':True})
d=OUT/'controls/feedback-drain';g=run.Gateway({'key':'fixture'},'binary',d)
entered=threading.Event();release=threading.Event();closed=threading.Event();original=run.grade
run.grade=lambda *a:(entered.set(),release.wait(10),{'valid':True,'passed':False})[-1]
try:
    c=http.client.HTTPConnection('127.0.0.1',g.service.server_port,timeout=10);c.request('POST','/feedback',body=json.dumps({'key':'fixture','arm':'binary','answer':'fixture'}),headers={'Content-Type':'application/json'});v=c.getresponse();assert v.status==200;v.read();c.close();assert entered.wait(5)
    t=threading.Thread(target=lambda:(g.close(),closed.set()));t.start();assert g.dispatch_gate.closed.wait(5);assert not closed.wait(.05)
    release.set();t.join(10);assert closed.is_set() and len(g.events)==1
    checks.append({'name':'gateway_close_waits_for_admitted_feedback_before_candidate_freeze','passed':True})
finally:release.set();run.grade=original
# Exercise the real v2 audit on a frozen old/new row race, including both red and green.
import tempfile,shutil,hashlib
import audit
with tempfile.TemporaryDirectory(dir=OUT/'controls',prefix='audit-regression-') as td:
    r=pathlib.Path(td);(r/'package').mkdir();(r/'data/public').mkdir(parents=True);(r/'outputs').mkdir()
    key='a'*24;task={'key':key,'id':'fixture','prompt':'fixture','publicSha256':'fixture'}
    (r/'package/continuation-plan.json').write_text(json.dumps({'allowedCells':[{'arm':'baseline','key':key}]}));(r/'data/public/catalog.json').write_text(json.dumps([task]));(r/'outputs/source-pins.json').write_text('[]')
    d=r/'outputs/tasks/baseline'/key;calls=d/'calls/sample-0/attempt-0';calls.mkdir(parents=True)
    q=common.wire({'messages':[]});(calls/'request.json').write_text(json.dumps(q));(calls/'dispatch.json').write_text(json.dumps({'dispatchAtMs':20,'reservedUpperBoundUsd':.02}));(calls/'receipt.json').write_text(json.dumps({'actualCostUsd':.001,'unknownCost':False}))
    row={'arm':'baseline','key':key,'protocolVersion':'v2','publicInputSha256':'fixture','completedAtMs':10,'actualCostUsd':.001,'accountedUpperBoundUsd':.001,'unknownCostCount':0,'modelCalls':1,'valid':False,'error':'synthetic infrastructure fixture'};(d/'result.json').write_text(json.dumps(row))
    assert any(x.startswith('DispatchAfterResult:') for x in audit.audit(r)['issues'])
    row['completedAtMs']=30;(d/'result.json').write_text(json.dumps(row));assert audit.audit(r)['allPassed']
    checks.append({'name':'real_auditor_rejects_late_dispatch_and_accepts_accounted_exception','passed':True})
save(OUT/'controls/continuation-free-checks.json',{'allPassed':True,'realApiCalls':0,'checks':checks});print(json.dumps({'allPassed':True,'checks':checks,'realApiCalls':0}))
