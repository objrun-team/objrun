"""Audit every trial; merge only first valid records into a separate result view."""
from pathlib import Path
import csv
import sys
from core import *

def generate(root,local=False):
    root=Path(root).resolve();cfg=read(root/'recovery.json');f=root/'frozen';sys.path.insert(0,str(f/'package'))
    import protocol as p
    import report as original_report
    original=read(root/'original-reference/records.json');public=read(f/'data/public-tasks.json');book={r['id']:r for r in read(f/'data/private-tasks.json')};pub={r['id']:r for r in public}
    checks=[]
    def check(name,value):checks.append({'name':name,'passed':bool(value)})
    verify_frozen(f);check('frozen-source-data-dependencies',True)
    for rel,h in read(root/'operations-pins.json').items():check('recovery-source:'+rel,sha(root/rel)==h)
    check('eight-original-infrastructure-only',len(cfg['jobs'])==8 and {(j['arm'],j['id']) for j in cfg['jobs']}=={(r['arm'],r['id']) for r in original if not valid(r)})
    for r in original:check('original-reference-record:'+r['arm']+'/'+r['id'],r==read(root/'original-reference/results'/r['arm']/(r['id']+'.json')))
    selected=read(root/'first-valid.json');composite={(r['arm'],r['id']):r for r in original};provenance=[];allhomes=[]
    for job in cfg['jobs']:
        homes=sorted((root/'attempts'/job['arm']/job['id']).glob('attempt-*'));terms=[]
        for home in homes:
            meta=read(home/'attempt.json');t=read(home/'terminal.json');terms.append(t);allhomes.append(home);out=home/'outputs/canonical';tag=meta['identity']
            check('fresh-budget:'+tag,meta['fullSolveBudgetSeconds']==600 and not meta['oldTimeOrCandidateReused'])
            expected=read(f/'package/experiment.json');expected.pop('canaryTransportRecovery',None)
            if (home/'effective-config.json').exists():check('effective-config:'+tag,read(home/'effective-config.json')==expected)
            else:check('zero-dispatch-startup-fault:'+tag,not list((out/'calls').glob('**/dispatch.json')) and not t.get('result'))
            record=read(home/t['result']) if t.get('result') else None
            check('validity:'+tag,t['valid']==valid(record))
            if record:
                check('result-hash:'+tag,sha(home/t['result'])==t['resultSha256'])
                d=out/'tasks'/job['arm']/job['id'];answer=(d/'final-answer.txt').read_text(encoding='utf-8');candidate=read(d/'frozen-candidate.json')
                check('frozen-candidate:'+tag,answer==record['answer']==candidate['answer'] and p.digest(answer)==record['candidateSha256'])
                check('original-prompt:'+tag,record['promptSha256']==p.digest(pub[job['id']]['prompt'])==job['promptSha256'])
                if record['grade'].get('valid'):
                    expected_grade=p.grade(answer,book[job['id']]);check('grade:'+tag,all(record['grade'].get(k)==v for k,v in expected_grade.items()))
                if job['arm']=='objrun' and (d/'engine/data/h2h.sqlite').exists():
                    native=original_report.submitted(d,job['id']);inp=read(d/'input.json')
                    check('native-submit-and-budget:'+tag,native is not None and native['answer']==answer and native['budgets']==[600,4] and abs(native['deadlineEpoch']-record['deadlineEpoch'])<.01)
                    check('fresh-native-clock:'+tag,not any(k in inp for k in ['priorSolveSeconds','replayFirstWire']))
                    feedback=read(d/'feedback.json') if (d/'feedback.json').exists() else []
                    check('feedback-boundary:'+tag,all(set(x['exposed'])=={'value','note'} and (x['node']!='correct' or x['exposed']['note']=='') for x in feedback))
                if job['arm']=='baseline':
                    completes=list((out/'calls/solve'/job['id']/'baseline').glob('**/complete.json'));check('one-baseline-generation:'+tag,len(completes)<=1)
                    for h in completes:
                        v=read(h);response=read(h.parent/v['responsePath']);check('baseline-content:'+tag,(response['choices'][0]['message'].get('content') or '')==answer)
            for dispatch in (out/'calls').glob('**/dispatch.json'):
                d=read(dispatch);q=read(dispatch.with_name('request.json'));name=tag+'/'+dispatch.relative_to(home).as_posix()
                check('wire:'+name,all(q.get(k)==v for k,v in p.PARAMETERS.items()) and p.digest(q)==d['requestSha256'])
                check('request-namespace:'+name,('recovery-%04d'%meta['number']) in dispatch.parts)
                check('max-three-transmissions:'+name,len(list(dispatch.parent.parent.glob('attempt-*/dispatch.json')))<=3)
                receipt=dispatch.with_name('receipt.json')
                if receipt.exists():
                    v=read(receipt);amount=(v.get('usage') or {}).get('cost')
                    check('actual-cost:'+name,v['actualCostUsd']==(float(amount) if isinstance(amount,(int,float)) and amount>=0 else None))
                    if not v['error']:check('actual-digitalocean-model:'+name,v['provider']=='DigitalOcean' and v['responseModel'] in [p.MODEL,p.CANONICAL])
                if t['valid']:check('valid-transmissions-settled:'+name,receipt.exists() and (dispatch.parent.parent/'complete.json').exists())
                check('allowed-tools:'+name,{x['function']['name'] for x in q.get('tools',[])}<=set(p.TOOLS))
                if job['arm']=='baseline':check('baseline-prompt:'+name,q['messages']==[{'role':'system','content':p.SYSTEM},{'role':'user','content':pub[job['id']]['prompt']}])
        first=first_valid(terms);choice=selected.get(key(job));check('first-valid-stop:'+key(job),first is not None and choice is not None and first==choice['terminal'] and first['number']==len(homes))
        if first:
            home=homes[first['number']-1];record=read(home/first['result']);composite[(job['arm'],job['id'])]=record
            provenance.append({'arm':job['arm'],'id':job['id'],'source':home.relative_to(root).as_posix(),'identity':first['identity'],'attemptCount':len(homes),'addedDeclaredSolveBudgetSeconds':600*len(homes),'resultSha256':first['resultSha256'],'passed':record['grade']['passed']})
    combined=list(composite.values());check('all1416-valid',len(combined)==1416 and all(valid(r) for r in combined))
    for r in original:
        if valid(r):check('original-valid-not-repeated:'+r['arm']+'/'+r['id'],composite[(r['arm'],r['id'])]==r)
    if not local:original_guard(cfg['originalRoot']);check('original-entire-inventory-unchanged',True)
    cost=ledger(allhomes);check('global-model-slots',cost['peakApiConcurrencyObserved']<=2)
    def summary(rows):
        records={(r['arm'],r['id']):r for r in rows}
        return {'arms':{a:original_report.stats([r for r in rows if r['arm']==a],708) for a in ['baseline','objrun']},
            'categories':{c:{a:original_report.stats([r for r in rows if r['arm']==a and r['category']==c],sum(t['category']==c for t in public)) for a in ['baseline','objrun']} for c in ['ProtocolQA','SeqQA']},
            'subtasks':{s:{a:original_report.stats([r for r in rows if r['arm']==a and r['subtask']==s],sum(t['subtask']==s for t in public)) for a in ['baseline','objrun']} for s in sorted({t['subtask'] for t in public})},
            'paired':original_report.paired(public,records),'knownDuplicateChoiceSensitivity':{a:original_report.stats([r for r in rows if r['arm']==a and r['id']!=p.DEFECT],707) for a in ['baseline','objrun']}}
    original_cost=read(root/'original-reference/SUMMARY.json')['accounting'];totals={a:{k:original_cost['byArm'][a][k]+cost['byArm'].get(a,{}).get(k,0) for k in ['knownActualCostUsd','unknownCostRequests','requests']} for a in ['baseline','objrun']}
    result={'original':summary(original),'completed':summary(combined),'recoverySources':provenance,'attemptCount':len(allhomes),'additionalDeclaredSolveBudgetSeconds':600*len(allhomes),
        'fees':{'original':original_cost,'allRecoveryAttempts':cost,'combinedByArm':totals},'selection':'first valid result regardless of correctness; never best-of; only eight original infrastructure identities',
        'interpretation':'infrastructure-conditioned supplemental view with new 600s trials; original frozen results remain primary and separately reported; ObjRun has oracle feedback'}
    audit={'allPassed':all(x['passed'] for x in checks),'checkCount':len(checks),'checks':checks,'failures':[x for x in checks if not x['passed']]}
    if local:return audit,result
    save(root/'AUDIT.json',audit);save(root/'SUMMARY.json',result);save(root/'COMPLETED_RECORDS.json',combined);save(root/'REPLACEMENT_PROVENANCE.json',provenance)
    for name,rows in [('ORIGINAL_RESULTS.csv',original),('COMPLETED_RESULTS.csv',combined)]:
        with (root/name).open('w',encoding='utf-8-sig',newline='') as fcsv:
            fields=['arm','id','category','subtask','solverValid','gradeValid','passed','answer','error','recoverySource','recoveryAttemptCount'];writer=csv.DictWriter(fcsv,fieldnames=fields);writer.writeheader()
            for r in rows:
                src=next((s for s in provenance if s['arm']==r['arm'] and s['id']==r['id']),None) if name.startswith('COMPLETED') else None
                writer.writerow({k:r.get(k) for k in fields if k not in ['gradeValid','passed','recoverySource','recoveryAttemptCount']}|{'gradeValid':r['grade'].get('valid'),'passed':r['grade'].get('passed'),'recoverySource':src['source'] if src else 'original','recoveryAttemptCount':src['attemptCount'] if src else 0})
    assert audit['allPassed'],audit['failures'][:5]

if __name__=='__main__':generate(sys.argv[1])
