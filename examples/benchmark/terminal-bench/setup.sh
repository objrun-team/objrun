#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   bash examples/benchmark/terminal-bench/setup.sh [几道] [种子]
#
# **在装了 docker 的那台机器上跑**（我们这台是 WSL，同 deepswe）：
#
#   wsl.exe -- bash /mnt/<盘>/<仓库路径>/examples/benchmark/terminal-bench/setup.sh 10 0
#
# Sherlock 上**没有 docker**（只有 /bin/apptainer）。harbor 自带一个 singularity 后端
# （`--fakeroot --writable-tmpfs`），但这个台子是按 docker 写的，没在 apptainer 上试过 ——
# 要在 sdev 节点上跑得先把 stand.py 里的 docker 命令换掉，见 G.md「已知坑」。
#
# 需要 python >= 3.11（stand.py 用 tomllib）。
#
# ## 语料装在**台子那一侧**，不在仓库里
#
# `tasks/<id>/solution/solve.sh` 是参考解，放仓库里一个 glob 就够。所以整份语料装在
# `$HOME/.cache/tgengin-terminal-bench/`。**但这不是隔离**：干活的容器有网（官方
# `allow_internet = true`，而且 test.sh 自己要上网），参考解就公开在 GitHub 上。
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

# **钉死的版本。** 2.1 是 2.x 的最后一版（89 道）；上游已经到 4.0（66 道，另一个题集，
# 分数不可比）。换版本 = 换实验，改这两行要连 G.md 一起改。
CORPUS_REPO=https://github.com/harbor-framework/terminal-bench-2-1
CORPUS_COMMIT=7131e4375048a0e408a8fb404b5f499d726b695b
# harbor 只 vendor 来对照（`src/harbor/verifier/verifier.py` 是 reward 的读法），不 import。
HARBOR_REPO=https://github.com/harbor-framework/harbor
HARBOR_COMMIT=5b9adbe6e51a2faf15ce2c8fa94a8fd2b44ff282

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

step "0/5 docker + python"
[ -x /snap/bin/docker ] && export PATH="/snap/bin:$PATH"
command -v docker >/dev/null || { echo "docker is not on PATH"; exit 1; }
docker version --format '  client {{.Client.Version}} | server {{.Server.Version}}'
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version' || { echo "need python >= 3.11 (tomllib)"; exit 1; }

# 代理：只在需要的时候，网关现算（同 deepswe）。
if [ -z "${https_proxy:-}" ] && ! curl -sS -o /dev/null -m 8 https://github.com 2>/dev/null; then
  GW=$(ip route | grep '^default' | tr -s ' ' | cut -d' ' -f3)
  PROXY=${TGENGIN_TB_PROXY:-http://$GW:7890}
  export https_proxy="$PROXY" http_proxy="$PROXY"
  echo "  direct is blocked, going through $PROXY"
else
  echo "  network is direct${https_proxy:+ (proxy already set: $https_proxy)}"
fi

# 钉 commit 的 clone：depth 1 拿不到任意 commit，所以 init + fetch 那一个。
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

step "1/5 语料（89 道题，含 solution/，所以进家目录不进仓库）"
pin "$CORPUS" "$CORPUS_REPO" "$CORPUS_COMMIT"
echo "  $(ls -d "$CORPUS"/tasks/*/ | wc -l) task dirs"

step "2/5 harbor（只对照，不 import）"
pin "$HARBOR" "$HARBOR_REPO" "$HARBOR_COMMIT"

step "3/5 运行时（内核那一份，一份实现两边通用）"
[ -f "$RUNTIME_SRC" ] || { echo "not built yet: $RUNTIME_SRC (run 'bun run build:runtime' in app/)"; exit 1; }
cp -f "$RUNTIME_SRC" "$RUNTIME"
chmod +x "$RUNTIME"
echo "  $(stat -c %s "$RUNTIME") bytes"

step "4/5 点名 + 拉镜像（n=$HOW_MANY seed=$SEED）"
IDS=$(TGENGIN_TB_HOME="$HOME_DIR" python3 -c "
import sys; sys.path.insert(0, '$(pwd)')
import stand
print(' '.join(stand.pick($HOW_MANY, $SEED)))
")
echo "$IDS" | tr ' ' '\n' | sed 's/^/  /'
# 一道题一个钉死的镜像（alexgshaw/<题>:20251031），大小没量过 —— **盘要看着。**
TGENGIN_TB_HOME="$HOME_DIR" python3 stand.py --pull $IDS
docker system df --format '  {{.Type}} {{.Size}}' | head -2

if [ "$SELFTEST" = "0" ]; then
  step "5/5 自检：跳过（TGENGIN_TB_SELFTEST=0）"
  echo "  镜像备齐了，判据没验。跑之前补一句："
  echo "  python3 stand.py --selftest <要验的题号>"
else
  step "5/5 自检：官方判据说得对不对"
  # 每道题两个干净容器：空的该判 0，跑过参考解的该判 1。
  # 参考解要上网装东西，慢的（build-pov-ray 12000 秒上限）一道就是几个钟头。
  TGENGIN_TB_HOME="$HOME_DIR" python3 stand.py --selftest $IDS
fi

echo
echo "备齐了。台子这么起（就在这台有 docker 的机器上）："
echo "  cd $(pwd) && python3 stand.py --level 2"
