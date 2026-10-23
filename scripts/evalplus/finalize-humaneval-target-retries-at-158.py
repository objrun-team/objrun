"""Finalize the existing retry batch after the user's revised stop target.

This command never starts, repeats, grades, or cancels a model request.
"""
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HE = ROOT / 'docs/evalplus-20261012/humaneval'
SPEC = importlib.util.spec_from_file_location(
    'original_retry_monitor',
    ROOT / 'scripts/evalplus/supervise-humaneval-target-retries.py',
)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)
OUT = monitor.OUT


def finalize():
    monitor.check_sources()
    for item in monitor.read(HE / 'objrun-retry-user-stop-source-pins.json')['files']:
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('StopSourceChanged:' + item['path'])
    control = monitor.read(OUT / 'control/user-stop-at-158.json')
    state = monitor.read(OUT / 'effective-state.json')
    initial = monitor.read(OUT / 'initial-state.json')
    cfg = monitor.read(HE / 'objrun-retry-to-target-v1-config.json')
    value = monitor.report(False)
    if value['processes'] or value['pendingRequests']:
        print(json.dumps({'stage': 'draining_user_target',
                          'passed': value['passed'],
                          'processes': value['processes'],
                          'pendingRequests': value['pendingRequests']}, indent=2))
        return 2
    fixed = monitor.read(HE / 'task-ids.json')
    assert state['fixedIds'] == fixed
    assert set(state['cases']) == set(fixed) and len(fixed) == len(set(fixed)) == 164
    assert 158 <= value['passed'] <= control['maxAlreadyInFlightAcceptedPassed'] == 159
    assert state['targetPassed'] == control['targetPassed'] == 158
    assert initial['passed'] == cfg['originalPassed'] == 152

    original_evidence = {r['officialId']: r for r in monitor.read(
        HE / 'diagnosis/final-native-submissions.json')['rows']}
    original_rows = []
    for tid in fixed:
        case = state['cases'][tid]
        original = monitor.read(case['originalResultPath'])
        evidence = original_evidence[tid]
        assert original['officialId'] == tid
        assert original['grade'] == evidence['grade']
        assert hashlib.sha256(original['answer'].encode()).hexdigest() == evidence['answerSha256']
        assert case['originalResultPath'] == initial['cases'][tid]['originalResultPath']
        if initial['cases'][tid]['passed']:
            assert case['passed'] and case['resultPath'] == initial['cases'][tid]['resultPath']
        if case['passed']:
            monitor.native_pass(case['resultPath'])
        original_rows.append(original)
    assert sum(r['grade']['valid'] for r in original_rows) == 164
    assert sum(r['grade']['passed'] for r in original_rows) == 152

    rounds = []
    prior_passed = {tid for tid in fixed if initial['cases'][tid]['passed']}
    for folder in sorted((OUT / 'rounds').glob('round-*')):
        number = int(folder.name.split('-')[-1])
        assert number <= control['round'] <= cfg['maxRounds'] == 10
        status = monitor.read(folder / 'status.json')
        if status['stage'] != 'complete' or status.get('active'):
            raise RuntimeError('RoundNotCompletelyDrained:' + folder.name)
        selected = monitor.read(folder / 'selected-task-ids.json')
        assert len(selected) == len(set(selected))
        assert set(selected).issubset(cfg['initialFailedIds'])
        assert not set(selected).intersection(prior_passed)
        rows = [monitor.read(p) for p in (folder / 'results/objrun').glob('*.json')]
        ids = [r['officialId'] for r in rows]
        assert len(ids) == len(set(ids)) and set(ids).issubset(selected)
        newly_passed = []
        for row in rows:
            assert row['round'] == number
            if row['grade'].get('valid') and row['grade'].get('passed'):
                assert row['candidateHow'] == 'submitted' and not row.get('modelProtocolFailure')
                if row['officialId'] not in prior_passed:
                    newly_passed.append(row['officialId'])
                    prior_passed.add(row['officialId'])
        rounds.append({'round': number, 'selectedIds': selected,
                       'completed': len(rows), 'valid': sum(r['grade']['valid'] for r in rows),
                       'passed': sum(r['grade']['passed'] for r in rows),
                       'newPassedIds': newly_passed,
                       'cumulativePassed': len(prior_passed),
                       'remainingFailedIds': [tid for tid in fixed if tid not in prior_passed],
                       'modelProtocolFailures': sum(bool(r.get('modelProtocolFailure')) for r in rows),
                       'interfaceExceptions': sum(not r['grade']['valid'] for r in rows),
                       'elapsedSeconds': status['elapsedSeconds']})
    assert prior_passed == {tid for tid in fixed if state['cases'][tid]['passed']}

    request_count = 0
    unknown_without_bound = 0
    for receipt_path in (OUT / 'rounds').rglob('receipt.json'):
        request_count += 1
        receipt = monitor.read(receipt_path)
        dispatch = monitor.read(receipt_path.parent / 'dispatch.json')
        request_path = receipt_path.parent / 'request.json'
        request = monitor.read(request_path)
        payload = json.dumps(request, ensure_ascii=False, separators=(',', ':'))
        assert hashlib.sha256(payload.encode()).hexdigest() == dispatch['requestSha256']
        assert receipt['requestSha256'] == dispatch['requestSha256']
        assert request['max_tokens'] == 16384 and request['temperature'] == 0
        assert request['reasoning']['effort'] == 'high'
        assert request['provider']['allow_fallbacks'] is False
        short = receipt_path.parts[receipt_path.parts.index('objrun') + 1]
        provider = cfg['providers'][short.replace('-', '/')]
        assert request['provider']['only'] == [provider.lower()]
        if receipt.get('unknownCost') or receipt.get('actualCostUsd') is None:
            unknown_without_bound += receipt.get('upperBoundUsd') is None
    assert request_count == value['modelCalls'] == value['receipts']
    value.update({'atUtc': monitor.now(), 'stage': 'complete',
                  'stopReason': 'user_revised_target_reached',
                  'originalUpperTargetPassed': 160, 'upperTargetPassed': 158,
                  'acceptedInFlightUpperPassed': 159, 'targetReached': True,
                  'userStopTargetPassed': 158, 'userStopTargetReached': True,
                  'rounds': rounds, 'allCountedPassesNativeVerified': value['passed'],
                  'effectiveValidTaskCount': 164,
                  'originalCandidateAndGradeEvidenceUnchanged': True,
                  'originalPassedCasesPreserved': 152,
                  'allDispatchesHaveReceipts': True, 'allOwnedProcessesExited': True,
                  'retryUnknownCostsWithoutUpperBound': unknown_without_bound,
                  'sourceChecksPassed': True,
                  'stopControlPath': str(OUT / 'control/user-stop-at-158.json')})
    monitor.save(OUT / 'FINAL-RETRY-REPORT.json', value)
    lines = ['HumanEval+ ObjRun cumulative retry final status', '',
             f"The user revised the stop target to 158 or 159. Stopped at {value['passed']}/164 ({value['accuracy']:.5%}) after {len(rounds)} rounds; no further retries are scheduled.",
             'Original single-run ObjRun: 152/164. This cumulative retry score is a different protocol and does not replace it.', '',
             'Newly passed: ' + ', '.join(value['newPassedIds']),
             'Still failed: ' + ', '.join(value['remainingFailedIds']), '',
             '| Round | Task attempts | New passes | Cumulative passed | Seconds |',
             '| --- | ---: | --- | ---: | ---: |']
    for row in rounds:
        lines.append(f"| {row['round']} | {row['completed']} | {', '.join(row['newPassedIds']) or 'none'} | {row['cumulativePassed']}/164 | {row['elapsedSeconds']:.3f} |")
    lines += ['',
              f"Retry time: {value['cumulativeRoundSeconds']:.3f} seconds. {value['attempts']} task attempts, {value['modelCalls']} requests/receipts, no pending requests. Protocol repairs: {value['protocolRepairCalls']}.",
              f"New retry known cost: ${value['retryKnownCostUsd']:.9f}; unknown {value['retryUnknownCostCount']}, upper bound ${value['retryUnknownCostUpperBoundUsd']:.7f}.",
              f"Including original ObjRun: known ${value['totalKnownCostUsd']:.9f}; unknown {value['totalUnknownCostCount']}, upper bound ${value['totalUnknownCostUpperBoundUsd']:.7f}. Unknown costs are not treated as zero.", '',
              'Fixed denominator 164; no duplicate cases; original 152 successes retained. Every counted pass matches completed native submit and full base+plus grading. Original candidate/grade evidence and frozen sources unchanged. Core and shared scoring unchanged.', '',
              'Per-task latest passing results: ' + str(OUT / 'effective-state.json'),
              'All calls, SQLite, traces and failed attempts: ' + str(OUT / 'rounds'),
              'Original report retained: ' + str(HE / 'FINAL-RESULTS.md'),
              'Detailed report: ' + str(OUT / 'FINAL-RETRY-REPORT.json')]
    (OUT / 'FINAL-RETRY-REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    monitor.save(OUT / 'progress-checkpoint.json', value)
    monitor.save(OUT / 'status.json', {'atUtc': value['atUtc'], 'pid': None,
                                      'stage': 'complete', 'round': len(rounds),
                                      'stopReason': value['stopReason'],
                                      'targetPassed': 158, 'passed': value['passed']})
    print(json.dumps(value, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(finalize())
