"""Offline raw-original, audited-original and deterministic applied-recovery report."""
from pathlib import Path
import csv
import datetime as dt
import hashlib
import json
import random
import sqlite3

REPO=Path(__file__).resolve().parents[3]
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
    result={'protocol':'DeepSeek model-grading protocol; same-model blind regrading measures consistency, not external independent verification; deepseek-flash is a rolling alias',
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
    pct=lambda v:f'{v*100:.2f}%' if v is not None else 'undetermined'
    pp=lambda v:f'{v*100:.2f} percentage points' if v is not None else 'undetermined'
    lines=['# FrontierScience-Olympiad: original batch and one bounded recovery','',
           '100 fixed public questions (50 physics, 40 chemistry, 10 biology), one run each for the single-attempt arm and real ObjRun. All model requests use official DeepSeek deepseek-flash, thinking enabled/high/max_tokens=16384.',
           'Uses a frozen DeepSeek model-grading protocol; blind regrading by the same model checks consistency, not external independent verification. A rolling alias is not an immutable version.','',
           '|Result basis|Single attempt: correct/valid (100 total)|ObjRun: correct/valid (100 total)|Paired difference and 95% interval|','|---|---:|---:|---|']
    for label,cn in [('rawOriginal','Original records'),('auditedOriginal','Audited original'),('appliedRecovery','After applying one recovery')]:
        s=summaries[label];a,b=s['arms']['baseline'],s['arms']['objrun'];p=s['paired']
        lines.append(f"|{cn}|{a['correct']}/{a['valid']}（{pct(a['accuracy'])}）|{b['correct']}/{b['valid']}（{pct(b['accuracy'])}）|{pp(p['difference'])} [{pp(p['ci95'][0])}, {pp(p['ci95'][1])}]，n={p['validPairs']}|")
    lines+=['','Unresolved original cases are not scored as wrong. JSON/CSV provide full-100 correctness bounds, valid denominators, and per-question states. The audited basis reclassifies only one receipt-supported case of original 600-second budget exhaustion as a normal empty-submission failure; original error flags, candidates, and score files remain unchanged.',
            '', 'The recovery list was frozen before calls: two ObjRun cases interrupted by genuine grading faults each receive at most 600 additional seconds; one complete single-attempt answer receives one independent grade only. Recovery results are applied according to the predetermined list, without selecting by score. Normal errors, solver truncation, and budget exhaustion are not rerun.','',
            '|Recovery task|Action|Valid|Blind-grade pass|','|---|---|---|---|']
    for r in recovery.values():lines.append(f"|{r['arm']}/{r['id']}|{r['action']}; extra solving {r['extraSolveSeconds']} seconds|{valid(r)}|{r['grade'].get('passed') if r['grade'].get('valid') else 'grading exception'}|")
    lines+=['','For enzyme-kinetics question `3d762ba1-3958-453b-b34e-fe24c2822994`, supplemental grading of the single-attempt answer was again truncated, and ObjRun recovery was again stopped by online-grading truncation. Both retain exception status rather than normal incorrect-answer status. The one recovery round is exhausted; no further automatic retries. Recovery of the iron-oxide question produced an actual submission, which the new blind grade rejected.',
            'After recovery, each arm has one pending case: missing-outcome accuracy bounds over all 100 questions are 59%–60% for single attempt and 86%–87% for ObjRun. These are pending-outcome ranges, not 95% confidence intervals.']
    lines+=['','|Subject (after recovery)|Single attempt correct/valid|ObjRun correct/valid|','|---|---:|---:|']
    for subject,v in summaries['appliedRecovery']['subjects'].items():lines.append(f"|{subject}|{v['baseline']['correct']}/{v['baseline']['valid']}|{v['objrun']['correct']}/{v['objrun']['valid']}|")
    p=summaries['appliedRecovery']['paired']
    lines+=['',f"Valid paired wins/losses/ties: {len(p['wins'])}/{len(p['losses'])}/{p['ties']}. Cross-arm wins and internal ObjRun repairs are counted separately and must not be equated.",
            f"Cases with an initially rejected equivalence-checked internal candidate and a final blind pass: {len(repairs)}; individual review classifications: {repair_counts}. Grading flips caused by equivalent rewording are not genuine content repairs; formatting changes are also excluded from content repair. See CASE_REVIEW.json.",
            f"Original online/blind-grade disagreements: {len(online_disagreements['original'])}; recovery batch: {len(online_disagreements['recovery'])}. Directions and question IDs are in JSON.",'',
            '|Batch|Known token-rate estimate (USD)|Requests with unknown cost|Actual per-request bills|','|---|---:|---:|---|']
    for label,a in accounting.items():
        g=a['byCategory'];lines.append(f"|{label}|{sum(x['estimatedUsd'] for x in g.values()):.6f}|{sum(x['unknownCostRequests'] for x in g.values())}|Unavailable|")
    lines+=['','Costs are estimates using verified official rates and cached tokens. Unknown requests are excluded from known-cost totals, which are not presented as actual bills. Solving, online grading, blind grading, controls, and failed requests retain separate accounts; failure categories are not added again as duplicate costs.',
            'Timing separately retains model time, solver wall time, in-solver grading waits, post-submission grading waits, blind-grading waits, and batch duration. In-budget waits did not extend solving deadlines.','',
            '95% intervals use 20,000 paired-question bootstrap samples with fixed seed 20261016. They reflect question-sampling uncertainty under this fixed protocol, not repeat-run or grading-model uncertainty. Conclusions are limited to this DeepSeek solving and grading protocol.','',
            f"Original archive SHA256: `{result['archiveSha256']['original']}`.",f"Recovery archive SHA256: `{result['archiveSha256']['recovery']}`.",
            'Complete materials, dependencies, requests/responses, candidates, judgments, costs, exceptions, and ObjRun SQLite/tree/message/tool traces are archived separately for both batches. Both-end SHA256 values and local checks are in each batch retrieval.json and LOCAL_VERIFICATION.json.']
    lines+=['',f"Original batch duration: {timing['original']['batchElapsedSeconds']:.1f} seconds; recovery batch: {timing['recovery']['batchElapsedSeconds']:.1f} seconds. Actual added solving wall time for the two ObjRun cases totals {sum(r['solverWallSeconds'] for k,r in rr.items() if k[0]=='objrun'):.2f} seconds, within the authorized extra 600 seconds per question. After deadlines, only cleanup and reading frozen submissions occurred.",
            'Original online pass but blind failure: ObjRun/710c1336-0995-4d45-bfea-48ff475f255f. Original online failure but blind pass: single-attempt/8b695bb3-ea3c-4372-9222-9f0b79a68b6c. Recovery has no such disagreement between valid judgments.',
            f"All {result['verification']['original']['checks']} original local checks and all {result['verification']['recovery']['checks']} recovery local checks passed. Audit evidence retains actual request endpoints, candidate identities, original/additional deadlines, c5, shared rate limits, and grader-side privacy.",
            'Response model identifiers: '+', '.join(sorted({m for v in model_versions.values() for m in v['responseModels']}))+'; response dates and available version information are in COMBINED_SUMMARY.json and original receipts.']
    (LOCAL/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'summaries':summaries,'repairClassifications':repair_counts,'accounting':accounting},ensure_ascii=False))

if __name__=='__main__':main()
