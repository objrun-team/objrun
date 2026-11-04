"""Post-stop existing-evidence review, receipt accounting and report. No search."""
from pathlib import Path
import sys,json,subprocess,hashlib,datetime,time,psutil,shutil
from decimal import Decimal
from fractions import Fraction
run=Path(sys.argv[1]).resolve();final=run/'final';final.mkdir(exist_ok=True)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
clock=read(run/'deadline.json')
assert time.time()>=clock['deadline_epoch'] or (run/'primary-success.json').exists(),'Research window still open'
assert (run/'deadline-guard.json').exists(),'Stop owned processes before finalization'
frozen=read(run/'frozen-g.json');integrity={p:sha(run/p)==h for p,h in frozen['files'].items()};assert all(integrity.values())
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
try:
    z=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_owned.py'),linux(run),'--stop'],capture_output=True,text=True,timeout=30)
    dump(final/'linux-stop.json',json.loads(z.stdout))
except Exception as e:dump(final/'linux-stop.json',{'error':str(e)})
owned=[]
for k,v in read(run/'process.json').items():
    if not isinstance(v,dict) or 'pid' not in v:continue
    try:p=psutil.Process(v['pid']);alive=abs(p.create_time()-v['created'])<.5
    except psutil.Error:alive=False
    owned.append({'name':k,'pid':v['pid'],'same_owned_process_alive':alive})
assert not any(x['same_owned_process_alive'] for x in owned),'Owned runner/engine still live'
bundles=[];accepted=[];secondary=[]
for folder in (run/'verified/bundles').glob('*'):
    manifest=read(folder/'manifest.json')
    assert all(sha(folder/n)==h for n,h in manifest['files'].items()),'Immutable evidence corrupted'
    digest=hashlib.sha256(json.dumps(manifest['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert digest==manifest['bundle_sha256']==folder.name
    obj=read(folder/'candidate.json');entry={'bundle_sha256':digest,'claim_type':obj['claim_type'],'statement':obj['statement'],'primary_passed':False,'unproved_steps':obj.get('unproved_steps',[])}
    rec=run/'reviews'/(digest+'.json')
    if rec.exists() and obj['claim_type'] in {'proof_ge_1','proof_gt_1','counterexample'}:
        review=read(rec)
        ok=review.get('primary_passed') is True and review.get('all_quantifiers_and_boundaries_verified') is True and review.get('independent_replay_passed') is True and review.get('bundle_sha256')==digest and review.get('claim_type')==obj['claim_type'] and not obj.get('unproved_steps')
        for key in ('review_report','replay_report'):
            p=(run/'reviews'/review.get(key,'missing')).resolve()
            ok=ok and p.is_relative_to((run/'reviews').resolve()) and p.is_file() and sha(p)==review.get(key+'_sha256')
        entry['primary_passed']=bool(ok);entry['review']=review
        if ok:accepted.append(entry)
    if obj.get('method')=='ball_average_v1':
        cert=final/(digest+'.secondary-certificate.json')
        first=subprocess.run([sys.executable,str(run/'checker/ball_check.py'),str(folder/'candidate.json'),str(cert)],capture_output=True,text=True)
        (final/(digest+'.check.log')).write_text(first.stdout+'\n'+first.stderr)
        try:r=json.loads(first.stdout)
        except ValueError:r={'valid':False}
        if r.get('valid') and r.get('improved'):
            second=subprocess.run([sys.executable,str(run/'checker/ball_replay.py'),str(cert)],capture_output=True,text=True)
            (final/(digest+'.replay.log')).write_text(second.stdout+'\n'+second.stderr)
            try:r['replay']=json.loads(second.stdout)
            except ValueError:r['replay']={'independent_replay_passed':False}
            if r['replay'].get('independent_replay_passed') and Fraction(r['b_scaled_exact'])>Fraction(347,500):secondary.append(r)
        entry['secondary']=r
    bundles.append(entry)
# Snapshot final unsubmitted material without treating it as a verified result.
for p in (run/'work').rglob('*'):
    if p.is_file():
        target=final/'last-work'/p.relative_to(run/'work');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
calls=[]
for line in (run/'calls.jsonl').read_text(encoding='utf-8').splitlines():
    try:calls.append(json.loads(line))
    except ValueError:pass
dispatch=[x for x in calls if x.get('event')=='dispatch'];response=[x for x in calls if x.get('event')=='response']
receipts=[x for x in response if (x.get('usage') or {}).get('cost') is not None]
ids={x['id'] for x in receipts};cost=sum((Decimal(str(x['usage']['cost'])) for x in receipts),Decimal(0))
guard=read(run/'deadline-guard.json');stopped=guard['utc']
elapsed=(datetime.datetime.fromisoformat(stopped.replace('Z','+00:00'))-datetime.datetime.fromisoformat(clock['started_utc'].replace('Z','+00:00'))).total_seconds()
best=max(secondary,key=lambda r:Fraction(r['b_scaled_exact'])) if secondary else None
summary={'round':2,'finalized_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'model':'deepseek/deepseek-v4.1-flash','primary_success':bool(accepted),'accepted_primary':accepted,'conjecture_ge_1':'proved' if any(x['claim_type'] in ('proof_ge_1','proof_gt_1') for x in accepted) else 'refuted' if any(x['claim_type']=='counterexample' for x in accepted) else 'unresolved','conjecture_gt_1':'proved' if any(x['claim_type']=='proof_gt_1' for x in accepted) else 'refuted' if any(x['claim_type']=='counterexample' for x in accepted) else 'unresolved','prior_bound_exact':'347/500 * 2^(1/6)','secondary_best':best,'clock':clock,'stopped_utc':stopped,'elapsed_seconds_to_process_stop':elapsed,'usage':{'requests':len(dispatch),'responses':len(response),'receipted_cost_usd':str(cost),'no_cost_receipt_ids':[x['id'] for x in dispatch if x['id'] not in ids],'served_models':sorted(set(x.get('response_model','unknown') for x in response)),'receipt_records':response},'frozen_integrity':integrity,'owned_process_check':owned,'bundles':bundles,'unsubmitted_evidence':'final/last-work; unverified claims are not success','automation_cleanup':'required via desktop tool','contributions':{'host':'Prior proof/calibrations, fixed criteria, intake checker, independent mathematical reviews/replays when present, orchestration, process guard, evidence/cost audit','model':'Actual fixed-model trajectories, research programs, proofs/attempts, exact/numerical artifacts in work and immutable bundles'}}
if (final/'automation-cleanup.json').exists():summary['automation_cleanup']=read(final/'automation-cleanup.json')
dump(final/'summary.json',summary)
text=f'''# LJ conjecture round2 closeout

Primary success: {bool(accepted)}.
Non-strict r_min>=1: {summary['conjecture_ge_1']}.
Strict r_min>1: {summary['conjecture_gt_1']}.
Only a complete universal proof or globally certified <1 counterexample counts.
Improved lower bounds below1 remain secondary and never imply resolution.

Prior bound retained: (347/500)*2^(1/6) ~ .778988661526704849.
Secondary improved bound: {best['c_new_expression'] if best else 'none independently replayed'}.
First paid request: {clock['started_utc']}; fixed deadline: {clock['deadline_utc']}.
Owned processes stopped: {stopped}; elapsed {elapsed:.3f}s.
Model: OpenRouter deepseek/deepseek-v4.1-flash.
Receipted cost USD{cost}; requests{len(dispatch)}; missing receipt ids{summary['usage']['no_cost_receipt_ids']}.
All frozen hashes passed. No publication, no unrelated process/WSL restart.

Complete reviewed evidence, proof gaps, immutable bundles, costs and provenance
are in summary.json, verified/bundles, reviews, work/RESEARCH_LOG.md and last-work.
The lack of a proof in this budget is not evidence that the conjecture is false
or impossible to prove. Unreviewed model assertions remain unverified.
Delete monitoring heartbeat through automation_update and record receipt here.
'''
    
(final/'REPORT.md').write_text(text,encoding='utf-8')
dump(final/'inventory-sha256.json',{str(p.relative_to(run)).replace('\\','/'):sha(p) for d in ('reference','checker','baseline','work','verified','reviews','requests','jobs','controller-sources') for p in (run/d).rglob('*') if p.is_file() and '__pycache__' not in str(p)})
print(json.dumps({k:summary[k] for k in ('primary_success','conjecture_ge_1','conjecture_gt_1','elapsed_seconds_to_process_stop')}))
