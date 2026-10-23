#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   sh_dev -c 2 -m 8GB            # Sherlock 上先要一个计算节点 —— 登录节点不许跑 python / pip
#   bash examples/benchmark/chembench/setup.sh
#
# 引擎不必在同一台 —— 它只知道两个 URL。台子在哪台机器上跟它无关。
#
# ## 题库和判据装在**台子那一侧**，不在仓库里
#
# `chembench.jsonl` 里每一行都带 `target` / `target_scores`，就是答案。放仓库里的话
# solver 一个 glob 就够。所以官方代码 + 题库都落在 `$HOME/.cache/tgengin-chembench/`
# （几 MB，家目录装得下）。venv 另放 `$SCRATCH` —— 那是几十 MB 的 numpy，家目录只有 15G，
# 而且 venv 丢了重跑这个脚本就回来。
#
# **但这不是隔离，别当成隔离。** solver 的 bash 跟台子同一台机器，`cat` 一下就是整本
# 答案。路径只是把门槛抬高一格；真要挡住得把 solver 关进沙箱（`place` 那一维）。
set -eu
cd "$(dirname "$0")"

# 钉死的版本。**改这两行等于换了一套判据**，改了要重跑自检并在 G.md 里记。
REPO=https://github.com/lamalab-org/chembench
COMMIT=45f8bad062fe552810c52be3a328d5da8597ed30       # 2025-09-11 "Fix in extract() (#858)"
HF=jablonkagroup/ChemBench
HF_REV=6e1d25748952393f44e35b8e85bbe567246a6430       # 数据集 2026-04-22 那一版，2785 题
TOPICS="analytical_chemistry chemical_preference general_chemistry inorganic_chemistry materials_science organic_chemistry physical_chemistry technical_chemistry toxicity_and_safety"

HOME_DIR="${TGENGIN_CHB_HOME:-$HOME/.cache/tgengin-chembench}"
VENDOR="$HOME_DIR/vendor/chembench"
DATA="$HOME_DIR/chembench.jsonl"
VENV="${TGENGIN_CHB_VENV:-${SCRATCH:-$HOME_DIR}/tgengin-chembench/venv}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-${SCRATCH:-/tmp}/.pip-cache}"

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR" "$HOME_DIR/parquet"

step "0/4 python 3.12"
# 官方代码要 ≥3.10（`dict | None` 那种写法）；系统 python3 是 3.6。用 Sherlock 的模块。
# `ml load` 在某些非交互 shell 里不生效（仍是 3.6），所以直接指到那个二进制，并补 LD_LIBRARY_PATH。
PY312=/share/software/user/open/python/3.12.1/bin/python3
if [ -x "$PY312" ]; then
  export LD_LIBRARY_PATH="/share/software/user/open/python/3.12.1/lib:${LD_LIBRARY_PATH:-}"
else
  PY312=$(command -v python3.12 || command -v python3)
fi
"$PY312" -c 'import sys; assert sys.version_info >= (3, 10), sys.version; print("  " + sys.version.split()[0])'

step "1/4 官方代码（只要 src/，仓库里 reports/ 有 1.6 GB）"
if [ -d "$VENDOR/.git" ] && [ "$(git -C "$VENDOR" rev-parse HEAD)" = "$COMMIT" ]; then
  echo "  already here: $(git -C "$VENDOR" rev-parse --short HEAD)"
else
  rm -rf "$VENDOR"
  mkdir -p "$(dirname "$VENDOR")"
  git clone --no-checkout --filter=blob:none "$REPO" "$VENDOR" >/dev/null 2>&1
  git -C "$VENDOR" sparse-checkout set src
  git -C "$VENDOR" checkout -q "$COMMIT"
  echo "  checked out $(git -C "$VENDOR" rev-parse --short HEAD)"
fi
[ -f "$VENDOR/src/chembench/prompter.py" ] || { echo "src/chembench/prompter.py is missing after checkout"; exit 1; }

step "2/4 题库（HF $HF @ ${HF_REV:0:7}，9 个 parquet，共 ~530 KB，不 gated）"
for t in $TOPICS; do
  f="$HOME_DIR/parquet/$t.parquet"
  [ -s "$f" ] && continue
  curl -sSL -o "$f" "https://huggingface.co/datasets/$HF/resolve/$HF_REV/$t/train-00000-of-00001.parquet"
  echo "  $t $(stat -c %s "$f") B"
done

step "3/4 venv + 依赖"
# **只装判卷那条路要的。** 官方 pyproject 还列着 litellm / langchain / torch / transformers /
# datasets —— 那些是它「拿模型跑一遍」「用 BERT 认拒答」那半边要的，判卷用不上。
# 版本下限照抄官方 pyproject（它自己也没钉死这几个）；pyarrow 只在下一步转 parquet 用。
[ -x "$VENV/bin/python" ] || "$PY312" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null
"$VENV/bin/pip" install -q --only-binary=:all: "numpy==2.2.5" "pandas==2.3.2" "pyarrow==20.0.0" && "$VENV/bin/pip" install -q "pint>=0.23" "fastcore>=1.5.29" "loguru>=0.7.2" "typing_extensions>=4.8"  # glibc 2.17 只吃 manylinux2014 轮子
"$VENV/bin/python" - <<'PY'
import fastcore, loguru, numpy, pint, pyarrow
print(f"  numpy {numpy.__version__} | pint {pint.__version__} | fastcore {fastcore.__version__} | loguru {loguru.__version__} | pyarrow {pyarrow.__version__}")
PY

# parquet → jsonl。清洗照抄官方 `TaskRegistry.from_huggingface`：target / target_scores
# 两栏只留非空的那一栏，target_scores 是个 JSON 串要 loads。一行一题。
if [ -s "$DATA" ] && [ "$(wc -l < "$DATA")" -ge 2785 ]; then
  echo "  jsonl already here: $(wc -l < "$DATA") lines"
else
  HOME_DIR="$HOME_DIR" TOPICS="$TOPICS" "$VENV/bin/python" - <<'PY'
import json, os
from pathlib import Path
import pyarrow.parquet as pq

home = Path(os.environ["HOME_DIR"])
out = home / "chembench.jsonl"
n = 0
with out.open("w", encoding="utf-8") as fh:
    for topic in os.environ["TOPICS"].split():
        rows = pq.read_table(home / "parquet" / f"{topic}.parquet").to_pylist()
        for row in rows:
            exs = row["examples"]
            if len(exs) != 1:  # 官方数据里每题恰好一个 example；不是的话别悄悄吞
                raise SystemExit(f"{row['uuid']} has {len(exs)} examples")
            ex = exs[0]
            example = {"input": ex["input"]}
            if ex.get("target") is not None:
                example["target"] = ex["target"]
            if ex.get("target_scores") is not None:
                example["target_scores"] = json.loads(ex["target_scores"])
            fh.write(json.dumps({
                "uuid": row["uuid"], "topic": topic, "name": row["name"], "keywords": row["keywords"],
                "metrics": row["metrics"], "preferred_score": row["preferred_score"],
                "relative_tolerance": row.get("relative_tolerance"),  # HF 版没有这一栏，永远 None —— 官方于是走 1%
                "example": example,
            }, ensure_ascii=False) + "\n")
            n += 1
print(f"  wrote {n} items to {out}")
PY
fi

step "4/4 自检：官方判据能不能加载、判得对不对"
TGENGIN_CHB_HOME="$HOME_DIR" "$VENV/bin/python" stand.py --selftest

echo
echo "备齐了。台子这么起（在计算节点上，不是登录节点）："
echo "  cd $(pwd) && TGENGIN_CHB_HOME=$HOME_DIR $VENV/bin/python stand.py --level 1"
