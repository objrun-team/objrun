"""Evaluate only after the supplemental freeze; original scores are comparison data only."""
import csv,statistics
from shared import *
from grader import fit,worker
def verify_freeze():
    f=load(OUT/'candidate-fee-freeze.json');assert f['idOodAccessed'] is False
    for e in f['files']:assert sha(ROOT/e['path'])==e['sha256'],('SupplementalFreezeChanged',e['path'])
    assert ledger(OUT/'tasks')==f['accounting'],'FinancialJournalChangedAfterFreeze'
    return f
def score(row):
    result={'solverValid':row['valid'],'answerSha256':row.get('finalCandidateSha256'),'training':row.get('trainingGrade')}
    if not row['valid']:return {**result,'error':row.get('error'),'id':None,'ood':None}
    answer=row['answer'];assert common.digest(answer)==row['finalCandidateSha256'];g=fit(row['key'],answer);result['training']=g
    import numpy as np
    for split in ['id','ood']:
        p=MAIN/'data/private'/(row['key']+'-'+split+'.npz')
        if not p.exists():result[split]=None;continue
        if g.get('expression') and 'parameters' in g:
            with np.load(p,allow_pickle=False) as a:q={'expression':g['expression'],'parameters':g['parameters'],'mode':'predict','X':a['X'].tolist(),'y':a['y'].tolist(),'cpuSeconds':60}
            result[split]=worker(q)
        else:result[split]={'valid':True,'passed':False,'acc01':False,'nmse':None,'errorType':g.get('errorType','InvalidFinalFormula')}
    return result
def main():
    verify_freeze();plan=load(CONTROL/'plan.json');rows=core.all_results();evaluated={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for r,v in zip(rows,pool.map(score,rows)):
            common.save(OUT/'tasks'/r['arm']/r['key']/'supplemental-evaluation.json',v);evaluated[r['arm'],r['key']]=v
    comparisons=[]
    for c in plan['cases']:
        pair=c['arm'],c['key'];v=evaluated.get(pair);d=OUT/'tasks'/c['arm']/c['key'];new=load(d/'result.json') if (d/'result.json').exists() else None;fees=ledger(d) if d.exists() else {'actualCostUsd':0,'accountedUpperBoundUsd':0,'unknownReserveUsd':0}
        # This is the FIRST point where original ID/OOD scores may be read.
        original_file=MAIN/'analysis/outputs/tasks'/c['arm']/c['key']/'final-evaluation.json';original=load(original_file) if original_file.exists() else {}
        comparisons.append({'id':c['id'],'arm':c['arm'],'originalVersion':c['originalProtocolVersion'],'originalValid':c['originalValid'],'originalError':c['originalError'],'eligibility':c['route'],'selected':c.get('selected',False),'budgetSkipped':c.get('budgetInsufficient',False),'attemptId':c.get('attemptId'),'attempted':new is not None,'repairValid':new.get('valid') if new else None,'repairError':new.get('error') if new else None,'originalIdPassed':(original.get('id') or {}).get('passed'),'originalOodPassed':(original.get('ood') or {}).get('passed'),'repairIdPassed':((v or {}).get('id') or {}).get('passed'),'repairOodPassed':((v or {}).get('ood') or {}).get('passed'),'repairIdNmse':((v or {}).get('id') or {}).get('nmse'),'repairOodNmse':((v or {}).get('ood') or {}).get('nmse'),'originalJournalActualUsd':c['originalAccounting']['actualCostUsd'],'originalUpperBoundUsd':c['originalAccounting']['accountedUpperBoundUsd'],'repairActualUsd':fees['actualCostUsd'],'repairUpperBoundUsd':fees['accountedUpperBoundUsd'],'repairUnknownReserveUsd':fees['unknownReserveUsd']})
    with (OUT/'original-vs-supplemental.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(comparisons[0]) if comparisons else ['id','arm']);w.writeheader();w.writerows(comparisons)
    money=ledger(OUT/'tasks');summary={'roundId':plan['roundId'],'originalMainUntouched':True,'originalAuditsRemainFailed':True,'selected':len(plan['selected']),'attempted':len(rows),'valid':sum(r['valid'] for r in rows),'budgetSkipped':sum(c.get('budgetInsufficient',False) for c in plan['cases']),'reconcileOnly':sum(c['route']=='reconcile_only' for c in plan['cases']),'supplementalAccounting':money,'originalAccounting':plan['originalAccounting'],'cumulativeActualCostUsd':plan['originalAccounting']['actualCostUsd']+money['actualCostUsd'],'cumulativeUpperBoundUsd':plan['originalAccounting']['accountedUpperBoundUsd']+money['accountedUpperBoundUsd'],'idSuccess':sum(bool((v.get('id') or {}).get('passed')) for v in evaluated.values()),'oodSuccess':sum(bool((v.get('ood') or {}).get('passed')) for v in evaluated.values()),'symbolicAccuracy':'not evaluated; numerical fidelity is not SA','resultsNeverReplaceMain':True}
    common.save(OUT/'summary.json',summary)
    (OUT/'REPORT.md').write_text('# Independent infrastructure-failure retry\n\nOriginal main results, versions, and all anomalies remain unchanged. This report covers one retry attempt only and never overwrites or replaces main results.\n\n'+json.dumps({k:v for k,v in summary.items() if k not in ['supplementalAccounting']},ensure_ascii=False,indent=2)+'\n\nSee original-vs-supplemental.csv for per-unit original/retry comparisons. Noncompletion, insufficient budget, and unsettled accounting remain visible. Retry does not change original audit failures; numerical metrics are not SA.\n',encoding='utf8')
    verify_freeze()
if __name__=='__main__':main()
