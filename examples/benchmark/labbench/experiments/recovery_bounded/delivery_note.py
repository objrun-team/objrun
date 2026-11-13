"""Build the local human-readable index and independent-verification supplement."""
from pathlib import Path
import datetime
import hashlib
import json
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recovery'))
from ops_recovery import LOCAL, ORIGINAL_LOCAL
from core import read, save, sha


def link(path, label):
    return f'[{label}]({Path(path).resolve().as_posix()})'


def main():
    delivery = read(LOCAL / 'DELIVERY.json')
    proof = read(LOCAL / 'LOCAL_VERIFICATION.json')
    assert delivery['delivered'] and delivery['verified'] and delivery['resolvedCount'] == 8 and proof['allPassed']
    result = read(LOCAL / 'INDEPENDENT_SUMMARY.json')
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    lines = ['# LAB-Bench final delivery', '', f'Full retrieval and local verification completed at {now} (Asia/Shanghai). The original experiment passed 82227 local checks and this recovery batch passed 18123. Local/server SHA256 matches for both complete archives. The 15-minute follow-up is paused, this batch’s dedicated SSH tunnel is closed, and the shared proxy is unchanged.', '', 'Final scoring follows the user-specified rule: count the final three timeouts as 0 within the 708-task denominator, preserving original solverValid, grade, answer, and actual submit. Timeout-default failures remain distinct from valid answers that failed; no answers or submissions were fabricated.', '', '|Task set|Single-shot baseline|Full ObjRun|Full-method timeout-default failures|', '|---|---:|---:|---:|']
    for category, arms in list(result['finalScored']['categories'].items()) + [('Total', result['finalScored']['arms'])]:
        a, b = arms['baseline'], arms['objrun']
        lines.append(f"|{category}|{a['passed']}/{a['tasks']}（{a['passRate']*100:.2f}%）|{b['passed']}/{b['tasks']}（{b['passRate']*100:.2f}%）|{b['timeoutDefaultFailures']}|")
    lines += ['', 'The single-shot arm has 708 actual valid records, 296 passes, and 412 failures, retaining the original 391 invalid-format outcomes. The full arm has 705 actual valid records, all passing, plus 3 timeout-default failures. Its 0 valid-but-failed outcomes must not be conflated with those 3 timeout-default failures.', '', '|Comparison view|baseline|ObjRun|', '|---|---|---|']
    for name, view in [('Original experiment, infrastructure unknowns retained', 'original'), ('After first-valid recovery, remaining unknowns retained', 'firstValidCompletedUnknown')]:
        a, b = result[view]['arms']['baseline'], result[view]['arms']['objrun']
        lines.append(f"|{name}|Passed {a['passed']}, unknown {a['unknown']}, accuracy bounds {a['accuracyBounds'][0]*100:.2f}%–{a['accuracyBounds'][1]*100:.2f}%|Passed {b['passed']}, unknown {b['unknown']}, accuracy bounds {b['accuracyBounds'][0]*100:.2f}%–{b['accuracyBounds'][1]*100:.2f}%|")
    lines += ['', '|Cost scope|Known actual USD|Transports with unknown cost|Transports|', '|---|---:|---:|---:|']
    for scope, groups in [('Original experiment', result['fees']['original']['byArm']), ('All recovery attempts, including failures', result['fees']['allRecoveryAttempts']['byArm']), ('Combined', result['fees']['combinedByArm'])]:
        lines.append(f"|{scope}|{sum(v['knownActualCostUsd'] for v in groups.values()):.9f}|{sum(v['unknownCostRequests'] for v in groups.values())}|{sum(v['requests'] for v in groups.values())}|")
    lines += ['', 'Unknown costs are not counted as 0. Costs follow actual OpenRouter usage.cost receipts; reservations are not actual charges. The original v2 ledger already includes v1, counted only once in the total.', '', f"Only the original 8 infrastructure-failure identities were retried, with {result['attemptCount']} independent attempts. Five identities obtained their first valid result; three ended at their final timeout. Total declared maximum solving budget for all recovery attempts is {result['additionalDeclaredSolveBudgetSeconds']} seconds (600 each, not actual elapsed time). After the bounded rule took effect, only 2 new attempts started, adding 1200 declared seconds; the clock for in-flight identity 9832’s sixth attempt was not reset.", '', '|Identity (ObjRun unless labeled baseline)|Total attempts|Final disposition|', '|---|---:|---|']
    for v in result['finalSources']:
        outcome = 'First actual valid result; stopped' if v['actualValid'] else 'Timeout-default failure; administratively scored 0'
        lines.append(f"|{v['arm']}/{v['id']}|{v['attemptCount']}|{outcome}|")
    lines += ['', '|Subtask|baseline|ObjRun|Timeout-default failures|', '|---|---:|---:|---:|']
    for name, arms in result['finalScored']['subtasks'].items():
        a, b = arms['baseline'], arms['objrun']
        lines.append(f"|{name}|{a['passed']}/{a['tasks']}|{b['passed']}/{b['tasks']}|{b['timeoutDefaultFailures']}|")
    pair = result['finalScored']['pairedScoredAll708']
    lines += ['', f"Under final zero-imputation scoring, the paired difference over 708 tasks is {pair['deltaObjrunMinusBaseline']*100:.2f} percentage points, with task-bootstrap 95% interval {pair['bootstrap95'][0]*100:.2f}–{pair['bootstrap95'][1]*100:.2f} points (5000 resamples, seed20261019). This describes this task sample only, excluding uncertainty from provider failures or repeated experiments. See SUMMARY.json for the actually valid paired subset.", '', 'Prespecified sensitivity analysis for identical-text-option task ded3f6ac-c54c-4626-86b4-cc607a44334f:']
    for arm, s in result['finalScored']['knownDuplicateChoiceSensitivity'].items():
        lines.append(f"- Overall excluding this task: {arm} {s['passed']}/{s['tasks']} ({s['passRate']*100:.2f}%).")
    rows = read(Path(delivery['recoveryArchive']['fullResults']) / 'FINAL_RECORDS.json')
    for arm in ['baseline', 'objrun']:
        items = [r for r in rows if r['arm'] == arm and r['category'] == 'SeqQA' and r['id'] != 'ded3f6ac-c54c-4626-86b4-cc607a44334f']
        passed = sum(bool(r['solverValid'] and r['grade'].get('valid') and r['grade'].get('passed')) for r in items)
        lines.append(f'- SeqQA excluding this task: {arm} {passed}/{len(items)} ({passed/len(items)*100:.2f}%).')
    lines += ['', 'Interpretation limits: full ObjRun receives ground-truth correctness feedback and can eliminate MCQ options sequentially. Its difference from single-shot reflects tools, feedback, budgets, and format constraints together, not directly improved biological reasoning without feedback. New attempts are infrastructure supplements with additional independent budgets; final scores also include user-specified administrative zeros for timeouts. A model-response alias is not an immutable version. The original 3 pilot recoveries used cumulative active-task clocks, with repair downtime recorded separately rather than a continuous 600-second wall clock; all new attempts in this batch receive a fresh 600 seconds.', '', 'Delivered files:', '']
    for name in ['RESULTS.md', 'ORIGINAL_RESULTS.csv', 'FIRST_VALID_UNKNOWN_RESULTS.csv', 'FINAL_RESULTS.csv', 'FINAL_PROVENANCE.json', 'SUMMARY.json', 'LOCAL_VERIFICATION.json', 'LOCAL_VERIFICATION_ADAPTER.json', 'DELIVERY.json']:
        lines.append('- ' + link(LOCAL / name, name))
    lines += ['- ' + link(delivery['originalArchive']['archive'], 'Complete original experiment archive'), '- ' + link(delivery['recoveryArchive']['archive'], 'Complete archive of all recoveries and final zero-imputation scoring'), '- ' + link(delivery['recoveryArchive']['fullResults'], 'All recovery logs, trajectories, candidates, SQLite, and raw request receipts'), '', 'Together the two archives contain the original experiment, every failed/successful recovery, generation IDs, usage, actual submit records, SQLite/task trees, error logs, source/dependencies/data, and recovery exceptions; original results are not overwritten. Windows local verification uses an adapter only to extract original pinned pure classification functions without importing Linux fcntl. Original reports and verification checks are unchanged item by item; adapter source and evidence are delivered too.', '', f"Original archive SHA256: {delivery['originalArchive']['sha256']}", f"Recovery archive SHA256: {delivery['recoveryArchive']['sha256']}"]
    (LOCAL / 'DELIVERY_REPORT.md').write_bytes(('\n'.join(lines) + '\n').encode())
    files = [LOCAL / name for name in ['DELIVERY_REPORT.md', 'RESULTS.md', 'ORIGINAL_RESULTS.csv', 'FIRST_VALID_UNKNOWN_RESULTS.csv', 'FINAL_RESULTS.csv', 'FINAL_PROVENANCE.json', 'SUMMARY.json', 'INDEPENDENT_SUMMARY.json', 'LOCAL_VERIFICATION.json', 'LOCAL_VERIFICATION_ADAPTER.json', 'DELIVERY.json', 'RUNNING.json', 'FOLLOWUP.json', 'proxy-stop.json', 'verification-process.json']]
    files += [Path(__file__), Path(__file__).with_name('verify_windows.py')]
    manifest = {p.name: sha(p) for p in files}
    save(LOCAL / 'local-delivery-inventory.json', manifest)
    archive = LOCAL / 'labbench-local-delivery-audit.zip'
    assert not archive.exists(), 'Do not overwrite an existing delivery supplement'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for p in files + [LOCAL / 'local-delivery-inventory.json']:
            zipped.write(p, p.name)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        for name, digest in manifest.items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest
    save(LOCAL / 'local-delivery-supplement.json', {'archive': str(archive), 'sha256': sha(archive), 'bytes': archive.stat().st_size, 'fileCount': len(manifest) + 1, 'localInventoryVerified': True})
    print(json.dumps({'report': str(LOCAL / 'DELIVERY_REPORT.md'), 'supplement': read(LOCAL / 'local-delivery-supplement.json')}))


if __name__ == '__main__':
    main()
