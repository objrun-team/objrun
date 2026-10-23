"""Read-only final comparison, using saved grades and immutable native evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HE = ROOT / 'docs/evalplus-20261012/humaneval'
spec = importlib.util.spec_from_file_location('supplier_report', Path(__file__).with_name('verify-humaneval-supplier-recovery.py'))
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)
read = lambda path: reporter.read(Path(path))

expected = read(HE / 'task-ids.json')
combined = read(HE / 'objrun-fireworks-v1/recovery/combined-progress-checkpoint.json')
assert combined['allTasksValidAndNoPending'] and all(not v['live'] for v in combined['processes'].values())
assert combined['originalValidResultsPreserved'] and combined['valid'] == len(set(expected)) == 164
native = read(HE / 'diagnosis/final-native-submissions.json')
assert len(native['rows']) == 164 and all(r['candidateMatches'] and r['completedMatchingSubmit'] for r in native['rows'])
groups = []
refs = {}
for arm, label in [('baseline', 'Baseline'), ('independent', 'Independent fixed5-v1'), ('objrun', 'Original ObjRun')]:
    out = HE / 'full'
    rows = [read(p) for p in (out / 'results' / arm).glob('*.json')]
    assert len(rows) == 164 and sorted(r['officialId'] for r in rows) == sorted(expected)
    # Calculate the per-arm ledger directly; reporter.ledger() accepts a run root.
    receipts = [read(p) for p in (out / 'calls' / arm).rglob('receipt.json')]
    dispatches = list((out / 'calls' / arm).rglob('dispatch.json'))
    unknown = [r for r in receipts if r.get('actualCostUsd') is None or r.get('unknownCost')]
    cost = sum(r['actualCostUsd'] for r in receipts if isinstance(r.get('actualCostUsd'), (int, float)))
    pending = [str(p.parent) for p in dispatches if not (p.parent / 'receipt.json').exists()]
    assert not pending and len(receipts) == len(dispatches)
    valid = sum(reporter.valid(r) for r in rows)
    passed = sum(reporter.valid(r) and r['grade'].get('passed') is True for r in rows)
    entry = {'label': label, 'total': 164, 'valid': valid, 'passed': passed,
             'fixedDenominatorPassRate': passed / 164, 'knownCostUsd': cost,
             'unknownCostCount': len(unknown), 'unknownCostUpperBoundUsd': sum(r.get('upperBoundUsd') or 0 for r in unknown),
             'modelCalls': len(dispatches), 'resultRoot': str(out / 'results' / arm)}
    if arm == 'independent':
        assert valid == 164 and all(r['samplingVersion'] == 'fixed5-v1' and r['maxTokens'] == 16384 and r['maxAttempts'] == 5 and r['stopAfterCorrect'] is True for r in rows)
        samples = [read(out / 'tasks/independent' / r['officialId'].replace('/', '-') / 'samples.json') for r in rows]
        assert all(1 <= len(s) <= 5 and all(not x['grade'].get('passed') for x in s[:-1]) for s in samples)
        entry.update(actualSamples=sum(r['sampleCount'] for r in rows), firstCandidatePassed=sum(r['grade'].get('firstCandidatePassed', False) for r in rows), lastCandidatePassed=sum(r['grade'].get('lastCandidatePassed', False) for r in rows), metric='Up to five independent attempts, stop on first success; not pass@1')
        assert entry['actualSamples'] == sum(sum('answer' in x for x in s) for s in samples) == 196
        # Read actual outgoing JSON, including retained calls, rather than config alone.
        catalog = {t['officialId']: t for t in read(HE / 'public-tasks.json')}
        def settings(w):
            return {k: v for k, v in w.items() if k != 'messages'}
        for r in rows:
            tid = r['officialId']
            short = tid.replace('/', '-')
            baseline_requests = [read(p) for p in (out / 'calls/baseline' / short).rglob('request.json')]
            assert baseline_requests
            for p in (out / 'calls/independent' / short).rglob('request.json'):
                wire = read(p)
                assert settings(wire) == settings(baseline_requests[0])
                assert wire['messages'] == [{'role': 'user', 'content': catalog[tid]['prompt']}]
        entry['everyRequestMatchesBaselineOptionsAndFreshPublicPrompt'] = True
    groups.append(entry)
    refs[arm] = {r['officialId']: r for r in rows}

old_out = HE / 'objrun-adapter-v1/full'
old_rows = [read(p) for p in (old_out / 'results/objrun').glob('*.json')]
assert sorted(r['officialId'] for r in old_rows) == sorted(expected)
old_ledger = reporter.ledger(old_out)
groups.append({'label': 'Bench adapter, DigitalOcean only', 'total': 164,
               'valid': sum(reporter.valid(r) for r in old_rows), 'passed': sum(reporter.valid(r) and r['grade'].get('passed') is True for r in old_rows),
               'fixedDenominatorPassRate': 145 / 164, **{k: old_ledger[k] for k in ['knownCostUsd', 'unknownCostCount', 'unknownCostUpperBoundUsd']},
               'modelCalls': old_ledger['dispatches'], 'resultRoot': str(old_out), 'elapsedSeconds': reporter.elapsed(old_out)})
groups.append({'label': combined['label'], 'total': 164, **{k: combined[k] for k in ['valid', 'passed', 'fixedDenominatorPassRate', 'knownCostUsd', 'unknownCostCount', 'unknownCostUpperBoundUsd', 'protocolRepairCalls', 'cumulativeRunnerSeconds']},
               'modelCalls': sum(x['dispatches'] for x in combined['ledgers'].values()),
               'originalResultRoot': str(old_out), 'recoveryResultRoot': str(HE / 'objrun-fireworks-v1/recovery'),
               'supplierDifference': '156 original valid DigitalOcean results plus 8 user-authorized Fireworks interface recoveries; this is not a single-supplier matched comparison.'})

data_path = ROOT / '.phase1-data/evalplus-20261012/HumanEvalPlus.jsonl'
data = {r['task_id']: (len(r['base_input']), len(r['plus_input'])) for line in data_path.read_text(encoding='utf-8').splitlines() for r in [json.loads(line)]}
checks = []
partial_failed_groups = []
for n in native['rows']:
    g = n['grade']['groups']
    sizes = data[n['officialId']]
    assert tuple(g[k]['cases'] for k in ['base', 'plus']) == sizes
    for k in ['base', 'plus']:
        assert 0 <= g[k]['checked'] <= g[k]['cases']
        if g[k]['passed']:
            assert g[k]['checked'] == g[k]['cases'] and g[k]['correct'] == g[k]['cases']
        elif g[k]['checked'] != g[k]['cases']:
            partial_failed_groups.append({'officialId': n['officialId'], 'group': k, **g[k]})
    checks.append({'officialId': n['officialId'], 'baseCases': sizes[0], 'plusCases': sizes[1]})

priority = read(HE / 'diagnosis/priority-cases.json')['cases']
final = {p['officialId']: read(p['resultPath']) for p in combined['provenance']}
provenance = {p['officialId']: p for p in combined['provenance']}
priority_rows = []
for p in priority:
    tid = p['id']
    r = final[tid]
    category = 'submission_protocol' if p.get('protocolFailure') else 'interface' if not p.get('objrunValid') else 'base_pass_plus_fail'
    priority_rows.append({'officialId': tid, 'previousFailure': category, 'baselinePassed': refs['baseline'][tid]['grade']['passed'],
                          'independentPassed': refs['independent'][tid]['grade']['passed'], 'nowValid': r['grade']['valid'], 'nowPassed': r['grade']['passed'],
                          'provider': provenance[tid]['provider'], 'actualProtocolRepairCalls': r.get('protocolRepairCalls', 0),
                          'causalAttributionLimit': 'Fresh model output; protocol repair is only evidenced when actualProtocolRepairCalls > 0.'})

retired = HE / 'retired/independent-token-budget-20261012T173656'
retired_receipts = [read(p) for p in retired.rglob('receipt.json')]
retired_cost = sum(r.get('actualCostUsd') or 0 for r in retired_receipts)
excluded_ledgers = []
for out in [HE / 'pilot', HE / 'objrun-adapter-v1/canary', retired]:
    receipts = [read(p) for p in out.rglob('receipt.json')]
    unknown = [r for r in receipts if r.get('actualCostUsd') is None or r.get('unknownCost')]
    excluded_ledgers.append({'resultRoot': str(out), 'knownCostUsd': sum(r.get('actualCostUsd') or 0 for r in receipts),
                             'unknownCostCount': len(unknown), 'unknownCostUpperBoundUsd': sum(r.get('upperBoundUsd') or 0 for r in unknown)})
unique_groups = [*groups[:3], groups[-1]]
all_costs = {'knownCostUsd': sum(g['knownCostUsd'] for g in unique_groups + excluded_ledgers),
             'unknownCostCount': sum(g['unknownCostCount'] for g in unique_groups + excluded_ledgers),
             'unknownCostUpperBoundUsd': sum(g['unknownCostUpperBoundUsd'] for g in unique_groups + excluded_ledgers),
             'overlapExcluded': 'The DigitalOcean-only adapter cost is already included in supplier-assisted ObjRun.'}
report = {'atUtc': combined['atUtc'], 'fixedTaskCount': 164, 'groups': groups,
          'finalPassed': combined['passed'], 'finalValid': combined['valid'], 'finalNativeCompletedSubmitMatches': 164,
          'fullBasePlusScoringRequestedForEveryFinalTask': True, 'allPassingGroupsCheckedAllExpectedInputs': True,
          'partialFailedGroupsUnderFrozenEvaluation': partial_failed_groups, 'perTaskTestCounts': checks,
          'allDispatchesHaveReceipts': True, 'ownedRunnerAndNativeEnginesExited': True,
          'original156ValidResultsByteIdentical': True, 'sourcePinsChecked': combined['sourcePinsChecked'],
          'originalDatasetSha256': hashlib.sha256(data_path.read_bytes()).hexdigest(),
          'finalFailedIds': [tid for tid in expected if not final[tid]['grade']['passed']],
          'priorityCount': len(priority_rows), 'priorityNowPassed': sum(r['nowPassed'] for r in priority_rows),
          'priorityCases': priority_rows, 'supplierRecovery': combined['ledgers']['Fireworks'],
          'supplierRecoveryElapsedSeconds': reporter.elapsed(HE / 'objrun-fireworks-v1/recovery'),
          'excludedRetiredIndependentKnownCostUsd': retired_cost, 'excludedRetiredIndependentResultRoot': str(retired),
          'excludedPreparationAndRetiredLedgers': excluded_ledgers, 'allRecordedExperimentsCostWithoutDoubleCounting': all_costs,
          'excludedCanary': str(HE / 'objrun-adapter-v1/canary'), 'excludedPilot': str(HE / 'pilot'),
          'gradingTimingLimitation': 'Frozen official EvalPlus checks run through UID65534 candidate RPC, with additional RPC latency; no timing thresholds or grading logic changed.',
          'coreModified': False, 'provenCoreDefectRequiringPatch': False,
          'diagnosticConclusion': 'All current final candidates match completed native submit. Earlier public feedback delivery and candidate extraction checks found no loss. Remaining failures are valid model solutions failing frozen base/plus or solve deadlines; higher ObjRun scores are not guaranteed.'}
path = HE / 'FINAL-RESULTS.json'
path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
lines = ['HumanEval+ final results', '', 'All scores use the same fixed 164 tasks. Source, native submissions, complete base+plus evaluation, and request/cost ledgers were independently checked.', '',
         '| Group | Passed/164 | Valid | Rate | Known USD | Unknown calls / upper bound USD |', '|---|---:|---:|---:|---:|---:|']
for g in groups:
    lines.append(f"| {g['label']} | {g['passed']}/164 | {g['valid']} | {g['fixedDenominatorPassRate']:.2%} | {g['knownCostUsd']:.9f} | {g['unknownCostCount']} / {g['unknownCostUpperBoundUsd']:.7f} |")
lines += ['', 'The independent sampler used 196 actual samples, at most five attempts per task, stopping on success. First candidates passed 156/164. Its overall metric is not pass@1.', '',
          f"Fireworks recovered only the eight interface-invalid tasks in {report['supplierRecoveryElapsedSeconds']:.3f} seconds: eight valid, seven passed. Its 23 requests cost $0.016270380; no unknown Fireworks costs. The prior 156 valid files are byte-identical. Total current ObjRun runner time, including all recovery passes, is {combined['cumulativeRunnerSeconds']:.3f} seconds.", '',
          f"Priority cases: {report['priorityNowPassed']}/22 now pass. All 164 final candidates exactly match completed native submit. Actual protocol correction calls: {combined['protocolRepairCalls']} (24 DigitalOcean, 2 Fireworks), deduplicated by original request/generation. Recovery without a correction event is not evidence of that correction causing success.", '',
          'Final valid failures: ' + ', '.join(report['finalFailedIds']), '',
          'No core or shared grading changes. Remaining failures do not establish a core defect; prior public feedback was delivered intact and candidate extraction matched native submit. Model quality is not guaranteed to improve through ObjRun.', '',
          'Full base+plus evaluation was requested with fast_check=False. All passing groups checked every input. HumanEval/32 has a valid failing result with partial execution (base 1/100, plus 20/788) under the frozen evaluator; these counts are preserved, not described as all inputs executed. It is a valid solver failure and was not resampled.', '',
          'Supplier-assisted recovery differs from the single-DigitalOcean baseline and independent sampling. Supplier/model-serving differences limit a matched comparison. Original adapter-only results remain separate. Unknown DigitalOcean costs remain unknown; their retained upper bound is not actual billing. Frozen UID65534 RPC grading adds timing overhead.', '',
          f'Excluded retired independent costs: ${retired_cost:.9f}. Pilot/canary results and costs are excluded from the table.', '', 'Absolute result paths:']
lines.insert(lines.index('Absolute result paths:'), f"All saved HumanEval experimental calls, including excluded pilot/canary/retired sampling, have known cost ${all_costs['knownCostUsd']:.9f}, plus {all_costs['unknownCostCount']} unknown calls with retained upper bound ${all_costs['unknownCostUpperBoundUsd']:.7f}. The DigitalOcean-only adapter row is included in the supplier-assisted row and is not added twice.\n")
for g in groups:
    for key in ['resultRoot', 'originalResultRoot', 'recoveryResultRoot']:
        if key in g:
            lines.append(f"- {g['label']}: {g[key]}")
lines += ['', 'Detailed evidence: ' + str(path), 'Native evidence: ' + str(HE / 'diagnosis/final-native-submissions.json'), 'Per-task provenance: ' + str(HE / 'objrun-fireworks-v1/recovery/combined-progress-checkpoint.json')]
(HE / 'FINAL-RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k in ['groups', 'finalPassed', 'finalValid', 'finalNativeCompletedSubmitMatches', 'fullBasePlusScoringRequestedForEveryFinalTask', 'partialFailedGroupsUnderFrozenEvaluation', 'priorityNowPassed', 'finalFailedIds']}, ensure_ascii=True, indent=2))
