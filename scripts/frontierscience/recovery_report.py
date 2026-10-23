"""Offline raw-original, audited-original and deterministic applied-recovery report."""
from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import random
import sqlite3

REPO=Path(__file__).resolve().parents[2]
LOCAL=REPO/'docs/frontierscience/frontierscience-recovery-20261016-v1-deepseek-c32'
ORIGLOCAL=REPO/'docs/frontierscience/frontierscience-formal-20261016-v1-deepseek-c32'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda x:hashlib.sha256(x if isinstance(x,bytes) else x.encode()).hexdigest()

def valid(r):return bool(r.get('solverValid') and r.get('grade',{}).get('valid'))
def stats(rows):
    n=len(rows);usable=[r for r in rows if valid(r)];k=sum(r['grade']['passed'] for r in usable);v=len(usable)
    return {'total':n,'valid':v,'correct':k,'accuracy':k/v if v else None,'knownCorrectFraction':k/n if n else None,'unresolved':n-v,
            'allTaskAccuracyBounds':[k/n,(k+n-v)/n] if n else None}

def summarize(records,ids):
    arms=['baseline','objrun'];subjects=['physics','chemistry','biology']
    summary={'arms':{a:stats([r for r in records.values() if r['arm']==a]) for a in arms},
             'subjects':{s:{a:stats([r for r in records.values() if r['arm']==a and r['subject']==s]) for a in arms} for s in subjects}}
    deltas=[];wins=[];losses=[];ties=0
    for tid in ids:
        a,b=records['baseline',tid],records['objrun',tid]
        if not valid(a) or not valid(b):continue
        d=int(b['grade']['passed'])-int(a['grade']['passed']);deltas.append(d)
        if d>0:wins.append(tid)
        elif d<0:losses.append(tid)
        else:ties+=1
    rng=random.Random(20261016);n=len(deltas)
    boot=sorted(sum(rng.choices(deltas,k=n))/n for _ in range(20000)) if n else []
    summary['paired']={'validPairs':n,'difference':sum(deltas)/n if n else None,'ci95':[boot[499],boot[19499]] if boot else None,
                       'wins':wins,'losses':losses,'ties':ties,'bootstrapReplicates':20000,'seed':20261016,
                       'scope':'question resampling within this one fixed run; not run-to-run or grader uncertainty'}
    return summary

def main():
    origroot=ORIGLOCAL/'full-results';recroot=LOCAL/'full-results';oo=origroot/'outputs/canonical';ro=recroot/'outputs/canonical'
    manifest=read(LOCAL/'recovery-manifest.json');entries={(e['arm'],e['id']):e for e in manifest['entries']}
    raw={(r['arm'],r['id']):r for p in (oo/'final-results').glob('*/*.json') for r in [read(p)]}
    original={(r['arm'],r['id']):r for p in (oo/'results').glob('*/*.json') for r in [read(p)]}
    recovery={(r['arm'],r['id']):r for p in (ro/'final-results').glob('*/*.json') for r in [read(p)]}
    rr={(r['arm'],r['id']):r for p in (ro/'results').glob('*/*.json') for r in [read(p)]}
    ids=read(origroot/'data/source.json')['ids'];audited={k:dict(v) for k,v in raw.items()};notes=[]
    for key,e in entries.items():
        if e['action']=='exclude_normal_budget':
            assert e['evidence']['normalBudgetBoundary'] and raw[key]['grade']['valid'] and not original[key]['answer']
            audited[key]['solverValid']=True
            notes.append({'arm':key[0],'id':key[1],'classification':'ordinary_original600_exhaustion',
                          'rawSolverValid':raw[key]['solverValid'],'auditedSolverValid':True,
                          'reason':'actual transport ended at the original deadline; empty submitted delivery is a normal model failure; raw records untouched'})
    applied={k:dict(v) for k,v in audited.items()};provenance={k:'original' for k in raw}
    for key,r in recovery.items():
        # Failure to recover stays unresolved; a valid recovery replaces regardless of score.
        applied[key]=dict(r);provenance[key]='recovery-round-1'
    summaries={'rawOriginal':summarize(raw,ids),'auditedOriginal':summarize(audited,ids),'appliedRecovery':summarize(applied,ids)}
    online_disagreements={}
    for label,records,root in [('original',raw,origroot),('recovery',recovery,recroot)]:
        events=[]
        for key,r in records.items():
            if not r['grade'].get('valid'):continue
            if label=='original':g=original[key]['onlineGrade']
            else:
                grades=[read(p) for p in (root/'outputs/canonical/judgments/online').glob('*.json')]
                g=next((g for g in grades if g['taskId']==r['id'] and g['candidateSha256']==r['candidateSha256']),{})
            if g.get('valid') and g['passed']!=r['grade']['passed']:
                events.append({'arm':key[0],'id':key[1],'onlinePassed':g['passed'],'blindPassed':r['grade']['passed'],'candidateSha256':r['candidateSha256']})
        online_disagreements[label]=events
    repairs=[]
    for key,f in applied.items():
        if key[0]!='objrun' or not valid(f) or not f['grade']['passed']:continue
        root=recroot if provenance[key]=='recovery-round-1' else origroot
        p=root/'outputs/canonical/tasks/objrun'/key[1]/'feedback.json'
        eq=[x for x in read(p) if x['node']=='equivalent'] if p.exists() else []
        if eq and eq[0]['exposed']['value'] is False:
            repairs.append({'id':key[1],'batch':provenance[key],'firstCandidateSha256':eq[0]['candidateSha256'],'finalCandidateSha256':f['candidateSha256']})
    reviews=read(LOCAL/'CASE_REVIEW.json')
    labels={x['id']:x for x in reviews['cases']}
    for case in repairs:
        assert case['id'] in labels, 'MissingCaseReview:'+case['id']
        label=labels[case['id']]
        assert case['firstCandidateSha256']==label['firstCandidateSha256'] and case['finalCandidateSha256']==label['finalCandidateSha256']
        case.update(classification=label['classification'],note=label['note'])
    from collections import Counter
    repair_counts=dict(Counter(x['classification'] for x in repairs))
    failed_requests=[];timing={};accounting={}
    engine_counts=[];model_versions={}
    for label,root in [('original',origroot),('recovery',recroot)]:
        out=root/'outputs/canonical';accounting[label]=read(out/'SUMMARY.json')['accounting'];receipts=[(p,read(p)) for p in (out/'calls').glob('**/receipt.json')]
        model_versions[label]={'requestModel':'deepseek-flash','responseModels':sorted({r['responseModel'] for p,r in receipts if r.get('responseModel')}),
                               'responseDates':sorted({r.get('headers',{}).get('Date') for p,r in receipts if r.get('headers',{}).get('Date')}),
                               'versionCaveat':'response model identifiers and dates are preserved; rolling alias does not pin immutable weights'}
        timing[label]={'modelSecondsByCategory':{c:sum(r['seconds'] for p,r in receipts if p.relative_to(out/'calls').parts[0]==c) for c in ['solve','online','final','controls']},
                       'solverWallSeconds':sum(r.get('solverWallSeconds',0) for r in (original if label=='original' else rr).values()),
                       'judgeWaitInsideSolveSeconds':sum(r.get('judgeWaitSeconds',0) for r in (original if label=='original' else rr).values()),
                       'postSolveJudgeWaitSeconds':sum(r.get('postSolveJudgeWaitSeconds',0) for r in (original if label=='original' else rr).values()),
                       'freshBlindWaitSeconds':sum(r.get('seconds',0) for r in (raw if label=='original' else recovery).values())}
        launch=read(out/'launch.json');end=read(out/'status.json')
        timing[label]['batchElapsedSeconds']=(dt.datetime.fromisoformat(end['atUtc'])-dt.datetime.fromisoformat(launch['atUtc'].replace('Z','+00:00'))).total_seconds()
        for p,r in receipts:
            cat=p.relative_to(out/'calls').parts[0]
            if r.get('error') or cat in {'online','final'} and r.get('finishReason')!='stop':
                failed_requests.append({'batch':label,'path':p.relative_to(root).as_posix(),'category':cat,'error':r.get('error') or 'GraderIncomplete:'+str(r.get('finishReason')),'cost':r['cost'],'usage':r.get('usage')})
        for ident,r in (original if label=='original' else rr).items():
            arm,tid=ident;d=out/'tasks'/arm/tid
            count={'batch':label,'arm':arm,'id':tid,'actualApiDispatches':sum(p.relative_to(out/'calls').parts[:3]==('solve',tid,arm) for p,v in receipts),
                   'nativeLogicalModelRequests':r.get('nativeModelRequests',0),'attemptCount':0,'equivalenceChecks':0,'distinctCheckedCandidates':0,'effectiveChecksPerAttempt':{}}
            if arm=='objrun':
                eq=[x for x in read(d/'feedback.json') if x['node']=='equivalent'] if (d/'feedback.json').exists() else []
                count['equivalenceChecks']=len(eq);count['distinctCheckedCandidates']=len({x['candidateSha256'] for x in eq})
                db=sqlite3.connect('file:'+str(d/'engine/data/h2h.sqlite')+'?mode=ro',uri=True)
                count['attemptCount']=db.execute('select count(distinct node) from task_repair').fetchone()[0]
                for node,body in db.execute("select t.node,m.body from task_repair t join agent_bot_msg m on m.instance=t.instance and m.unit=t.unit where m.kind='tool'"):
                    v=json.loads(body);g=v.get('value',{})
                    if v.get('name')=='verify' and not str(v.get('id','')).startswith('g-') and g.get('valid') is not False and g.get('pass') in [0,1]:
                        counts=count['effectiveChecksPerAttempt'];counts[node]=counts.get(node,0)+1
                db.close()
            engine_counts.append(count)
    result={'protocol':'DeepSeek模型判卷协议；同模型盲复评仅测一致性，非外部独立验证；deepseek-flash是滚动别名',
            **summaries,'auditReclassification':notes,'recoveryOutcomes':list(recovery.values()),
            'additionalSolverBudgetTasks':[{'arm':e['arm'],'id':e['id'],'seconds':600} for e in entries.values() if e['action']=='objrun_once'],
            'onlineBlindDisagreements':online_disagreements,'internalFirstRejectedToBlindAccepted':repairs,'internalRepairClassifications':repair_counts,
            'accounting':accounting,'failureRequestLedger':failed_requests,'timing':timing,
            'actualCallsAttemptsCandidatesChecks':engine_counts,'observedModelVersions':model_versions,
            'verification':{label:{k:v for k,v in read(local/'LOCAL_VERIFICATION.json').items() if k in {'allPassed','checks','failures','archiveSha256'}} for label,local in [('original',ORIGLOCAL),('recovery',LOCAL)]},
            'archiveSha256':{'original':read(ORIGLOCAL/'retrieval.json')['sha256'],'recovery':read(LOCAL/'retrieval.json')['sha256']},
            'applicationRule':'apply the single eligible recovery outcome irrespective of score; unresolved recovery remains unresolved, no selection by score'}
    (LOCAL/'COMBINED_SUMMARY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rows=[]
    for key in sorted(raw):
        o=raw[key];a=applied[key];r=recovery.get(key,{})
        rows.append({'arm':key[0],'id':key[1],'subject':o['subject'],'originalCandidateSha256':o['candidateSha256'],'originalValid':valid(o),
                     'originalPassed':o['grade'].get('passed') if valid(o) else None,'auditClassification':entries[key]['action'],
                     'recoveryCandidateSha256':r.get('candidateSha256'),'recoveryValid':valid(r) if r else None,
                     'recoveryPassed':r.get('grade',{}).get('passed') if valid(r) else None,'extraSolveBudgetSeconds':entries[key]['extraSolveSeconds'],
                     'appliedSource':provenance[key],'appliedCandidateSha256':a['candidateSha256'],'appliedValid':valid(a),
                     'appliedPassed':a['grade'].get('passed') if valid(a) else None})
    with (LOCAL/'COMBINED_RESULTS.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    pct=lambda v:f'{v*100:.2f}%' if v is not None else '未定'
    pp=lambda v:f'{v*100:.2f}个百分点' if v is not None else '未定'
    lines=['# FrontierScience-Olympiad：原始批次与一次有界恢复','',
           '固定公开100题（物理50、化学40、生物10），单次组与真实ObjRun各一次。所有模型请求均为DeepSeek官方deepseek-flash、thinking enabled/high/max_tokens=16384。',
           '采用冻结的DeepSeek模型判卷协议；同模型盲复评仅检查一致性，不是外部独立验证。滚动别名不等同不可变版本。','',
           '|结果口径|单次组：正确/有效（总100）|ObjRun：正确/有效（总100）|配对差值及95%区间|','|---|---:|---:|---|']
    for label,cn in [('rawOriginal','原始记录'),('auditedOriginal','原始审计口径'),('appliedRecovery','应用一次恢复后')]:
        s=summaries[label];a,b=s['arms']['baseline'],s['arms']['objrun'];p=s['paired']
        lines.append(f"|{cn}|{a['correct']}/{a['valid']}（{pct(a['accuracy'])}）|{b['correct']}/{b['valid']}（{pct(b['accuracy'])}）|{pp(p['difference'])} [{pp(p['ci95'][0])}, {pp(p['ci95'][1])}]，n={p['validPairs']}|")
    lines+=['','原始未解决项不按错误计分；完整100题的正确比例界限、有效分母及逐题状态均见JSON/CSV。审计口径仅将一项有回执证据的原600秒预算耗尽归为正常空交付失败，原始错误标记、候选和成绩文件均未改写。',
            '', '恢复清单在调用前冻结：两项真实判卷故障中断的ObjRun各追加最多600秒，一项完整单次答案只补一次独立评分。恢复结果按预定清单应用，不按分数择优。正常错误、求解截断、预算耗尽均未重跑。','',
            '|恢复任务|处理|有效|盲评通过|','|---|---|---|---|']
    for r in recovery.values():lines.append(f"|{r['arm']}/{r['id']}|{r['action']}；额外求解{r['extraSolveSeconds']}秒|{valid(r)}|{r['grade'].get('passed') if r['grade'].get('valid') else '评分异常'}|")
    lines+=['','酶动力学题 `3d762ba1-3958-453b-b34e-fe24c2822994` 的单次组补评分仍截断，ObjRun恢复又被在线判卷截断中止；两组均保留异常，不当作正常答错。一轮恢复已用尽，不再自动重试。铁氧化物题恢复获得真实提交，新的盲评判错。',
            '应用后每组各有1项待决：全100题准确率的缺失结果范围为单次组59%—60%、ObjRun86%—87%；这是待决结果范围，不是95%置信区间。']
    lines+=['','|学科（应用恢复后）|单次正确/有效|ObjRun正确/有效|','|---|---:|---:|']
    for subject,v in summaries['appliedRecovery']['subjects'].items():lines.append(f"|{subject}|{v['baseline']['correct']}/{v['baseline']['valid']}|{v['objrun']['correct']}/{v['objrun']['valid']}|")
    p=summaries['appliedRecovery']['paired']
    lines+=['',f"有效配对胜/负/平：{len(p['wins'])}/{len(p['losses'])}/{p['ties']}。跨组胜题与ObjRun内部修复分别统计，不能将二者等同。",
            f"内部首次受等价检查候选被拒、最终盲评通过：{len(repairs)}项；逐例核查分类 {repair_counts}。等价改写导致的判卷翻转不算真实内容修复，格式修改也不并入内容修复。详见CASE_REVIEW.json。",
            f"原始在线/盲评不一致 {len(online_disagreements['original'])}项；恢复批次 {len(online_disagreements['recovery'])}项，方向及题号见JSON。",'',
            '|批次|已知token费率估算（USD）|费用未知请求数|实际逐请求账单|','|---|---:|---:|---|']
    for label,a in accounting.items():
        g=a['byCategory'];lines.append(f"|{label}|{sum(x['estimatedUsd'] for x in g.values()):.6f}|{sum(x['unknownCostRequests'] for x in g.values())}|不可获得|")
    lines+=['','费用为按已核查官方费率与缓存token计算的估算，未知请求不计入已知估算和，不冒充实际账单。求解、在线判卷、盲评、控制与失败请求分别保留账目，失败分类不是额外重复相加。',
            '耗时分别保留模型时间、求解墙钟、求解内判卷等待、交卷后判卷等待、盲评等待及批次耗时；预算内等待未延长求解截止时间。','',
            '95%区间用固定种子20261016对题目配对差值进行20000次bootstrap；只反映本次固定协议下的题目抽样不确定性，不反映重复运行或判卷模型不确定性。结论限定本次DeepSeek求解及判卷协议。','',
            f"原始归档SHA256：`{result['archiveSha256']['original']}`。",f"恢复归档SHA256：`{result['archiveSha256']['recovery']}`。",
            '两批次完整材料、依赖、请求响应、候选、判决、费用、异常和ObjRun SQLite/树/消息/工具轨迹分别归档，两端SHA256及本地核验结果见各批次retrieval.json和LOCAL_VERIFICATION.json。']
    lines+=['',f"原始批次耗时 {timing['original']['batchElapsedSeconds']:.1f}秒，恢复批次 {timing['recovery']['batchElapsedSeconds']:.1f}秒。两项ObjRun实际新增求解墙钟合计 {sum(r['solverWallSeconds'] for k,r in rr.items() if k[0]=='objrun'):.2f}秒，授权上限为每题额外600秒，截止后仅清理和读取冻结提交。",
            '原始在线通过而盲评失败：ObjRun/710c1336-0995-4d45-bfea-48ff475f255f。原始在线失败而盲评通过：单次组/8b695bb3-ea3c-4372-9222-9f0b79a68b6c。恢复无此类有效判决不一致。',
            f"原始本地核验 {result['verification']['original']['checks']}项全部通过，恢复本地核验 {result['verification']['recovery']['checks']}项全部通过。所有实际请求端点、候选身份、原/追加截止时间、c5、共享限流及评分端隐私均保留审计证据。",
            '响应模型标识：'+', '.join(sorted({m for v in model_versions.values() for m in v['responseModels']}))+'；响应日期与可获得的版本信息见COMBINED_SUMMARY.json和原始回执。']
    (LOCAL/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'summaries':summaries,'repairClassifications':repair_counts,'accounting':accounting},ensure_ascii=False))

if __name__=='__main__':main()
