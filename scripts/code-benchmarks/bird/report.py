import collections, datetime, json, pathlib
root=pathlib.Path(__file__).resolve().parents[3]
out=root/'docs/newbench-20261014/bird'
arms=['baseline','objrun','independent','binary']
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
summary={'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'benchmark':'BIRD dev_20251106','tasksPerArm':1534,'protocolVersion':'count-bounded-independent-ex-stop-v4','perQuestionDollarCap':None,'independentMaxAttempts':5,'binaryMaxChecks':5,'comparison':'set(predicted_rows) == set(gold_rows)','oracleFeedbackArms':['objrun','binary'],'oracleSelectionArms':['independent'],'independentLabel':'独立采样，EX早停，最多5次','independentFinalCandidate':'first correct candidate; otherwise fifth','independentEXVisibility':'scheduler only; every model context contains only the unchanged public task prompt','arms':{}}
for arm in arms:
    folder='independent-ex-stop' if arm=='independent' else arm
    rows=[read(p) for p in (out/'full/results'/folder).glob('*.json')]
    valid=[r for r in rows if r.get('grade',{}).get('valid')]
    failed=[r for r in rows if not r.get('grade',{}).get('valid')]
    passed=sum(bool(r['grade']['passed']) for r in valid)
    receipts=[read(p) for p in (out/'full/calls'/arm).rglob('receipt.json')]
    unresolved=[read(p) for p in (out/'full/calls'/arm).rglob('unresolved-dispatch.json')]
    s={'completed':len(rows),'valid':len(valid),'passed':passed,'completeWithValidScores':len(valid)==1534,'EX':passed/1534 if len(valid)==1534 else None,'observedPassedFractionAllTasksLowerBound':passed/1534,'noCandidate':sum(r.get('sampleCount')==0 or r.get('candidateHow')=='none' for r in rows),'actualCostUsd':sum(r.get('actualCostUsd') or 0 for r in receipts),'completedResultCostUsd':sum(r.get('actualCostUsd',0) for r in rows),'unknownCostCount':sum(bool(r.get('unknownCost')) for r in receipts)+len(unresolved),'unknownCostUpperBoundUsd':sum(r.get('upperBoundUsd',0) for r in receipts if r.get('unknownCost'))+sum(r.get('upperBoundUsd',0) for r in unresolved),'modelCalls':len(receipts)+len(unresolved),'exceptions':[{'officialId':r['officialId'],'error':r.get('error'),'errorType':r.get('grade',{}).get('errorType')} for r in failed]}
    s['administrativeAbortedAttemptCostUsd']=sum(r.get('administrativeAbortedAttemptCostUsd',0) for r in rows)
    warnings=[{'officialId':r['officialId'],**r['feedbackIntegrityWarnings']} for r in rows if r.get('feedbackIntegrityWarnings')]
    clean=[r for r in valid if not r.get('feedbackIntegrityWarnings')]
    s.update(historicalFeedbackWarnings=warnings,authorizerRegradedResults=sum('authorizerRepairedAtUtc' in r for r in rows),validCandidatesWithCleanFeedback=len(clean),passedWithCleanFeedback=sum(bool(r['grade']['passed']) for r in clean))
    if arm=='independent':
        s.update(label='独立采样，EX早停，最多5次',finalCandidatePolicy='first_correct_else_fifth',executionModes=dict(collections.Counter(r.get('executionMode','unclassified') for r in rows)),postHocReconstructedTasks=[r['officialId'] for r in rows if r.get('executionMode')=='post_hoc_early_stop_reconstruction'],onlineEarlyStopExecutedTasks=[r['officialId'] for r in rows if r.get('actualEarlyStopExecuted')],reusedSamples=sum(r.get('reusedSampleCount',0) for r in rows),newSamples=sum(r.get('newSampleCount',0) for r in rows),generatedSamplesInCompletedResults=sum(r.get('generatedSampleCount',0) for r in rows),postSuccessExtraSamples=sum(r.get('postSuccessExtraSampleCount',0) for r in rows),postSuccessExtraActualCostUsd=sum(r.get('postSuccessExtraActualCostUsd',0) for r in rows),prefixActualCostUsdForAnalysisOnly=sum(r.get('prefixActualCostUsdForAnalysisOnly',0) for r in rows),truncatedSamples=sum(r.get('truncatedSamples',0) for r in rows),costDisclosure='Actual cost is the full receipt ledger, including historical samples after first success and active/incomplete requests. Prefix cost is retrospective analysis only. Historical reconstruction is not actual historical early stopping.')
    summary['arms'][arm]=s
summary['complete']=all(x['completed']==1534 for x in summary['arms'].values())
summary['completeWithValidScores']=all(x['completeWithValidScores'] for x in summary['arms'].values())
summary['actualCostUsd']=sum(x['actualCostUsd'] for x in summary['arms'].values())
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
lines=['# BIRD dev_20251106 results','','Independent sampling is reported as **独立采样，EX早停，最多5次**: every generation uses a fresh context; EX is visible only to the scheduler, which stops on the first correct candidate, otherwise chooses the fifth. Historical stored sequences are explicitly labeled **事后按早停规则重建**. They did not actually execute early stopping. ObjRun and binary retain their original oracle-feedback protocols. EX-based stopping/selection must be distinguished from the standard no-oracle BIRD leaderboard. Every actual charge is included, including samples generated after a historical first success.','','| Arm | Completed | Valid | Passed | Full EX | Actual USD | Unknown cost calls |','|---|---:|---:|---:|---:|---:|---:|']
for arm,s in summary['arms'].items():
    ex=f"{s['EX']:.2%}" if s['EX'] is not None else 'pending/has exceptions'
    label=summary['independentLabel'] if arm=='independent' else arm
    lines.append(f"| {label} | {s['completed']}/1534 | {s['valid']} | {s['passed']} | {ex} | {s['actualCostUsd']:.6f} | {s['unknownCostCount']} |")
s=summary['arms']['independent']
lines+=['',f"Independent execution modes: {s['executionModes']}. Historical reused samples: {s['reusedSamples']}; newly generated samples in completed results: {s['newSamples']}. Post-success historical extra samples: {s['postSuccessExtraSamples']}; actual extra charges: ${s['postSuccessExtraActualCostUsd']:.9f}. Prefix charges (${s['prefixActualCostUsdForAnalysisOnly']:.9f}) are analysis only and are not represented as actual total spending.",'','Original v3 independent results remain in full/results/independent. Corrected and new primary results are in full/results/independent-ex-stop. Candidate selection, reused/new sample IDs and actual online stopping are recorded per question. Canary results and costs remain excluded.']
for arm,s in summary['arms'].items():
    if s['historicalFeedbackWarnings']:
        lines+=['',f"{arm}: {len(s['historicalFeedbackWarnings'])} historical trajectories contain read-authorizer feedback false positives. Original feedback and corrected reassessments are retained; valid final candidates were not regenerated. Clean-feedback subset: {s['passedWithCleanFeedback']}/{s['validCandidatesWithCleanFeedback']}."]
(out/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
print(json.dumps(summary,ensure_ascii=False))
