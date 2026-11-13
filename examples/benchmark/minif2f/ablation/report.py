"""Verify saved requests, feedback, scores and cost, then export complete small artifacts."""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import tarfile
import time
from lean_worker import digest, save
from sequence import check_messages

def finish(root, archive=False):
    root = Path(root).resolve(); out = root / 'outputs'
    cfg = json.loads((root / 'package/experiment.json').read_text())
    catalog = json.loads((root / 'data/public-pilot.json').read_text())
    state = json.loads((out / 'status.json').read_text())
    if state['stage'] not in ('complete', 'complete_with_exceptions'): raise RuntimeError('ExperimentNotTerminal')
    errors, records, costs, task_rows, all_receipts = [], [], {}, [], []
    pins = json.loads((out / 'source-pins.json').read_text())
    for path, expected in pins.items():
        if digest((root / path).read_bytes()) != expected: errors.append('SourceChanged:' + path)
    controls = json.loads((out / 'controls.json').read_text())
    if not controls['allPassed']: errors.append('ControlsFailed')
    for arm in cfg['arms']:
        for task in catalog:
            group = arm + '/' + task['name']; base = out / 'tasks' / group
            result_path = out / 'results' / arm / (task['name'] + '.json')
            if not result_path.exists(): errors.append('MissingResult:' + group); continue
            result = json.loads(result_path.read_text()); records.append(result)
            samples = json.loads((base / 'samples.json').read_text()) if (base / 'samples.json').exists() else []
            if len(samples) > cfg['maxAttempts']: errors.append('AttemptLimit:' + group)
            if result['id'] != task['id'] or result['promptSha256'] != digest(task['prompt']): errors.append('TaskIdentity:' + group)
            if result['sampleCount'] != len(samples): errors.append('SampleCount:' + group)
            for index, sample in enumerate(samples):
                if sample['index'] != index: errors.append('AttemptSequence:' + group)
                if sample['candidateSha256'] != digest(sample['answer']) or sample['grade'].get('candidateSha256') != digest(sample['answer']): errors.append('CandidateBinding:' + group)
                request = json.loads((root / sample['callDirectory'] / 'request.json').read_text())
                try: check_messages(request['messages'], cfg['systemPrompt'], task, arm, samples[:index])
                except Exception: errors.append('InformationIsolation:' + group + ':' + str(index))
                if index + 1 < len(samples) and (sample['grade']['passed'] or not sample['grade']['valid']): errors.append('InvalidContinuation:' + group)
                if sample['grade']['valid']:
                    original = json.loads((root / sample['grade']['gradeDirectory'] / 'grade.json').read_text())
                    if any(original[k] != sample['grade'][k] for k in ['valid', 'passed', 'candidateSha256', 'identity']): errors.append('GradeBinding:' + group)
            if samples and result['candidateSha256'] != samples[-1]['candidateSha256']: errors.append('FinalCandidateBinding:' + group)
            if not result['grade']['valid']: errors.append('InfrastructureException:' + group)
            receipts = []
            call_base = out / 'calls' / group
            for dispatch_path in call_base.rglob('dispatch.json') if call_base.exists() else []:
                directory = dispatch_path.parent
                if not (directory / 'receipt.json').exists(): errors.append('UnresolvedDispatch:' + str(directory.relative_to(root))); continue
                receipt = json.loads((directory / 'receipt.json').read_text()); receipts.append(receipt); all_receipts.append(receipt)
                request_raw = (directory / 'request.json').read_bytes(); request = json.loads(request_raw)
                index = int(directory.parent.name.removeprefix('attempt-'))
                retry = int(directory.name.removeprefix('transport-'))
                if not (0 <= index < cfg['maxAttempts'] and 0 <= retry < cfg.get('transportRetryOffset', 0) + cfg['maxTransportAttempts']): errors.append('TransportAttemptLimit:' + group)
                try: check_messages(request['messages'], cfg['systemPrompt'], task, arm, samples[:index])
                except Exception: errors.append('DispatchInformationIsolation:' + group + ':' + str(index))
                if digest(request_raw) != receipt['requestSha256']: errors.append('RequestHash:' + group)
                if request.get('tools') or request['provider']['only'] != [cfg['providerTag']] or request['provider']['allow_fallbacks'] is not False: errors.append('RouteOrTools:' + group)
                if request['model'] != cfg['model'] or request['temperature'] != cfg['temperature'] or request['max_tokens'] != cfg['maxTokens'] or request['reasoning']['effort'] != cfg['reasoningEffort']: errors.append('WireParameters:' + group)
                if receipt['success']:
                    response = json.loads((directory / 'response.json').read_text())
                    if response['provider'] != cfg['provider'] or response['model'] != cfg['model'] or response['id'] != receipt['generationId']: errors.append('ActualModelRoute:' + group)
            spent = sum(r['actualCostUsd'] if r['actualCostUsd'] is not None else r['reservationUsd'] for r in receipts)
            if spent > cfg['perTaskDollarCap'] + 1e-9: errors.append('TaskDollarCap:' + group)
            costs[group] = {'actualCostUsd': sum(r['actualCostUsd'] or 0 for r in receipts), 'unknownCostCount': sum(r['unknownCost'] for r in receipts), 'budgetChargedUsd': spent, 'modelRequests': len(receipts)}
            hashes = [s['candidateSha256'] for s in samples]
            task_rows.append({'arm': arm, 'id': task['id'], 'stratum': task['stratum'], 'valid': result['grade']['valid'], 'passed': result['grade']['passed'],
                              'firstAttemptPassed': bool(samples and samples[0]['grade']['valid'] and samples[0]['grade']['passed']),
                              'samples': len(samples), 'duplicateCandidates': len(hashes) - len(set(hashes)), 'seconds': result['seconds'], 'stoppingReason': result['stoppingReason'], **costs[group]})
    total = sum(v['budgetChargedUsd'] for v in costs.values())
    if total > cfg['batchDollarCap'] + 1e-9: errors.append('BatchDollarCap')
    if len(records) != 24: errors.append('Expected24ArmTaskRecords')
    summary = {'runId': cfg['runId'], 'scope': cfg['scope'], 'model': cfg['model'], 'providerTag': cfg['providerTag'],
               'taskCount': 12, 'records': len(records), 'actualCostUsd': sum(v['actualCostUsd'] for v in costs.values()),
               'unknownCostCount': sum(v['unknownCostCount'] for v in costs.values()), 'budgetChargedUsd': total,
               'modelRequests': len(all_receipts), 'finishReasonLength': sum(r['finishReason'] == 'length' for r in all_receipts),
               'transportFailures': sum(not r['success'] for r in all_receipts),
               'upstream429': sum(r['httpStatus'] == 429 for r in all_receipts),
               'promptTokens': sum(r['usage'].get('prompt_tokens', 0) for r in all_receipts),
               'completionTokens': sum(r['usage'].get('completion_tokens', 0) for r in all_receipts),
               'arms': {a: {'records': sum(r['arm'] == a for r in task_rows), 'valid': sum(r['arm'] == a and r['valid'] for r in task_rows),
                            'passed': sum(r['arm'] == a and r['passed'] and r['valid'] for r in task_rows),
                            'infrastructureExceptions': sum(r['arm'] == a and not r['valid'] for r in task_rows),
                            'firstAttemptPassed': sum(r['arm'] == a and r['firstAttemptPassed'] for r in task_rows),
                            'samples': sum(r['samples'] for r in task_rows if r['arm'] == a),
                            'actualCostUsd': sum(r['actualCostUsd'] for r in task_rows if r['arm'] == a),
                            'duplicateCandidates': sum(r['duplicateCandidates'] for r in task_rows if r['arm'] == a)} for a in cfg['arms']},
               'formal244Launched': False, 'rows': task_rows}
    audit = {'allPassed': not errors, 'errors': errors, 'checks': ['source identities', '12 valid tasks per arm', 'max5 and first-correct stop', 'actual message isolation', 'strict binary feedback', 'candidate and grade identity', 'actual wire route', 'all request receipts', 'per-task and batch cost ceilings'],
             'controlsPassed': controls['allPassed'], 'completeRecords': len(records), 'formal244Launched': False}
    save(out / 'summary.json', summary); save(out / 'audit.json', audit)
    with (out / 'results.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(task_rows[0]) if task_rows else ['arm', 'id']); writer.writeheader(); writer.writerows(task_rows)
    independent, binary = summary['arms']['independent'], summary['arms']['binary']
    lineage_path = out / 'recovery-lineage.json'
    recovery_note = ''
    if lineage_path.exists():
        lineage = json.loads(lineage_path.read_text())
        recovery_note = f"This report combines the initial batch with the sole engineering-recovery batch: {lineage['reusedValidResults']} valid terminal states reused and {len(lineage['retryGroups'])} interface anomalies recovered. Original candidates, five-round caps, original per-task deadlines, and all existing costs are retained. Concurrency is reduced to 1, request spacing is at least 10 seconds, and recovery permits at most three transports (indices 3–5), with no automatic new recovery batch after failure. Model, endpoint, temperature, reasoning level, token cap, and feedback protocol remain identical.\n\n"
    text = f"""# miniF2F valid: 12-task, two-arm pilot results

This run covers only 12 development tasks, using OpenRouter `{cfg['model']}`, `{cfg['providerTag']}`, medium, temperature=0, 16384 tokens, and at most five rounds per task. The formal 244-task test run has not started.

{recovery_note}| Arm | Valid grades | Passed | Generation rounds | Actual cost USD |
| --- | ---: | ---: | ---: | ---: |
| Independent sampling | {independent['valid']}/12 | {independent['passed']}/12 | {independent['samples']} | {independent['actualCostUsd']:.9f} |
| Binary feedback | {binary['valid']}/12 | {binary['passed']}/12 | {binary['samples']} | {binary['actualCostUsd']:.9f} |

Independent first-round passes: {independent['firstAttemptPassed']}/12. Both arms total {summary['modelRequests']} requests, ${summary['actualCostUsd']:.9f} known actual cost, and {summary['unknownCostCount']} unknown charges. Budget exposure including conservative reservations is ${summary['budgetChargedUsd']:.9f}. Length-truncated receipts: {summary['finishReasonLength']}.

Interface failures: {summary['transportFailures']}, including {summary['upstream429']} HTTP429 responses. Terminal infrastructure anomalies: independent {independent['infrastructureExceptions']}, binary {binary['infrastructureExceptions']}; these do not count as proof failures.

Engineering audit: {'passed' if audit['allPassed'] else 'some checks failed'}. Errors: {json.dumps(errors, ensure_ascii=False)}. Model-free controls: {len(controls['checks'])}, all passed: {controls['allPassed']}. The complete archive retains raw API requests/responses, round-level candidates, raw Lean output, grading identities/environments, cost receipts, and source code.

Each independent round includes only the fixed system prompt and public task. Binary feedback adds only prior complete answers and passed/failed; infrastructure anomalies never enter failed history. Lean runs in fresh network, PID, mount, and user namespaces, with a read-only toolchain, independent temporary filesystem, and no inherited credentials. The pilot task list was fixed before generation; 12 tasks do not represent the full test set.

Per-task results: results.csv; audit: audit.json; environment: environment.json; actual controls: controls.json. A formal run requires a separate user decision based on pilot results; once started, follow up every 15 minutes and retrieve/verify results on completion.
"""
    (out / 'REPORT.md').write_text(text)
    if archive:
        target = out / 'results.tar.gz'; integrity = out / 'archive-integrity.json'
        if target.exists():
            saved = json.loads(integrity.read_text())
            with target.open('rb') as stream: assert hashlib.file_digest(stream, 'sha256').hexdigest() == saved['sha256']
            return summary
        paths = [p for d in ['package', 'vendor', 'data', 'outputs'] for p in (root / d).rglob('*') if p.is_file() and p.name not in ['results.tar.gz', 'archive-integrity.json'] and not p.name.endswith('.tmp')]
        for name in ['dependency-bundle.json', 'package.tar.gz']:
            if (root / name).exists(): paths.append(root / name)
        with tarfile.open(target, 'w:gz') as tar:
            for path in paths: tar.add(path, arcname=str(path.relative_to(root)))
        with target.open('rb') as stream: checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        save(integrity, {'archive': 'results.tar.gz', 'sha256': checksum, 'bytes': target.stat().st_size, 'files': len(paths),
                         'completeExperimentLogs': True, 'dependencyBundleSeparate': json.loads((root / 'dependency-bundle.json').read_text())['sha256']})
    return summary
