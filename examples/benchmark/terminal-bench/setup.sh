#!/usr/bin/env bash
# Prepare everything this example needs. **Idempotent**: safe to run repeatedly.
#
#   bash examples/benchmark/terminal-bench/setup.sh [count] [seed]
#
# **Run on a machine with Docker installed** (WSL here, as for deepswe):
#
#   wsl.exe -- bash /mnt/<drive>/<repository-path>/examples/benchmark/terminal-bench/setup.sh 10 0
#
# Sherlock **has no Docker**, only /bin/apptainer. harbor includes a singularity backend (`--fakeroot --writable-tmpfs`), but this service was written for Docker and has not been tested with Apptainer. Running on an sdev node first requires replacing the Docker commands in stand.py; see “Known issues” in G.md.
#
# Requires Python >= 3.11 (stand.py uses tomllib).
#
# ## Install the corpus **on the service side**, outside the repository
#
# `tasks/<id>/solution/solve.sh` contains reference solutions; a glob would find them inside the repository. Install the entire corpus under `$HOME/.cache/tgengin-terminal-bench/`. **This is not isolation**, however: work containers have network access (official `allow_internet = true`, and test.sh itself needs the network), while reference solutions are public on GitHub.
set -eu
cd "$(dirname "$0")"

HOW_MANY=${1:-10}
SEED=${2:-0}
SELFTEST=${TGENGIN_TB_SELFTEST:-1}

HOME_DIR="$HOME/.cache/tgengin-terminal-bench"
CORPUS="$HOME_DIR/terminal-bench-2-1"
HARBOR="$HOME_DIR/harbor"
RUNTIME="$HOME_DIR/tgengin-runtime-linux-x64"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RUNTIME_SRC=${TGENGIN_RUNTIME_SRC:-$ROOT/dist/tgengin-runtime-linux-x64}

# **Pinned version.** 2.1 is the final 2.x version (89 tasks); upstream is already at 4.0 (66 tasks, a different set,
# with incomparable scores). Changing versions changes the experiment; update G.md along with these two lines.
CORPUS_REPO=https://github.com/harbor-framework/terminal-bench-2-1
CORPUS_COMMIT=7131e4375048a0e408a8fb404b5f499d726b695b
# Vendor harbor only for comparison (`src/harbor/verifier/verifier.py` defines reward parsing); do not import it.
HARBOR_REPO=https://github.com/harbor-framework/harbor
HARBOR_COMMIT=5b9adbe6e51a2faf15ce2c8fa94a8fd2b44ff282

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

step "0/5 docker + python"
[ -x /snap/bin/docker ] && export PATH="/snap/bin:$PATH"
command -v docker >/dev/null || { echo "docker is not on PATH"; exit 1; }
docker version --format '  client {{.Client.Version}} | server {{.Server.Version}}'
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version' || { echo "need python >= 3.11 (tomllib)"; exit 1; }

# Proxy: only when needed, calculating the gateway at runtime (as in deepswe).
if [ -z "${https_proxy:-}" ] && ! curl -sS -o /dev/null -m 8 https://github.com 2>/dev/null; then
  GW=$(ip route | grep '^default' | tr -s ' ' | cut -d' ' -f3)
  PROXY=${TGENGIN_TB_PROXY:-http://$GW:7890}
  export https_proxy="$PROXY" http_proxy="$PROXY"
  echo "  direct is blocked, going through $PROXY"
else
  echo "  network is direct${https_proxy:+ (proxy already set: $https_proxy)}"
fi

# Clone a pinned commit: depth 1 cannot retrieve an arbitrary commit, so init + fetch that specific one.
pin () {  # pin <dir> <repo> <commit>
  local dir=$1 repo=$2 commit=$3
  if [ -d "$dir/.git" ] && [ "$(git -C "$dir" rev-parse HEAD)" = "$commit" ]; then
    echo "  already here: $(git -C "$dir" rev-parse --short HEAD)"
    return
  fi
  rm -rf "$dir"; mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" remote add origin "$repo"
  git -C "$dir" fetch -q --depth 1 origin "$commit"
  git -C "$dir" checkout -q FETCH_HEAD
  echo "  pinned $(git -C "$dir" rev-parse --short HEAD)"
}

step "1/5 Corpus (89 tasks with solution/; install in home, outside the repository)"
pin "$CORPUS" "$CORPUS_REPO" "$CORPUS_COMMIT"
echo "  $(ls -d "$CORPUS"/tasks/*/ | wc -l) task dirs"

step "2/5 harbor (reference only, not imported)"
pin "$HARBOR" "$HARBOR_REPO" "$HARBOR_COMMIT"

step "3/5 Runtime (kernel implementation shared by both sides)"
[ -f "$RUNTIME_SRC" ] || { echo "not built yet: $RUNTIME_SRC (run 'bun run build:runtime' in app/)"; exit 1; }
cp -f "$RUNTIME_SRC" "$RUNTIME"
chmod +x "$RUNTIME"
echo "  $(stat -c %s "$RUNTIME") bytes"

step "4/5 Select tasks + pull images (n=$HOW_MANY seed=$SEED)"
IDS=$(TGENGIN_TB_HOME="$HOME_DIR" python3 -c "
import sys; sys.path.insert(0, '$(pwd)')
import stand
print(' '.join(stand.pick($HOW_MANY, $SEED)))
")
echo "$IDS" | tr ' ' '\n' | sed 's/^/  /'
# One pinned image per task (alexgshaw/<task>:20251031); sizes have not been measured. **Watch disk usage.**
TGENGIN_TB_HOME="$HOME_DIR" python3 stand.py --pull $IDS
docker system df --format '  {{.Type}} {{.Size}}' | head -2

if [ "$SELFTEST" = "0" ]; then
  step "5/5 Self-test: skipped (TGENGIN_TB_SELFTEST=0)"
  echo "  Images are ready; grader unchecked. Before running, execute:"
  echo "  python3 stand.py --selftest <task-id-to-check>"
else
  step "5/5 Self-test: official grader correctness"
  # Two clean containers per task: an empty one should score 0; one that ran the reference solution should score 1.
  # Reference solutions install dependencies online; slow tasks (build-pov-ray, with a 12000-second limit) can take hours each.
  TGENGIN_TB_HOME="$HOME_DIR" python3 stand.py --selftest $IDS
fi

echo
echo "Ready. Start the service on this Docker host:"
echo "  cd $(pwd) && python3 stand.py --level 2"
