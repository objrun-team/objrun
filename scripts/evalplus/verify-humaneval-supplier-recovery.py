"""Report the fixed 164 tasks with explicit supplier-assisted invalid-task recovery.

Original valid results always win. This reads saved grades; it never grades,
generates candidates, or alters any original result or raw request ledger.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HE = ROOT / 'docs/evalplus-20261012/humaneval'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def valid(row):
    return row.get('grade', {}).get('valid') is True


def rows_at(out):
    result = {}
    for path in sorted((out / 'results/objrun').glob('*.json')):
        row = read(path)
        tid = row['officialId']
        if path.name != tid.replace('/', '-') + '.json' or tid in result:
            raise RuntimeError('DuplicateOrWrongResultIdentity: ' + str(path))
        result[tid] = (row, str(path))
    return result


def select_effective(expected, original, recovery, allowed):
    if len(expected) != 164 or len(set(expected)) != 164:
        raise RuntimeError('FixedDenominatorMustBe164UniqueTasks')
    if set(original) - set(expected) or set(recovery) - set(allowed):
        raise RuntimeError('UnexpectedTaskResult')
    selected = []
    for tid in expected:
        prior = original.get(tid)
        new = recovery.get(tid)
        if new and (not prior or valid(prior[0])):
            raise RuntimeError('RecoveryCannotReplacePriorValidOrUnverifiedTask: ' + tid)
        chosen, provider = (new, 'Fireworks') if new and valid(new[0]) else (prior, 'DigitalOcean')
        if chosen:
            row, path = chosen
            selected.append({'officialId': tid, 'provider': provider, 'resultPath': path,
                             'valid': valid(row), 'passed': valid(row) and row['grade'].get('passed') is True,
                             'candidateHow': row.get('candidateHow'),
                             'modelProtocolFailure': bool(row.get('modelProtocolFailure'))})
    return selected


def ledger(out):
    dispatches = list((out / 'calls').rglob('dispatch.json'))
    receipts = [read(p) for p in (out / 'calls').rglob('receipt.json')]
    unknown = [r for r in receipts if r.get('actualCostUsd') is None or r.get('unknownCost')]
    return {'dispatches': len(dispatches), 'receipts': len(receipts),
            'pendingRequests': [str(p.parent) for p in dispatches if not (p.parent / 'receipt.json').exists()],
            'knownCostUsd': sum(r['actualCostUsd'] for r in receipts if isinstance(r.get('actualCostUsd'), (int, float))),
            'unknownCostCount': len(unknown),
            'unknownCostUpperBoundUsd': sum(r.get('upperBoundUsd') or 0 for r in unknown),
            'unknownWithoutUpperBound': sum(r.get('upperBoundUsd') is None for r in unknown)}


def protocol_repairs(out):
    keys = set()
    uncorrelated = []
    for path in (out / 'tasks').rglob('submit-response-attempts.json'):
        for event in read(path):
            if event.get('protocolAttempt') != 1:
                continue
            if not event.get('generationId'):
                uncorrelated.append(str(path))
            else:
                keys.add((event.get('requestHash'), event['generationId']))
    return {'protocolRepairCalls': len(keys), 'protocolEventsWithoutGenerationId': sorted(set(uncorrelated))}


def elapsed(out):
    runs = {}
    for path in [*sorted((out / 'recovery').glob('*summary.json')), out / 'status.json']:
        if not path.exists():
            continue
        value = read(path)
        status = value.get('status', value)
        started = status.get('startedAtUtc')
        if started and isinstance(status.get('elapsedSeconds'), (int, float)):
            runs[started] = max(runs.get(started, 0), status['elapsedSeconds'])
    return sum(runs.values())


def process_snapshot(script, out):
    spec = importlib.util.spec_from_file_location('recovery_identity_' + out.parent.name, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.process_snapshot(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--checkpoint', action='store_true')
    args = ap.parse_args()
    original_out = HE / 'objrun-adapter-v1/full'
    recovery_out = HE / 'objrun-fireworks-v1/recovery'
    cfg = read(HE / 'objrun-fireworks-v1-config.json')
    expected = read(HE / 'task-ids.json')
    original = rows_at(original_out)
    active_original_count = len(original)
    # Archived invalid records supply display coverage while a task is in flight.
    snapshot = original_out / 'recovery/first-pass-summary.json'
    if snapshot.exists():
        for row in read(snapshot)['resultRows']:
            original.setdefault(row['officialId'], (row, str(snapshot)))
    recovery = rows_at(recovery_out)
    selected = select_effective(expected, original, recovery, cfg['recoveryIds'])
    selection_path = recovery_out / 'selected-task-ids.json'
    recovery_ids = read(selection_path) if selection_path.exists() else []
    if len(recovery_ids) != len(set(recovery_ids)) or set(recovery_ids) - set(cfg['recoveryIds']):
        raise RuntimeError('UnexpectedRecoverySelection')
    if set(recovery) - set(recovery_ids):
        raise RuntimeError('ResultOutsidePersistedRecoverySelection')
    original_ledger, recovery_ledger = ledger(original_out), ledger(recovery_out)
    known = original_ledger['knownCostUsd'] + recovery_ledger['knownCostUsd']
    unknown = original_ledger['unknownCostCount'] + recovery_ledger['unknownCostCount']
    upper = original_ledger['unknownCostUpperBoundUsd'] + recovery_ledger['unknownCostUpperBoundUsd']
    preservation = read(HE / 'objrun-fireworks-v1-original-valid-hashes.json')
    changed = [p['path'] for p in preservation['files'] if not Path(p['path']).exists() or hashlib.sha256(Path(p['path']).read_bytes()).hexdigest() != p['sha256']]
    pins_checked = {}
    for name in ['../source-pins.json', 'objrun-adapter-v1-source-pins.json', 'objrun-validity-recovery-source-pins.json', 'objrun-validity-recovery-v2-source-pins.json', 'objrun-fireworks-v1-source-pins.json']:
        pins = read(HE / name)['files']
        for item in pins:
            if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('FrozenSourceChanged: ' + item['path'])
        pins_checked[name] = len(pins)
    validity = sum(r['valid'] for r in selected)
    passed = sum(r['passed'] for r in selected)
    pending = original_ledger['pendingRequests'] + recovery_ledger['pendingRequests']
    old_checkpoint = recovery_out / 'combined-progress-checkpoint.json'
    previous = read(old_checkpoint) if old_checkpoint.exists() else {'valid': preservation['validCount']}
    old_protocol, new_protocol = protocol_repairs(original_out), protocol_repairs(recovery_out)
    report = {'atUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'label': 'ObjRun with supplier-assisted infrastructure recovery',
              'completed': len(selected), 'total': 164, 'valid': validity, 'passed': passed,
              'newValidSinceLastCheck': validity - previous['valid'],
              'temporaryPassRate': passed / validity if validity else None,
              'fixedDenominatorPassRate': passed / 164, 'remainingInvalid': [r['officialId'] for r in selected if not r['valid']],
              'activeOriginalRecords': active_original_count,
              'recoverySelected': recovery_ids, 'recoveryCompleted': len(recovery),
              'recoveryValid': sum(valid(r[0]) for r in recovery.values()),
              'recoveredByFireworks': [r['officialId'] for r in selected if r['provider'] == 'Fireworks'],
              'originalValidResultsPreserved': not changed, 'changedOriginalValidResults': changed,
              'modelProtocolFailures': sum(r['modelProtocolFailure'] for r in selected),
              'protocolRepairCalls': old_protocol['protocolRepairCalls'] + new_protocol['protocolRepairCalls'],
              'protocolEventsWithoutGenerationId': old_protocol['protocolEventsWithoutGenerationId'] + new_protocol['protocolEventsWithoutGenerationId'],
              'cumulativeRunnerSeconds': elapsed(original_out) + elapsed(recovery_out),
              'knownCostUsd': known, 'unknownCostCount': unknown, 'unknownCostUpperBoundUsd': upper,
              'unknownWithoutUpperBound': original_ledger['unknownWithoutUpperBound'] + recovery_ledger['unknownWithoutUpperBound'],
              'pendingRequests': pending, 'ledgers': {'DigitalOcean': original_ledger, 'Fireworks': recovery_ledger},
              'processes': {'DigitalOcean': process_snapshot(ROOT / 'scripts/evalplus/prepare-humaneval-objrun-recovery-v2.py', original_out),
                            'Fireworks': process_snapshot(ROOT / 'scripts/evalplus/prepare-humaneval-objrun-fireworks-recovery.py', recovery_out)},
              'sourcePinsChecked': pins_checked, 'provenance': selected, 'dockerForbidden': True}
    report['allTasksValidAndNoPending'] = len(selected) == 164 and validity == 164 and not pending and not changed
    if args.checkpoint:
        recovery_out.mkdir(parents=True, exist_ok=True)
        old_checkpoint.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        with (recovery_out / 'combined-progress-history.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({k: v for k, v in report.items() if k != 'provenance'}) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'provenance'}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
