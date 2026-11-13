#!/usr/bin/env bash
# Prepare this example's dependencies. **Idempotent**; safe to rerun.
#
#   bash examples/benchmark/aime/setup.sh
#
# **On Sherlock, run on a compute node, not a login node** (request one with `sh_dev` or sbatch).
# Creating a venv, running pip, and self-tests are prohibited on login nodes. The engine can run elsewhere; it only knows two URLs.
#
#   sh_dev -c 2 -m 8GB -t 1:00:00
#   bash /path/to/examples/benchmark/aime/setup.sh
#
# ## Install the problems **on the grader side**, outside the repository
#
# All 60 problems include answers. Inside the repository, one solver glob would find them (observed with CMT).
# Install them under `$HOME/.cache/tgengin-aime/`. **This is not isolation**: if the solver's bash runs on the same machine as the grader, cat can still read them. The path changes; reachability does not.
#
# ## Three sources: two primary, one for cross-checking
#
#   2024  AI-MO/aimo-validation-aime   Apache-2.0  parquet  90 problems (22–24); use the 30 from 24
#   2025  math-ai/aime25               Apache-2.0  jsonl    30 problems; answer is a clean int
#   2025  opencompass/AIME2025         MIT         jsonl    Cross-check against math-ai only
#                                                         (II-5 is "336^\circ", so it is not the primary source)
#
# Pin everything to commit SHAs: HF main can change, making scores incomparable.
set -eu
cd "$(dirname "$0")"

HOME_DIR="${TGENGIN_AIME_HOME:-$HOME/.cache/tgengin-aime}"
VENV="$HOME_DIR/venv"
RAW="$HOME_DIR/raw"
DATA="$HOME_DIR/aime.jsonl"

HF=https://huggingface.co/datasets
AIMO_SHA=13f9e12f613e720c2a2b2f345dd04b998a29494d
MATHAI_SHA=563bb8404243c5f09de6ec262f2db674fe5bce9b
OC_SHA=a6ad95f611d72cf628a80b58bd0432ef6638f958
# Pin the official grader version. math_verify changes its parsing rules between releases; changing versions changes the criterion.
MV_VERSION=0.9.0

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR" "$RAW"

step "0/4 python"
# On Sherlock use the Python 3.12 module (`ml spider python` lists 3.12.1). Python 3.11+ is sufficient elsewhere.
if command -v ml >/dev/null 2>&1 || command -v module >/dev/null 2>&1; then
  ml python/3.12.1 2>/dev/null || module load python/3.12.1 2>/dev/null || true
fi
PY=$(command -v python3)
# In noninteractive bash, `ml` is often not a function because Lmod was not initialized. Use the module installation path directly.
# Its libpython is outside the default search path, so LD_LIBRARY_PATH is required for python3 to start.
SHERLOCK_PY=/share/software/user/open/python/3.12.1
if ! "$PY" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null && [ -x "$SHERLOCK_PY/bin/python3" ]; then
  export LD_LIBRARY_PATH="$SHERLOCK_PY/lib:${LD_LIBRARY_PATH:-}"
  PY="$SHERLOCK_PY/bin/python3"
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version' || { echo "need python >= 3.11 (on Sherlock: ml python/3.12.1)"; exit 1; }
echo "  $("$PY" --version) at $PY"
# Keep the pip cache outside $HOME; its 15 GB quota fills quickly.
export PIP_CACHE_DIR="${SCRATCH:-/tmp}/.pip-cache"

step "1/4 Source data (three sources, all pinned by SHA)"
fetch () {  # fetch <url> <dst>
  if [ -s "$2" ]; then echo "  have  $(basename "$2")"; else curl -sSL -o "$2" "$1"; echo "  got   $(basename "$2") ($(stat -c %s "$2") bytes)"; fi
}
fetch "$HF/AI-MO/aimo-validation-aime/resolve/$AIMO_SHA/data/train-00000-of-00001.parquet" "$RAW/aimo-validation-aime.parquet"
fetch "$HF/math-ai/aime25/resolve/$MATHAI_SHA/test.jsonl"                               "$RAW/math-ai-aime25.jsonl"
fetch "$HF/opencompass/AIME2025/resolve/$OC_SHA/aime2025-I.jsonl"                       "$RAW/opencompass-aime2025-I.jsonl"
fetch "$HF/opencompass/AIME2025/resolve/$OC_SHA/aime2025-II.jsonl"                      "$RAW/opencompass-aime2025-II.jsonl"

step "2/4 venv: official grader math-verify==$MV_VERSION (+ pyarrow to read the parquet)"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null
"$VENV/bin/pip" install -q --only-binary=:all: "numpy==2.2.5" "pandas==2.3.2" "pyarrow==20.0.0" && "$VENV/bin/pip" install -q "math-verify[antlr4_13_2]==$MV_VERSION"  # glibc 2.17 requires manylinux2014-compatible wheels.
"$VENV/bin/python" - <<'PY'
import math_verify, sympy, pyarrow
print(f"  math-verify {getattr(math_verify, '__version__', '?')} | sympy {sympy.__version__} | pyarrow {pyarrow.__version__}")
PY

step "3/4 Build dataset $DATA (60 tasks with answers; read only by the grading service)"
# **This section only copies data; it does not grade.** For 2024, infer the year and session from the URL. For 2025, use line order: math-ai IDs 0–14 are I and 15–29 are II, with problem numbers determined by line order.
# Use opencompass only for cross-checking: one answer contains "^\circ". Strip nondigits and require all 30 answers to match math-ai, failing on any discrepancy.
RAW="$RAW" DATA="$DATA" "$VENV/bin/python" - <<'PY'
import json, os, re
from pathlib import Path
import pyarrow.parquet as pq

raw, out = Path(os.environ["RAW"]), Path(os.environ["DATA"])
rows = []

# 2024: AI-MO; select the 30 tasks whose URL contains 2024_AIME.
t = pq.read_table(raw / "aimo-validation-aime.parquet").to_pylist()
for r in t:
    m = re.search(r"(\d{4})_AIME_(I|II)_Problems/Problem_(\d+)", r["url"])
    if not m or m.group(1) != "2024":
        continue
    year, contest, num = int(m.group(1)), m.group(2), int(m.group(3))
    ans = int(str(r["answer"]).strip())         # Official answers have leading zeros ("025"); int handles them.
    rows.append({"id": f"aime-{year}-{contest}-{num}", "year": year, "contest": contest, "number": num,
                 "problem": r["problem"], "answer": ans, "url": r["url"], "source": "AI-MO/aimo-validation-aime"})
n24 = len(rows)
assert n24 == 30, f"expected 30 problems for 2024, got {n24}"

# 2025: math-ai; row order = task number.
ma = [json.loads(l) for l in (raw / "math-ai-aime25.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
assert len(ma) == 30, len(ma)
for i, r in enumerate(ma):
    contest, num = ("I", i + 1) if i < 15 else ("II", i - 14)
    rows.append({"id": f"aime-2025-{contest}-{num}", "year": 2025, "contest": contest, "number": num,
                 "problem": r["problem"], "answer": int(str(r["answer"]).strip()),
                 "url": f"https://artofproblemsolving.com/wiki/index.php/2025_AIME_{contest}_Problems/Problem_{num}",
                 "source": "math-ai/aime25"})

# Reconcile: all 30 opencompass answers, after removing nondigits, must match math-ai task by task.
oc = []
for part in ("I", "II"):
    oc += [json.loads(l) for l in (raw / f"opencompass-aime2025-{part}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
assert len(oc) == 30, len(oc)
for r, o in zip(rows[n24:], oc):
    a, b = r["answer"], int(re.sub(r"\D", "", str(o["answer"])))
    assert a == b, f"{r['id']}: math-ai says {a}, opencompass says {o['answer']}"

for r in rows:
    assert 0 <= r["answer"] <= 999, r
out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
print(f"  {len(rows)} problems -> {out}  (2024: {n24}, 2025: {len(rows) - n24}; opencompass agrees on all 30 of 2025)")
PY

step "4/4 Self-test: official grader loading and correctness"
TGENGIN_AIME_HOME="$HOME_DIR" "$VENV/bin/python" stand.py --selftest

echo
echo "Ready. Start the grading service on this host with the venv:"
# The venv was created with the module Python. Include its library path when starting the grader, or libpython3.12.so cannot be found.
[ "$PY" = "$SHERLOCK_PY/bin/python3" ] && echo "  export LD_LIBRARY_PATH=$SHERLOCK_PY/lib:\$LD_LIBRARY_PATH"
echo "  cd $(pwd) && TGENGIN_AIME_HOME=$HOME_DIR $VENV/bin/python stand.py --level 1"
