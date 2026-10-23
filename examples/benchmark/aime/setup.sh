#!/usr/bin/env bash
# 把这个例子要的东西备齐。**幂等**，跑几遍都行。
#
#   bash examples/benchmark/aime/setup.sh
#
# **在 Sherlock 上要在计算节点跑，不在登录节点**（`sh_dev` 拿一个，或者 sbatch）：
# 建 venv、pip、跑自检都是登录节点禁止的事。引擎不必在同一台 —— 它只知道两个 URL。
#
#   sh_dev -c 2 -m 8GB -t 1:00:00
#   bash /path/to/examples/benchmark/aime/setup.sh
#
# ## 题库装在**判卷台那一侧**，不在仓库里
#
# 60 道题带答案。放仓库里的话 solver 一个 glob 就够（cmt 那边实测发生过）。
# 所以装在 `$HOME/.cache/tgengin-aime/`。**但这不是隔离** —— solver 的 bash 跟判卷台
# 在同一台机器上，一条 cat 一样拿到。改的是路径，不是可达性。
#
# ## 三个来源，两个用、一个对账
#
#   2024  AI-MO/aimo-validation-aime   Apache-2.0  parquet  90 道（22–24），只取 24 的 30 道
#   2025  math-ai/aime25               Apache-2.0  jsonl    30 道，answer 是干净的 int
#   2025  opencompass/AIME2025         MIT         jsonl    只用来跟 math-ai 对账
#                                                           （它 II-5 写成 "336^\circ"，
#                                                            所以不当主来源）
#
# 全钉在 commit sha 上 —— HF 的 main 会动，动了分数就不可比。
set -eu
cd "$(dirname "$0")"

HOME_DIR="${TGENGIN_AIME_HOME:-$HOME/.cache/tgengin-aime}"
VENV="$HOME_DIR/venv"
RAW="$HOME_DIR/raw"
DATA="$HOME_DIR/aime.jsonl"

HF=https://huggingface.co/datasets
AIMO_SHA=13f9e12f613e720c2a2b2f345dd04b998a29494d
MATHAI_SHA=563bb8404243c5f09de6ec262f2db674fe5bce9b
OC_SHA=a6ad95f611d72cf628a80b58bd0432ef6638f958
# 官方判据的版本。**钉死**：math_verify 的解析规则每版都在改，换版本 = 换尺子。
MV_VERSION=0.9.0

step () { echo; echo "── $* ──"; }
mkdir -p "$HOME_DIR" "$RAW"

step "0/4 python"
# Sherlock 上用模块里的 3.12（`ml spider python` 能看到 3.12.1）；别的机器有 3.11+ 就行。
if command -v ml >/dev/null 2>&1 || command -v module >/dev/null 2>&1; then
  ml python/3.12.1 2>/dev/null || module load python/3.12.1 2>/dev/null || true
fi
PY=$(command -v python3)
# 非交互 bash 里 `ml` 常常不是函数（Lmod 没初始化），那就直接指到模块的安装位置。
# 它的 libpython 不在默认搜索路径上，得带 LD_LIBRARY_PATH，否则 python3 起不来。
SHERLOCK_PY=/share/software/user/open/python/3.12.1
if ! "$PY" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null && [ -x "$SHERLOCK_PY/bin/python3" ]; then
  export LD_LIBRARY_PATH="$SHERLOCK_PY/lib:${LD_LIBRARY_PATH:-}"
  PY="$SHERLOCK_PY/bin/python3"
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version' || { echo "need python >= 3.11 (on Sherlock: ml python/3.12.1)"; exit 1; }
echo "  $("$PY" --version) at $PY"
# pip 的缓存别落在 $HOME（15 GB 很快满）。
export PIP_CACHE_DIR="${SCRATCH:-/tmp}/.pip-cache"

step "1/4 原始数据（三个来源，全钉 sha）"
fetch () {  # fetch <url> <dst>
  if [ -s "$2" ]; then echo "  have  $(basename "$2")"; else curl -sSL -o "$2" "$1"; echo "  got   $(basename "$2") ($(stat -c %s "$2") bytes)"; fi
}
fetch "$HF/AI-MO/aimo-validation-aime/resolve/$AIMO_SHA/data/train-00000-of-00001.parquet" "$RAW/aimo-validation-aime.parquet"
fetch "$HF/math-ai/aime25/resolve/$MATHAI_SHA/test.jsonl"                               "$RAW/math-ai-aime25.jsonl"
fetch "$HF/opencompass/AIME2025/resolve/$OC_SHA/aime2025-I.jsonl"                       "$RAW/opencompass-aime2025-I.jsonl"
fetch "$HF/opencompass/AIME2025/resolve/$OC_SHA/aime2025-II.jsonl"                      "$RAW/opencompass-aime2025-II.jsonl"

step "2/4 venv：官方判据 math-verify==$MV_VERSION（+ pyarrow，只为读那个 parquet）"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null
"$VENV/bin/pip" install -q --only-binary=:all: "numpy==2.2.5" "pandas==2.3.2" "pyarrow==20.0.0" && "$VENV/bin/pip" install -q "math-verify[antlr4_13_2]==$MV_VERSION"  # glibc 2.17 只吃 manylinux2014 轮子
"$VENV/bin/python" - <<'PY'
import math_verify, sympy, pyarrow
print(f"  math-verify {getattr(math_verify, '__version__', '?')} | sympy {sympy.__version__} | pyarrow {pyarrow.__version__}")
PY

step "3/4 合成题库 $DATA（60 道，带 answer；只有判卷台读它）"
# **这一段只搬数据、不判卷。** 2024 从 url 里认年份和场次；2025 按行序（math-ai 的
# id 0–14 是 I、15–29 是 II，行序就是题号）。opencompass 只用来对账：它的 answer 有
# 一条带 "^\circ"，去掉非数字后 30 道必须跟 math-ai 一致，不一致就炸。
RAW="$RAW" DATA="$DATA" "$VENV/bin/python" - <<'PY'
import json, os, re
from pathlib import Path
import pyarrow.parquet as pq

raw, out = Path(os.environ["RAW"]), Path(os.environ["DATA"])
rows = []

# 2024：AI-MO，取 url 里带 2024_AIME 的 30 道
t = pq.read_table(raw / "aimo-validation-aime.parquet").to_pylist()
for r in t:
    m = re.search(r"(\d{4})_AIME_(I|II)_Problems/Problem_(\d+)", r["url"])
    if not m or m.group(1) != "2024":
        continue
    year, contest, num = int(m.group(1)), m.group(2), int(m.group(3))
    ans = int(str(r["answer"]).strip())         # 官方写法带前导零（"025"），int 吃得下
    rows.append({"id": f"aime-{year}-{contest}-{num}", "year": year, "contest": contest, "number": num,
                 "problem": r["problem"], "answer": ans, "url": r["url"], "source": "AI-MO/aimo-validation-aime"})
n24 = len(rows)
assert n24 == 30, f"expected 30 problems for 2024, got {n24}"

# 2025：math-ai，行序 = 题号
ma = [json.loads(l) for l in (raw / "math-ai-aime25.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
assert len(ma) == 30, len(ma)
for i, r in enumerate(ma):
    contest, num = ("I", i + 1) if i < 15 else ("II", i - 14)
    rows.append({"id": f"aime-2025-{contest}-{num}", "year": 2025, "contest": contest, "number": num,
                 "problem": r["problem"], "answer": int(str(r["answer"]).strip()),
                 "url": f"https://artofproblemsolving.com/wiki/index.php/2025_AIME_{contest}_Problems/Problem_{num}",
                 "source": "math-ai/aime25"})

# 对账：opencompass 的 30 个答案（去掉非数字）得跟 math-ai 逐题一致
oc = []
for part in ("I", "II"):
    oc += [json.loads(l) for l in (raw / f"opencompass-aime2025-{part}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
assert len(oc) == 30, len(oc)
for r, o in zip(rows[n24:], oc):
    a, b = r["answer"], int(re.sub(r"\D", "", str(o["answer"])))
    assert a == b, f"{r['id']}: math-ai says {a}, opencompass says {o['answer']}"

for r in rows:
    assert 0 <= r["answer"] <= 999, r
out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
print(f"  {len(rows)} problems -> {out}  (2024: {n24}, 2025: {len(rows) - n24}; opencompass agrees on all 30 of 2025)")
PY

step "4/4 自检：官方判据能不能加载、判得对不对"
TGENGIN_AIME_HOME="$HOME_DIR" "$VENV/bin/python" stand.py --selftest

echo
echo "备齐了。判卷台这么起（在有 venv 的这台机器上）："
# venv 是拿模块 python 建的，起台子时同样得带上它的 lib，不然 libpython3.12.so 找不到。
[ "$PY" = "$SHERLOCK_PY/bin/python3" ] && echo "  export LD_LIBRARY_PATH=$SHERLOCK_PY/lib:\$LD_LIBRARY_PATH"
echo "  cd $(pwd) && TGENGIN_AIME_HOME=$HOME_DIR $VENV/bin/python stand.py --level 1"
