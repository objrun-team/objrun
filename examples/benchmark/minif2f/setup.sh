#!/usr/bin/env bash
# Prepare everything this example needs. **Idempotent**: safe to run repeatedly.
#
#   bash examples/benchmark/minif2f/setup.sh
#
# **Run on the machine that can execute Lean.** On Sherlock, use an sdev / sbatch compute node, **not a login node** (`lake build` of Mathlib uses several cores for tens of minutes; `lake exe cache get` downloads about 5 GB):
#
#   sdev -c 8 -m 32GB -t 02:00:00
#   ml python/3.12.1
#   bash examples/benchmark/minif2f/setup.sh
#
# The engine may run elsewhere; it only knows three URLs.
#
# ## Install everything **on the service side**, outside the repository
#
# Install under `$TGENGIN_MF2F_HOME` (default `$HOME/.cache/tgengin-minif2f`). Sherlock limits `$HOME` to 15 GB, while Mathlib .olean files alone occupy 5–6 GB. On machines with `$SCRATCH`, store the actual files at `$SCRATCH/tgengin-minif2f` and make `$HOME/.cache/tgengin-minif2f` a link. **`$SCRATCH` files unchanged for 90 days are deleted**; rerun this script if that happens.
#
# ## All versions are pinned; change none of them
#
# Changing any version makes scores incomparable with Kimina’s table and breaks the self-test that replays Kimina’s published proofs.
set -eu
cd "$(dirname "$0")"

LEAN_VERSION=v4.15.0                                            # lean-toolchain for Kimina’s public proofs.
MATHLIB_TAG=v4.15.0                                             # = 9837ca9d65d9de6fad1ef4381750ca688774e608
MATHLIB_REV=9837ca9d65d9de6fad1ef4381750ca688774e608
REPL_TAG=v4.15.0                                                # leanprover-community/repl，= 21966799da36…
KIMINA_SERVER_REV=fb2393de3461db35eda4c714e3fd21187e92ec90      # project-numina/kimina-lean-server (only client/ is used).
KIMINA_PREVIEW_REV=7abd61a5d9861bf5c15b195c216c1bb233ac32e4     # MoonshotAI/Kimina-Prover-Preview (golden proof zip).
DSP_REV=2c4ba9119eef74d0d611f494261b2c5bae98c69a                # deepseek-ai/DeepSeek-Prover-V1.5 (244 validation tasks).
AIMO_SHA=5def318348521dfc34875045a9ecddf729a2b49f               # HF AI-MO/minif2f_test (244 test tasks, corrected version).
AIMO_HEADER=$'import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n'

if [ -z "${TGENGIN_MF2F_HOME:-}" ] && [ -n "${SCRATCH:-}" ]; then
  REAL="$SCRATCH/tgengin-minif2f"
  LINK="$HOME/.cache/tgengin-minif2f"
  mkdir -p "$REAL" "$HOME/.cache"
  [ -e "$LINK" ] || ln -s "$REAL" "$LINK"
  HOME_DIR="$LINK"
else
  HOME_DIR="${TGENGIN_MF2F_HOME:-$HOME/.cache/tgengin-minif2f}"
fi
mkdir -p "$HOME_DIR/vendor" "$HOME_DIR/golden"
VENDOR="$HOME_DIR/vendor"

step () { echo; echo "── $* ──"; }

step "0/7 Check this host"
if [ -z "${SLURM_JOB_ID:-}" ] && [ -x /usr/bin/sbatch ] && [ "${TGENGIN_MF2F_FORCE:-0}" != "1" ]; then
  echo "this looks like a Slurm login node - run inside sdev/sbatch (TGENGIN_MF2F_FORCE=1 to override)"; exit 1
fi
for c in curl git jq python3 unzip; do command -v "$c" >/dev/null || { echo "$c is not on PATH"; exit 1; }; done
echo "  install root: $HOME_DIR"

step "1/7 elan + Lean $LEAN_VERSION"
# Install elan inside the service directory; leave ~/.elan and ~/.bashrc untouched (slow paths in Sherlock .bashrc can stall login).
export ELAN_HOME="$HOME_DIR/elan"
export PATH="$ELAN_HOME/bin:$PATH"
if ! [ -x "$ELAN_HOME/bin/elan" ]; then
  curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- --default-toolchain "$LEAN_VERSION" --no-modify-path -y
fi
elan toolchain install "leanprover/lean4:$LEAN_VERSION" 2>/dev/null || true
elan default "leanprover/lean4:$LEAN_VERSION"
# The bundled clang requires glibc >= 2.27 (libLLVM-15 / libc++abi), while CentOS 7 has 2.17. `lean` itself runs
# (with its bundled glibc and static libraries), but leanc C compilation and REPL linking fail. `LEAN_CC=gcc` was tried: .c.o compiles, but linking lacks
# -lc++ -lc++abi -lgmp -luv, and the bundled libc++abi also needs glibc 2.18 at runtime. This route failed (2026-09-25).
# Use a container on older glibc: `runs/minif2f-setup-apptainer.sbatch` (python:3.12-bookworm, glibc 2.36).
# Run all of setup.sh and subsequent stand.py inside it. All 4 setup steps and 5/5 self-tests passed in testing.
TOOLCHAIN_BIN="$ELAN_HOME/toolchains/leanprover--lean4---$LEAN_VERSION/bin"
if ! "$TOOLCHAIN_BIN/clang" --version >/dev/null 2>&1; then
  echo "the toolchain's clang cannot run on this glibc ($(ldd --version | head -1 | grep -oE '[0-9.]+$'));"
  echo "REPL will not link. Run this script inside a newer-glibc container: runs/minif2f-setup-apptainer.sbatch"
  exit 1
fi
lean --version || { echo "lean binary does not run here (old glibc?) - see Known issues in G.md"; exit 1; }

step "2/7 Lean REPL $REPL_TAG"
if [ ! -d "$HOME_DIR/repl/.git" ]; then
  git clone --branch "$REPL_TAG" --single-branch --depth 1 https://github.com/leanprover-community/repl "$HOME_DIR/repl"
fi
( cd "$HOME_DIR/repl" && lake build 2>&1 | tail -2 )
[ -x "$HOME_DIR/repl/.lake/build/bin/repl" ] || { echo "repl did not build"; exit 1; }

step "3/7 Mathlib $MATHLIB_TAG (cache get downloads several GB of .olean; lake build should then have nothing to do)"
if [ ! -d "$HOME_DIR/mathlib4/.git" ]; then
  git clone --branch "$MATHLIB_TAG" --single-branch --depth 1 https://github.com/leanprover-community/mathlib4 "$HOME_DIR/mathlib4"
fi
( cd "$HOME_DIR/mathlib4"
  [ "$(git rev-parse HEAD)" = "$MATHLIB_REV" ] || { echo "mathlib4 is at $(git rev-parse HEAD), expected $MATHLIB_REV"; exit 1; }
  lake exe cache get 2>&1 | tail -2
  lake build 2>&1 | tail -2 )

step "4/7 Official grading code (kimina-lean-server @ ${KIMINA_SERVER_REV:0:8}; only client/kimina_client/models.py)"
fetch_rev () {  # Name, URL, commit: shallow-clone, then fetch that specific SHA; pin the SHA, not a branch.
  local d="$VENDOR/$1"
  if [ ! -d "$d/.git" ]; then git clone --depth 1 "$2" "$d"; fi
  ( cd "$d" && [ "$(git rev-parse HEAD)" = "$3" ] || { git fetch --depth 1 origin "$3" && git checkout -q "$3"; } )
  echo "  $1 @ $(git -C "$d" rev-parse --short HEAD)"
}
fetch_rev kimina-lean-server https://github.com/project-numina/kimina-lean-server "$KIMINA_SERVER_REV"
fetch_rev Kimina-Prover-Preview https://github.com/MoonshotAI/Kimina-Prover-Preview "$KIMINA_PREVIEW_REV"

step "5/7 Dataset (test: AI-MO corrected @ ${AIMO_SHA:0:7}; valid: DeepSeek-Prover-V1.5 @ ${DSP_REV:0:7})"
GOT_SHA=$(curl -sSL "https://huggingface.co/api/datasets/AI-MO/minif2f_test" | jq -r .sha)
[ "$GOT_SHA" = "$AIMO_SHA" ] || { echo "AI-MO/minif2f_test moved to $GOT_SHA (pinned $AIMO_SHA) - review the diff before re-pinning"; exit 1; }
TMP=$(mktemp -d)
for o in 0 100 200; do
  curl -sSL "https://datasets-server.huggingface.co/rows?dataset=AI-MO/minif2f_test&config=default&split=train&offset=$o&length=100" > "$TMP/rows_$o.json"
done
curl -sSL "https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Prover-V1.5/$DSP_REV/datasets/minif2f.jsonl" > "$TMP/dsp.jsonl"
# Store header, problem-statement comments, and declaration separately. **The declaration is `theorem … := by\n`**; the service compares it with the candidate.
jq -c --arg h "$AIMO_HEADER" '.rows[].row | .informal_prefix as $p | .formal_statement as $f
  | {id: ("test/" + .name), name, split: "test", header: $h, informal: $p, statement: ($f | ltrimstr($h + $p))}' \
  "$TMP/rows_0.json" "$TMP/rows_100.json" "$TMP/rows_200.json" > "$TMP/test.jsonl"
jq -c 'select(.split == "valid") | {id: ("valid/" + .name), name, split, header, informal: .informal_prefix, statement: .formal_statement}' \
  "$TMP/dsp.jsonl" > "$TMP/valid.jsonl"
NT=$(wc -l < "$TMP/test.jsonl"); NV=$(wc -l < "$TMP/valid.jsonl")
[ "$NT" = 244 ] && [ "$NV" = 244 ] || { echo "expected 244 + 244, got $NT + $NV"; exit 1; }
BAD=$(jq -r '[.statement | startswith("theorem ") and test(":= by\\s*$")] | .[]' "$TMP/test.jsonl" "$TMP/valid.jsonl" | grep -c false || true)
[ "$BAD" = 0 ] || { echo "$BAD statements do not look like 'theorem … := by'"; exit 1; }
cat "$TMP/test.jsonl" "$TMP/valid.jsonl" > "$HOME_DIR/problems.jsonl"
rm -rf "$TMP"
echo "  $(wc -l < "$HOME_DIR/problems.jsonl") problems -> $HOME_DIR/problems.jsonl"

step "6/7 Golden proofs (Kimina public 197 + 29, for self-tests only)"
for z in minif2f_test_solved.zip minif2f_test_solved_filtered_0710.zip; do
  unzip -qo "$VENDOR/Kimina-Prover-Preview/$z" -d "$HOME_DIR/golden/_zip"
done
find "$HOME_DIR/golden/_zip" -name '*.lean' -path '*/src/*' -exec cp -f {} "$HOME_DIR/golden/" \;
rm -rf "$HOME_DIR/golden/_zip"
echo "  $(ls "$HOME_DIR/golden"/*.lean | wc -l) golden proofs"

step "7/7 venv (only the four packages required by kimina_client.models) + self-test"
if [ ! -x "$HOME_DIR/venv/bin/python" ]; then python3 -m venv "$HOME_DIR/venv"; fi
PIP_CACHE_DIR="${PIP_CACHE_DIR:-$HOME_DIR/pip-cache}" "$HOME_DIR/venv/bin/pip" install -q pydantic pygments colorama tabulate typing_extensions
# Check REPL connectivity with one `#eval`, using the same path as the service (lake env repl in the mathlib4 directory).
( cd "$HOME_DIR/mathlib4" && printf '{"cmd": "import Mathlib\\n#eval 1 + 1"}\n\n' | timeout 600 lake env "$HOME_DIR/repl/.lake/build/bin/repl" | head -20 )
if [ "${TGENGIN_MF2F_SELFTEST:-1}" = 1 ]; then
  TGENGIN_MF2F_HOME="$HOME_DIR" "$HOME_DIR/venv/bin/python" stand.py --selftest
fi

echo
echo "done. start the stand with:"
echo "  export ELAN_HOME=$ELAN_HOME PATH=$ELAN_HOME/bin:\$PATH TGENGIN_MF2F_HOME=$HOME_DIR"
echo "  $HOME_DIR/venv/bin/python $(pwd)/stand.py --level 1"
