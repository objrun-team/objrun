"""Separate raw validity from the explicitly authorized timeout scoring overlay."""
from pathlib import Path
import csv
import random
import sys


def generate(root, local=False):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / 'operations'))
    from core import read, save, sha, valid, key, original_guard
    from report_recovery import generate as original_recovery_audit
    from run_bounded import final_classification
    old_audit, result = original_recovery_audit(root, local=True)
    policy = read(root / 'control/final-attempt-policy.json')
    caps = {v['identity']: v for v in policy['boundaries']}
    dispositions = read(root / 'FINAL_DISPOSITIONS.json')
    original = read(root / 'original-reference/records.json')
    jobs = read(root / 'recovery.json')['jobs']
    selected = read(root / 'first-valid.json')
    checks = []

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})

    default_keys = {k for k, d in dispositions.items() if d['classification'] != 'actual-valid'}
    replaced_gates = {'all1416-valid'} | {'first-valid-stop:' + k for k in default_keys}
    for c in old_audit['checks']:
        if c['name'] not in replaced_gates:
            checks.append(c)
    check('only-explicit-human-policy-gates-changed', all(c['name'] in replaced_gates for c in old_audit['failures']))
    check('eight-resolved-identities-exactly', set(caps) == set(dispositions) == {key(j) for j in jobs} and len(caps) == 8)
    check('bounded-zero-model-controls', read(root / 'bounded-controls.json')['allPassed'] and read(root / 'bounded-controls.json')['modelCalls'] == 0)
    for pinfile in ['bounded-operations-pins.json', 'bounded-report-pins.json']:
        for rel, digest in read(root / pinfile).items():
            check(pinfile + ':' + rel, sha(root / rel) == digest)
    composite = {(r['arm'], r['id']): r for r in original}
    provenance = []
    for job in jobs:
        k = key(job)
        homes = sorted((root / 'attempts' / job['arm'] / job['id']).glob('attempt-*'))
        terms = [read(h / 'terminal.json') for h in homes]
        d = dispositions[k]
        cap = caps[k]
        first = next((t for t in terms if t['valid']), None)
        check('never-exceeded-final-cap:' + k, len(homes) <= cap['lastAttemptNumber'])
        check('exact-policy-boundary:' + k, cap['lastAttemptNumber'] == cap['attemptsAtBoundary'] + int(not cap['alreadyFirstValid'] and not cap['activeAtBoundary']))
        if first:
            t = first
            check('first-valid-no-later-attempt:' + k, first['number'] == len(homes) and selected[k]['terminal'] == first and d['classification'] == 'actual-valid')
        else:
            t = terms[-1]
            check('invalid-final-cap-exhausted:' + k, len(homes) == cap['lastAttemptNumber'] and d['classification'] == final_classification(t) and d['administrativeScore'] == 0 and d['solverValid'] is False and d['answerFabricated'] is False)
        home = homes[t['number'] - 1]
        raw = read(home / t['result']) if t.get('result') else None
        check('disposition-source:' + k, d['source'] == home.relative_to(root).as_posix() and d['attemptNumber'] == t['number'])
        check('raw-validity-unmodified:' + k, valid(raw) == t['valid'])
        if raw:
            check('raw-result-hash:' + k, sha(home / t['result']) == t['resultSha256'])
            final = dict(raw)
        else:
            final = dict(composite[(job['arm'], job['id'])])
            final['unavailableFinalAttemptResult'] = True
        outcome = d['classification']
        administrative = {'classification': outcome, 'score': int(raw['grade']['passed']) if valid(raw) else 0, 'source': d['source'], 'policySha256': sha(root / 'control/final-attempt-policy.json'), 'isSolverAnswer': bool(valid(raw)), 'rawResultPath': t.get('result'), 'rawResultSha256': t.get('resultSha256')}
        final['administrativeOutcome'] = administrative
        composite[(job['arm'], job['id'])] = final
        if raw:
            check('answer-grade-and-validity-not-fabricated:' + k, final['answer'] == raw['answer'] and final['solverValid'] == raw['solverValid'] and final['grade'] == raw['grade'])
        if outcome == 'timeout-default-failure':
            failures = [read(p) for p in (home / 'outputs/canonical/calls').glob('**/receipt.json') if read(p).get('error')]
            check('timeout-evidence:' + k, any(any(x in str(v.get('error', '')).lower() for x in ['timeout', 'timed out']) for v in failures) or (raw is not None and raw.get('transportIncomplete') and 'deadline' in str(t.get('error', '')).lower()))
        check('valid-boundary-no-repeat:' + k, not cap['alreadyFirstValid'] or len(homes) == cap['attemptsAtBoundary'])
        provenance.append({'arm': job['arm'], 'id': job['id'], 'source': d['source'], 'classification': outcome, 'attemptCount': len(homes), 'lastAttemptNumber': cap['lastAttemptNumber'], 'attemptsAfterPolicyBoundary': len(homes) - cap['attemptsAtBoundary'], 'addedDeclaredSolveBudgetSeconds': 600 * len(homes), 'rawResultSha256': t.get('resultSha256'), 'actualValid': t['valid'], 'administrativeScore': administrative['score']})
    final_rows = list(composite.values())
    check('all1416-identities-preserved', len(composite) == 1416 and set(composite) == {(r['arm'], r['id']) for r in original})
    for r in original:
        if valid(r):
            check('original-valid-record-byte-meaning-unchanged:' + r['arm'] + '/' + r['id'], composite[(r['arm'], r['id'])] == r)
    if not local:
        original_guard(read(root / 'recovery.json')['originalRoot'])
        check('original-entire-inventory-unchanged', True)
    public = read(root / 'frozen/data/public-tasks.json')
    import protocol as p

    def score(row):
        return int(row['grade'].get('passed', False)) if valid(row) else 0

    def stats(rows, total):
        known = [r for r in rows if valid(r)]
        timeouts = sum(r.get('administrativeOutcome', {}).get('classification') == 'timeout-default-failure' for r in rows)
        other = sum(r.get('administrativeOutcome', {}).get('classification') == 'other-infrastructure-default-failure' for r in rows)
        return {'tasks': total, 'records': len(rows), 'actualValid': len(known), 'actualValidCorrect': sum(score(r) for r in known), 'actualValidWrong': sum(not r['grade']['passed'] for r in known), 'timeoutDefaultFailures': timeouts, 'otherInfrastructureDefaultFailures': other, 'rawUnknown': total - len(known), 'scoreUnknown': 0, 'passed': sum(score(r) for r in rows), 'scoredFailures': total - sum(score(r) for r in rows), 'passRate': sum(score(r) for r in rows) / total if total else None, 'denominator': total}

    def by_category(category):
        return {arm: stats([r for r in final_rows if r['arm'] == arm and r['category'] == category], sum(t['category'] == category for t in public)) for arm in ['baseline', 'objrun']}

    paired = [(score(composite[('baseline', t['id'])]), score(composite[('objrun', t['id'])])) for t in public]
    differences = [b - a for a, b in paired]
    rng = random.Random(20261019)
    boot = sorted(sum(rng.choice(differences) for _ in differences) / len(differences) for _ in range(5000))
    final_stats = {'arms': {a: stats([r for r in final_rows if r['arm'] == a], 708) for a in ['baseline', 'objrun']}, 'categories': {c: by_category(c) for c in ['ProtocolQA', 'SeqQA']}, 'subtasks': {s: {a: stats([r for r in final_rows if r['arm'] == a and r['subtask'] == s], sum(t['subtask'] == s for t in public)) for a in ['baseline', 'objrun']} for s in sorted({t['subtask'] for t in public})}, 'pairedScoredAll708': {'pairs': 708, 'deltaObjrunMinusBaseline': sum(differences) / 708, 'bootstrap95': [boot[124], boot[4874]], 'resamples': 5000, 'seed': 20261019, 'baselineOnlyPass': sum(a and not b for a, b in paired), 'objrunOnlyPass': sum(b and not a for a, b in paired), 'bothPass': sum(a and b for a, b in paired), 'bothFail': sum(not a and not b for a, b in paired)}, 'knownDuplicateChoiceSensitivity': {a: stats([r for r in final_rows if r['arm'] == a and r['id'] != p.DEFECT], 707) for a in ['baseline', 'objrun']}}
    check('default-zero-keeps-708-denominator', all(s['denominator'] == 708 and s['actualValid'] + s['timeoutDefaultFailures'] + s['otherInfrastructureDefaultFailures'] == 708 for s in final_stats['arms'].values()))
    result['firstValidCompletedUnknown'] = result.pop('completed')
    result['finalScored'] = final_stats
    result['finalSources'] = provenance
    result['firstValidCount'] = len(selected)
    result['resolvedCount'] = len(dispositions)
    result['finalAttemptPolicy'] = policy
    result['selection'] = 'first actual valid, otherwise stop at authorized final attempt; timeout scored zero administratively, never marked solver-valid'
    result['interpretation'] = 'Original unknown view and first-valid supplemental unknown view retained. Final score uses the human-authorized administrative zero for final infrastructure failures with 708 denominator. No fabricated answers or submissions. ObjRun has oracle feedback. Fresh600 trials add independent budget.'
    check('all-recovery-transmissions-settled', all(g['unsettledRequests'] == 0 for g in result['fees']['allRecoveryAttempts']['byArm'].values()))
    if local:
        check('independent-raw-final-records-and-overlay', read(root / 'FINAL_RECORDS.json') == final_rows)
        check('independent-final-source-file', read(root / 'FINAL_PROVENANCE.json') == provenance)
    audit = {'allPassed': all(x['passed'] for x in checks), 'checkCount': len(checks), 'checks': checks, 'failures': [x for x in checks if not x['passed']], 'explicitlyReplacedGates': sorted(replaced_gates), 'policySha256': sha(root / 'control/final-attempt-policy.json')}
    if local:
        return audit, result
    save(root / 'AUDIT_WITHOUT_FINAL_POLICY.json', old_audit)
    save(root / 'AUDIT.json', audit)
    save(root / 'SUMMARY.json', result)
    save(root / 'FINAL_RECORDS.json', final_rows)
    save(root / 'FINAL_PROVENANCE.json', provenance)
    # CSV retains scientific validity and administrative score as distinct columns.
    first_rows = {(r['arm'], r['id']): r for r in original}
    for k, v in selected.items():
        t = v['terminal']
        row = read(root / v['home'] / t['result'])
        first_rows[(row['arm'], row['id'])] = row
    for name, rows in [('ORIGINAL_RESULTS.csv', original), ('FIRST_VALID_UNKNOWN_RESULTS.csv', list(first_rows.values())), ('FINAL_RESULTS.csv', final_rows)]:
        fields = ['arm', 'id', 'category', 'subtask', 'solverValid', 'gradeValid', 'actualValid', 'actualPassed', 'scoredPassed', 'outcomeClass', 'answer', 'error', 'recoverySource', 'attemptCount']
        with (root / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                src = next((v for v in provenance if v['arm'] == row['arm'] and v['id'] == row['id']), None) if not name.startswith('ORIGINAL') else None
                if name == 'FIRST_VALID_UNKNOWN_RESULTS.csv' and src and not src['actualValid']:
                    src = None
                outcome = 'actual-valid-correct' if valid(row) and row['grade']['passed'] else 'actual-valid-wrong' if valid(row) else 'infrastructure-unknown'
                if name == 'FINAL_RESULTS.csv' and src and not src['actualValid']:
                    outcome = src['classification']
                writer.writerow({k: row.get(k) for k in ['arm', 'id', 'category', 'subtask', 'solverValid', 'answer', 'error']} | {'gradeValid': row['grade'].get('valid'), 'actualValid': valid(row), 'actualPassed': row['grade'].get('passed') if valid(row) else None, 'scoredPassed': score(row) if name == 'FINAL_RESULTS.csv' or valid(row) else None, 'outcomeClass': outcome, 'recoverySource': src['source'] if src else 'original', 'attemptCount': src['attemptCount'] if src else 0})
    assert audit['allPassed'], audit['failures'][:10]
    return audit, result


if __name__ == '__main__':
    generate(sys.argv[1])
