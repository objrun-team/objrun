"""Independent local audit of raw records and the bounded scoring overlay."""
from pathlib import Path
import csv
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recovery'))
from ops_recovery import LOCAL, ORIGINAL_LOCAL, REPO
from core import read, save, sha, valid
from report_bounded import generate


def main():
    meta = read(LOCAL / 'retrieval.json')
    root = Path(meta['fullResults'])
    checks = []

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})

    check('archive-two-ends-SHA', meta['twoEndsSha256Verified'] and sha(meta['archive']) == meta['sha256'] and Path(meta['archive']).stat().st_size == meta['bytes'])
    check('trusted-latest-bounded-policy', (LOCAL / 'final-attempt-policy.json').read_bytes() == (root / 'control/final-attempt-policy.json').read_bytes() and read(root / 'control/final-attempt-policy.json')['supersedesUnlimitedRetries'])
    parent = read(ORIGINAL_LOCAL / 'retrieval.json')
    check('original-verified-archive-unchanged', read(ORIGINAL_LOCAL / 'LOCAL_VERIFICATION.json')['allPassed'] and sha(parent['archive']) == parent['sha256'] == read(root / 'recovery.json')['originalArchiveSha256'])
    inventory = read(root / 'file-inventory-recovery.json')
    check('exact-file-inventory-set', set(inventory) == {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name != 'file-inventory-recovery.json'})
    old_inventory = read(Path(parent['fullResults']) / 'outputs/canonical/file-inventory.json')
    for p in (root / 'original-reference/results').glob('*/*.json'):
        rel = 'outputs/canonical/results/' + p.parent.name + '/' + p.name
        check('original-record:' + rel, sha(p) == old_inventory[rel])
    for n, (rel, digest) in enumerate(inventory.items(), 1):
        check('inventory:' + rel, (root / rel).is_file() and sha(root / rel) == digest)
        if n % 2000 == 0:
            print(json.dumps({'inventoryChecked': n, 'total': len(inventory)}), flush=True)
    audit, result = generate(root, local=True)
    checks.extend(audit['checks'])
    server = read(root / 'SUMMARY.json')
    check('independent-final-statistics', result['finalScored'] == server['finalScored'])
    check('independent-original-and-unknown-statistics', result['original'] == server['original'] and result['firstValidCompletedUnknown'] == server['firstValidCompletedUnknown'])
    check('independent-final-provenance', result['finalSources'] == server['finalSources'])
    check('independent-all-attempt-costs', result['fees'] == server['fees'])
    check('server-audit-and-final-freeze', read(root / 'AUDIT.json')['allPassed'] and read(root / 'final-freeze.json')['resolvedCount'] == 8)
    original_records = {(r['arm'], r['id']): r for r in read(root / 'original-reference/records.json')}
    final_records = {(r['arm'], r['id']): r for r in read(root / 'FINAL_RECORDS.json')}
    check('final-record-identities', set(original_records) == set(final_records) and len(final_records) == 1416)
    for name in ['ORIGINAL_RESULTS.csv', 'FIRST_VALID_UNKNOWN_RESULTS.csv', 'FINAL_RESULTS.csv']:
        with (root / name).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        check('csv-identities:' + name, len(rows) == 1416 and {(r['arm'], r['id']) for r in rows} == set(original_records))
        if name == 'FINAL_RESULTS.csv':
            for row in rows:
                raw = final_records[(row['arm'], row['id'])]
                check('csv-scientific-validity:' + row['arm'] + '/' + row['id'], row['actualValid'] == str(valid(raw)) and row['solverValid'] == str(raw['solverValid']) and row['answer'] == raw['answer'])
                expected = int(raw['grade']['passed']) if valid(raw) else 0
                check('csv-policy-score:' + row['arm'] + '/' + row['id'], row['scoredPassed'] == str(expected) and (valid(raw) or row['outcomeClass'] in ['timeout-default-failure', 'other-infrastructure-default-failure']))
    env = (REPO / '.env').read_text(encoding='utf-8-sig')
    match = re.search(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$', env, re.M)
    assert match
    secret = match[1].strip().strip('\"\'').encode()
    assert len(secret) > 8
    hits = []
    for n, p in enumerate((p for p in root.rglob('*') if p.is_file()), 1):
        tail = b''
        with p.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                data = tail + chunk
                if secret in data:
                    hits.append(p.relative_to(root).as_posix())
                    break
                tail = data[-len(secret):]
        if n % 5000 == 0:
            print(json.dumps({'credentialAbsenceFilesScanned': n}), flush=True)
    check('credential-absent', not hits)
    proof = {'allPassed': all(c['passed'] for c in checks), 'checkCount': len(checks), 'checks': checks, 'failures': [c for c in checks if not c['passed']], 'archiveSha256': meta['sha256']}
    save(LOCAL / 'LOCAL_VERIFICATION.json', proof)
    assert proof['allPassed'], proof['failures'][:10]
    save(LOCAL / 'INDEPENDENT_SUMMARY.json', result)
    for name in ['SUMMARY.json', 'ORIGINAL_RESULTS.csv', 'FIRST_VALID_UNKNOWN_RESULTS.csv', 'FINAL_RESULTS.csv', 'FINAL_PROVENANCE.json', 'FINAL_DISPOSITIONS.json']:
        (LOCAL / name).write_bytes((root / name).read_bytes())
    lines = ['# LAB-Bench final bounded results', '', 'Original unknown results remain preserved. The final scoring overlay counts final infrastructure timeouts as zero with the full 708-item denominator. Raw solver validity, answers, grades and submissions remain unchanged.', '', '|View|Dataset|Arm|Pass / denominator|Raw unknown|Timeout default failures|Actual valid wrong|Pass rate|', '|---|---|---|---:|---:|---:|---:|---|']
    for view in ['original', 'firstValidCompletedUnknown']:
        for category, arms in list(result[view]['categories'].items()) + [('All', result[view]['arms'])]:
            for arm, s in arms.items():
                lines.append(f"|{view}|{category}|{arm}|{s['passed']}/{s['tasks']}|{s['unknown']}|N/A|{s['valid']-s['passed']}|{s['accuracyBounds'][0]*100:.2f}% to {s['accuracyBounds'][1]*100:.2f}%|")
    for category, arms in list(result['finalScored']['categories'].items()) + [('All', result['finalScored']['arms'])]:
        for arm, s in arms.items():
            lines.append(f"|Final scored|{category}|{arm}|{s['passed']}/{s['tasks']}|{s['rawUnknown']}|{s['timeoutDefaultFailures']}|{s['actualValidWrong']}|{s['passRate']*100:.2f}%|")
    lines += ['', f"All recovery attempts: {result['attemptCount']}; added declared solve budget: {result['additionalDeclaredSolveBudgetSeconds']} seconds (600 per independent attempt). First-valid identities: {result['firstValidCount']}; resolved identities under the final policy: {result['resolvedCount']}/8.", '', '|Scope|Arm|Known actual USD|Unknown fees|Transmissions|', '|---|---|---:|---:|---:|']
    for scope, groups in [('Original', result['fees']['original']['byArm']), ('All recovery attempts', result['fees']['allRecoveryAttempts']['byArm']), ('Combined', result['fees']['combinedByArm'])]:
        for arm, g in groups.items():
            lines.append(f"|{scope}|{arm}|{g['knownActualCostUsd']:.9f}|{g['unknownCostRequests']}|{g['requests']}|")
    lines += ['', 'All failed and successful recovery attempts are included; missing fees remain unknown. The original v2 ledger already includes v1 and is counted once.', '', 'The supplemental view adds independent trial budgets and final administrative zero scoring. ObjRun has gold-label feedback and can eliminate MCQ choices. Original baseline format failures and truncations remain. Original three pilot recoveries used accumulated active task time with repair downtime recorded separately; all new trials received a fresh600 seconds.', '', 'Per-identity provenance, caps, attempt counts, source hashes and added budget are in FINAL_PROVENANCE.json. All original failures and all recovery requests, generation IDs, usage, candidates, actual submits, SQLite/task trees, logs, source, dependencies and data are retained in the two archives.', '', f"Local verification passed {proof['checkCount']} checks.", f"Recovery archive SHA256: {meta['sha256']}", f"Original archive SHA256: {parent['sha256']}", '', f"Recovery archive: {meta['archive']}", f"Original archive: {parent['archive']}", f"Full recovery files: {meta['fullResults']}"]
    (LOCAL / 'RESULTS.md').write_bytes(('\n'.join(lines) + '\n').encode())
    save(LOCAL / 'DELIVERY.json', {'delivered': True, 'verified': True, 'localChecks': proof['checkCount'], 'recoveryArchive': meta, 'originalArchive': parent, 'resolvedCount': result['resolvedCount'], 'firstValidCount': result['firstValidCount'], 'attemptCount': result['attemptCount'], 'additionalDeclaredSolveBudgetSeconds': result['additionalDeclaredSolveBudgetSeconds'], 'fees': result['fees'], 'finalScored': result['finalScored']['arms']})
    print(json.dumps({'allPassed': True, 'checks': proof['checkCount'], 'finalScored': result['finalScored']['arms'], 'fees': result['fees']}), flush=True)


if __name__ == '__main__':
    main()
