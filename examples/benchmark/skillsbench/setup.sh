#!/usr/bin/env bash
# Prepare everything this example needs. **Idempotent**: safe to run repeatedly.
#
#   bash examples/benchmark/skillsbench/setup.sh [count] [seed]
#
# **Run on a machine with Docker installed** (WSL here). The engine may run elsewhere; it only knows three URLs. Sherlock has no Docker and prohibits Python on login nodes, so this script can complete only step 1 (clone) there; subsequent steps stop at `command -v docker`.
#
#   wsl.exe -- bash /mnt/<drive>/<repository-path>/examples/benchmark/skillsbench/setup.sh 10 0
#
# ## Install the dataset **on the service side**, outside the repository
#
# `tasks/<id>/oracle/solve.sh` contains reference solutions and `tasks/<id>/verifier/` contains the grader (including ground truth such as expected_*.json). Inside the repository, a solver could find them with a glob. Clone the entire repository under `$HOME/.cache/tgengin-skillsbench/`.
#
# **This is not isolation; do not treat it as such.** The official work containers use `network_mode: public` for 86/87 tasks, and the whole benchmark (including oracle) is public on GitHub. A `git clone` inside the container obtains the answers. Follow that official configuration; `stand.py --network none` is our own control, and enabling it changes the experiment from the leaderboard’s.
set -eu
cd "$(dirname "$0")"

HOW_MANY=${1:-10}
SEED=${2:-0}
SELFTEST=${TGENGIN_SKB_SELFTEST:-1}

# **Pinned version.** The official v1.1 tag was re-stamped once (the registry says task content is pinned to
# 55bfe693, docs say 27738384, and the tag resolves to b63b7b28). Use the commit resolved by the tag and stop
# on any mismatch: silently running another snapshot would make scores refer to different tasks than the leaderboard.
TAG=v1.1
PIN=b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af
UPSTREAM=https://github.com/benchflow-ai/skillsbench

HOME_DIR="$HOME/.cache/tgengin-skillsbench"
REPO="$HOME_DIR/skillsbench"
VENV="$HOME_DIR/venv"
RUNTIME="$HOME_DIR/tgengin-runtime-linux-x64"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RUNTIME_SRC=${TGENGIN_RUNTIME_SRC:-$ROOT/dist/tgengin-runtime-linux-x64}

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

step "1/5 Dataset (87 tasks with oracle/ and verifier/; install in home, outside the repository)"
if [ -d "$REPO/.git" ]; then
  echo "already here: $(git -C "$REPO" rev-parse HEAD)"
else
  # 666 MB (sec-financial-report alone contains 165 MB of data); --depth 1 already minimizes the clone.
  git clone --depth 1 --branch "$TAG" "$UPSTREAM" "$REPO"
fi
HAVE=$(git -C "$REPO" rev-parse HEAD)
if [ "$HAVE" != "$PIN" ]; then
  echo "tag $TAG resolves to $HAVE, but this example is pinned to $PIN"
  echo "  (the tag has been re-stamped before; do not run on an unknown snapshot)"
  exit 1
fi
echo "  $(ls "$REPO/tasks" | wc -l) tasks under tasks/, $(ls "$REPO/tasks-extra" | wc -l) under tasks-extra/ (excluded, as upstream does)"

step "2/5 Python dependencies (PyYAML for task.md frontmatter only; each test.sh installs its own grading dependencies)"
# Create the environment with uv, as in cmt/setup.sh: WSL lacks python3-venv, and installing it requires root.
if ! command -v uv >/dev/null 2>&1; then export PATH="$HOME/.local/bin:$PATH"; fi
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
  export PATH="$HOME/.local/bin:$PATH"
fi
[ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV" >/dev/null
VIRTUAL_ENV="$VENV" uv pip install -q "pyyaml==6.0.2"
"$VENV/bin/python" -c 'import yaml; print(f"  pyyaml {yaml.__version__}")'

step "3/5 docker"
[ -x /snap/bin/docker ] && export PATH="/snap/bin:$PATH"
command -v docker >/dev/null || { echo "docker is not on PATH (on Sherlock there is none: run the rest on the WSL box)"; exit 1; }
docker version --format '  client {{.Client.Version}} | server {{.Server.Version}}'

step "4/5 Runtime (kernel implementation, copied into containers for /place)"
[ -f "$RUNTIME_SRC" ] || { echo "not built yet: $RUNTIME_SRC (run 'bun run build:runtime' in app/)"; exit 1; }
cp -f "$RUNTIME_SRC" "$RUNTIME"
chmod +x "$RUNTIME"

step "5/5 Build selected images (n=$HOW_MANY seed=$SEED), then self-test"
# All 87 images are built from their task’s environment/Dockerfile (there is no official registry).
# build_timeout_sec reaches 3600 seconds, and the two bugswarm images are large; build only the selected tasks.
IDS=$("$VENV/bin/python" stand.py --pick "$HOW_MANY" "$SEED")
echo "$IDS" | sed 's/^/  /'
# shellcheck disable=SC2086
"$VENV/bin/python" stand.py --build $IDS
if [ "$SELFTEST" != "0" ]; then
  # For each task, an empty container must score 0 and the official oracle/solve.sh must score 1. A faulty installation fails here.
  # shellcheck disable=SC2086
  "$VENV/bin/python" stand.py --selftest $IDS
fi

echo
echo "Ready. Start the service:"
echo "  cd $(pwd) && $VENV/bin/python stand.py --level 2 --skills with"
