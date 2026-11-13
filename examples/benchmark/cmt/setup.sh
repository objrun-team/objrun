#!/usr/bin/env bash
# Prepare this example's dependencies. **Idempotent**; safe to rerun.
#
#   ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt/setup.sh"
#
# Run the grader in WSL because the official code requires Python ≥3.12 and Windows has only the Store stub. The Windows engine sees just a URL and does not depend on the grader's machine.
#
# ## Install corpus and grader **on the grader side**, outside the repository
#
# The solver has read/glob/bash, and `place: local` is the engine machine. A repository corpus would be one glob and read away from GT.
#
# **This was observed**: the model read grader.py, then the official parser, then found cmt_data.jsonl with glob. The run ended before it read GT, but the route was found. Install all three components under `$HOME/.cache/tgengin-cmt/` in WSL.
#
# **This is not isolation.** Windows system32 contains wsl.exe; `wsl.exe -- head ~/.cache/tgengin-cmt/cmt_data.jsonl` retrieves the data, as observed. Containers remain reachable through `wsl.exe -- docker exec`. Paths change, not reachability: host-based solver bash can reach anything the host can.
#
# These routes are **deliberately retained**: access now takes three steps rather than one glob, considered a sufficient barrier here. Full isolation requires a solver sandbox in the `place` dimension; see the README section on genuine solver isolation.
#
# This script is the **non-container** route. With Docker, use compose.yaml instead; choose one route.
set -eu
cd "$(dirname "$0")"

DATA_URL=https://huggingface.co/datasets/JVRoggeveen/cmt_benchmark/resolve/main/cmt_data.jsonl
HARNESS=https://github.com/JamesRoggeveen/cmt_benchmark_data
HOME_DIR="$HOME/.cache/tgengin-cmt"
VENV="$HOME_DIR/venv"
DATA="$HOME_DIR/cmt_data.jsonl"
VENDOR="$HOME_DIR/vendor/cmt_benchmark_data"

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

step "0/3 Remove old copies remaining in the repository"
for stale in cmt_data.jsonl vendor; do
  if [ -e "$stale" ]; then
    rm -rf "$stale"
    echo "Removed repository copy $stale: it was accessible to the solver"
  fi
done
echo "oracle exists only under $HOME_DIR"

step "1/3 Dataset"
if [ -f "$DATA" ]; then
  echo "Existing rows: $(wc -l < "$DATA") rows"
else
  curl -sSL -o "$DATA" "$DATA_URL"
  echo "Downloaded rows: $(wc -l < "$DATA") rows"
fi

step "2/3 Official grading code"
if [ -d "$VENDOR/.git" ]; then
  echo "Already have $(git -C "$VENDOR" rev-parse --short HEAD)"
else
  mkdir -p "$(dirname "$VENDOR")"
  git clone --depth 1 "$HARNESS" "$VENDOR"
  echo "Cloned commit $(git -C "$VENDOR" rev-parse --short HEAD)"
fi

step "3/3 Python dependencies"
# Use uv rather than `python3 -m venv`: this WSL installation lacks python3.12-venv/ensurepip, and installing it needs root. uv is a static executable runnable from ~/.local/bin and manages Python and pip itself.
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "Install uv (no root required)"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "uv $(uv --version | awk '{print $2}')"

# **Install only the three grading dependencies.** Official pyproject also lists openai/anthropic/google-genai/datasets/matplotlib for model execution and plotting, not grading. Copy the official pins to preserve score comparability.
[ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV" >/dev/null
VIRTUAL_ENV="$VENV" uv pip install -q \
  "sympy==1.13.3" "numpy==2.2.5" "regex==2024.11.6"
"$VENV/bin/python" - <<'PY'
import sympy, numpy, regex
print(f"sympy {sympy.__version__}｜numpy {numpy.__version__}｜regex {regex.__version__}")
PY

step "Self-test: official grader loading and correctness"
"$VENV/bin/python" grader.py --selftest

echo
echo "Ready. Start the grading service:"
echo "  ssh wsl \"cd $(pwd) && $VENV/bin/python grader.py\""
