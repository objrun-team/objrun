"""Trusted G. This file and ca_verify.py are outside the solver's mount namespace.

Strict complete integer arrays only. G enumerates every required interaction;
the independently authored ca-tools implementation uses tuple sets instead.
"""
import argparse
import hashlib
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

T, K, V, BASELINE = 3, 24, 2, 21


def check_text(text, threshold=BASELINE):
    result = dict(t=T, k=K, v=V, baseline=BASELINE, threshold=threshold,
                  valid=False, improved=False, size=0)
    lines = text.splitlines()
    if not lines or any(not line.strip() for line in lines):
        return {**result, 'error': 'Empty array or blank row; one complete row per line required.'}
    rows = []
    for i, line in enumerate(lines):
        tokens = line.split()
        if len(tokens) != K:
            return {**result, 'error': 'Wrong column count', 'row': i, 'actual_k': len(tokens)}
        if any(re.fullmatch(r'[01]', token) is None for token in tokens):
            return {**result, 'error': 'Only literal complete symbols 0 and 1 are allowed', 'row': i}
        rows.append([int(x) for x in tokens])
    result['size'] = len(rows)
    result['sha256'] = hashlib.sha256(('\n'.join(' '.join(map(str, r)) for r in rows)+'\n').encode()).hexdigest()
    missing = []
    multiplicities = {}
    subsets = 0
    for cols in itertools.combinations(range(K), T):
        counts = [0] * (V ** T)
        for row in rows:
            code = 0
            for col in cols:
                code = code * V + row[col]
            counts[code] += 1
        for code, count in enumerate(counts):
            multiplicities[count] = multiplicities.get(count, 0) + 1
            if count == 0:
                missing.append({'columns_zero_based': list(cols),
                                'symbols': [(code // (V ** j)) % V for j in reversed(range(T))]})
        subsets += 1
    result.update(column_subsets_checked=subsets, required_interactions=subsets * V**T,
                  missing_count=len(missing), missing=missing,
                  minimum_multiplicity=min(multiplicities), multiplicity_histogram=multiplicities,
                  valid=not missing, improved=not missing and len(rows) < threshold)
    return result


def cross_check(path, threshold=BASELINE):
    path = Path(path)
    report = check_text(path.read_text(encoding='utf-8-sig'), threshold)
    independent = Path(__file__).with_name('ca_verify.py')
    # Run the upstream checker even on malformed inputs; G remains stricter
    # than its documented wildcard/one-based format. Never execute candidate code.
    other = subprocess.run([sys.executable, str(independent), str(path), str(T), str(V)],
                           capture_output=True, text=True)
    report['independent'] = dict(implementation='chrispbsmolen/ca-tools ca_verify.py',
        source_sha256=hashlib.sha256(independent.read_bytes()).hexdigest(),
        exit_code=other.returncode, stdout=other.stdout, stderr=other.stderr,
        coverage_valid=other.returncode == 0)
    if 'missing_count' in report:
        report['implementations_agree'] = report['valid'] == (other.returncode == 0)
        if not report['implementations_agree']:
            report.update(valid=False, improved=False, error='Independent checker disagreement')
    else:
        report['implementations_agree'] = None
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--threshold', type=int, default=BASELINE)
    parser.add_argument('--independent', action='store_true')
    args = parser.parse_args()
    print(json.dumps(cross_check(args.path, args.threshold) if args.independent else
                     check_text(Path(args.path).read_text(encoding='utf-8-sig'), args.threshold)))
