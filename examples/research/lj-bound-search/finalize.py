"""Closeout/replay only, never search; safe to rerun after fixed deadline/success."""
from pathlib import Path
import sys,json,time,hashlib,subprocess,psutil,os,datetime
from decimal import Decimal
RUN=Path(sys.argv[1]).resolve();FINAL=RUN/'final';FINAL.mkdir(exist_ok=True)
deadline=json.loads((RUN/'deadline.json').read_text())
assert time.time()>=deadline['deadline_epoch'] or (RUN/'primary-success.json').exists(),'Window still open'
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
actions=[]
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
try:
    owned=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(RUN/'linux_owned.py'),linux(RUN),'--stop'],capture_output=True,text=True,timeout=20)
    dump(FINAL/'linux-stop.json',json.loads(owned.stdout))
except Exception as e:dump(FINAL/'linux-stop.json',{'error':str(e)})
if (RUN/'process.json').exists():
    for name,item in json.loads((RUN/'process.json').read_text()).items():
        if not isinstance(item,dict) or 'pid' not in item:continue
        try:
            p=psutil.Process(item['pid'])
            if abs(p.create_time()-item['created'])>.5:continue
            protected={os.getpid(),*[q.pid for q in psutil.Process().parents()]}
            kids=p.children(recursive=True)
            if p.pid not in protected:p.kill();actions.append({'pid':p.pid,'name':name})
            for k in kids:
                if k.pid not in protected:
                    try:k.kill();actions.append({'pid':k.pid,'name':'owned child'})
                    except psutil.Error:pass
        except (psutil.Error,KeyError):pass
frozen=json.loads((RUN/'frozen-g.json').read_text())
integrity={n:hashlib.sha256((RUN/n).read_bytes()).hexdigest()==h for n,h in frozen['files'].items()}
assert all(integrity.values()),'Frozen evidence changed'
artifacts=list((RUN/'verified').glob('*.candidate.json'))
last=RUN/'work/candidate.json'
if last.exists():
    raw=last.read_bytes();p=FINAL/(hashlib.sha256(raw).hexdigest()+'.last-candidate.json');p.write_bytes(raw);artifacts.append(p)
seen=set();reports=[]
for p in artifacts:
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    if sha in seen:continue
    seen.add(sha);cert=FINAL/(sha+'.certificate.json')
    result=subprocess.run([sys.executable,str(RUN/'checker/check.py'),str(p),str(cert)],capture_output=True,text=True)
    (FINAL/(sha+'.checker.stdout.log')).write_text(result.stdout)
    (FINAL/(sha+'.checker.stderr.log')).write_text(result.stderr)
    try:r=json.loads(result.stdout)
    except ValueError:r={'valid':False,'reason':'incomplete final verification'}
    r.update(artifact=str(p),sha256=sha)
    if r.get('valid') and r.get('improved'):
        replay=subprocess.run([sys.executable,str(RUN/'checker/replay.py'),str(cert)],capture_output=True,text=True)
        (FINAL/(sha+'.replay.stdout.log')).write_text(replay.stdout)
        (FINAL/(sha+'.replay.stderr.log')).write_text(replay.stderr)
        try:r['final_replay']=json.loads(replay.stdout)
        except ValueError:r['final_replay']={'independent_replay_passed':False}
    reports.append(r)
accepted=[r for r in reports if r.get('final_replay',{}).get('independent_replay_passed')]
from fractions import Fraction
best=max(accepted,key=lambda r:Fraction(r['b_scaled_exact'])) if accepted else None
calls=[]
if (RUN/'calls.jsonl').exists():
    for line in (RUN/'calls.jsonl').read_text().splitlines():
        try:calls.append(json.loads(line))
        except ValueError:pass
dispatch=[e for e in calls if e['event']=='dispatch'];responses=[e for e in calls if e['event']=='response']
receipts=[e for e in responses if (e.get('usage') or {}).get('cost') is not None]
cost=sum((Decimal(str(e['usage']['cost'])) for e in receipts),Decimal(0));paid={r['id'] for r in receipts}
usage={'dispatched_requests':len(dispatch),'responses':len(responses),'recorded_cost_usd':str(cost),'without_cost_receipt':[r['id'] for r in dispatch if r['id'] not in paid],'response_models':sorted(set(r.get('response_model','unknown') for r in responses)),'receipt_details':responses,'note':'Missing receipt means cost unknown, not zero. Local abort is not proof of provider cancellation.'}
ref=json.loads((RUN/'baseline/reference.json').read_text())
now=datetime.datetime.now(datetime.timezone.utc)
ended=json.loads((RUN/'primary-success.json').read_text())['utc'] if (RUN/'primary-success.json').exists() else deadline['deadline_utc']
elapsed=(datetime.datetime.fromisoformat(ended.replace('Z','+00:00'))-datetime.datetime.fromisoformat(deadline['started_utc'].replace('Z','+00:00'))).total_seconds()
summary={'material_passport':{'type':'mathematical-code-experiment','sources':'reference/sources.json and LITERATURE.md','model':'OpenRouter deepseek/deepseek-v4.1-flash','host_contribution':'Literature baseline, proof-family formulation, exact checkers, engine adapter, process control, replay and final audit','model_contribution':'See saved API outputs, model-written work files, selected parameters and model proof; no other paid model used'},'finalized_utc':now.isoformat(),'deadline':deadline,'research_elapsed_seconds':elapsed,'research_stopped_utc':ended,'main_goal_success':bool(best),'published_old_bound':ref['published_exact'],'c_ref_definition':ref['c_ref_definition'],'c_ref_decimal_interval':ref['c_ref_decimal_interval'],'new_bound':best,'original_conjecture_ge_1':'unresolved','strict_conjecture_gt_1':'unresolved','claim': 'Improved lower bound; the original conjecture remains unresolved' if best else 'This run found no new uniform lower bound passing independent final checks; the original conjecture remains unresolved','scope':'All finite N>=2 and all global energy minimizers in R3; V(r)=r^-12-r^-6, E=sum_{i<j}V.','integrity':integrity,'usage':usage,'stop_actions':actions,'candidate_checks':reports,'automation_cleanup':'pending desktop tool deletion'}
summary['material_passport']['model_contribution']='Fixed-model ObjRun numerical search programs and saved parameters b=.694,L=.75 in jobs13/14; no model-authored standalone proof was finished before early stop.'
summary['material_passport']['host_contribution']='Source audit, unrounded baseline, frozen analytic proof family, two separate rational checkers, extraction of the already model-documented candidate, full proof instantiation, terminal replay and cleanup.'
if (FINAL/'automation-cleanup.json').exists():summary['automation_cleanup']=json.loads((FINAL/'automation-cleanup.json').read_text(encoding='utf-8'))
if (RUN/'deadline-guard.json').exists():
    stopped=json.loads((RUN/'deadline-guard.json').read_text())['utc']
    summary['owned_process_stop_utc']=stopped
    summary['elapsed_to_owned_process_stop_seconds']=(datetime.datetime.fromisoformat(stopped)-datetime.datetime.fromisoformat(deadline['started_utc'].replace('Z','+00:00'))).total_seconds()
dump(FINAL/'summary.json',summary)
proof='No new all-N certificate passed.' if not best else best['c_new_expression']+' = '+best['c_new_decimal']+'...'
text=f'''# Lennard-Jones experiment closeout

{summary['claim']}。

- Published old bound: {ref['published_exact']} = {ref['published_decimal']}...
- Frozen unrounded existing baseline: {ref['c_ref_decimal_interval']}.
- Independently replayed bound: {proof}
- Applies to ALL N>=2, ALL global minimizers in R3, V(r)=r^-12-r^-6.
- Non-strict >=1 conjecture: unresolved. Strict >1 conjecture: unresolved.
- First paid dispatch: {deadline['started_utc']}; fixed cutoff: {deadline['deadline_utc']}.
- Research stopped: {ended}; elapsed {elapsed:.3f} seconds.
- Receipted API cost: USD {cost}; missing cost receipt ids: {usage['without_cost_receipt']}.
- All frozen checker hashes passed. Complete rational certificates and independent replays are in this directory.

Host contribution: literature retrieval, baseline reproduction including unrounded
existing implication, proof-family/checker construction, orchestration and final
verification and the full proof instantiation. Model contribution: its logged
parameter searches, selected candidate and code in work/ and jobs/. The model
had not finished a standalone proof when the host certified its saved candidate.
This is not represented as an unaided model proof.
No local minimum, database energy comparison, virial identity or finite-N experiment
was promoted to an all-N conclusion. No results were published.
See reference/LITERATURE.md for source access limits and search-bounded novelty.
Monitoring automation cleanup is recorded separately in automation-cleanup.json.
'''
(FINAL/'REPORT.md').write_text(text,encoding='utf-8')
dump(FINAL/'inventory-sha256.json',{str(p.relative_to(RUN)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('reference','checker','baseline','work','verified','requests','proof') for p in (RUN/d).rglob('*') if p.is_file() and '__pycache__' not in str(p)})
print(json.dumps({'main_goal_success':bool(best),'bound':proof,'elapsed_seconds':elapsed,'receipted_cost_usd':str(cost),'without_cost_receipt':usage['without_cost_receipt']},ensure_ascii=False))
