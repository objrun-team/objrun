"""Offline paired summary; never invokes a model or changes frozen candidates."""
from pathlib import Path
import csv
import json
import math
import random
import re
import sqlite3
import sys
from runtime import accounting, save, digest, read, CFG

root=Path(sys.argv[1]);out=root/'outputs/canonical'
original=[read(p) for p in (out/'results').glob('*/*.json')]
final=[read(p) for p in (out/'final-results').glob('*/*.json')]
lookup={(r['arm'],r['id']):r for r in final};orig={(r['arm'],r['id']):r for r in original}
audit=[]
def check(name,ok,**detail):audit.append({'name':name,'passed':bool(ok),**detail})
ids=[r['id'] for r in read(root/'data/public-tasks.json')]
check('100x2-original-map',set(orig)=={(a,i) for a in CFG['arms'] for i in ids} and len(original)==200)
check('100x2-final-map',set(lookup)==set(orig) and len(final)==200)
for rel,sha in read(out/'source-pins.json')['files'].items():check('pin:'+rel,digest((root/rel).read_bytes())==sha)
def valid(r):return r.get('solverValid') and r.get('grade',{}).get('valid')
def stats(rows):
    usable=[r for r in rows if valid(r)];k=sum(r['grade']['passed'] for r in usable);n=len(usable)
    return {'tasks':len(rows),'valid':n,'correct':k,'accuracy':k/n if n else None,'knownCorrectFraction':k/len(rows) if rows else None,
            'unresolved':len(rows)-n,'allTaskAccuracyBounds':[k/len(rows),(k+len(rows)-n)/len(rows)] if rows else None}
summary={'protocol':'DeepSeek model grading protocol; same-model blind regrade measures consistency, not external independent validation',
         'model':CFG['parameters'],'rollingAlias':CFG['modelMapping'],'arms':{a:stats([r for r in final if r['arm']==a]) for a in CFG['arms']},
         'subjects':{s:{a:stats([r for r in final if r['arm']==a and r['subject']==s]) for a in CFG['arms']} for s in ['physics','chemistry','biology']}}
paired=[];wins=[];losses=[];ties=0
for tid in ids:
    a,b=lookup.get(('baseline',tid)),lookup.get(('objrun',tid))
    if not a or not b or not valid(a) or not valid(b):continue
    x=int(b['grade']['passed'])-int(a['grade']['passed']);paired.append(x)
    if x>0:wins.append(tid)
    elif x<0:losses.append(tid)
    else:ties+=1
rng=random.Random(CFG['statistics']['seed']);n=len(paired)
boot=sorted(sum(rng.choices(paired,k=n))/n for _ in range(20000)) if n else []
summary['paired']={'validPairs':n,'difference':sum(paired)/n if n else None,'ci95':[boot[499],boot[19499]] if n else None,'bootstrapReplicates':20000,'seed':20261016,'wins':wins,'losses':losses,'ties':ties,'uncertainty':'resampling questions from this fixed one-run protocol; does not estimate repeated-run or grader-model uncertainty'}
summary['disagreements']={a:[r['id'] for r in final if r['arm']==a and r['onlineFinalDisagree']] for a in CFG['arms']}
repairs=[]
def final_text(s):
    tail=re.split(r'FINAL\s+ANSWER\s*[:：]?',s,flags=re.I)[-1]
    return re.sub(r'[\s`${}\\]','',tail).lower()
for row in original:
    arm,tid=row['arm'],row['id'];directory=out/'tasks'/arm/tid
    check('candidate:'+arm+'/'+tid,digest(row['answer'])==row['candidateSha256']==read(directory/'frozen-candidate.json')['candidateSha256'])
    check('frozen-final:'+arm+'/'+tid,lookup.get((arm,tid),{}).get('candidateSha256')==row['candidateSha256'])
    if arm=='objrun':
        feedback=read(directory/'feedback.json') if (directory/'feedback.json').exists() else []
        eq=[x for x in feedback if x['node']=='equivalent']
        check('feedback-fields:'+tid,all(set(x['exposed'])=={'value','note'} and x['exposed']['note'] in ['', 'Provide an answer to the question.'] for x in feedback))
        last=lookup.get((arm,tid))
        if eq and eq[0]['exposed']['value'] is False and last and valid(last) and last['grade']['passed']:
            repairs.append({'id':tid,'firstCandidateSha256':eq[0]['candidateSha256'],'finalCandidateSha256':row['candidateSha256'],
                            'classification':'format_only_candidate' if final_text(eq[0]['candidate'])==final_text(row['answer']) else 'content_change_requires_case_review'})
        dbp=directory/'engine/data/h2h.sqlite'
        if dbp.exists():
            db=sqlite3.connect('file:'+str(dbp)+'?mode=ro',uri=True)
            try:
                tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
                tools=[r[0] for r in db.execute('select name from tool where usable=1')]
                check('tool-allowlist:'+tid,set(tools)==set(CFG['toolPolicy']))
                row['attemptCount']=db.execute('select count(distinct node) from task_repair').fetchone()[0]
                row['checkCandidates']=len(eq)
                task=db.execute('select solve_seconds,max_branches,max_dead_siblings from task').fetchone()
                check('engine-budgets:'+tid,task[0]==600 and task[1]==4)
                checks={}
                for node,body in db.execute("select t.node,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='tool'"):
                    try:
                        v=json.loads(body);decision=v.get('value',{})
                        if v.get('name')=='verify' and not str(v.get('id','')).startswith('g-') and decision.get('valid') is not False and decision.get('pass') in [0,1]:checks[node]=checks.get(node,0)+1
                    except (ValueError,AttributeError):pass
                check('c5-per-attempt:'+tid,all(v<=5 for v in checks.values()),counts=checks)
                row['effectiveCheckCount']=sum(checks.values())
                cycles=db.execute("select cycle,max_units from cycle where mode='repair' and cycle in ('ask','act')").fetchall()
                check('cycle12:'+tid,len(cycles)==2 and all(x[1]==12 for x in cycles))
            finally:db.close()
for p in (out/'calls').glob('**/request.json'):
    request=read(p)
    check('wire:'+str(p.relative_to(out)),all(request.get(k)==v for k,v in CFG['parameters'].items()) and 'temperature' not in request and 'provider' not in request)
    category=p.relative_to(out/'calls').parts[0]
    dispatch=read(p.with_name('dispatch.json'))
    check('dispatch-deadline:'+str(p.relative_to(out)),dispatch['startedEpoch']<=dispatch['deadlineEpoch'])
    check('request-identity:'+str(p.relative_to(out)),digest(request)==dispatch['requestSha256'])
    if category=='solve':
        names=[t['function']['name'] for t in request.get('tools',[])]
        check('tools:'+str(p.relative_to(out)),set(names)<=set(CFG['toolPolicy']))
        for m in request['messages']:
            if request.get('tools') and m['role']=='assistant':check('reasoning-history:'+str(p.relative_to(out)),isinstance(m.get('reasoning_content'),str))
    elif category in {'online','final'}:
        messages=request['messages']
        payload=json.loads(messages[1]['content'])
        check('blind-judge:'+str(p.relative_to(out)),len(messages)==2 and set(payload)=={'problem','reference_answer','candidate_answer'})
    check('official-endpoint:'+str(p.relative_to(out)),dispatch['endpoint']=='https://api.deepseek.com/chat/completions')
for home in {p.parent.parent for p in (out/'calls').glob('**/dispatch.json')}:
    check('bounded-attempts:'+str(home.relative_to(out)),len(list(home.glob('attempt-*/dispatch.json')))<=3)
summary['realRepairs']=repairs
summary['accounting']=accounting()
summary['timing']={a:{'totalSolverWallSeconds':sum(r.get('solverWallSeconds',0) for r in original if r['arm']==a),
                        'totalOnlineJudgeWaitSeconds':sum(r.get('judgeWaitSeconds',0) for r in original if r['arm']==a),
                        'totalPostSolveJudgeWaitSeconds':sum(r.get('postSolveJudgeWaitSeconds',0) for r in original if r['arm']==a),
                        'totalTaskWallSeconds':sum(r.get('totalWallSeconds',0) for r in original if r['arm']==a)} for a in CFG['arms']}
save(out/'SUMMARY.json',summary)
save(out/'AUDIT.json',{'allPassed':all(x['passed'] for x in audit),'checks':audit,'failures':[x for x in audit if not x['passed']]})
rows=[]
for record in original:
    f=lookup.get((record['arm'],record['id']),{})
    rows.append({'arm':record['arm'],'id':record['id'],'subject':record['subject'],'candidateSha256':record['candidateSha256'],
                 'solverValid':record['solverValid'],'onlineValid':record['onlineGrade'].get('valid'),'onlinePassed':record['onlineGrade'].get('passed'),
                 'finalValid':f.get('grade',{}).get('valid'),'finalPassed':f.get('grade',{}).get('passed'),'disagree':f.get('onlineFinalDisagree'),
                 'solverWallSeconds':record['solverWallSeconds'],'judgeWaitSeconds':record.get('judgeWaitSeconds',0),'totalWallSeconds':record['totalWallSeconds'],
                 'nativeModelRequests':record.get('nativeModelRequests'),'attemptCount':record.get('attemptCount'),'checkCandidates':record.get('checkCandidates')})
with (out/'FINAL_RESULTS.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
lines=['# FrontierScience-Olympiad 正式实验','',
       '范围：固定公开 Olympiad 100题，两组各一次。求解与判卷均为 DeepSeek 官方 deepseek-flash，thinking/high/16384。',
       '这是 DeepSeek 模型判卷协议；同模型盲复评只测一致性，不构成外部独立验证。滚动别名不视为不可变模型版本。','',
       '|组别|有效/总数|正确|有效样本正确率|','|---|---:|---:|---:|']
for a,s in summary['arms'].items():lines.append(f"|{a}|{s['valid']}/{s['tasks']}|{s['correct']}|{s['accuracy']}|")
lines+=['',f"配对差值与95% CI：{summary['paired']['difference']}；{summary['paired']['ci95']}，有效配对 {n}。",'异常保留未解决状态；不得把缺失评分默认为错误。',
        f"跨组胜/负：{len(wins)}/{len(losses)}；ObjRun内部首次候选错误后最终通过：{len(repairs)}，案例分类仍须逐条核查。",'费用按官方token费率估算，非逐请求实际账单；未知费用另列。',
        '完整数字、学科分项、评分不一致及费用详见 SUMMARY.json；逐题详见 FINAL_RESULTS.csv；审计详见 AUDIT.json。']
(out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'auditPassed':all(x['passed'] for x in audit),'original':len(original),'final':len(final),'arms':summary['arms']}))
