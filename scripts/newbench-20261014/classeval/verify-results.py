"""Offline reconciliation; no model requests, no regrading, no credentials in output."""
import datetime,hashlib,importlib.util,json,pathlib,sqlite3
from decimal import Decimal

SRC=pathlib.Path(__file__).resolve().parent
ROOT=SRC.parents[2]
OUT=ROOT/'docs/newbench-20261014/classeval'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
catalog=read(SRC/'public-tasks.json'); expected={t['officialId'] for t in catalog}
config=read(SRC/'experiment.json')
approved_providers={'digitalocean':'DigitalOcean'}
if config.get('objrunProvider'):
    approved_providers[config['objrunProvider']['providerSlug']]=config['objrunProvider']['providerName']
public={t['officialId']:t for t in catalog}
spec=importlib.util.spec_from_file_location('classeval_offline_extraction',SRC/'grader_service.py')
grader=importlib.util.module_from_spec(spec);spec.loader.exec_module(grader)
source_pins=read(OUT/'source-pins.json')
assert all(sha(pathlib.Path(p['path']))==p['sha256'] for p in source_pins['files']), 'Pinned source changed'
assert len(expected)==100
assert read(OUT/'controls.json')['allPassed']
assert all(not({'test','solution_code','test_classes'}&set(t)) for t in catalog)
for tid,t in public.items():
    assert grader.ROWS[tid]['test'] not in t['prompt']
    assert grader.ROWS[tid]['solution_code'] not in t['prompt']

all_receipts=[];unresolved=[]
for dispatch in (OUT/'calls').rglob('dispatch.json'):
    receipt=dispatch.with_name('receipt.json')
    if not receipt.exists(): unresolved.append(str(dispatch));continue
    r=read(receipt); arm=receipt.relative_to(OUT/'calls').parts[0]
    request=read(receipt.with_name('request.json'))
    assert request['model']=='deepseek/deepseek-v4.1-flash'
    requested=request['provider']['only']
    assert len(requested)==1 and requested[0] in approved_providers and request['provider']['allow_fallbacks'] is False
    if arm=='baseline': assert requested==['digitalocean']
    assert request['reasoning']=={'enabled':True,'effort':'high','exclude':False}
    assert request['max_tokens']==16384 and request['temperature']==0
    assert not {'api_key','authorization'}&set(request)
    response=receipt.with_name('response.json')
    if r.get('responseSha256'):
        assert response.exists() and sha(response)==r['responseSha256']
    if r.get('fault') in [None,'MissingOrInvalidOpenRouterUsdCost'] and r.get('httpStatus')==200:
        assert r['provider']==approved_providers[requested[0]]
    all_receipts.append({'arm':arm,'receiptPath':str(receipt.resolve()),**r})
assert not unresolved,'Unresolved model dispatches'

arms={}; rows=[]
for arm in ['baseline','objrun']:
    result_files=list((OUT/'results'/arm).glob('*.json'))
    records=[read(p) for p in result_files]
    assert len({r['taskId'] for r in records})==len(records)
    assert all(r['taskId'] in expected and r['promptSha256']==public[r['taskId']]['promptSha256'] for r in records)
    valid=[r for r in records if r['grade']['valid']]
    for result,path in zip(records,result_files):
        tid=result['taskId']
        if result['grade']['valid']:
            candidates=list((OUT/'tasks'/arm/tid).glob('attempt-*/candidate.json'))
            matching=[p for p in candidates if read(p).get('answer')==result.get('answer')]
            assert matching,('Missing final candidate',arm,tid)
            code=grader.extract(result.get('answer',''))
            if not result.get('modelProtocolFailure'):
                assert hashlib.sha256(code.encode()).hexdigest()==result['grade']['candidateSha256']
                assert len(result['grade']['details'])==len(grader.ROWS[tid]['test_classes'])
                assert bool(result['grade']['passed'])==all(g['passed'] for g in result['grade']['details'])
                assert result['grade']['image']=='sha256:45bd04b2941a81856945b5e46cff8ba2ae5111ec7ead633b12f5c89ab6989b56'
                assert result['grade']['officialTimeoutSecondsPerGroup']==5
            if arm=='objrun' and not result.get('modelProtocolFailure'):
                assert result.get('candidateHow')=='submitted',('Non-native ObjRun candidate',tid)
                db_path=matching[-1].parent/'engine/data/h2h.sqlite'
                conn=sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True)
                try:
                    task_row=conn.execute('SELECT created_at,solve_seconds FROM task WHERE id=?',('classeval-20261014/objrun/'+tid,)).fetchone()
                    assert task_row and task_row[1] in (600,1200,2400)
                    if task_row[1]==2400:
                        assert tid in config.get("exceptionRecovery",{}).get("taskIds",[])
                        assert read(OUT/"exception-timeout-amendment.json")["approved"]
                    deadline=task_row[0]+task_row[1]*1000
                    submissions=[]
                    for body,at in conn.execute("SELECT body,at FROM agent_bot_msg WHERE kind='call' AND at<=?",(deadline,)):
                        submissions.extend(c.get('input',{}).get('answer') for c in json.loads(body).get('calls',[]) if c.get('name')=='submit')
                    assert result['answer'] in submissions,('No original submit before native deadline',tid)
                    if result.get('solveSeconds') is not None: assert result['solveSeconds']==task_row[1]
                finally:conn.close()
            if arm=='baseline':
                own=[r for r in all_receipts if r['arm']==arm and pathlib.Path(r['receiptPath']).relative_to(OUT/'calls').parts[1]==tid]
                successful=[r for r in own if r.get('httpStatus')==200 and r.get('fault') in [None,'MissingOrInvalidOpenRouterUsdCost']]
                assert len(successful)==1,('Baseline must have one successful model response',tid)
                response=read(pathlib.Path(successful[0]['receiptPath']).with_name('response.json'))
                content=response['choices'][0]['message'].get('content')
                assert ('' if content is None else content)==result['answer'],('Candidate response mismatch',tid)
                assert response['provider']=='DigitalOcean' and response['model'] in ['deepseek/deepseek-v4.1-flash','deepseek/deepseek-v4.1-flash-20260910']
        rows.append({'arm':arm,'taskId':tid,'gradeValid':result['grade']['valid'],'passed':result['grade']['passed'],
            'candidateHow':result.get('candidateHow'),'candidateSha256':result['grade'].get('candidateSha256'),
            'resultPath':str(path.resolve()),'actualCostUsdKnown':result.get('actualCostUsd'),
            'unknownCostCount':result.get('unknownCostCount'),'error':result.get('error')})
    receipts=[r for r in all_receipts if r['arm']==arm]
    known=sum((Decimal(str(r['actualCostUsd'])) for r in receipts if r.get('actualCostUsd') is not None),Decimal(0))
    unknown=[r for r in receipts if r.get('unknownCost')]
    upper=sum((Decimal(str(r['upperBoundUsd'])) for r in unknown),Decimal(0))
    passed=sum(bool(r['grade']['passed']) for r in valid)
    arms[arm]={'fixedTaskCount':100,'attemptedTaskCount':len(records),'validScoredTaskCount':len(valid),
        'passed':passed,'failedValid':len(valid)-passed,'scoringOrGenerationExceptions':len(records)-len(valid),
        'unattemptedTaskCount':100-len(records),'remainingValidTaskCount':100-len(valid),
        'fullArmComplete':len(valid)==100 and {r['taskId'] for r in valid}==expected,
        'fullPassRate':passed/100 if len(valid)==100 else None,'modelCalls':len(receipts),
        'nativeTaskAttemptsForClassEval0':next((r.get('taskAttempts',0) for r in records if r['taskId']=='ClassEval_0'),0),
        'providerTimeoutEnvelopes':sum('Provider timed out' in (r.get('fault') or '') for r in receipts),
        'localDeadlineTimeouts':sum('TimeoutError' in (r.get('fault') or '') for r in receipts),
        'emptyFinalCandidateCount':sum(not r.get('answer') for r in valid),
        'lengthLimitedResponseCount':sum(r.get('finishReason')=='length' for r in valid),
        'knownCostSubtotalUsd':str(known),'unknownCostCount':len(unknown),'unknownCostEstimatedUpperBoundUsd':str(upper)}
assert arms['baseline']['fullArmComplete'],'Baseline did not complete the fixed 100 tasks'
summary={'verifiedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'allExperimentsComplete':all(a['fullArmComplete'] for a in arms.values()),'arms':arms,
    'verification':{'sourcePinsMatch':True,'officialScoringControlsPassed':True,'candidateGradeHashesMatch':True,
        'baselineOneSuccessfulResponsePerTask':True,'realProviderAndModelReceiptsVerified':True,
        'publicPromptsExcludeTestsAndSolutions':True,'unresolvedDispatchCount':0,'newModelCalls':0,'newGradingCalls':0},
    'concurrency':8,'perTaskDollarCap':None,'pairedComparisonAvailable':all(a['fullArmComplete'] for a in arms.values()),
    'objrunSolveSeconds':config.get('objrunSolveSeconds',config['solveSeconds']),
    'objrunProtocolAmended':config.get('objrunSolveSeconds',config['solveSeconds'])!=600,
    'exceptionRecovery':config.get('exceptionRecovery'),
    'baselineProvider':'DigitalOcean','objrunProvider':config.get('objrunProvider',{}).get('providerName','DigitalOcean'),
    'providerDifferenceMustBeReported':bool(config.get('objrunProvider')),
    'knownCostSubtotalUsd':str(sum((Decimal(str(r['actualCostUsd'])) for r in all_receipts if r.get('actualCostUsd') is not None),Decimal(0))),
    'unknownCostCount':sum(bool(r.get('unknownCost')) for r in all_receipts),
    'unknownCostEstimatedUpperBoundUsd':str(sum((Decimal(str(r['upperBoundUsd'])) for r in all_receipts if r.get('unknownCost')),Decimal(0))),
    'interfaceDiagnosticCalls':sum(r['arm']=='interface_diagnostic' for r in all_receipts),
    'interfaceDiagnosticKnownCostUsd':str(sum((Decimal(str(r['actualCostUsd'])) for r in all_receipts if r['arm']=='interface_diagnostic' and r.get('actualCostUsd') is not None),Decimal(0))),
    'unknownCostReceipts':[{'arm':r['arm'],'receiptPath':r['receiptPath'],'generationId':r.get('generationId'),
        'fault':r.get('fault'),'upperBoundUsd':r['upperBoundUsd']} for r in all_receipts if r.get('unknownCost')],
    'taskResults':sorted(rows,key=lambda r:(r['arm'],int(r['taskId'].split('_')[1])))}
(OUT/'verified-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf8')
base=arms['baseline'];obj=arms['objrun']
complete=summary['allExperimentsComplete']
status=read(OUT/'status.json')
trial=read(OUT/'provider-trial-outcome.json') if (OUT/'provider-trial-outcome.json').exists() else None
amendment=read(OUT/'protocol-amendment.json') if (OUT/'protocol-amendment.json').exists() else None
lines=[f"# ClassEval {'final' if complete else 'partial'} results — 2026-10-14",
    f"Verified at {summary['verifiedAtUtc']}. This is an offline snapshot; current process state is in status.json.",
    f"Baseline: **{base['passed']}/100 passed ({base['fullPassRate']:.0%})**, 100 valid final candidates, {base['failedValid']} valid failures and no remaining exceptions. Each candidate matches one successful DigitalOcean response and its official scoring hash.",
    f"ObjRun: {obj['validScoredTaskCount']}/100 valid scored tasks, {obj['passed']} passed, {obj['failedValid']} valid failures, {obj['scoringOrGenerationExceptions']} recorded exceptions and {obj['unattemptedTaskCount']} unattempted tasks. " + (f"Final complete-class pass rate: **{obj['fullPassRate']:.0%}**." if obj['fullArmComplete'] else "The full 100-task arm is incomplete; no full-arm pass rate is reported."),
    "| Arm | Valid scored | Passed | Exceptions | Unattempted | Model requests | Known USD subtotal | Unknown-cost requests |",
    "|---|---:|---:|---:|---:|---:|---:|---:|" ]
for arm,a in arms.items():
    lines.append(f"| {arm} | {a['validScoredTaskCount']} | {a['passed']} | {a['scoringOrGenerationExceptions']} | {a['unattemptedTaskCount']} | {a['modelCalls']} | {a['knownCostSubtotalUsd']} | {a['unknownCostCount']} |")
lines.extend([f"Known recorded cost subtotal: **${summary['knownCostSubtotalUsd']}**, including {summary['interfaceDiagnosticCalls']} separate interface diagnostics costing ${summary['interfaceDiagnosticKnownCostUsd']}. Diagnostics do not enter experiment scores. {summary['unknownCostCount']} requests have unknown billing with conservative estimated upper bound ${summary['unknownCostEstimatedUpperBoundUsd']}. This estimate is not an invoice. Shared account/key balance changes also include other benches and are not used as this experiment's cost.",
    "Official ClassEval v1.0.0 commit 90825141e640418ae6dc8257397345ee3ac36cbc; 100 fixed public prompts with official imports. Real model context excludes tests and reference solutions. Scoring uses pinned image sha256:45bd04b2941a81856945b5e46cff8ba2ae5111ec7ead633b12f5c89ab6989b56, five seconds per official test class, and complete-class success requiring all groups to pass.",
    f"Both arms retain DeepSeek V4.1 Flash / high, temperature 0, max_tokens 16384 and no provider fallback. Baseline remains DigitalOcean; the user authorized {summary['objrunProvider']} for ObjRun. Any comparison must disclose this provider difference. ObjRun uses the frozen native machine / declare / tasks / verify / submit / finalCandidate, c5 / {summary['objrunSolveSeconds']} seconds / 12 units / 4 branches, with clipped official-test feedback. This differs from the baseline single-response protocol. All valid ObjRun candidates are matched to original submit calls before their native task deadlines.",
    f"Total shared task concurrency and grader concurrency are 8. No per-task dollar cap is configured. Native deadlines, finite retries and actual account/key availability remain. Baseline candidates and scoring are never regenerated when resuming. Historical attempts, canceled calls and all unknown costs remain in the ledger."])
if config.get('exceptionRecovery'):
    policy=config['exceptionRecovery']
    lines.append(f"The user additionally authorized a 2400-second budget and one extra attempt (maximum three total) only for these seven still-invalid tasks: {', '.join(policy['taskIds'])}. All other ObjRun tasks retain 1200 seconds. Prior failed attempts and all valid results are preserved; this selective recovery condition must accompany reported comparisons. Authorization: exception-timeout-amendment.json.")
if trial:
    lines.append(f"The retained fourth ClassEval_0 attempt used Fireworks under the original 600-second budget: {trial['successfulProviderResponses']} successful real responses, {len(trial['officialVerifyFeedback'])} valid verify decisions, {trial['submitBeforeDeadlineCount']} submit calls before deadline. Its last in-flight request was canceled at the task deadline; verify arguments were not promoted to final candidates.")
if amendment:
    lines.append("The user explicitly approved changing only the ObjRun solve limit from 600 to 1200 seconds and adding one canary attempt, for a maximum of five retained ClassEval_0 attempts. The 100 completed baseline results and the original four failed canaries remain intact. The amended time condition must be reported with any comparison; protocol-amendment.json records authorization and source archival.")
lines.append(f"Last recorded runner stage: {status['stage']}; active entries at that snapshot: {len(status.get('active',[]))}. " + ("Both full arms are complete; the follow-up should be disabled after final verification." if complete else "Both full arms are not complete; the existing follow-up remains enabled and reports only completion, important failure or required user action."))
lines.append("Verification: source pins, fixed task IDs and prompt hashes, official controls, all valid final candidates and scoring hashes, native submit provenance, real provider/model receipts, complete durable dispatch receipts and all known/unknown fees. Full per-task index: verified-summary.json; candidates and grades: tasks/ and results/.")
report='\n\n'.join(lines)+'\n'
(OUT/('FINAL-RESULTS.md' if complete else 'PARTIAL-RESULTS.md')).write_text(report,encoding='utf8')
running=OUT/'RUNNING.md';text=running.read_text(encoding='utf8');marker='\n## Latest verified outcome\n'
text=text.split(marker)[0]
text+=marker+f"\nBaseline: {base['passed']}/100 passed with all 100 final candidates verified. ObjRun: {obj['validScoredTaskCount']}/100 valid tasks, {obj['passed']} passed and {obj['unattemptedTaskCount']} unattempted at verification. ObjRun solve limit: {summary['objrunSolveSeconds']} seconds. Both experiments complete: {complete}. Known USD subtotal: {summary['knownCostSubtotalUsd']}; unknown-cost requests: {summary['unknownCostCount']}. Current state is in status.json. See verified-summary.json and {'FINAL-RESULTS.md' if complete else 'PARTIAL-RESULTS.md'}.\n"
running.write_text(text,encoding='utf8')
print(json.dumps({k:v for k,v in summary.items() if k not in ['taskResults','unknownCostReceipts']},indent=2))
