"""Verification-only closeout, no paid API inference and no search after deadline."""
import json,sys,time,hashlib,subprocess,os
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
import psutil
from checker import check
run=Path(sys.argv[1]).resolve();end=json.loads((run/'deadline.json').read_text())
assert time.time()>=end['deadline_epoch'] or (run/'success-certified.json').exists(),'Only certified success permits early finalization'
final=run/'final';final.mkdir(exist_ok=True)
def dump(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
actions=[];me=os.getpid();ancestors={p.pid for p in psutil.Process().parents()}
for name,v in json.loads((run/'process.json').read_text()).items():
    if not isinstance(v,dict) or 'pid' not in v:continue
    try:
        p=psutil.Process(v['pid'])
        if abs(p.create_time()-v['created'])>.5:continue
        kids=p.children(recursive=True)
        for c in kids+[p]:
            if c.pid in ancestors|{me}:continue
            try:c.kill();actions.append({'name':name,'pid':c.pid})
            except psutil.Error:pass
    except psutil.Error:pass
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
r=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_stop.py'),linux(run/'work')],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
observed={}
identities=json.loads((run/'process.json').read_text())
for extra in ['guard-process','auditor-process']:
    if (run/(extra+'.json')).exists():identities[extra]=json.loads((run/(extra+'.json')).read_text())
for name,v in identities.items():
    if not isinstance(v,dict) or 'pid' not in v:continue
    try:
        p=psutil.Process(v['pid']);observed[name]={'pid':v['pid'],'owned_identity_alive':abs(p.create_time()-v.get('created',p.create_time()))<.5}
    except psutil.Error:observed[name]={'pid':v['pid'],'owned_identity_alive':False}
dump(final/'stop-audit.json',{'checked_utc':datetime.now(timezone.utc).isoformat(),'windows_stop_actions':actions,'windows_observed':observed,'linux':json.loads(r.stdout) if r.returncode==0 else {'error':r.stderr}})
freeze=json.loads((run/'frozen-g.json').read_text())
for n,h in freeze['files'].items():assert hashlib.sha256((run/n).read_bytes()).hexdigest()==h,'Frozen checker changed '+n
seen=set();reports=[];paths=[run/'reference/ck31.json']+list((run/'work/candidates').glob('*.json'))+[run/'work/candidate.json']+list((run/'verified').glob('*.candidate.json'))
for p in paths:
    try:
        data=p.read_bytes();key=hashlib.sha256(data).hexdigest()
        if key in seen:continue
        obj=json.loads(data)
        if not isinstance(obj,dict) or 'vectors' not in obj:continue
        seen.add(key);dest=final/(key+'.candidate.json');dest.write_bytes(data)
        result=check(dest,final/(key+'.report.json'),freeze['baseline_n']);result['artifact']=str(dest);reports.append(result)
    except (OSError,ValueError) as exc:reports.append({'valid':False,'source':str(p),'error':str(exc)})
valid=[r for r in reports if r['valid']];best=min(valid,key=lambda x:x['n']) if valid else None
calls=[]
for line in (run/'calls.jsonl').read_text().splitlines():
    try:calls.append(json.loads(line))
    except ValueError:pass
dispatch=[x for x in calls if x['event']=='dispatch'];responses=[x for x in calls if x['event']=='response'];receipts=[x for x in responses if (x.get('usage') or {}).get('cost') is not None]
# A hard stop can occur after the complete response is saved but before the
# JSONL receipt is appended. Reconcile existing local evidence, no API call.
logged={x['id'] for x in responses}
for p in (run/'requests').glob('*.response.json'):
    request_id=int(p.name.split('.')[0])
    if request_id in logged:continue
    try:
        raw=json.loads(p.read_text());responses.append({'event':'response','id':request_id,'generation_id':raw.get('id'),'response_model':raw.get('model'),'provider':raw.get('provider'),'usage':raw.get('usage'),'recovered_from_saved_response':True})
    except ValueError:pass
receipts=[x for x in responses if (x.get('usage') or {}).get('cost') is not None]
cost=sum((Decimal(str(x['usage']['cost'])) for x in receipts),Decimal(0));receipt_ids={x['id'] for x in receipts}
usage={'model':'deepseek/deepseek-v4.1-flash','requests':len(dispatch),'responses':len(responses),'recorded_cost_usd':str(cost),'without_cost_receipt':[x['id'] for x in dispatch if x['id'] not in receipt_ids],'unsettled_note':'Missing/in-flight/faulted requests have unknown cost, not zero; local cancellation does not prove remote cancellation.','receipts':responses}
usage['without_response']=[x['id'] for x in dispatch if x['id'] not in {y['id'] for y in responses}]
usage['rejected_without_cost_receipt']=[{'request_id':x['id'],'http_status':x.get('http_status'),'error':x.get('error')} for x in responses if x['id'] not in receipt_ids and x.get('error')]
dump(final/'usage.json',usage)
stop_source='deadline-guard.json' if (run/'deadline-guard.json').exists() else 'stop-requested.json'
stop=json.loads((run/stop_source).read_text()) if (run/stop_source).exists() else {}
finished=datetime.now(timezone.utc).isoformat();elapsed=min(end['deadline_epoch'],datetime.fromisoformat(stop.get('utc',finished)).timestamp())-datetime.fromisoformat(end['started_utc']).timestamp()
summary={'finished_utc':finished,'deadline':end,'elapsed_search_seconds':elapsed,'baseline_n':31,'target_max_n':30,'primary_success':bool(best and best['strict_success']),'minimum_valid_n':best['n'] if best else None,'best':best,'candidate_artifacts_rechecked':len(seen),'valid_artifacts':len(valid),'usage':usage,'stop_reason':stop.get('reason'),'claim_boundary':'Finite search does not give a universal lower bound. Reproduced or new 31-ray sets are partial outcomes only.','attribution':json.loads((run/'runtime-manifest.json').read_text())['attribution'],'monitor_automation_cleanup':'PENDING: delete this experiment heartbeat through automation_update, then record receipt.'}
dump(final/'summary.json',summary)
summary['stop_record_source']=stop_source
summary['closeout_execution']='Host heartbeat finalization after verified stop. The guard wrote stop-requested.json at the deadline but did not complete its final receipt or launch finalization; all owned processes were independently observed stopped before this verification-only closeout.' if stop_source=='stop-requested.json' else 'Guard deadline/success closeout.'
dump(final/'summary.json',summary)
lines=['# Original R3 KS search closeout','',f'Primary success: {summary["primary_success"]}. Minimum independently valid rays: {summary["minimum_valid_n"]}. Frozen target: at most 30.',f'Start: {end["started_utc"]}; immutable deadline: {end["deadline_utc"]}. Search elapsed: {elapsed:.3f} seconds.',f'Exact coordinate geometry, reconstructed CNF, complete DPLL UNSAT certificate, independent SymPy geometry and bitmask replay are saved beside each valid candidate.',f'Receipted API cost: USD {cost}. Requests without cost receipt: {usage["without_cost_receipt"]}.',summary['claim_boundary'],'','Model: fixed OpenRouter deepseek/deepseek-v4.1-flash. Host/tool/model attribution is in summary.json and runtime-manifest.json. Results not published.']
(final/'REPORT.md').write_text('\n\n'.join(lines),encoding='utf-8');print(json.dumps({k:summary[k] for k in ['primary_success','minimum_valid_n','elapsed_search_seconds','candidate_artifacts_rechecked','stop_reason']}))
