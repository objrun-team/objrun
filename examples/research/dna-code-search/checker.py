"""Independent integer checker; never execute candidate-supplied code.

The primary profile matches the reproducible Table 4 construction, NOT the
paper's stronger literal all-pairs R/RC inequalities. Check those separately.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ALPHABET = 'ATCG'
COMPLEMENT = str.maketrans('ATCG', 'TAGC')


def check(words, threshold=676):
    result = dict(profile='reproduced-table4-closed', n=10, d=4, gc=5,
                  threshold=threshold, size=len(words), valid=False,
                  improved=False, strict_r_rc_valid=False)
    if not words or any(not isinstance(w, str) or len(w) != 10 or
                        set(w) - set(ALPHABET) for w in words):
        return {**result, 'error': 'Every word must have exactly 10 uppercase ATCG bases.'}
    if len(set(words)) != len(words):
        return {**result, 'error': 'Duplicate codewords.'}
    words = sorted(words)
    canonical = '\n'.join(words) + '\n'
    result['sha256'] = hashlib.sha256(canonical.encode()).hexdigest()
    pool = set(words)
    for w in words:
        if sum(c in 'GC' for c in w) != 5:
            return {**result, 'error': 'GC content is not exactly 5.', 'witness': w}
        for i in range(8):
            rc = w[i:i+3].translate(COMPLEMENT)[::-1]
            for j in range(i, 8):
                if w[j:j+3] == rc:
                    return {**result, 'error': 'Forbidden reverse-complement length-3 substrings (including overlaps).', 'witness': [w, i, j]}
        for transformed in (w[::-1], w.translate(COMPLEMENT), w.translate(COMPLEMENT)[::-1]):
            if transformed not in pool:
                return {**result, 'error': 'The reproduced construction profile requires reversal and complement closure.', 'witness': [w, transformed]}
    encoded = np.array([[ALPHABET.index(c) for c in w] for w in words], dtype=np.uint8)
    minimum = 10
    for i, w in enumerate(encoded[:-1]):
        distances = np.count_nonzero(encoded[i+1:] != w, axis=1)
        hit = np.flatnonzero(distances < 4)
        if len(hit):
            j = i + 1 + int(hit[0])
            return {**result, 'error': 'Hamming distance below 4.', 'witness': [words[i], words[j], int(distances[hit[0]])]}
        minimum = min(minimum, int(distances.min()))
    result.update(valid=True, improved=len(words) > threshold, minimum_hamming=minimum)
    # The literal stronger conditions include x=y. Provide concrete witnesses;
    # closed sets necessarily contain transformed pairs, giving distance zero.
    for field, transform in [('reverse', lambda w: w[::-1]),
                             ('reverse_complement', lambda w: w.translate(COMPLEMENT)[::-1])]:
        w = words[0]
        result[field + '_distance_min'] = 0
        result[field + '_violation'] = {'x': w, 'y': transform(w), 'distance': 0}
    result['scope'] = 'Finite combinatorial code construction only; not a strict R/RC code or experimental biology claim.'
    return result


def independent_check(words):
    """Second implementation: native Python strings and integer bit operations."""
    s = set(words)
    if len(s) != len(words) or not s:
        return False
    encoded = []
    for w in words:
        if len(w) != 10 or any(c not in ALPHABET for c in w) or sum(c in 'GC' for c in w) != 5:
            return False
        comp = ''.join({'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}[c] for c in w)
        if not {w[::-1], comp, comp[::-1]} <= s:
            return False
        triples = [w[k:k+3] for k in range(8)]
        for a in triples:
            reverse_comp = ''.join({'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}[c] for c in a[::-1])
            if reverse_comp in triples:
                return False
        code = 0
        for c in w:
            code = (code << 2) | ALPHABET.index(c)
        encoded.append(code)
    mask = sum(1 << (2*k) for k in range(10))
    for i, x in enumerate(encoded):
        for y in encoded[i+1:]:
            z = x ^ y
            if (((z | (z >> 1)) & mask).bit_count()) < 4:
                return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--threshold', type=int, default=676)
    parser.add_argument('--independent', action='store_true')
    args = parser.parse_args()
    words = Path(args.path).read_text(encoding='utf-8-sig').split()
    result = check(words, args.threshold)
    if args.independent:
        result['independent_valid'] = independent_check(words)
        result['valid'] = result['valid'] and result['independent_valid']
        result['improved'] = result['improved'] and result['valid']
    print(json.dumps(result))


if __name__ == '__main__':
    main()
