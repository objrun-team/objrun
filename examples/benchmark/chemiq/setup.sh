#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   在 Sherlock 上：先 `sdev`（或 `sh_dev`）拿一个计算节点，再
#   bash /scratch/users/ehz0002/TgEngin/examples/benchmark/chemiq/setup.sh
#
# **不要在登录节点跑** —— 它会 pip、会跑 python 自检。引擎不必在同一台，它只认两个 URL。
#
# ## 题库和判据装在**判卷台那一侧**，不在仓库里
#
# `questions/chemiq.jsonl` 每一行都带 `answer`。放仓库里的话 solver 一个 glob 就找到。
# 所以整个官方仓库 vendored 到 `$HOME/.cache/tgengin-chemiq/`（可用 TGENGIN_CHEMIQ_HOME 改）。
# 22 MB，放 $HOME 不占地方；放 $SCRATCH 的话 90 天不动会被清。
#
# **但这不是隔离。** 官方仓库是公开的，solver 能出网就能 clone 到同一份。改的是路径，不是可达性。
#
# ## 依赖走 Sherlock 的模块，不走 pip 装 rdkit
#
# 这台机器 glibc 2.17，PyPI 上新版 rdkit 的 wheel（manylinux_2_28）装不上。集群有
# `chemistry/py-rdkit/2024.3.2_py312`，配 python/3.12.1 + py-numpy/1.26.3_py312。
# 官方 verifier 还要 `requests`，集群没有这个模块 —— 建一个 `--system-site-packages` 的 venv
# 只 pip 这一个包。官方 conda 环境里的 pandas / matplotlib / openai / jupyterlab 是它
# 「拿模型跑一遍」和「画图」那半边要的，判卷用不上。
set -eu
cd "$(dirname "$0")"

REPO=https://github.com/oxpig/ChemIQ
PIN=63826f64990802e87f1b11b9192606a20838d522   # 2026-03-26，816 题版（2025-07-10 换进 50 道 2D NMR 之后）
HOME_DIR="${TGENGIN_CHEMIQ_HOME:-$HOME/.cache/tgengin-chemiq}"
VENDOR="$HOME_DIR/vendor/ChemIQ"
VENV="$HOME_DIR/venv"
ENVSH="$HOME_DIR/env.sh"
ML_LINE="ml math devel chemistry python/3.12.1 py-numpy/1.26.3_py312 py-rdkit/2024.3.2_py312"

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR"

if [ -z "${SLURM_JOB_ID:-}" ]; then
  echo "this looks like a login node (no SLURM_JOB_ID). run 'sdev' first." >&2
  exit 1
fi

step "0/4 仓库里要是还留着旧的，挪走"
for stale in ChemIQ chemiq.jsonl vendor; do
  if [ -e "$stale" ]; then
    rm -rf "$stale"
    echo "删了仓库里的 $stale —— 它在 solver 够得着的地方"
  fi
done
echo "oracle 只在 $HOME_DIR"

step "1/4 官方仓库（题库 + 判据 + OPSIN 缓存，钉 ${PIN:0:7}）"
if [ -d "$VENDOR/.git" ]; then
  echo "已有 $(git -C "$VENDOR" rev-parse --short HEAD)"
else
  mkdir -p "$(dirname "$VENDOR")"
  git clone --depth 1 "$REPO" "$VENDOR"
fi
if [ "$(git -C "$VENDOR" rev-parse HEAD)" != "$PIN" ]; then
  git -C "$VENDOR" fetch --depth 1 origin "$PIN"
  git -C "$VENDOR" checkout -q "$PIN"
  echo "钉到 $(git -C "$VENDOR" rev-parse --short HEAD)"
fi
echo "题库 $(wc -l < "$VENDOR/questions/chemiq.jsonl") 行"

step "2/4 python：集群模块 + 一个只装 requests 的 venv"
# `ml` 是 Lmod 的 shell 函数，非交互 shell 里没有 —— 从 Lmod 自己的 init 拿（Sherlock 上
# LMOD_PKG=/share/software/user/open/lmod/lmod）。
# shellcheck disable=SC1090
type ml >/dev/null 2>&1 || source "${LMOD_PKG:-/share/software/user/open/lmod/lmod}/init/bash"
ml purge
$ML_LINE
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' \
  || { echo "python/3.12.1 did not load; see MEMORY.md note about ml in Claude's bash" >&2; exit 1; }
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
PIP_CACHE_DIR="${SCRATCH:-/tmp}/.pip-cache" "$VENV/bin/pip" install -q "requests>=2.31"
"$VENV/bin/python" - <<'PY'
import numpy, requests, rdkit
from rdkit import Chem
print(f"numpy {numpy.__version__} | requests {requests.__version__} | rdkit {rdkit.__version__}")
assert Chem.MolToSmiles(Chem.MolFromSmiles("OCC")) == "CCO"
PY
# 起判卷台时 source 这个，模块行只写这一处
cat > "$ENVSH" <<EOF
# 由 setup.sh 生成。起判卷台：source $ENVSH && python stand.py
type ml >/dev/null 2>&1 || source "${LMOD_PKG:-/share/software/user/open/lmod/lmod}/init/bash"
ml purge
$ML_LINE
export TGENGIN_CHEMIQ_HOME="$HOME_DIR"
export PATH="$VENV/bin:\$PATH"
EOF
echo "写了 $ENVSH"

step "3/4 OPSIN 网络服务（smiles_to_iupac 那 200 道要它）"
# 官方代码打 opsin.ch.cam.ac.uk，它 301 到 www.ebi.ac.uk/opsin/ws；requests 会跟。
# 这儿量一次往返：官方 @timeout(2) 把网络也算在两秒里，超过 1.5 秒就该担心。
t=$(curl -sL -m 15 -o /dev/null -w '%{time_total}' 'https://opsin.ch.cam.ac.uk/opsin/ethanol.json' || echo fail)
echo "ethanol → ${t}s"
case "$t" in fail) echo "OPSIN unreachable from this node - the 200 smiles_to_iupac questions will all grade as wrong" >&2 ;; esac

step "4/4 自检：官方判据能不能加载、判得对不对"
export TGENGIN_CHEMIQ_HOME="$HOME_DIR"
"$VENV/bin/python" stand.py --selftest

echo
echo "备齐了。判卷台这么起（在 sdev 节点上，引擎那边把端口转过来）："
echo "  source $ENVSH && cd $(pwd) && python stand.py --level 1"
