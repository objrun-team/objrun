#!/usr/bin/env bash
# Prepare this example's dependencies. **Idempotent**; safe to rerun.
#
#   sh_dev -c 2 -m 8GB            # Request a Sherlock compute node first; Python/pip are prohibited on login nodes.
#   bash examples/benchmark/chembench/setup.sh
#
# The engine can run on another machine; it only knows two URLs and does not depend on the grader's location.
#
# ## Install the corpus and grader **on the grader side**, outside the repository
#
# Each `chembench.jsonl` row contains the answer in `target` or `target_scores`. A solver could find it inside the repository with one glob.
# Install official code and data under `$HOME/.cache/tgengin-chembench/` (a few MB, small enough for home). Put the venv in `$SCRATCH`: NumPy occupies tens of MB, home has a 15 GB quota, and rerunning this script restores a lost venv.
#
# **This is not isolation.** If the solver's bash shares the machine, `cat` can read the whole answer set. Relocation raises the access barrier slightly; real prevention requires a solver sandbox in the `place` dimension.
set -eu
cd "$(dirname "$0")"

# Pinned versions. **Changing these two lines changes the grading criterion.** Rerun self-tests and record any change in G.md.
REPO=https://github.com/lamalab-org/chembench
COMMIT=45f8bad062fe552810c52be3a328d5da8597ed30       # 2025-09-11 "Fix in extract() (#858)"
HF=jablonkagroup/ChemBench
HF_REV=6e1d25748952393f44e35b8e85bbe567246a6430       # Dataset revision from 2026-04-22: 2785 problems.
TOPICS="analytical_chemistry chemical_preference general_chemistry inorganic_chemistry materials_science organic_chemistry physical_chemistry technical_chemistry toxicity_and_safety"

HOME_DIR="${TGENGIN_CHB_HOME:-$HOME/.cache/tgengin-chembench}"
VENDOR="$HOME_DIR/vendor/chembench"
DATA="$HOME_DIR/chembench.jsonl"
VENV="${TGENGIN_CHB_VENV:-${SCRATCH:-$HOME_DIR}/tgengin-chembench/venv}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-${SCRATCH:-/tmp}/.pip-cache}"

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR" "$HOME_DIR/parquet"

step "0/4 python 3.12"
# Official code requires Python ≥3.10 (syntax such as `dict | None`); system python3 is 3.6. Use the Sherlock module.
# `ml load` may leave 3.6 active in noninteractive shells, so select the binary directly and set LD_LIBRARY_PATH.
PY312=/share/software/user/open/python/3.12.1/bin/python3
if [ -x "$PY312" ]; then
  export LD_LIBRARY_PATH="/share/software/user/open/python/3.12.1/lib:${LD_LIBRARY_PATH:-}"
else
  PY312=$(command -v python3.12 || command -v python3)
fi
"$PY312" -c 'import sys; assert sys.version_info >= (3, 10), sys.version; print("  " + sys.version.split()[0])'

step "1/4 Official code (src/ only; repository reports/ occupies 1.6 GB)"
if [ -d "$VENDOR/.git" ] && [ "$(git -C "$VENDOR" rev-parse HEAD)" = "$COMMIT" ]; then
  echo "  already here: $(git -C "$VENDOR" rev-parse --short HEAD)"
else
  rm -rf "$VENDOR"
  mkdir -p "$(dirname "$VENDOR")"
  git clone --no-checkout --filter=blob:none "$REPO" "$VENDOR" >/dev/null 2>&1
  git -C "$VENDOR" sparse-checkout set src
  git -C "$VENDOR" checkout -q "$COMMIT"
  echo "  checked out $(git -C "$VENDOR" rev-parse --short HEAD)"
fi
[ -f "$VENDOR/src/chembench/prompter.py" ] || { echo "src/chembench/prompter.py is missing after checkout"; exit 1; }

step "2/4 Dataset (HF $HF @ ${HF_REV:0:7}, 9 parquet files, ~530 KB total, ungated)"
for t in $TOPICS; do
  f="$HOME_DIR/parquet/$t.parquet"
  [ -s "$f" ] && continue
  curl -sSL -o "$f" "https://huggingface.co/datasets/$HF/resolve/$HF_REV/$t/train-00000-of-00001.parquet"
  echo "  $t $(stat -c %s "$f") B"
done

step "3/4 venv + dependencies"
# **Install only grading dependencies.** Official pyproject also lists litellm/langchain/torch/transformers/datasets for model execution and BERT refusal detection; grading does not use them.
# Copy the official minimum versions (upstream does not pin these either). pyarrow is needed only for the following parquet conversion.
[ -x "$VENV/bin/python" ] || "$PY312" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null
"$VENV/bin/pip" install -q --only-binary=:all: "numpy==2.2.5" "pandas==2.3.2" "pyarrow==20.0.0" && "$VENV/bin/pip" install -q "pint>=0.23" "fastcore>=1.5.29" "loguru>=0.7.2" "typing_extensions>=4.8"  # glibc 2.17 requires manylinux2014-compatible wheels.
"$VENV/bin/python" - <<'PY'
import fastcore, loguru, numpy, pint, pyarrow
print(f"  numpy {numpy.__version__} | pint {pint.__version__} | fastcore {fastcore.__version__} | loguru {loguru.__version__} | pyarrow {pyarrow.__version__}")
PY

# parquet -> jsonl. Follow official `TaskRegistry.from_huggingface` cleaning: retain only the nonempty field among target/target_scores, and loads the JSON string in target_scores. One problem per line.
if [ -s "$DATA" ] && [ "$(wc -l < "$DATA")" -ge 2785 ]; then
  echo "  jsonl already here: $(wc -l < "$DATA") lines"
else
  HOME_DIR="$HOME_DIR" TOPICS="$TOPICS" "$VENV/bin/python" - <<'PY'
import json, os
from pathlib import Path
import pyarrow.parquet as pq

home = Path(os.environ["HOME_DIR"])
out = home / "chembench.jsonl"
n = 0
with out.open("w", encoding="utf-8") as fh:
    for topic in os.environ["TOPICS"].split():
        rows = pq.read_table(home / "parquet" / f"{topic}.parquet").to_pylist()
        for row in rows:
            exs = row["examples"]
            if len(exs) != 1:  # Official data has exactly one example per task; reject deviations rather than silently accepting them.
                raise SystemExit(f"{row['uuid']} has {len(exs)} examples")
            ex = exs[0]
            example = {"input": ex["input"]}
            if ex.get("target") is not None:
                example["target"] = ex["target"]
            if ex.get("target_scores") is not None:
                example["target_scores"] = json.loads(ex["target_scores"])
            fh.write(json.dumps({
                "uuid": row["uuid"], "topic": topic, "name": row["name"], "keywords": row["keywords"],
                "metrics": row["metrics"], "preferred_score": row["preferred_score"],
                "relative_tolerance": row.get("relative_tolerance"),  # HF lacks this field, so it is always None and the official grader uses 1%.
                "example": example,
            }, ensure_ascii=False) + "\n")
            n += 1
print(f"  wrote {n} items to {out}")
PY
fi

step "4/4 Self-test: official grader loading and correctness"
TGENGIN_CHB_HOME="$HOME_DIR" "$VENV/bin/python" stand.py --selftest

echo
echo "Ready. Start the service on a compute node, not a login node:"
echo "  cd $(pwd) && TGENGIN_CHB_HOME=$HOME_DIR $VENV/bin/python stand.py --level 1"
