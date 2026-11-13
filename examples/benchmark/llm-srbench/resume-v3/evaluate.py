"""Free post-freeze analysis, all versions separate, no best-score replacement."""
import csv,statistics
from shared import *

def verify_freezes():
    for name in ['main','repair']:
        d=round_out(name);f=load(d/'candidate-fee-freeze.json');assert not f['idOodAccessed']
        for e in f['files']:assert sha(ROOT/e['path'])==e['sha256'],e['path']
        assert math.isclose(ledger(d/'tasks')['accountedUpperBoundUsd'],f['accounting']['accountedUpperBoundUsd'],abs_tol=1e-9)

def score(root,name,r):
    import grader,numpy as np
    result={'source':name,'id':None,'ood':None,'solverNormallyCompleted':r.get('valid',False),'answerSha256':common.digest(r.get('answer','')),'numericalMetricsNotSA':True}
    if not r.get('valid'):return result
    g=r.get('trainingGrade')
    if not g:
        grader.OUT=ROOT/'analysis/fit-cache';g=grader.fit(r['key'],r.get('answer',''))
    if g.get('candidateSha256'):assert g['candidateSha256']==common.digest(r.get('answer',''))
    result['training']=g
    for split in ['id','ood']:
        p=HISTORY[1]/'data/private'/(r['key']+'-'+split+'.npz')
        if not p.exists():continue
        if g.get('expression') and 'parameters' in g:
            with np.load(p,allow_pickle=False) as a:q={'expression':g['expression'],'parameters':g['parameters'],'mode':'predict','X':a['X'].tolist(),'y':a['y'].tolist(),'cpuSeconds':60}
            result[split]=grader.worker(q)
        else:result[split]={'valid':True,'passed':False,'acc01':False,'nmse':None,'errorType':g.get('errorType','InvalidFinalFormula')}
    return result

def main():
    verify_freezes();p=load(CONTROL/'plan.json');sources=[('history-v1',HISTORY[0]/'outputs'),('history-v2',HISTORY[1]/'outputs'),('history-infra-r1',HISTORY[2]/'outputs'),('new-main',round_out('main')),('new-repair',round_out('repair'))];jobs=[]
    for name,d in sources:
        for file in d.glob('tasks/*/*/result.json'):jobs.append((name,file,load(file)))
    evaluations={};summaries={}
    def work(job):
        name,file,r=job;v=score(file.parents[4],name,r);common.save(ROOT/'analysis/attempts'/name/r['arm']/r['key']/'evaluation.json',v);return name,r,v
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for name,r,v in pool.map(work,jobs):
            evaluations[name,r['arm'],r['key']]=v;s=summaries.setdefault(name,{'records':0,'normallyCompleted':0,'infrastructureOrInterrupted':0,'idEligible':0,'idPassed':0,'oodEligible':0,'oodPassed':0,'actualCostUsd':0.,'accountedUpperBoundUsd':0.})
            s['records']+=1;s['normallyCompleted']+=bool(r['valid']);s['infrastructureOrInterrupted']+=not bool(r['valid'])
            d=dict(sources)[name]/'tasks'/r['arm']/r['key'];a=ledger(d);s['actualCostUsd']+=a['actualCostUsd'];s['accountedUpperBoundUsd']+=a['accountedUpperBoundUsd']
            for split in ['id','ood']:
                if v[split] is not None:s[split+'Eligible']+=1;s[split+'Passed']+=bool(v[split].get('passed'))
    rows=[]
    for c in p['cases']:
        a,k=c['arm'],c['key'];row={'id':c['id'],'key':k,'arm':a};attempts=[]
        for name,d in sources:
            directory=d/'tasks'/a/k;rp=directory/'result.json';started=directory.exists() and any(directory.iterdir());r=load(rp) if rp.exists() else None;v=evaluations.get((name,a,k));fees=ledger(directory) if started else None
            row[name+'_state']='completed' if r and r['valid'] else 'infrastructure_failure' if r else 'interrupted' if started else 'not_in_this_source'
            row[name+'_idPassed']=((v or {}).get('id') or {}).get('passed');row[name+'_oodPassed']=((v or {}).get('ood') or {}).get('passed');row[name+'_actualUsd']=fees['actualCostUsd'] if fees else 0;row[name+'_upperUsd']=fees['accountedUpperBoundUsd'] if fees else 0
            if started:attempts.append({'source':name,'state':row[name+'_state'],'error':r.get('error') if r else 'interrupted','rawResultSha256':sha(rp) if rp.exists() else None,'accounting':fees})
        row['terminalState']='normally_completed_attempt_recorded' if any(x['state']=='completed' for x in attempts) else 'infrastructure_exception_retained'
        row['scoreSelectionPolicy']='all_sources_separate_no_best_score_selection';rows.append(row)
        common.save(ROOT/'analysis/mapping'/a/(k+'.json'),{'id':c['id'],'key':k,'arm':a,'terminalState':row['terminalState'],'attempts':attempts,'historicalPrimaryNotOverwritten':True,'noBestScoreSelection':True})
    assert len(rows)==len({(r['arm'],r['key']) for r in rows})==960
    with (OUT/'original-vs-continuation-vs-repair.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    total=p['historicalAccounting'];m=ledger(round_out('main')/'tasks');b=ledger(round_out('repair')/'tasks')
    summary={'versionsAndRoundsSeparate':summaries,'uniqueMappings':960,'terminalMappingCount':len(rows),'mainAttempts':len(list(round_out('main').glob('tasks/*/*/result.json'))),'repairAttempts':len(list(round_out('repair').glob('tasks/*/*/result.json'))),'cumulativeActualCostUsd':math.fsum([total['actualCostUsd'],m['actualCostUsd'],b['actualCostUsd']]),'cumulativeUpperBoundUsd':math.fsum([total['accountedUpperBoundUsd'],m['accountedUpperBoundUsd'],b['accountedUpperBoundUsd']]),'historicalUnknownReserveRetainedUsd':total['unknownReserveUsd'],'newUnknownReserveUsd':m['unknownReserveUsd']+b['unknownReserveUsd'],'allVersionsIntegrityPassed':False,'historicalAuditsPassed':False,'oldResultsNeverOverwritten':True,'allScoresKeptSeparately':True,'numericalMetricsNotSA':True}
    common.save(OUT/'summary.json',summary)
    (OUT/'REPORT.md').write_text('# LLM-SRBench independent continuation and new infrastructure retry\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n\nReport each version/round and task cohort separately. Retries neither replace main results nor select the best scores. Preserve historical failed audits, late dispatches, cost discrepancies, unknown costs, and original interruptions permanently. Passing controlled unknown-cost reconciliation does not mean every original-version audit passed; numerical metrics are not SA. See original-vs-continuation-vs-repair.csv and analysis/mapping for per-unit provenance.\n',encoding='utf8')
    verify_freezes()
if __name__=='__main__':main()
