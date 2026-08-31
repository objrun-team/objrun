#!/usr/bin/env bash
# 跑一趟 cmtbench。**一步一步都在这儿。**
#
#   bash examples/benchmark/cmt/run.sh [几道] [这一跑叫什么]
#
# 前提：`setup.sh` 跑过（题库 + 官方判据 + venv），判卷台起着，引擎起着。
# 三样都没起的话看 README 开头那三条命令。
set -eu
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

BASE=${TGENGIN_BASE:-http://127.0.0.1:7801/api}
GRADER=${TGENGIN_CMT_GRADER:-http://127.0.0.1:7901}
HOW_MANY=${1:-5}
RUN=${2:-cmt-demo}

step () { echo; echo "── $* ──"; }

# `bun` 得在 PATH 上。**这一条先查** —— 不查的话它会一路跑到「挂扩展」那一步
# 才 command not found，而前面几步已经改过库了：看着像跑完了，其实批根本没发。
command -v bun >/dev/null || { echo "bun 不在 PATH 上（Git Bash 里常见）：先刷一下 PATH 再来"; exit 1; }

step "0 判卷台在不在"
curl -sS "$GRADER/health"; echo

step "1 底子：一个地方、两周期的机制、一个智能体，外加判卷台那两条句柄"
curl -s -X POST "$BASE/declare" -H 'content-type: application/json' -d @- <<JSON
{ "places":[{"place":"local"}],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":6,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":8,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"}],
  "handles":[
    {"name":"$GRADER/parsed","expectMs":60000},
    {"name":"$GRADER/equiv", "expectMs":60000}] }
JSON
echo

step "2a 关掉这道题用不上的那几个工具"
# **一道纯推导题不需要文件系统。** 这几个是 system 工具（谁都有、不看条件），
# 而这台机器上连可用的 python 都没有 —— 实测模型拿 12 个执行单元去查
# `python --version`，一个字答案都没写。伸手要算力却摸到空气，额度就这么没的。
#
# 关的是 usable 那一列，纯数据；`does`/`params` 一个字不动，想开回来把 0 改成 1。
curl -s -X POST "$BASE/exec" -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "update tool set usable = 0 where name in ('bash','read','write','edit','glob','grep')" }
JSON
echo

step "2b 给它一个能算的沙箱"
# **老仓库跑这套 bench 时，智能体手上只有两个工具：交卷，和 `python_exec`。**
# 我们这边原来给的是 `bash` —— 而这台机器上没有可用的 python，于是模型伸手要
# 算力却摸到空气，一道题 12 个执行单元全花在查 `python --version` 上。
#
# 沙箱是一次性容器，`--network none`，而且**不是判卷台那个镜像**（那里面装着
# 答案）。见 python-server.ts 和 sandbox.Dockerfile。
#
# 门按 `task.domain` 分发：会算的题给算力，跟是哪一套 benchmark 无关。
curl -s -X POST "$BASE/declare" -H 'content-type: application/json' -d @- <<'JSON'
{ "handles": [{ "name": "http://127.0.0.1:7902/python_exec", "expectMs": 60000 }],
  "tools": [{
    "name": "python_exec",
    "identity": "http://127.0.0.1:7902/python_exec",
    "does": "Run a short Python program in a throwaway sandbox and get its output back. sympy, numpy and scipy are installed. There is no network and no filesystem to explore - use it to compute and to check, not to look around.",
    "params": { "type": "object", "properties": { "code": { "type": "string", "description": "The program. Print what you want to see." } }, "required": ["code"] },
    "output": { "type": "object", "properties": { "exitCode": { "type": "integer" }, "stdout": { "type": "string" }, "stderr": { "type": "string" } } },
    "prompt": "Prefer computing over guessing. If a quantity can be counted, enumerated, expanded or checked numerically, write the program and read the answer off it. Several calls in one turn cost the same as one - every tool call you make is run before you are asked again, so batch the work rather than spending a turn per question. What is scarce is turns.",
    "when": [[{ "dim": "task", "key": "domain", "op": "eq", "value": "physics" }]] }] }
JSON
echo

step "2 挂扩展"
bun examples/benchmark/cmt/parmeras/load.ts

step "2b 条件本身有没有毛病"
curl -sS "$BASE/check"; echo

step "3 发一批（一道不过就整批不发）"
bun examples/benchmark/cmt/send.ts "$HOW_MANY" "$RUN"

step "4 等它跑完"
# 判 0 的题会被树判死、开兄弟换条路重试，所以「跑完」得等到 running 和 open 都归零
# —— 要么做对了，要么 solveSeconds 到点被判 failed。
for i in $(seq 1 200); do
  sleep 10
  r=$(curl -s "$BASE/bench/$RUN")
  left=$(echo "$r" | grep -o '"running":[0-9]*' | grep -o '[0-9]*$')
  open=$(echo "$r" | grep -o '"open":[0-9]*' | grep -o '[0-9]*$')
  [ $((i % 6)) -eq 0 ] && echo "  在跑 ${left:-?}｜没开工 ${open:-?}（$((i*10))s）"
  [ "${left:-1}" = "0" ] && [ "${open:-1}" = "0" ] && break
done

step "5 成绩单"
curl -s "$BASE/bench/$RUN"
echo

step "6 扩展塞进去没有"
for t in $(curl -s "$BASE/tasks?run=$RUN" | grep -o '"id":"[^"]*"' | grep -o 'cmt-[0-9]*'); do
  n=$(curl -s "$BASE/tasks/$t/messages?kind=skill" | grep -o '"total":[0-9]*' | grep -o '[0-9]*$')
  echo "  $t: skill 行 ${n:-0} 条"
done
