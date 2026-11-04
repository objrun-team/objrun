#!/usr/bin/env python3
"""ca_verify.py - portable strength-t coverage checker for covering arrays.

Same semantics as ca_verify.c (use that one for speed; this one runs anywhere
Python does, no compiler needed). Verifies that an N x k array over v symbols
covers every t-way interaction. A don't-care entry ('-', '*', 'x', 'NA', or
-1) contributes nothing to a projection that contains it: coverage must hold
on the concrete entries alone (the rule of caverify 0.2.0).

Usage: ca_verify.py FILE t v
Exit status: 0 = verified, 1 = gaps found, 2 = error.
"""
import sys
from itertools import combinations, product

WILD = -1

def read_array(path):
    rows = []
    with open(path) as f:
        for line in f:
            toks = line.replace(",", " ").split()
            if not toks:
                continue
            row = []
            for tok in toks:
                tl = tok.strip().lower()
                if tl in ("-", "*", "x", "na", "-1"):
                    row.append(WILD)
                else:
                    row.append(int(tok))
            rows.append(row)
    if not rows:
        raise ValueError("empty file")
    k = len(rows[0])
    if any(len(r) != k for r in rows):
        raise ValueError("ragged rows")
    vals = [x for r in rows for x in r if x != WILD]
    if min(vals) == 1:               # auto-shift 1-based symbols
        rows = [[x - 1 if x != WILD else x for x in r] for r in rows]
    return rows

def verify(rows, t, v, max_report=10):
    k = len(rows[0])
    vt = v ** t
    gaps = 0
    missing_total = 0
    examples = []
    for cols in combinations(range(k), t):
        seen = set()
        for r in rows:
            vals = [r[c] for c in cols]
            if WILD in vals:
                continue
            seen.add(tuple(vals))
        miss = vt - len(seen)
        if miss:
            gaps += 1
            missing_total += miss
            if len(examples) < max_report:
                for tup in product(range(v), repeat=t):
                    if tup not in seen:
                        examples.append((cols, tup))
                        break
    return gaps, missing_total, examples

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    path, t, v = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    rows = read_array(path)
    n, k = len(rows), len(rows[0])
    gaps, mt, ex = verify(rows, t, v)
    if gaps == 0:
        print(f"VERIFIED: CA(N={n}; t={t}, k={k}, v={v})")
        return 0
    print(f"NOT A COVERING ARRAY: {gaps} column sets have gaps "
          f"({mt} missing tuples total)")
    for cols, tup in ex:
        print(f"  missing: columns {cols} tuple {tup}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
