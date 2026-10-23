#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   bash examples/benchmark/deepswe/setup.sh [几道] [种子]
#
# **在装了 docker 的那台机器上跑**。引擎不必在同一台 —— 它只知道三个 URL。
# 我们这台是 Windows 上的引擎 + WSL 里的 docker，于是那边这么叫：
#
#   wsl.exe -- bash /mnt/<盘>/<仓库路径>/examples/benchmark/deepswe/setup.sh 10 0
#
# **路径全从这个脚本自己的位置推**，一处都不写死 —— 仓库放哪儿、叫什么名字，
# 跟这个例子无关。
#
# ## 语料装在**台子那一侧**，不在仓库里
#
# `tasks/<id>/solution/solution.patch` 是参考解。放仓库里的话，一个 glob 就够。
# 所以整份语料装在 `$HOME/.cache/tgengin-deepswe/`（WSL 家目录）。
#
# **但这不是隔离，别当成隔离** —— 干活的容器是 `--network none`，它够不着这个
# 目录也够不着网，那才是拦住它的东西。路径只是把门槛抬高一格。
set -eu
cd "$(dirname "$0")"

HOW_MANY=${1:-10}
SEED=${2:-0}
# **自检要不要跑。** 一道题两次判卷（参考解一次、空补丁一次），慢的那几道一次五分半
# —— 全量 113 道要跑几个钟头。只是想把镜像备齐的话设成 0。
SELFTEST=${TGENGIN_DSW_SELFTEST:-1}

HOME_DIR="$HOME/.cache/tgengin-deepswe"
REPO="$HOME_DIR/deep-swe"
RUNTIME="$HOME_DIR/tgengin-runtime-linux-x64"
# 仓库根 = 这个脚本往上三层（examples/benchmark/deepswe/）。**不写死绝对路径。**
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# 运行时是 `bun run build:runtime` 编出来的那个二进制。**得拷进家目录**：
# snap 装的 docker 够不着 /mnt 和 /tmp（实测 `docker cp /tmp/…` 报 lstat no such file）。
RUNTIME_SRC=${TGENGIN_RUNTIME_SRC:-$ROOT/dist/tgengin-runtime-linux-x64}

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

step "0/5 docker"
# **PATH 得自己补。** snap 装的 docker 只在登录 shell 的 PATH 上，而这个脚本多半是被
# 非登录 shell 叫起来的 —— 不补的话下面每一条都是 command not found。别处装的不受影响。
[ -x /snap/bin/docker ] && export PATH="/snap/bin:$PATH"
command -v docker >/dev/null || { echo "docker is not on PATH"; exit 1; }
docker version --format '  client {{.Client.Version}} | server {{.Server.Version}}'

# 代理：**只在需要的时候**。WSL 在 NAT 模式下够不着宿主机那个 127.0.0.1 的代理，
# 得走网关，而**网关每次重启会变**，所以现算，不写死。
#
# 已经能直连的机器上这一段什么都不干。要指到别处就先 `export TGENGIN_DSW_PROXY=…`。
if [ -z "${https_proxy:-}" ] && ! curl -sS -o /dev/null -m 8 https://github.com 2>/dev/null; then
  GW=$(ip route | grep '^default' | tr -s ' ' | cut -d' ' -f3)
  PROXY=${TGENGIN_DSW_PROXY:-http://$GW:7890}
  export https_proxy="$PROXY" http_proxy="$PROXY"
  echo "  direct is blocked, going through $PROXY"
else
  echo "  network is direct${https_proxy:+ (proxy already set: $https_proxy)}"
fi

step "1/5 语料（113 道题，含 solution/，所以进家目录不进仓库）"
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" fetch --depth 1 origin >/dev/null 2>&1 || true
  echo "already here: $(git -C "$REPO" rev-parse --short HEAD), $(ls "$REPO/tasks" | grep -cv README) tasks"
else
  git clone --depth 1 https://github.com/datacurve-ai/deep-swe "$REPO"
  echo "cloned $(git -C "$REPO" rev-parse --short HEAD), $(ls "$REPO/tasks" | grep -cv README) tasks"
fi

step "2/5 运行时（内核那一份，一份实现两边通用）"
[ -f "$RUNTIME_SRC" ] || { echo "not built yet: $RUNTIME_SRC (run 'bun run build:runtime' in app/)"; exit 1; }
cp -f "$RUNTIME_SRC" "$RUNTIME"
chmod +x "$RUNTIME"
echo "  $(stat -c %s "$RUNTIME") bytes"

step "3/5 点名这一跑要哪几道（n=$HOW_MANY seed=$SEED）"
# 台子和发批脚本用同一条挑法，所以这儿也用它来点名 —— 两处各写一套的话会漂。
IDS=$(TGENGIN_DSW_HOME="$HOME_DIR" python3 -c "
import sys; sys.path.insert(0, '$(pwd)')
import stand
print(' '.join(stand.pick($HOW_MANY, $SEED)))
")
echo "$IDS" | tr ' ' '\n' | sed 's/^/  /'

step "4/5 拉题目镜像 + 建判据镜像"
# 一道题一个钉死的镜像（3.7–9.9 GB），判据镜像是它上面薄薄一层。
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
  # **建判据镜像叫 stand.py 去办。** tag 认的是 `tests/` 那几个文件的指纹，
  # 规则写两份的话会漂 —— 这边按名字建、那边按指纹找，于是每次判卷都重建一遍。
  TGENGIN_DSW_HOME="$HOME_DIR" python3 stand.py --build "$t" >/dev/null
  # **盘要看着。** 一道题的镜像 3.7–9.9 GB，全量 113 道装不下的话，得在撑爆之前知道。
  echo "  [$N/$TOTAL] $what  $t  (images $(docker system df --format '{{.Size}}' | head -1), free $(df -h / | tail -1 | tr -s ' ' | cut -d' ' -f4))"
done
docker system df --format '  {{.Type}} {{.Size}}' | head -2

if [ "$SELFTEST" = "0" ]; then
  step "5/5 自检：跳过（TGENGIN_DSW_SELFTEST=0）"
  echo "  镜像备齐了，判据没验。跑之前补一句："
  echo "  python3 stand.py --selftest <要验的题号>"
else
  step "5/5 自检：官方判据说得对不对"
  # 拿每道题自己的参考解喂回去，官方判据该判 1；空补丁该判 0。
  # **装错了在这儿就炸**，不会等到跑完一趟才发现。
  TGENGIN_DSW_HOME="$HOME_DIR" python3 stand.py --selftest $IDS
fi

echo
echo "备齐了。台子这么起（就在这台有 docker 的机器上）："
echo "  cd $(pwd) && python3 stand.py --level 2"
