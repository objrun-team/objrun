#!/usr/bin/env bash
# 跑一趟 DeepSWE。**一步一步都在这儿。**
#
#   bash examples/benchmark/deepswe/run.sh [几道] [这一跑叫什么] [种子]
#
# 前提：`setup.sh` 跑过（语料 + 镜像 + 判据自检），台子起着，引擎起着。
# 三样都没起的话看 README 开头那三条命令。
set -eu
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

BASE=${TGENGIN_BASE:-http://127.0.0.1:7801/api}
STAND=${TGENGIN_DSW_STAND:-http://127.0.0.1:7902}
HOW_MANY=${1:-10}
RUN=${2:-dsw-demo}
SEED=${3:-0}

step () { echo; echo "── $* ──"; }

# `bun` 得在 PATH 上。**这一条先查** —— 不查的话它会一路跑到发批那一步才
# command not found，而前面几步已经改过库了。
command -v bun >/dev/null || { echo "bun 不在 PATH 上（Git Bash 里常见）：先刷一下 PATH 再来"; exit 1; }

step "0 台子在不在"
curl -sS "$STAND/health"; echo

step "1 这一跑要哪几道"
# 点名是**确定的**：同一个 (n, seed) 永远是同一批。台子和发批脚本用同一条挑法。
# **匹配要容得下冒号后面的空格。** 台子那边是 `json.dumps` 的默认排版，出来的是
# `{"id": "…"}` —— 写成 `"id":"` 的话一个都匹配不上，而且不报错：题号取空、
# 位置一行都不声明、批被 /bench 拒掉，而错误信息指向 workplace。
IDS=$(curl -s "$STAND/problems?n=$HOW_MANY&seed=$SEED" | grep -o '"id": *"[^"]*"' | sed 's/.*: *"\(.*\)"/\1/')
[ -n "$IDS" ] || { echo "台子一道题都没给：$STAND/problems?n=$HOW_MANY&seed=$SEED"; exit 1; }
echo "$IDS" | sed 's/^/  /'

step "2 底子：位置、机制、智能体，外加台子那三条句柄"
# **位置那一行必须带 identity。** 转发的时候「怎么到那个位置」是句柄的事 ——
# 内核自带的 `fn:place.hops` 读的是 wsl/ssh/docker 那套跳板串，在这台机器上过不去
# （三条实测见 stand.py 模块头）。这儿指的是台子，地址写法 `dsw:<task-id>` 也归它读。
#
# **一道题一行，而且带跑名** —— `task.place` 指的是 `workplace.place`，一跑一个容器。
# 跑名不进去的话，换个级别重跑会接着上一趟的工作区干，那两趟就不是同一种实验了。
# 一份声明整份收整份验，所以拼成一次发出去，不是一道一条。
TOOLS='[{"tool":"bash","policy":"always"},{"tool":"read","policy":"always"},{"tool":"write","policy":"always"},{"tool":"edit","policy":"always"},{"tool":"glob","policy":"always"},{"tool":"grep","policy":"always"}]'
PLACES='{"place":"local"}'
for t in $IDS; do
  PLACES="$PLACES,{\"place\":\"dsw:$RUN/$t\",\"identity\":\"$STAND/place\",\"forward\":true,\"tools\":$TOOLS}"
done

curl -s -X POST "$BASE/declare" -H 'content-type: application/json' -d @- <<JSON
{ "handles":[
    {"name":"$STAND/place",   "expectMs":300000},
    {"name":"$STAND/applies", "expectMs":1800000},
    {"name":"$STAND/resolved","expectMs":1800000}],
  "places":[$PLACES],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":70,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":70,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[
    {"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"}] }
JSON
echo

step "3 关掉这一跑用不上的那两件"
# **不许搜。** 官方那套两侧都是 no-network，而检索那件工具不转发到 workplace ——
# 它是条真网络，而这套题的参考解就公开在 GitHub 上，按题目 id 一搜就是。
#
# **那件工具叫 `web_search`，不叫 `search`。** 名字写错的话这条 SQL 匹配零行，
# 而 `update … where name in (…)` 匹配零行是合法的，不报错 —— 于是这一跑会带着
# 检索工具出去。所以第 3c 步要回头数一遍留着的是哪几件。
#
# `python_exec` 也关：这套题的仓库是 Go / TS / Rust / Python 五种，要跑什么都在
# 容器里用 `bash` 跑，用容器自己那套工具链。引擎这边的 Pyodide 跟那个环境无关。
#
# 关的是 usable 那一列，纯数据；`does`/`params` 一个字不动。
curl -s -X POST "$BASE/exec" -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "update tool set usable = 0 where name in ('web_search','python_exec')" }
JSON
echo

step "3c 真关掉了吗"
# 上一句要是名字写错了，SQL 匹配零行，而那是合法的、不报错的 —— 「关掉了」这件事
# 就从头到尾没被验证过。所以这儿数的是**留着的是哪几件**，不是改了几行。
ON=$(curl -s -X POST "$BASE/query" -H 'content-type: application/json' -d @- <<'JSON' | grep -o '"name":"[^"]*"' | cut -d'"' -f4
{ "sql": "select name from tool where usable = 1 order by name" }
JSON
)
echo "$ON" | sed 's/^/  留着 /'
for banned in web_search python_exec; do
  if echo "$ON" | grep -qx "$banned"; then
    echo "  ✗ $banned 还开着 —— 停在这儿，不发批"
    exit 1
  fi
done
echo "  ✓ web_search / python_exec 都关了"

step "3b 条件本身有没有毛病"
curl -sS "$BASE/check"; echo

step "4 发一批（一道不过就整批不发）"
bun examples/benchmark/deepswe/send.ts "$HOW_MANY" "$RUN" "$SEED"

step "5 等它跑完"
# 判 0 的题会被树判死、开兄弟换条路重试，所以「跑完」得等到 running 和 open 都归零
# —— 要么做成了，要么 solveSeconds 到点被判 failed。
for i in $(seq 1 1200); do
  sleep 10
  r=$(curl -s "$BASE/bench/$RUN")
  left=$(echo "$r" | grep -o '"running":[0-9]*' | grep -o '[0-9]*$')
  open=$(echo "$r" | grep -o '"open":[0-9]*' | grep -o '[0-9]*$')
  [ $((i % 30)) -eq 0 ] && echo "  在跑 ${left:-?}｜没开工 ${open:-?}（$((i*10))s）"
  [ "${left:-1}" = "0" ] && [ "${open:-1}" = "0" ] && break
done

step "6 成绩单"
curl -s "$BASE/bench/$RUN"
echo

step "7 收摊：干活的容器留着（里头是它做的东西），判据容器本来就是 --rm"
echo "  docker ps --filter name=dsw- --format '{{.Names}}'"
