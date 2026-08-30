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
