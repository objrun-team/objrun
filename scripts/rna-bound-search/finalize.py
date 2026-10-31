"""Stop only this run, independently replay complete certificates, reconcile receipts."""
import json,sys,hashlib,subprocess,time,psutil,os
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[2]
run=Path(sys.argv[1]) if len(sys.argv)>1 else Path((ROOT/'data/rna-bound-search/latest-run.txt').read_text().strip())
deadline=json.loads((run/'deadline.json').read_text())
early_path=run/'early-stop-request.json'
early=json.loads(early_path.read_text(encoding='utf-8')) if early_path.exists() else None
if time.time()<deadline['deadline_epoch'] and not (early and early.get('authorized') and early.get('allow_final_verification_only')):raise SystemExit('Original window is still open and no user-authorized early closeout exists.')
final=run/'final';final.mkdir(exist_ok=True)
def dump(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8')
def linux(p):return '/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
actions=[]
info=json.loads((run/'process.json').read_text())
for name in ('engine','runner'):
 v=info.get(name,{})
 try:
  p=psutil.Process(v['pid'])
  if abs(p.create_time()-v['created'])<.5:
   kids=p.children(recursive=True);p.kill()
   for k in kids:
    try:k.kill()
    except psutil.Error:pass
   actions.append({'name':name,'pid':v['pid'],'killed':True})
 except (psutil.Error,KeyError):pass
for n,h in json.loads((run/'frozen-g.json').read_text())['files'].items():assert hashlib.sha256((run/n).read_bytes()).hexdigest()==h,('frozen checker changed',n)
freeze=json.loads((run/'targets-frozen.json').read_text())
best=json.loads((run/'best-verified.json').read_text())
selection_path=final/'finalization-candidates.json'
selection=json.loads(selection_path.read_text(encoding='utf-8')) if selection_path.exists() else {}
results=[]
for target in freeze['targets']:
 tid=target['id'];b=selection.get(tid,best.get(tid));fresh=None
 if b and (b.get('eligible_for_replay') or b.get('valid')):
  artifact=Path(b['artifact']);assert hashlib.sha256(artifact.read_bytes()).hexdigest()==b['raw_sha256']
  out=final/('target-'+tid+'-independent-replay');out.mkdir(exist_ok=True)
  py='/home/imontlaji/.local/share/objrun-rna-20261030-env/bin/python'
  proc=subprocess.run(['wsl','-d','Ubuntu','--','env','OMP_NUM_THREADS=4',py,linux(run/'checker/check.py'),linux(artifact),'--freeze',linux(run/'targets-frozen.json'),'--out',linux(out)],capture_output=True,text=True)
  (out/'host.stdout.log').write_text(proc.stdout);(out/'host.stderr.log').write_text(proc.stderr)
  if proc.returncode==0:
   try:fresh=json.loads(proc.stdout)
   except ValueError:pass
 old=Decimal(target['author_cache_baseline']); paper=Decimal(target['paper_display_bound'])
 independently_proved=Decimal(fresh['probability_upper']) if fresh and fresh.get('valid') else None
 improved=independently_proved is not None and independently_proved<min(old,paper)
 # Preserve the original reference if this campaign did not improve it.
 new=min(old,independently_proved) if independently_proved is not None else old
 results.append({'target_id':tid,'name':target['name'],'role':'primary' if tid==freeze['primary_id'] else 'backup','dot_bracket':target['dot_bracket'],'paper_display_bound':str(paper),'author_cache_baseline':str(old),'new_best_bound':str(new),'independently_certified_campaign_bound':None if independently_proved is None else str(independently_proved),'strict_success_against_both_references':improved,'absolute_improvement':str(old-new),'relative_improvement':str((old-new)/old),'new_bound_evidence':'complete independently replayed campaign certificate' if independently_proved is not None and independently_proved<old else 'original author cache retained; no stronger complete campaign certificate','replay':fresh,'candidate':b.get('artifact') if b else None})
events=[]
if (run/'calls.jsonl').exists():
 for line in (run/'calls.jsonl').read_text().splitlines():
  try:events.append(json.loads(line))
  except ValueError:pass
dispatch=[e for e in events if e['event']=='dispatch'];responses=[e for e in events if e['event']=='response']
receipts=[e for e in responses if (e.get('usage') or {}).get('cost') is not None]
receipt_ids={e['id'] for e in receipts}
cost=sum((Decimal(str(e['usage']['cost'])) for e in receipts),Decimal(0))
usage={'dispatched_requests':len(dispatch),'responses':len(responses),'recorded_receipt_cost_usd':str(cost),'no_cost_receipt_request_ids':[e['id'] for e in dispatch if e['id'] not in receipt_ids],'generation_ids':[{k:e.get(k) for k in ('id','generation_id','http_status','response_model','provider','usage')} for e in responses],'note':'Missing/in-flight/faulted request cost is unknown, not zero. Local abort is not proof of provider-side cancellation.'}
summary={'finalized_utc':datetime.now(timezone.utc).isoformat(),'deadline':deadline,'model':'deepseek/deepseek-v4.1-flash','results':results,'usage':usage,'stop_actions':actions,'claim_scope':'Only the frozen Turner2004/ViennaRNA computational model; no biological experiment or state-of-the-art claim.','baseline_discrepancy':'Chicken feet paper display 0.1336 versus public cache 0.13368987270026328; both thresholds required. Bulges excluded before search after failed baseline reproduction.','automation_cleanup':'Required through Codex automation_update after this script completes.'}
dump(final/'summary.json',summary)
lines=['# RNA probability-bound experiment final record','',f'Model: {summary["model"]}',f'First paid dispatch: {deadline["started_utc"]}',f'Immutable deadline: {deadline["deadline_utc"]}','', '| Target | Author cache | New best | Absolute decrease | Relative decrease | Strict success |','|---|---:|---:|---:|---:|---|']
for r in results:lines.append('| '+r['name']+' | '+r['author_cache_baseline']+' | '+r['new_best_bound']+' | '+r['absolute_improvement']+' | '+r['relative_improvement']+' | '+str(r['strict_success_against_both_references'])+' |')
lines+=['',f'Recorded API cost: USD {cost}. Requests lacking cost receipts: {usage["no_cost_receipt_request_ids"]}.',summary['baseline_discrepancy'],summary['claim_scope'],'','Complete certificates, regenerated energy tables, all differential positions, assignment domains and full-coverage receipts are in the target replay directories. All frozen targets appear, including failures.']
(final/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False))
print(json.dumps([{k:v for k,v in r.items() if k not in ('replay','dot_bracket')} for r in results],ensure_ascii=False))
