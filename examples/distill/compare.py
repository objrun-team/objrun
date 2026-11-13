r"""Compare two unaided.csv files on shared tasks: baseline versus a distilled skill. Count only shared tasks."""
import csv, sys

def load(p):
    rows = list(csv.DictReader(open(p)))
    col = next(k for k in ("equiv", "correct", "pass") if rows and k in rows[0])
    return {r["task"]: int(r[col]) for r in rows}

base, new = load(sys.argv[1]), load(sys.argv[2])
common = sorted(set(base) & set(new), key=lambda s: (len(s), s))
b = sum(base[t] for t in common); n = sum(new[t] for t in common)
gained = [t for t in common if new[t] and not base[t]]
lost = [t for t in common if base[t] and not new[t]]
print(f"common {len(common)}: baseline {b}/{len(common)}  with skill {n}/{len(common)}  delta {n-b:+d}")
print(f"  gained: {','.join(gained) or '-'}")
print(f"  lost:   {','.join(lost) or '-'}")
