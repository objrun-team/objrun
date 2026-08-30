#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt/setup.sh"
#
# 判卷台跑在 WSL 里，因为官方评分代码要 Python ≥3.12（Windows 这边只有 Store 的壳）。
# 引擎在 Windows 上，它只知道一个 URL —— 判卷台在哪台机器上跟它无关。
#
# ## 题库和判据装在**判卷台那一侧**，不在仓库里
#
# 这一条是**安全边界，不是整理癖**。solver 手上有 `read` / `glob` / `bash`，而它干活
# 的地方（`place: local`）就是引擎那台机器 —— 题库放仓库里的话，它 glob 一下就找到，
# 读一下就拿到 GT。
#
# **实测发生过**：模型先 `read grader.py` 搞清楚判据怎么比，接着 `read` 官方 parser
# 源码，然后 `glob` 到了 `cmt_data.jsonl`。那一跑它还没来得及读出 GT 就被判完了，
# 但路已经摸到门口。
#
# 所以三样全装在 `$HOME/.cache/tgengin-cmt/` 底下（WSL 家目录）——
# Windows 那侧的 solver 看不见这个路径。**这一条是够不着，不是不许。**
#
# 但判卷台的端口它够得着（同一台机器上的 127.0.0.1:7901），`/equiv` 能当验证 oracle 刷。
# 那一条现在只靠「没告诉它地址」。要堵死得把判卷台连题库打包进容器、只对引擎开口 ——
# 这台机器上暂时没有 docker/podman。
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

step "0/3 仓库里要是还留着旧的，挪走"
for stale in cmt_data.jsonl vendor; do
  if [ -e "$stale" ]; then
    rm -rf "$stale"
    echo "删了仓库里的 $stale —— 它在 solver 够得着的地方"
  fi
done
echo "oracle 只在 $HOME_DIR"

step "1/3 题库"
if [ -f "$DATA" ]; then
  echo "已有 $(wc -l < "$DATA") 行"
else
  curl -sSL -o "$DATA" "$DATA_URL"
  echo "下好了 $(wc -l < "$DATA") 行"
fi

step "2/3 官方评分代码"
if [ -d "$VENDOR/.git" ]; then
  echo "已有 $(git -C "$VENDOR" rev-parse --short HEAD)"
else
  mkdir -p "$(dirname "$VENDOR")"
  git clone --depth 1 "$HARNESS" "$VENDOR"
  echo "克隆到 $(git -C "$VENDOR" rev-parse --short HEAD)"
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
