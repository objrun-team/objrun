"""Offline audit, paired statistics, costs and human-readable delivery report."""
from pathlib import Path
import csv
import json
import random
import sqlite3
from runtime import ROOT,OUT,CFG,read,save,accounting
from protocol import digest,PARAMETERS,TOOLS

def main():
    public=read(ROOT/'data/public-tasks.json');book={r['id']:r for r in public};ids=list(book)
    rows=[read(p) for p in (OUT/'results').glob('*/*.json')];records={(r['arm'],r['id']):r for r in rows};checks=[]
    def check(name,ok,**detail):checks.append({'name':name,'passed':bool(ok),**detail})
    check('236x2-identities',len(rows)==472 and set(records)=={(a,i) for a in CFG['arms'] for i in ids})
    check('zero-model-controls',read(OUT/'controls.json')['allPassed'] and read(OUT/'controls.json')['modelCalls']==0)
    check('eight-question-canary',read(OUT/'canary.json')['allPassed'])
    for rel,sha in read(ROOT/'provenance/source-pins.json')['files'].items():check('source:'+rel,digest((ROOT/rel).read_bytes())==sha)
    for rel,sha in read(ROOT/'provenance/dependencies.json')['files'].items():check('dependency:'+rel,digest((ROOT/rel).read_bytes())==sha)
    exports=[];repairs=[]
    for r in rows:
        arm,tid=r['arm'],r['id'];d=OUT/'tasks'/arm/tid;f=read(d/'frozen-candidate.json')
        check('frozen:'+arm+'/'+tid,r['candidateSha256']==digest(r['answer'])==f['candidateSha256'] and f['answer']==r['answer'] and (d/'final-answer.txt').read_text(encoding='utf-8')==r['answer'])
        check('public-prompt:'+arm+'/'+tid,r['promptSha256']==digest(book[tid]['prompt']))
        if r['grade'].get('valid'):check('grade-binding:'+arm+'/'+tid,r['grade']['candidateSha256']==r['candidateSha256'] and r['grade']['taskId']==tid)
        if arm=='baseline' and r['solverValid']:
            call=OUT/'calls/solve'/tid/'baseline/sample-0'
            if (call/'complete.json').exists():
                c=read(call/'complete.json');response=read(call/c['responsePath'])
                check('single-delivered-content:'+tid,r['answer']==(response['choices'][0]['message'].get('content') or ''))
            check('one-logical-generation:'+tid,len(list((OUT/'calls/solve'/tid/'baseline').glob('*/complete.json')))==1)
        if arm=='objrun' and (d/'engine/data/h2h.sqlite').exists():
            db=sqlite3.connect('file:'+str(d/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
            try:
                check('tools:'+tid,{x[0] for x in db.execute('select name from tool where usable=1')}==set(TOOLS))
                check('task-budget:'+tid,db.execute('select solve_seconds,max_branches from task').fetchone()==(600,4))
                cycles=db.execute("select cycle,max_units from cycle where mode='repair' and cycle in ('ask','act')").fetchall()
                check('cycle12:'+tid,len(cycles)==2 and all(x[1]==12 for x in cycles))
                delivered=[];counts={};deadline=r.get('nativeDeadlineEpoch',r['deadlineEpoch'])*1000
                for node,at,body in db.execute("select t.node,m.at,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='call' order by m.at,m.seq"):
                    for c in json.loads(body).get('calls',[]):
                        if c['name']=='submit' and at<=deadline:delivered.append(c['input'].get('answer',''))
                check('actual-submission:'+tid,(delivered[-1] if delivered else '')==r['answer'])
                for node,body in db.execute("select t.node,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='tool'"):
                    v=json.loads(body);g=v.get('value',{})
                    if v.get('name')=='verify' and not str(v.get('id','')).startswith('g-') and g.get('valid') is not False and g.get('pass') in [0,1]:counts[node]=counts.get(node,0)+1
                check('per-attempt-c5:'+tid,all(v<=5 for v in counts.values()),counts=counts)
                r['effectiveVerifyCount']=sum(counts.values());r['attemptCount']=db.execute('select count(distinct node) from task_repair').fetchone()[0]
            finally:db.close()
            feedback=read(d/'feedback.json') if (d/'feedback.json').exists() else []
            check('safe-feedback:'+tid,all(set(x['exposed'])=={'value','note'} and x['exposed']['note'] in ['','Provide an answer to the question.'] for x in feedback))
            correctness=[x for x in feedback if x['node']=='correct'];r['correctnessNodeCalls']=len(correctness)
            if correctness and correctness[0]['exposed']['value'] is False and r['solverValid'] and r['grade'].get('valid') and r['grade'].get('passed'):
                repairs.append({'id':tid,'firstCandidateSha256':correctness[0]['candidateSha256'],'finalCandidateSha256':r['candidateSha256'],'classification':'requires_independent_case_review'})
        exports.append({k:r.get(k) for k in ['arm','id','originalId','subfield','answerType','multiple','solverValid','candidateSha256','candidateHow','finishReason','nativeModelRequests','effectiveVerifyCount','correctnessNodeCalls','attemptCount','solverWallSeconds','totalWallSeconds','error']} | {'gradeValid':r['grade'].get('valid'),'passed':r['grade'].get('passed')})
    for p in (OUT/'calls').glob('**/request.json'):
        q=read(p);rel=p.relative_to(OUT/'calls');dispatch=read(p.with_name('dispatch.json'))
        check('wire:'+str(rel),all(q.get(k)==v for k,v in PARAMETERS.items()) and 'provider' not in q and 'temperature' not in q)
        check('request-identity:'+str(rel),digest(q)==dispatch['requestSha256'])
        check('official-endpoint:'+str(rel),dispatch['endpoint']=='https://api.deepseek.com/chat/completions')
        check('receipt:'+str(rel),p.with_name('receipt.json').exists())
        if q.get('tools'):
            check('wire-tools:'+str(rel),{t['function']['name'] for t in q['tools']}<=set(TOOLS))
            check('thinking-history:'+str(rel),all(isinstance(m.get('reasoning_content'),str) for m in q['messages'] if m['role']=='assistant'))
        tid,arm=rel.parts[1:3]
        if (arm,tid) in records:
            r=records[(arm,tid)];check('deadline:'+str(rel),dispatch['deadlineEpoch']<=r['deadlineEpoch']+.01 and dispatch['startedEpoch']<=dispatch['deadlineEpoch'])
    for home in {p.parent.parent for p in (OUT/'calls').glob('**/dispatch.json')}:check('retry3:'+str(home.relative_to(OUT)),len(list(home.glob('attempt-*/dispatch.json')))<=3)
    costs=accounting();check('model-concurrency16',costs['peakApiConcurrencyObserved']<=16)
    def valid(r):return r['solverValid'] and r['grade'].get('valid')
    def stats(items,total=None):
        total=len(items) if total is None else total;s=sum(bool(r['grade'].get('passed')) for r in items if valid(r));v=sum(bool(valid(r)) for r in items);u=total-v
        return {'tasks':total,'completed':len(items),'valid':v,'passed':s,'unknown':u,'knownCorrectFraction':s/total if total else None,'accuracyBounds':[s/total,(s+u)/total] if total else None,
            'noSubmission':sum(r.get('candidateHow')!='submitted' for r in items if r['arm']=='objrun'),'length':sum(r.get('finishReason')=='length' for r in items)}
    fields=list(dict.fromkeys(r['subfield'] for r in public));paired={field:[] for field in fields};wins=[];losses=[];ties=0
    for tid in ids:
        a,b=records.get(('baseline',tid)),records.get(('objrun',tid))
        if not a or not b or not valid(a) or not valid(b):continue
        difference=int(b['grade']['passed'])-int(a['grade']['passed']);paired[book[tid]['subfield']].append(difference)
        if difference>0:wins.append(tid)
        elif difference<0:losses.append(tid)
        else:ties+=1
    n=sum(map(len,paired.values()));rng=random.Random(20261017)
    samples=sorted(sum(sum(rng.choices(values,k=len(values))) for values in paired.values() if values)/n for _ in range(20000)) if n else []
    summary={'benchmark':CFG['benchmark'],'run':CFG['run'],'dataRevision':CFG['dataRevision'],'modelParameters':PARAMETERS,'modelMapping':CFG['expectedModelMapping'],'rollingAlias':True,
        'arms':{a:stats([r for r in rows if r['arm']==a],236) for a in CFG['arms']},
        'subfields':{s:{a:stats([r for r in rows if r['arm']==a and r['subfield']==s],sum(x['subfield']==s for x in public)) for a in CFG['arms']} for s in fields},
        'answerMultiplicity':{str(m):{a:stats([r for r in rows if r['arm']==a and r['multiple']==m]) for a in CFG['arms']} for m in [False,True]},
        'paired':{'validPairs':n,'difference':sum(map(sum,paired.values()))/n if n else None,'ci95':[samples[499],samples[19499]] if samples else None,'wins':wins,'losses':losses,'ties':ties,'replicates':20000,'seed':20261017,'stratify':'subfield','uncertainty':'question resampling conditional on this API run; not repeated-run stability'},
        'realRepairCandidates':repairs,'accounting':costs,'canaryIncludedInFormal':True,'canaryIds':read(ROOT/'data/source.json')['canaryIds'],
        'interpretation':'whole-system comparison with online oracle access and more attempts; budgets and feedback are not matched to single attempt'}
    save(OUT/'SUMMARY.json',summary);save(OUT/'AUDIT.json',{'allPassed':all(x['passed'] for x in checks),'checks':checks,'failures':[x for x in checks if not x['passed']]})
    with (OUT/'FINAL_RESULTS.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(exports[0]));writer.writeheader();writer.writerows(exports)
    lines=['# OlympiadBench 两组正式实验','',f"固定英文纯文本物理236题；DeepSeek官方deepseek-flash（观察映射{CFG['expectedModelMapping']}，滚动别名）。",'',
        '|组别|有效/总数|通过|全体成功率范围|','|---|---:|---:|---|']
    for a,s in summary['arms'].items():lines.append(f"|{a}|{s['valid']}/236|{s['passed']}|{s['accuracyBounds']}|")
    lines+=['',f"配对有效题 {n}；ObjRun减单次差值 {summary['paired']['difference']}；95%区间 {summary['paired']['ci95']}。",f"仅ObjRun通过{len(wins)}题；仅单次通过{len(losses)}题；真实修复候选{len(repairs)}题（内容需独立审查）。",'',
        '费用为官方token费率估算，逐请求实际账单不可获得；缺失usage及未结算请求单列，不计零。','', '|组别|估算费用USD范围|请求数|未知费用请求|','|---|---:|---:|---:|']
    for a,c in costs['byArm'].items():lines.append(f"|{a}|{c['estimateLowerUsd']:.9f}—{c['estimateUpperUsd']:.9f}|{c['requests']}|{c['unknownCostRequests']}|")
    lines+=['','8题两组canary沿同一冻结协议纳入正式236题，无重复生成。','本比较包含更多尝试和在线评分访问，不单独证明机制贡献或同费用效率。',f"审计通过：{all(x['passed'] for x in checks)}。完整逐题结果、日志、调用回执、源码和依赖随归档交付。"]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'auditPassed':all(x['passed'] for x in checks),'arms':summary['arms'],'failures':[x for x in checks if not x['passed']][:5]}))

if __name__=='__main__':main()
