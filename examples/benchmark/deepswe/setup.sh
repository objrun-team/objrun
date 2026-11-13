#!/usr/bin/env bash
# Prepare this example's dependencies. **Idempotent**; safe to rerun.
#
#   bash examples/benchmark/deepswe/setup.sh [count] [seed]
#
# **Run on the Docker host.** The engine may run elsewhere and knows only three URLs. For a Windows engine with Docker in WSL:
#
#   wsl.exe -- bash /mnt/<drive>/<repository-path>/examples/benchmark/deepswe/setup.sh 10 0
#
# **Derive every path from this script's location**; the repository location and name are irrelevant.
#
# ## Install the corpus **on the grader side**, outside the repository
#
# `tasks/<id>/solution/solution.patch` is the reference solution. A repository copy is one glob away, so install the corpus under `$HOME/.cache/tgengin-deepswe/` in WSL.
#
# **Relocation is not isolation.** The actual protection is the working container's --network none and inability to reach that directory. Moving the path only adds a small access barrier.
set -eu
cd "$(dirname "$0")"

HOW_MANY=${1:-10}
SEED=${2:-0}
# **Whether to run self-tests.** Each problem is graded twice (reference solution and empty patch); slow cases take 5.5 minutes per grading pass, so all 113 take hours. Set 0 when only preparing images.
SELFTEST=${TGENGIN_DSW_SELFTEST:-1}

HOME_DIR="$HOME/.cache/tgengin-deepswe"
REPO="$HOME_DIR/deep-swe"
RUNTIME="$HOME_DIR/tgengin-runtime-linux-x64"
# Repository root is three levels above this script (examples/benchmark/deepswe/). **No hard-coded absolute paths.**
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# The runtime is the binary built by bun run build:runtime. **Copy it under home**: snap Docker cannot access /mnt or /tmp; docker cp /tmp/... was observed to fail with lstat no such file.
RUNTIME_SRC=${TGENGIN_RUNTIME_SRC:-$ROOT/dist/tgengin-runtime-linux-x64}

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

step "0/5 docker"
# **Extend PATH explicitly.** snap Docker is on the login-shell PATH, but this script usually runs in a non-login shell and would otherwise report command not found throughout. Other Docker installations are unaffected.
[ -x /snap/bin/docker ] && export PATH="/snap/bin:$PATH"
command -v docker >/dev/null || { echo "docker is not on PATH"; exit 1; }
docker version --format '  client {{.Client.Version}} | server {{.Server.Version}}'

# Proxy only **when necessary**. NAT-mode WSL cannot reach the host proxy at 127.0.0.1; use the gateway, recomputing it because it changes after reboot.
#
# Do nothing if direct connectivity already works. Set TGENGIN_DSW_PROXY explicitly to choose another proxy.
if [ -z "${https_proxy:-}" ] && ! curl -sS -o /dev/null -m 8 https://github.com 2>/dev/null; then
  GW=$(ip route | grep '^default' | tr -s ' ' | cut -d' ' -f3)
  PROXY=${TGENGIN_DSW_PROXY:-http://$GW:7890}
  export https_proxy="$PROXY" http_proxy="$PROXY"
  echo "  direct is blocked, going through $PROXY"
else
  echo "  network is direct${https_proxy:+ (proxy already set: $https_proxy)}"
fi

step "1/5 Corpus (113 tasks, including solution/; install in home, outside the repository)"
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" fetch --depth 1 origin >/dev/null 2>&1 || true
  echo "already here: $(git -C "$REPO" rev-parse --short HEAD), $(ls "$REPO/tasks" | grep -cv README) tasks"
else
  git clone --depth 1 https://github.com/datacurve-ai/deep-swe "$REPO"
  echo "cloned $(git -C "$REPO" rev-parse --short HEAD), $(ls "$REPO/tasks" | grep -cv README) tasks"
fi

step "2/5 Runtime (the kernel’s implementation, shared by both sides)"
[ -f "$RUNTIME_SRC" ] || { echo "not built yet: $RUNTIME_SRC (run 'bun run build:runtime' in app/)"; exit 1; }
cp -f "$RUNTIME_SRC" "$RUNTIME"
chmod +x "$RUNTIME"
echo "  $(stat -c %s "$RUNTIME") bytes"

step "3/5 Select tasks (n=$HOW_MANY seed=$SEED)"
# Use the same problem-selection rule as the grader and sender to avoid independent implementations drifting.
IDS=$(TGENGIN_DSW_HOME="$HOME_DIR" python3 -c "
import sys; sys.path.insert(0, '$(pwd)')
import stand
print(' '.join(stand.pick($HOW_MANY, $SEED)))
")
echo "$IDS" | tr ' ' '\n' | sed 's/^/  /'

step "4/5 Pull task images + build grader images"
# One pinned image per problem (3.7–9.9 GB), with a thin grading layer on top.
TOTAL=$(echo "$IDS" | wc -w); N=0
for t in $IDS; do
  N=$((N + 1))
  img=$(sed -n 's/^docker_image = "\(.*\)"/\1/p' "$REPO/tasks/$t/task.toml")
  if docker image inspect "$img" >/dev/null 2>&1; then
    what=have
  else
    what=pull
    docker pull -q "$img" >/dev/null
  fi
  # **Let stand.py build grader images.** Tags use fingerprints of tests/ files. Duplicated rules could build by name here but look up by fingerprint there, rebuilding on every grading request.
  TGENGIN_DSW_HOME="$HOME_DIR" python3 stand.py --build "$t" >/dev/null
  # **Monitor disk space.** Images occupy 3.7–9.9 GB per problem; detect insufficient capacity for all 113 before filling the disk.
  echo "  [$N/$TOTAL] $what  $t  (images $(docker system df --format '{{.Size}}' | head -1), free $(df -h / | tail -1 | tr -s ' ' | cut -d' ' -f4))"
done
docker system df --format '  {{.Type}} {{.Size}}' | head -2

if [ "$SELFTEST" = "0" ]; then
  step "5/5 Self-test: skipped (TGENGIN_DSW_SELFTEST=0)"
  echo "  Images are ready; grader unchecked. Before running, execute:"
  echo "  python3 stand.py --selftest <task-id-to-check>"
else
  step "5/5 Self-test: official grader correctness"
  # The official grader must accept each problem's reference solution and reject an empty patch. **Fail here on an invalid installation**, before completing a benchmark run.
  TGENGIN_DSW_HOME="$HOME_DIR" python3 stand.py --selftest $IDS
fi

echo
echo "Ready. Start the service on this Docker host:"
echo "  cd $(pwd) && python3 stand.py --level 2"
