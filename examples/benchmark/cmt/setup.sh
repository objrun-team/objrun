#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt/setup.sh"
#
# 判卷台跑在 WSL 里，因为官方评分代码要 Python ≥3.12（Windows 这边只有 Store 的壳）。
# 引擎在 Windows 上，它只知道一个 URL —— 判卷台在哪台机器上跟它无关。
#
# 备三样：
#   1. 题库   cmt_data.jsonl              50 道，HuggingFace
#   2. 判据   vendor/cmt_benchmark_data   官方评分代码（LaTeX→Sympy）
#   3. 依赖   ~/.cache/tgengin-cmt/venv   官方 pin 的那几个版本
#
# 前两样不进 git（见 .gitignore）—— 题库带 GT，是 oracle。
set -eu
cd "$(dirname "$0")"

DATA_URL=https://huggingface.co/datasets/JVRoggeveen/cmt_benchmark/resolve/main/cmt_data.jsonl
HARNESS=https://github.com/JamesRoggeveen/cmt_benchmark_data
VENV="$HOME/.cache/tgengin-cmt/venv"

step () { echo; echo "── $* ──"; }

step "1/3 题库"
if [ -f cmt_data.jsonl ]; then
  echo "已有 $(wc -l < cmt_data.jsonl) 行"
else
  curl -sSL -o cmt_data.jsonl "$DATA_URL"
  echo "下好了 $(wc -l < cmt_data.jsonl) 行"
fi

step "2/3 官方评分代码"
if [ -d vendor/cmt_benchmark_data/.git ]; then
  echo "已有 $(git -C vendor/cmt_benchmark_data rev-parse --short HEAD)"
else
  mkdir -p vendor
  git clone --depth 1 "$HARNESS" vendor/cmt_benchmark_data
  echo "克隆到 $(git -C vendor/cmt_benchmark_data rev-parse --short HEAD)"
fi

step "3/3 python 依赖"
# 用 uv 建环境，不用 `python3 -m venv` —— 这台 WSL 上没装 `python3.12-venv`
# （ensurepip 缺），而装它要 root。uv 是个静态二进制，`~/.local/bin` 里就能跑，
# 而且它自己带得动 Python 和 pip。
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "装 uv（不用 root）"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "uv $(uv --version | awk '{print $2}')"

# **只装判卷那条路要的三个。** 官方 pyproject 还列着 openai / anthropic / google-genai
# / datasets / matplotlib —— 那些是它「拿模型跑一遍」和「画图」那半边要的，判卷用不上。
# 版本照抄官方 pin，不然分数不可比。
[ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV" >/dev/null
VIRTUAL_ENV="$VENV" uv pip install -q \
  "sympy==1.13.3" "numpy==2.2.5" "regex==2024.11.6"
"$VENV/bin/python" - <<'PY'
import sympy, numpy, regex
print(f"sympy {sympy.__version__}｜numpy {numpy.__version__}｜regex {regex.__version__}")
PY

step "自检：官方判据能不能加载、判得对不对"
"$VENV/bin/python" grader.py --selftest

echo
echo "备齐了。判卷台这么起："
echo "  ssh wsl \"cd $(pwd) && $VENV/bin/python grader.py\""
