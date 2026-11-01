"""Evidence review after stop only. Never invokes a model or search program."""
import json,sys,time,hashlib,shutil,subprocess,psutil,sqlite3
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
from audit import scan,frozen,put
run=Path(sys.argv[1]).resolve();deadline=json.loads((run/'deadline.json').read_text())
assert time.time()>=deadline['deadline_epoch'] or (run/'success.json').exists(),'Window open; no verified main success'
(run/'control/STOP').write_text('finalization; no more search')
final=run/'final';final.mkdir(exist_ok=True);frozen(run)
db_snapshots=[]
db_dir=final/'databases';db_dir.mkdir(exist_ok=True)
for source in (run/'engine').rglob('*.sqlite'):
    target=db_dir/('__'.join(source.relative_to(run).parts))
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)
    dst=sqlite3.connect(target)
    try:src.backup(dst)
    finally:dst.close();src.close()
    db_snapshots.append({'source':source.relative_to(run).as_posix(),'snapshot':target.relative_to(run).as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
put(final/'database-snapshots.json',db_snapshots)
scan(run)
best=json.loads((run/'best-verified.json').read_text());last_files=sorted((run/'work/candidates').glob('*.json'),key=lambda p:p.stat().st_mtime)
if (run/'work/candidate.json').exists():last_files.append(run/'work/candidate.json')
replays=[]
for tag,path in [('best',Path(best['artifact']))] if best.get('artifact') else []:
    shutil.copy2(path,final/(tag+'.matrix.json'))
    for c in ('check_pairs.py','check_matrix.py'):
        r=json.loads(subprocess.check_output([sys.executable,str(run/'checker'/c),str(final/(tag+'.matrix.json'))],text=True));put(final/(tag+'.'+c+'.json'),r);replays.append({'tag':tag,'checker':c,'valid':r['valid']})
if last_files:
    for p in sorted(last_files,key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            raw=p.read_bytes();obj=json.loads(raw);a=obj.get('matrix') if isinstance(obj,dict) else obj
            if not isinstance(a,list) or len(a)!=99 or any(len(row)!=99 for row in a):continue
            (final/'last-complete.matrix.json').write_bytes(raw)
            for c in ('check_pairs.py','check_matrix.py'):
                r=json.loads(subprocess.check_output([sys.executable,str(run/'checker'/c),str(final/'last-complete.matrix.json')],text=True));put(final/('last.'+c+'.json'),r)
            break
        except (ValueError,TypeError):pass
events=[]
if (run/'calls.jsonl').exists():
    for line in (run/'calls.jsonl').read_text().splitlines():
        try:events.append(json.loads(line))
        except ValueError:pass
dispatch=[e for e in events if e['event']=='dispatch'];responses=[e for e in events if e['event']=='response']
receipts=[e for e in responses if (e.get('usage') or {}).get('cost') is not None];ids={e['id'] for e in receipts}
usage={'requests':len(dispatch),'responses':len(responses),'receipt_cost_usd':str(sum((Decimal(str(e['usage']['cost'])) for e in receipts),Decimal(0))),'no_cost_receipt_request_ids':[e['id'] for e in dispatch if e['id'] not in ids],'no_response_request_ids':[e['id'] for e in dispatch if e['id'] not in {e['id'] for e in responses}],'generation_receipts':[{k:e.get(k) for k in ('id','generation_id','response_model','provider','usage','http_status')} for e in responses],'note':'Unreceipted costs unknown, not zero. Local HTTP cancellation does not establish remote cancellation.'}
success=json.loads((run/'success.json').read_text()) if (run/'success.json').exists() else None
health={}
for key,item in json.loads((run/'process.json').read_text()).items():
    if isinstance(item,dict) and 'pid' in item:
        try:p=psutil.Process(item['pid']);health[key]=abs(p.create_time()-item['created'])<.5 and p.is_running()
        except psutil.Error:health[key]=False
summary={'finalized_utc':datetime.now(timezone.utc).isoformat(),'deadline':deadline,'elapsed_seconds':min(time.time(),deadline['deadline_epoch'])-datetime.fromisoformat(deadline['started_utc'].replace('Z','+00:00')).timestamp(),'main_goal_solved':bool(success),'success':success,'status':'SOLVED_EXISTENCE' if success else 'UNKNOWN','best_approximate_candidate':best,'verified_candidates':len(list((run/'verified').glob('*/report.json'))),'replays':replays,'usage':usage,'owned_processes_still_alive':health,'proof_files':[str(p.relative_to(run)) for p in (run/'work/proofs').rglob('*') if p.is_file()],'partial_results':'Frozen rooted reduction and small encoding recovery reproduce prior art; approximate graphs are not success. Model lemmas/proof claims require separate review.','automation_cleanup':'Pending host automation_update deletion; this script never edits automation internals.'}
try:
 from owned_linux import inspect
 summary['owned_linux_after_stop']=inspect(run)
except Exception as e:summary['owned_linux_verification_error']=str(e)
put(final/'summary.json',summary);put(final/'usage.json',usage)
files={p.relative_to(run).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('checker','work','verified','requests','final') for p in (run/folder).rglob('*') if p.is_file() and p.name!='evidence-hashes.json'}
for name in ('GOAL.md','LITERATURE.md','frozen-g.json','runtime-manifest.json','host-code-manifest.json','contributions.json','preparation.json','deadline.json','calls.jsonl','events.jsonl','RUN_NOTES.md','monitoring/interventions.jsonl','sources/manifest.json'):
    p=run/name
    if p.exists():files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
put(final/'evidence-hashes.json',files)
(final/'REPORT.md').write_text(f"# Conway 99 experiment\n\nStatus: {summary['status']}. Full problem solved: {bool(success)}.\n\nFirst paid request: {deadline['started_utc']}. Immutable deadline: {deadline['deadline_utc']}.\n\nVerified candidate count: {summary['verified_candidates']}. Best violations: {best.get('constraint_violations')}, including degree {best.get('degree_violations')}, adjacent {best.get('adjacent_pair_violations')}, nonadjacent {best.get('nonadjacent_pair_violations')}.\n\nReceipt cost USD {usage['receipt_cost_usd']}; requests without cost receipt: {usage['no_cost_receipt_request_ids']}. Unknown cost is not zero.\n\nNo general nonexistence conclusion follows from a timeout or local-search stall. See summary.json, usage.json, verifier reports and contribution ledger.\n")
print(json.dumps(summary,indent=2))
