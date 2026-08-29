# 干活的地方

[← 例子](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · **place**

登记一个本机开着的浏览器标签页当一个地方。**执行单元落在这儿，就有这一页的那几个工具；
落在别处就没有。**

这儿只讲地方。工具怎么注册的在 [`../tool/`](../tool/)。

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

浏览器得带调试端口起着，标签页开着那份 deck：

```bash
chrome --remote-debugging-port=9222 \
       --user-data-dir=/tmp/deck-profile \
       file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
```

底子（两个周期、一个智能体）：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":12, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":12, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-chat"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## 登记

一行地方，加上属于它的那几个工具。工具的 `when` 写 `dim: "place"` —— 这一维问的是
**这个执行单元在哪儿**。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "tab:deck" }],
  "servers": [{
    "name": "deck",
    "command": "bun",
    "args": ["examples/place/tab-server.ts", "deck.html"],
    "tools": {
      "deck_state": { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_next":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_prev":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_goto":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] }
    }
  }]
}
JSON
```
```json
{"servers":{"deck":["deck_state","deck_next","deck_prev","deck_goto"]},
 "places":["tab:deck"],"handles":[],"modes":[],"cycles":0,"agents":[],
 "tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select place, forward, usable from workplace order by place" }
JSON
```
```json
{"count":2,"rows":[
  {"place":"local",   "forward":0,"usable":1},
  {"place":"tab:deck","forward":0,"usable":1}]}
```

`forward` 是关的。这几个工具本来就在本机 —— 它们连的是本机 9222 端口上的那个浏览器，
没有什么要送到别处去。**`forward` 管的是「工具跑在哪台机器上」，地方名管的是
「这一站在哪儿」，两件事。** 只有开了 `forward` 的地方，名字才得写成一串跳板
（`wsl` / `ssh://box-7` / `wsl/docker:build-01`）；不转发的地方，名字就是个名字。

引擎这边它叫 `tab:deck`，浏览器那边它是哪个标签页由 server 的参数
（`"deck.html"`）说了算。两边各认各的，中间靠这份声明对上。

## 在这儿给不给

不用发任务就能问：

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
  -d '{"kind":"tool","owner":"deck_next","place":"tab:deck"}'
```
```json
{"fired":true,"groups":[[{"group":0,"dim":"place","key":"","op":"eq","value":"tab:deck","got":"tab:deck","hit":true}]]}
```

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
  -d '{"kind":"tool","owner":"deck_next","place":"local"}'
```
```json
{"fired":false,"groups":[[{"group":0,"dim":"place","key":"","op":"eq","value":"tab:deck","got":"local","hit":false}]]}
```

---

## 落在这儿的任务

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-deck", "mode":"work", "agent":"bot", "place":"tab:deck", "source":"user",
  "solveSeconds": 300,
  "description": "这份 deck 现在翻到第几张了？把它翻到讲「出了什么问题」的那一张，告诉我是第几张，然后结束" }
JSON
```

这一站手上有哪些工具：

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=inject" | grep -o '"tools":\[[^]]*\]' | head -1
```
```
"tools":["read","write","edit","glob","grep","bash","deck_goto","deck_next","deck_prev","deck_state"]
```

前六个是 `system = 1` 的，哪儿都有；后四个是这个地方带来的。

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=call" | grep -o '"name":"deck[^}]*}'
```
```
"name":"deck_state","input":{}
"name":"deck_goto","input":{"page":2}
"name":"deck_next","input":{}
…（一直翻到第 9 张）
```

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=tool" | grep -o '"value":{[^{}]*}'
```
```
"value":{"page":1,"total":12,"title":"开场"}
"value":{"page":2,"total":12,"title":"这一季干了什么"}
…
"value":{"page":9,"total":12,"title":"出了什么问题"}
```

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"找到了，翻到了第9张，标题为「出了什么问题」。\n\n- 这份 deck 一开始在第1张（标题「开场」）\n- 讲「出了什么问题」的是**第9张**\n\n现在停在第9张，结束。"
```

浏览器里那一页这时候真停在第 9 张。任务完了它不回去 —— **页面的状态在页面上，
不在库里。** 下一个落在这儿的执行单元接着从第 9 张开始。

## 同一个任务，换个地方

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-deck-local", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 180,
  "description": "这份 deck 现在翻到第几张了？把它翻到讲「出了什么问题」的那一张，告诉我是第几张，然后结束" }
JSON
```
```bash
curl -s "$BASE/tasks/t-deck-local/messages?kind=inject" | grep -o '"tools":\[[^]]*\]' | head -1
```
```
"tools":["read","write","edit","glob","grep","bash"]
```

deck 那四个没上来。同一份描述、同一个智能体，只有地方不一样。模型于是拿
`read` 去翻 `deck.html` 的源码，答的是**文件里写着什么**，不是**那一页现在在哪**：

```
"body":"I've found the deck file. It's a JavaScript-powered presentation with 12 slides.
The titles are: 1. 开场 … 12. 问答\n\nThe deck starts on page 1, and the slide …"
```

「一开始在第 1 张」是源码里的初始值，不是那个标签页的现况 —— 它够不着。

---

## 日志

```
[tab] 起来了，认「deck.html」，调试端口 9222
[tab] 接上了 Q3 Review — 1/12 开场｜file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
[tab] deck_state → {"page":1,"total":12,"title":"开场"}
[tab] deck_goto → {"page":2,"total":12,"title":"这一季干了什么"}
[tab] deck_next → {"page":3,"total":12,"title":"收入"}
```

## 字段

`places[]`

| | |
| --- | --- |
| `place` | 名字。开了 `forward` 才必须是一串跳板 |
| `forward` | 工具调用转不转发过去。默认不转 |
| `runtime` | 转发时送过去的那个运行时（本机文件路径） |
| `tools` | 转发白名单，每项 `{tool, policy}`，policy 是 `always` / `agent` |
| `usable` | **登记**的可用性，不是探活 |

探活是现探的，不写回库：

```bash
curl -s -X POST $BASE/places/tab:deck/ping
```
```json
{"place":"tab:deck","alive":true,"ms":0,"why":"这个地方不转发，没有连接可探"}
```

`when` 上的 `place` 这一维不看属性，`key` 留空。比的是**这个执行单元**的工作区 ——
不是 `task.place`：树岔开之后同一个任务的两站可以落在不同地方。
