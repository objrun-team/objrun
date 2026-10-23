"""Recount exact public mappings without reading historical evaluation contents."""
import copy
from shared import *

def inventory(roots,catalog):
    reports=[];started=set();histories={};money=[]
    for root in roots:
        assert processes_exited(root),('HistoricalProcessStillLive',str(root))
        cells={}
        for d in (root/'outputs/tasks').glob('*/*'):
            if not any(d.iterdir()):continue
            pair=(d.parent.name,d.name);cells[pair]=d;started.add(pair)
        m=ledger(root/'outputs/tasks');money.append(m)
        reports.append({'root':str(root),'started':len(cells),'results':sum((d/'result.json').exists() for d in cells.values()),'accounting':m})
        for pair,d in cells.items():histories.setdefault(pair,[]).append({'root':str(root),'directory':str(d),'resultPresent':(d/'result.json').exists(),'resultSha256':sha(d/'result.json') if (d/'result.json').exists() else None})
    allpairs={(a,t['key']) for t in catalog for a in core.ARMS}
    assert len(allpairs)==960 and started<=allpairs
    claims=[]
    for root in roots:
        for p in (root/'outputs/concurrency16/claims').glob('*/*.json'):
            c=load(p);pair=(c['arm'],c['key']);claims.append(pair)
            assert pair in started,('ClaimWithoutExecutionEvidenceRequiresReview',pair)
    pending=[];cases=[]
    for t in catalog:
        for arm in core.ARMS:
            pair=(arm,t['key']);old=histories.get(pair,[])
            c={'id':t['id'],'key':t['key'],'arm':arm,'historicalAttempts':old,'neverStarted':pair not in started}
            cases.append(c)
            if not old:pending.append({k:c[k] for k in ['id','key','arm']})
    accounting={'actualCostUsd':math.fsum(m['actualCostUsd'] for m in money),'accountedUpperBoundUsd':math.fsum(m['accountedUpperBoundUsd'] for m in money),'unknownReserveUsd':math.fsum(m['unknownReserveUsd'] for m in money)}
    return {'cases':cases,'remaining':pending,'histories':reports,'uniqueStarted':len(started),'accounting':accounting,'claimsChecked':len(claims)}

def prepare():
    assert not (CONTROL/'launch.json').exists(),'AlreadyLaunched'
    if (CONTROL/'plan.json').exists():return load(CONTROL/'plan.json')
    catalog=core.CATALOG
    inv=inventory(HISTORY,catalog)
    assert len(inv['remaining'])==258 and inv['uniqueStarted']==702,'ExpectedInventoryChangedReviewBeforePayment'
    assert sum(r['results'] for r in inv['histories'])==736 and sum(r['started'] for r in inv['histories'])==738
    assert abs(inv['accounting']['accountedUpperBoundUsd']-17.336783301)<1e-7
    files=[]
    for root in HISTORY:
        for pin in load(root/'outputs/source-pins.json'):assert sha(root/pin['path'])==pin['sha256'],'HistoricalSolverChanged'
        for c in ['control','outputs/concurrency16','outputs/continuation-429']:
            if (root/c/'source-pins.json').exists():
                for pin in load(root/c/'source-pins.json'):assert sha(root/pin['path'])==pin['sha256'],'HistoricalControllerChanged'
        for folder in ['outputs/tasks','analysis/outputs']:
            for p in (root/folder).rglob('*'):
                if p.is_file():files.append({'path':str(p),'sha256':sha(p)})
        for folder in ['outputs','control','outputs/concurrency16','outputs/continuation-429']:
            for p in (root/folder).glob('*'):
                if p.is_file() and p.suffix in ['.json','.jsonl','.md','.log','.py','.patch']:files.append({'path':str(p),'sha256':sha(p)})
    files={x['path']:x for x in files}
    frozen={'atUtc':utc(),'files':sorted(files.values(),key=lambda e:e['path']),'accounting':inv['accounting'],'histories':inv['histories'],'oldEvaluationsNotRead':True,'onlyHashedForPreservation':True}
    common.durable(CONTROL/'history-freeze.json',frozen)
    runid='resume-v3-'+sha(CONTROL/'history-freeze.json')[:16]
    selected=[{**e,'attemptId':runid+'-main-'+e['arm']+'-'+e['key'],'maximumUsd':cap(e['arm'])} for e in inv['remaining']]
    maximum=math.fsum(e['maximumUsd'] for e in selected)
    assert inv['accounting']['accountedUpperBoundUsd']+2*maximum<=78+1e-9,'NotEnoughBudgetForPrimaryAndWorstCaseOneRepair'
    plan={'runId':runid,'atUtc':utc(),'authorization':'Human authorized never-started continuation and one subsequent infrastructure repair, bounded isolated unknown costs, 2026-10-19','historyFreezeSha256':sha(CONTROL/'history-freeze.json'),'historicalAccounting':inv['accounting'],'cases':inv['cases'],'selected':selected,'uniqueHistoricalMappings':702,'expectedMappings':960,'expectedMainAttempts':258,'maxNewRepairAttemptsPerCell':1,'concurrency':[16,16,16],'mainMaximumUsd':maximum,'maximumIncludingEveryPotentialRepairUsd':inv['accounting']['accountedUpperBoundUsd']+2*maximum,'claimsChecked':inv['claimsChecked'],'noOldIdOodOrFailureFeedbackToSolver':True}
    plan['serverRoot']=str(ROOT)
    common.durable(CONTROL/'plan.json',plan)
    cfg=copy.deepcopy(load(CONTROL/'base-experiment.json'));cfg.update(priorUpperBoundUsd=inv['accounting']['accountedUpperBoundUsd'],priorUnknownReserveUsd=inv['accounting']['unknownReserveUsd'],taskConcurrency=16,graderConcurrency=16,expectedNewRecords=258,run='llm-srbench-20261019-resume-v3')
    common.save(ROOT/'package/experiment.json',cfg)
    common.save(ROOT/'package/continuation-plan.json',{'allowedCells':[{k:e[k] for k in ['id','key','arm']} for e in selected],'purpose':'only historically never-started primary cells; supplemental subset separately frozen','canaryIds':[]})
    common.save(OUT/'source-pins.json',core.sourcepins())
    return plan
if __name__=='__main__':
    p=prepare();print(json.dumps({'selected':len(p['selected']),'runId':p['runId'],'historicalUpper':p['historicalAccounting']['accountedUpperBoundUsd'],'mainMaximumUsd':p['mainMaximumUsd'],'maximumWithAllRepairs':p['maximumIncludingEveryPotentialRepairUsd']}))
