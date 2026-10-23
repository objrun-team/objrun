"""Deterministic full-result audit and paired analysis; no provider operations."""
import csv
import json
import random
import sqlite3
from protocol import PARAMETERS,TOOLS,DEFECT,MODEL,CANONICAL,PROTOCOL_SHA,digest,parse,grade
from runtime import ROOT,OUT,CFG,read,save,accounting


def submitted(directory,tid):
    path=directory/'engine/data/h2h.sqlite'
    if not path.exists():return None
    db=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
    try:
        row=db.execute('select created_at,solve_seconds,max_branches from task where id=?',('labbench/'+tid,)).fetchone()
        if row is None:return None
        deadline=row[0]+row[1]*1000
        for instance,unit in db.execute('select instance,unit from task_repair where task=? order by unit desc',('labbench/'+tid,)):
            for body, in db.execute("select body from agent_bot_msg where instance=? and unit=? and kind='call' and at<=? order by seq desc",(instance,unit,deadline)):
                for call in reversed(json.loads(body).get('calls',[])):
                    if call.get('name')=='submit':
                        value=(call.get('input') or {}).get('answer')
                        return {'answer':value if isinstance(value,str) else '', 'deadlineEpoch':deadline/1000,'budgets':list(row[1:])}
        return {'answer':'','deadlineEpoch':deadline/1000,'budgets':list(row[1:]),'noSubmission':True}
    finally:db.close()


def audit():
    public=read(ROOT/'data/public-tasks.json');book={r['id']:r for r in read(ROOT/'data/private-tasks.json')};byid={r['id']:r for r in public}
    rows=[read(p) for p in (OUT/'results').glob('*/*.json')];checks=[]
    def check(name,passed):checks.append({'name':name,'passed':bool(passed)})
    check('all1416-identities',len(rows)==1416 and {(r['arm'],r['id']) for r in rows}=={(a,i) for a in CFG['arms'] for i in byid})
    check('zero-model-controls',read(OUT/'controls.json')['allPassed'] and read(OUT/'controls.json')['modelCalls']==0)
    check('canary20x2',read(OUT/'canary.json')['allPassed'] and len(read(OUT/'canary.json')['records'])==40)
    for manifest in ['source-pins.json','dependencies.json']:
        for rel,sha in read(ROOT/'provenance'/manifest)['files'].items():check(manifest+':'+rel,(ROOT/rel).is_file() and digest((ROOT/rel).read_bytes())==sha)
    for r in rows:
        identity=r['arm']+'/'+r['id'];d=OUT/'tasks'/r['arm']/r['id'];candidate=read(d/'frozen-candidate.json')
        check('candidate:'+identity,r['answer']==candidate['answer']==(d/'final-answer.txt').read_text(encoding='utf-8') and digest(r['answer'])==r['candidateSha256']==candidate['candidateSha256'])
        check('prompt:'+identity,r['promptSha256']==digest(byid[r['id']]['prompt'])==book[r['id']]['promptSha256'])
        if r['grade'].get('valid'):
            expected=grade(r['answer'],book[r['id']]);check('grade:'+identity,all(r['grade'].get(k)==expected[k] for k in ['passed','parsed','label','sure','abstain','formatInvalid','candidateSha256','taskId','protocolSha256']))
        if r['arm']=='baseline':
            homes=list((OUT/'calls/solve'/r['id']/'baseline').glob('*/complete.json'))
            check('one-baseline-generation:'+r['id'],len(homes)<=1)
            for h in homes:
                c=read(h);q=read(h.parent/read(h)['responsePath']).get('choices',[{}])[0].get('message',{})
                check('baseline-content:'+r['id'],(q.get('content') or '')==r['answer'])
                request=read(h.parent/'attempt-0/request.json')
                check('baseline-public-input:'+r['id'],request['messages']==[{'role':'system','content':__import__('protocol').SYSTEM},{'role':'user','content':byid[r['id']]['prompt']}])
        elif (d/'engine/data/h2h.sqlite').exists():
            native=submitted(d,r['id'])
            check('actual-final-submit:'+r['id'],native is not None and native['answer']==r['answer'] and native['budgets']==[600,4] and abs(native['deadlineEpoch']-r['deadlineEpoch'])<.01)
            if r['candidateHow']=='submitted':check('submitted-exists:'+r['id'],not native.get('noSubmission'))
            feedback=read(d/'feedback.json') if (d/'feedback.json').exists() else []
            check('feedback-boundary:'+r['id'],all(set(x['exposed'])=={'value','note'} and (x['node']!='correct' or x['exposed']['note']=='') for x in feedback))
    for p in (OUT/'calls').glob('**/dispatch.json'):
        d=read(p);q=read(p.with_name('request.json'));relative=p.relative_to(OUT/'calls')
        check('wire:'+str(relative),all(q.get(k)==v for k,v in PARAMETERS.items()) and d['endpoint']=='https://openrouter.ai/api/v1/chat/completions' and digest(q)==d['requestSha256'])
        check('tool-policy:'+str(relative),{t['function']['name'] for t in q.get('tools',[])}<=set(TOOLS))
        check('receipt:'+str(relative),p.with_name('receipt.json').exists())
        if p.with_name('receipt.json').exists():
            receipt=read(p.with_name('receipt.json'))
            usage=receipt.get('usage') or {}
            if isinstance(usage.get('cost'),(int,float)):
                check('actual-cost:'+str(relative),receipt['actualCostUsd']==usage['cost'])
            if not receipt['error']:check('actual-route:'+str(relative),receipt['provider']=='DigitalOcean' and receipt['responseModel'] in [MODEL,CANONICAL])
        home=p.parent.parent;check('retry-budget:'+str(relative),len(list(home.glob('attempt-*/dispatch.json')))<=3)
    costs=accounting();check('global-model-slots',costs['peakApiConcurrencyObserved']<=CFG['modelConcurrency'])
    return {'allPassed':all(x['passed'] for x in checks),'checks':checks,'failures':[x for x in checks if not x['passed']]}


def valid(r):return bool(r and r['solverValid'] and r['grade'].get('valid'))


def stats(items,total):
    usable=[r for r in items if valid(r)];correct=sum(r['grade']['passed'] for r in usable);answered=sum(r['grade']['sure'] for r in usable);u=total-len(usable)
    return {'tasks':total,'completed':len(items),'valid':len(usable),'passed':correct,'unknown':u,'accuracyBounds':[correct/total,(correct+u)/total] if total else None,
            'accuracy':correct/total if u==0 and total else None,'precision':correct/answered if answered else 0.,'coverage':answered/total if total else 0.,
            'abstain':sum(r['grade']['abstain'] for r in usable),'formatInvalid':sum(r['grade']['formatInvalid'] for r in usable),
            'noSubmission':sum(r['arm']=='objrun' and r.get('candidateHow')!='submitted' for r in usable),
            'length':sum(r.get('finishReason')=='length' for r in usable)}


def paired(public,records):
    strata={};wins=[];losses=[];ties=0
    for task in public:
        a,b=records.get(('baseline',task['id'])),records.get(('objrun',task['id']))
        if not valid(a) or not valid(b):continue
        delta=int(b['grade']['passed'])-int(a['grade']['passed']);strata.setdefault(task['subtask'],[]).append(delta)
        if delta>0:wins.append(task['id'])
        elif delta<0:losses.append(task['id'])
        else:ties+=1
    n=sum(map(len,strata.values()));rng=random.Random(CFG['statistics']['seed']);samples=[]
    if n:samples=sorted(sum(sum(rng.choices(v,k=len(v))) for v in strata.values())/n for _ in range(CFG['statistics']['replicates']))
    armstats={a:stats([r for (arm,tid),r in records.items() if arm==a and tid in {p['id'] for p in public}],len(public)) for a in CFG['arms']}
    sa,sb=armstats['baseline'],armstats['objrun'];total=len(public)
    return {'validPairs':n,'differenceOnValidPairs':sum(map(sum,strata.values()))/n if n else None,'ci95ConditionalOnValidPairs':[samples[499],samples[19499]] if samples else None,
            'wholeDenominatorDifferenceBounds':[(sb['passed']-sa['passed']-sa['unknown'])/total,(sb['passed']+sb['unknown']-sa['passed'])/total],
            'wins':wins,'losses':losses,'ties':ties,'seed':CFG['statistics']['seed'],'replicates':CFG['statistics']['replicates'],'stratify':'subtask','uncertainty':'item resampling conditional on this API run'}


def main():
    checked=audit();save(OUT/'AUDIT.json',checked)
    public=read(ROOT/'data/public-tasks.json');private={r['id']:r for r in read(ROOT/'data/private-tasks.json')}
    rows=[read(p) for p in (OUT/'results').glob('*/*.json')];records={(r['arm'],r['id']):r for r in rows}
    costs=accounting();analyses=[];exports=[]
    for r in rows:
        detail={'arm':r['arm'],'id':r['id'],'firstCandidate':None,'firstCandidateGrade':None,'correctnessFeedbackCount':0,'distinctEvaluatedLabels':[]}
        if r['arm']=='objrun':
            d=OUT/'tasks/objrun'/r['id'];feedback=read(d/'feedback.json') if (d/'feedback.json').exists() else []
            correct=[x for x in feedback if x['node']=='correct'];detail['correctnessFeedbackCount']=len(correct)
            detail['distinctEvaluatedLabels']=sorted({parse(x['candidate'],r['choiceCount']) for x in correct if parse(x['candidate'],r['choiceCount']) is not None})
            first=None
            for response in read(d/'bridge-responses.json') if (d/'bridge-responses.json').exists() else []:
                for c in response['choices'][0]['message'].get('tool_calls') or []:
                    if c['function']['name'] in {'verify','submit'}:
                        try:
                            args=json.loads(c['function']['arguments'])
                            if 'answer' in args:first=args['answer'] if isinstance(args['answer'],str) else '';break
                        except (ValueError,TypeError):pass
                if first is not None:break
            detail['firstCandidate']=first
            detail['firstCandidateGrade']=grade(first or '',private[r['id']])
            detail['realRepairCandidate']=bool(correct and not correct[0]['exposed']['value'] and valid(r) and r['grade']['passed'] and r.get('candidateHow')=='submitted')
            detail['classification']='known_label_ambiguity' if r['id']==DEFECT else 'requires_independent_content_review'
        analyses.append(detail)
        exports.append({k:r.get(k) for k in ['arm','id','category','subtask','choiceCount','solverValid','candidateHow','candidateSha256','finishReason','nativeModelRequests','solverWallSeconds','error']}|
                       {'gradeValid':r['grade'].get('valid'),'passed':r['grade'].get('passed'),'label':r['grade'].get('label'),'abstain':r['grade'].get('abstain'),'formatInvalid':r['grade'].get('formatInvalid'),
                        'firstCandidatePassed':(detail['firstCandidateGrade'] or {}).get('passed'),'distinctEvaluatedLabels':len(detail['distinctEvaluatedLabels']),'correctnessFeedbackCount':detail['correctnessFeedbackCount']})
    categories=sorted({r['category'] for r in public});subtasks=sorted({r['subtask'] for r in public})
    summary={'benchmark':CFG['benchmark'],'run':CFG['run'],'parameters':PARAMETERS,'oracleFeedback':True,
             'arms':{a:stats([r for r in rows if r['arm']==a],708) for a in CFG['arms']},
             'categories':{c:{a:stats([r for r in rows if r['arm']==a and r['category']==c],sum(p['category']==c for p in public)) for a in CFG['arms']} for c in categories},
             'subtasks':{c:{a:stats([r for r in rows if r['arm']==a and r['subtask']==c],sum(p['subtask']==c for p in public)) for a in CFG['arms']} for c in subtasks},
             'paired':paired(public,records),'pairedByCategory':{c:paired([p for p in public if p['category']==c],records) for c in categories},
             'knownDuplicateChoiceSensitivity':{'excludedId':DEFECT,'arms':{a:stats([r for r in rows if r['arm']==a and r['id']!=DEFECT],707) for a in CFG['arms']}},
             'firstCandidate':{'objrunPassed':sum(bool(x['firstCandidateGrade']['passed']) for x in analyses if x['arm']=='objrun'),'denominator':708},
             'accounting':costs,'canaryIncludedInFormal':True,'interpretation':'whole-system oracle-assisted MCQ performance and cost; label exclusion is not proof of biological reasoning repair'}
    save(OUT/'SUMMARY.json',summary);save(OUT/'TRAJECTORY_ANALYSIS.json',analyses)
    with (OUT/'FINAL_RESULTS.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(exports[0]));writer.writeheader();writer.writerows(exports)
    lines=['# LAB-Bench 两组结果','','ProtocolQA 108；SeqQA 600。OpenRouter 固定 DigitalOcean；完整组具有在线金标正误反馈。','',
           '|组别|有效/总数|通过|准确率范围|','|---|---:|---:|---|']
    for arm,s in summary['arms'].items():lines.append(f"|{arm}|{s['valid']}/708|{s['passed']}|{s['accuracyBounds']}|")
    lines+=['','费用来自 OpenRouter usage.cost；缺失费用保留未知，不记零。','', '|组别|已知实际美元|未知费用请求|请求数|','|---|---:|---:|---:|']
    for arm,c in costs['byArm'].items():lines.append(f"|{arm}|{c['knownActualCostUsd']:.9f}|{c['unknownCostRequests']}|{c['requests']}|")
    lines+=['',f"远端审计通过：{checked['allPassed']}。20题两组试跑已计入全量，没有重新生成。",'完整原始请求、响应、候选、评分、轨迹与数据库随归档交付；高最终分数可能包含选项排除收益。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'auditPassed':checked['allPassed'],'arms':summary['arms'],'failures':checked['failures'][:5]}))


if __name__=='__main__':main()
