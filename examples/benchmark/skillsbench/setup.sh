#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   bash examples/benchmark/skillsbench/setup.sh [几道] [种子]
#
# **在装了 docker 的那台机器上跑**（我们这儿是 WSL）。引擎不必在同一台 —— 它只知道
# 三个 URL。Sherlock 上没有 docker，登录节点又禁 python：在 Sherlock 上这个脚本只能
# 走到第 1 步（clone），后面几步会在 `command -v docker` 那儿停下来。
#
#   wsl.exe -- bash /mnt/<盘>/<仓库路径>/examples/benchmark/skillsbench/setup.sh 10 0
#
# ## 题库装在**台子那一侧**，不在仓库里
#
# `tasks/<id>/oracle/solve.sh` 是参考解，`tasks/<id>/verifier/` 是判据（含 expected_*.json
# 之类的 GT）。放仓库里的话 solver 一个 glob 就够。所以整份 clone 落在
# `$HOME/.cache/tgengin-skillsbench/`。
#
# **但这不是隔离，别当成隔离。** 86/87 道题官方给干活容器的是 `network_mode: public`，
# 而整个 benchmark（含 oracle）在 GitHub 上公开 —— 容器里 `git clone` 一下就是答案。
# 那是官方设定，照官方跑；`stand.py --network none` 是我们的旋钮，开了就不是榜上那个实验。
set -eu
cd "$(dirname "$0")"

HOW_MANY=${1:-10}
SEED=${2:-0}
SELFTEST=${TGENGIN_SKB_SELFTEST:-1}

# **钉死的版本。** tag v1.1 被官方「re-stamped」过一次（registry 说题目内容钉在
# 55bfe693，docs 说 27738384，tag 解出来是 b63b7b28）。我们认 tag 解出来的那个 commit，
# 对不上就停 —— 悄悄跑另一个快照的话，分数和榜单不是同一批题。
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

step "1/5 题库（87 道，含 oracle/ 和 verifier/，所以进家目录不进仓库）"
if [ -d "$REPO/.git" ]; then
  echo "already here: $(git -C "$REPO" rev-parse HEAD)"
else
  # 666 MB（sec-financial-report 一道就 165 MB 数据），--depth 1 已经是最省的了。
  git clone --depth 1 --branch "$TAG" "$UPSTREAM" "$REPO"
fi
HAVE=$(git -C "$REPO" rev-parse HEAD)
if [ "$HAVE" != "$PIN" ]; then
  echo "tag $TAG resolves to $HAVE, but this example is pinned to $PIN"
  echo "  (the tag has been re-stamped before; do not run on an unknown snapshot)"
  exit 1
fi
echo "  $(ls "$REPO/tasks" | wc -l) tasks under tasks/, $(ls "$REPO/tasks-extra" | wc -l) under tasks-extra/ (excluded, as upstream does)"

step "2/5 python 依赖（只要 PyYAML —— 解 task.md 的 frontmatter；判卷依赖各题 test.sh 自己装）"
# 用 uv 建环境，理由同 cmt/setup.sh：WSL 上没 python3-venv，装它要 root。
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

step "4/5 运行时（内核那一份，送进容器给 /place 用）"
[ -f "$RUNTIME_SRC" ] || { echo "not built yet: $RUNTIME_SRC (run 'bun run build:runtime' in app/)"; exit 1; }
cp -f "$RUNTIME_SRC" "$RUNTIME"
chmod +x "$RUNTIME"

step "5/5 建这一跑要的镜像（n=$HOW_MANY seed=$SEED），然后自检"
# 87 个镜像都是从各题 environment/Dockerfile 现 build 的（没有官方 registry），
# build_timeout_sec 最长 3600 秒，两道 bugswarm 题镜像很大 —— 只建点到名的那几道。
IDS=$("$VENV/bin/python" stand.py --pick "$HOW_MANY" "$SEED")
echo "$IDS" | sed 's/^/  /'
# shellcheck disable=SC2086
"$VENV/bin/python" stand.py --build $IDS
if [ "$SELFTEST" != "0" ]; then
  # 每道题：空容器该判 0，跑完官方 oracle/solve.sh 该判 1。装错了在这儿就炸。
  # shellcheck disable=SC2086
  "$VENV/bin/python" stand.py --selftest $IDS
fi

echo
echo "备齐了。台子这么起："
echo "  cd $(pwd) && $VENV/bin/python stand.py --level 2 --skills with"
