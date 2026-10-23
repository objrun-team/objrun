"""Freeze the finished original campaign, then an eligibility/budget manifest."""
import argparse,copy,os,uuid
from shared import *
from selection import classify,usable_candidate
def ready():
    s=load(MAIN/'outputs/status.json')
    if s['stage'] not in ['complete','complete_with_exceptions','needs_attention','drained']:return False,'main_still_running'
    for root in [V1,MAIN]:
        state=load(root/'outputs/status.json')
        for field,default in [('pid','run.py'),('graderPid','grader.py')]:
            entry=state.get('controllerEntry' if field=='pid' else 'graderEntry',str(root/'package'/default))
            if live(state.get(field,0),entry):return False,'original_process_still_live'
        for d in (root/'outputs/tasks').glob('*/*'):
            p=d/'native-process.json'
            if p.exists() and live(load(p)['pid'],root/'package/native.ts'):return False,'original_native_still_live'
    # No read-only preparation can establish a remote provider's unreported bill;
    # preserve it and wait beyond the original request's maximum local lifetime.
    for root in [V1,MAIN]:
        for u in ledger(root/'outputs/tasks')['unknownRequests']:
            if time.time()*1000<u['dispatchAtMs']+720000:return False,'unknown_dispatch_quiet_window'
    return True,'original_processes_exited_and_local_requests_terminated'
def prepare():
    for pin in load(CONTROL/'blueprint-pins.json'):
        if pin['path'] not in ['package/experiment.json','package/continuation-plan.json']:assert sha(ROOT/pin['path'])==pin['sha256'],'BlueprintChanged'
    if (CONTROL/'plan.json').exists():return {'prepared':True,'alreadyFrozen':True,'selected':len(load(CONTROL/'plan.json')['selected'])}
    ok,why=ready()
    if not ok:return {'prepared':False,'waiting':why}
    for root in [V1,MAIN]:
        for pin in load(root/'outputs/source-pins.json'):assert sha(root/pin['path'])==pin['sha256'],'OriginalPackageChanged'
    for pin in load(MAIN/'outputs/concurrency16/source-pins.json'):assert sha(MAIN/pin['path'])==pin['sha256'],'MainControlChanged'
    assert sha(CONTROL/'base-experiment.json')==next(e['sha256'] for e in load(CONTROL/'base-source-pins.json') if e['path']=='package/experiment.json'),'BaseConfigurationChanged'
    files=[]
    for root in [V1,MAIN]:
        for p in (root/'outputs/tasks').rglob('*'):
            if p.is_file():files.append({'path':str(p),'sha256':sha(p)})
        for name in ['status.json','source-pins.json','all-candidates-frozen.json','combined-analysis-audit.json','summary.json','results.csv','REPORT.md']:
            p=root/'outputs'/name
            if p.exists():files.append({'path':str(p),'sha256':sha(p)})
    for p in (MAIN/'analysis/outputs').rglob('*'):
        if p.is_file():files.append({'path':str(p),'sha256':sha(p)})
    first=ledger(V1/'outputs/tasks');second=ledger(MAIN/'outputs/tasks');prior_actual=first['actualCostUsd']+second['actualCostUsd'];prior_upper=first['accountedUpperBoundUsd']+second['accountedUpperBoundUsd'];reserve=first['unknownReserveUsd']+second['unknownReserveUsd']
    freeze={'atUtc':utc(),'mainState':load(MAIN/'outputs/status.json'),'files':files,'originalAccounting':{'actualCostUsd':prior_actual,'accountedUpperBoundUsd':prior_upper,'unknownReserveUsd':reserve},'v1Ledger':first,'v2Ledger':second,'onlyPublicAndTrainUsedForEligibility':True,'noIdOodRead':True,'sourceManifest':load(CONTROL/'base-source-pins.json')}
    common.durable(CONTROL/'main-freeze.json',freeze);freezehash=sha(CONTROL/'main-freeze.json');catalog=load(MAIN/'data/public/catalog.json');roundid='infra-r1-'+freezehash[:16];cases=[];selected=[];left=max(0.,78-prior_upper)
    for t in catalog:
        for arm in ['baseline','objrun','independent','binary']:
            candidates=[r/'outputs/tasks'/arm/t['key'] for r in [V1,MAIN]];present=[d for d in candidates if d.exists() and any(d.iterdir())];assert len(present)<=1,('OriginalMappingOverlap',arm,t['key'])
            d=present[0] if present else None;r=load(d/'result.json') if d and (d/'result.json').exists() else None;a=ledger(d) if d else {'actualCostUsd':0,'accountedUpperBoundUsd':0,'unknownReserveUsd':0,'unknownRequests':[],'modelCalls':0}
            has=usable_candidate(d,r or {}) if d else False;c=classify(r,bool(d),bool(a['unknownRequests']),has)
            case={'id':t['id'],'key':t['key'],'arm':arm,'sourceRoot':str(d.parents[3]) if d else None,'originalDirectory':str(d) if d else None,'originalProtocolVersion':'v1' if d and d.is_relative_to(V1) else 'v2','originalResultSha256':sha(d/'result.json') if r else None,'originalError':r.get('error') if r else ('interrupted' if d else None),'originalValid':bool(r and r.get('valid')),'originalAccounting':a,'usableCandidate':has,**c}
            if c['eligible']:
                cap=.025 if arm=='baseline' else .1
                if cap<=left+1e-10:
                    case.update(selected=True,attemptId=roundid+'-'+arm+'-'+t['key'],attemptMaximumUsd=cap);left-=cap;selected.append({k:case[k] for k in ['id','key','arm','attemptId','attemptMaximumUsd']})
                else:case.update(selected=False,budgetInsufficient=True)
            cases.append(case)
    manifest={'roundId':roundid,'authorization':'Human explicitly authorized one independent infrastructure attempt per eligible cell after original freeze, 2026-10-19','atUtc':utc(),'originalFreezeSha256':freezehash,'originalAccounting':freeze['originalAccounting'],'selected':selected,'cases':cases,'maxNewAttemptsPerCell':1,'concurrency':[16,16,16],'maximumTotalUsd':78,'reservedAttemptMaximumUsd':sum(e['attemptMaximumUsd'] for e in selected),'budgetRemainderAfterFullAttemptCapsUsd':left,'noIdOodReadForSelection':True,'noOriginalFailureFeedbackToSolver':True}
    common.durable(CONTROL/'plan.json',manifest)
    base=load(CONTROL/'base-experiment.json');cfg=copy.deepcopy(base);cfg.update(priorUpperBoundUsd=prior_upper,priorUnknownReserveUsd=reserve);common.save(ROOT/'package/experiment.json',cfg)
    common.save(ROOT/'package/continuation-plan.json',{'allowedCells':[{k:e[k] for k in ['id','key','arm']} for e in selected],'canaryIds':[],'purpose':'new independent infrastructure attempts only; no old feedback or original errors'})
    common.save(OUT/'source-pins.json',core.sourcepins());return {'prepared':True,'selected':len(selected),'eligible':sum(c['eligible'] for c in cases),'reconcileOnly':sum(c['route']=='reconcile_only' for c in cases),'budgetSkipped':sum(c.get('budgetInsufficient',False) for c in cases),'originalUpperBoundUsd':prior_upper,'attemptCapsUsd':manifest['reservedAttemptMaximumUsd'],'roundId':roundid}
if __name__=='__main__':print(json.dumps(prepare()))
