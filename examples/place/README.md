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

> **这样起来的浏览器没有音视频输入。** Chrome 136 起，默认 profile 上不许开远程调试，
> 所以只能另开一个 `--user-data-dir` —— 那是个空 profile：没登录，也没给过任何站点
> 摄像头麦克风的权限。在那个标签页里探一下就知道：
>
> ```
> enumerateDevices  [{"kind":"audioinput","label":"","id":"空"},
>                    {"kind":"videoinput","label":"","id":"空"}, …]
> getUserMedia      （挂住不返回 —— 权限弹窗在那儿等人点，没人点）
> ```
>
> `label` 和 `deviceId` 全是空的，就是「一个都没授权」。所以这条路只能开**不需要
> 摄像头麦克风的页面** —— deck 这种正好是。真要拿一个能进会说话的浏览器，
> 得走扩展那条路（跑在用户自己那个 profile 里），不是调试端口。

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

一份声明里三样：**这个地方是哪条链接**、**它给哪几个工具**、**一条核这两样的规则**。

工具的 `when` 写 `dim: "place"` —— 这一维问的是**这个执行单元在哪儿**。

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
LINK=file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "places": [{ "place": "tab:deck" }],
  "servers": [{
    "name": "deck",
    "command": "bun",
    "args": ["examples/place/tab-server.ts", "$LINK"],
    "tools": {
      "deck_state": { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_next":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_prev":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_goto":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] }
    }
  }],
  "handles": [{ "name":"fn:rule.deck_contract", "expectMs":15000,
                "module":"\$R/examples/place/deck-contract.ts#run" }],
  "rules": [{
    "identity": "fn:rule.deck_contract",
    "does": "这一站落在 tab:deck 上的时候，核一下那一页还开着、该有的工具都在",
    "params": {}, "writes": {}, "scope": {},
    "when": [[{ "dim":"moment","op":"eq","value":"unit_start" },
              { "dim":"place", "op":"eq","value":"tab:deck" }]]
  }]
}
JSON
```
```json
{"servers":{"deck":["deck_state","deck_next","deck_prev","deck_goto"]},
 "handles":["fn:rule.deck_contract"],"places":["tab:deck"],"rules":["fn:rule.deck_contract"],
 "modes":[],"cycles":0,"agents":[],"tools":[],"skills":[],"tables":[],"entries":{}}
```

链接要整条给，不是给一截让它去猜 —— **链接就是这个地方的身份**。同时开着两个 deck
的时候，猜会连错一个，而且连错了看不出来。

那条 `when` 里两项在**同一组**，所以是 and：`unit_start` 这一刻，**并且**这一站落在
`tab:deck` 上。

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

引擎这边它叫 `tab:deck`，浏览器那边它是哪条链接由 server 的参数说了算。
两边各认各的，中间靠这份声明对上。

## 核这个地方还在不在

[`deck-contract.ts`](./deck-contract.ts) 就是上面那条规则。每次有执行单元落在这儿、
开工之前，核两样：那条链接还开着，那四个工具还在表里。

齐的时候（引擎 stdout）：

```
[deck-contract] tab:deck 齐了：deck_goto、deck_next、deck_prev、deck_state｜t-deck 第 1 站
```

把那个标签页导走，再发一个任务：

```
{"level":50,…,"msg":"规则 fn:rule.deck_contract 在 unit_start 这一刻炸了：tab:deck 这个地方不对劲（t-gone 第 8 站）：那一页没开着：file:///E:/…/deck.html（现在开着的是 about:blank）"}
```

**为什么这件事非得是规则**：声明那一刻能核的只是第一遍。标签页是活的 —— 人随手一关，
库里那几行 `tool` 还好端端躺着，地方却已经空了。下一个执行单元照样把 `deck_next`
摆给模型，模型照样调，然后拿一条 isError 回来。「登记」和「现在还在不在」是两回事，
跟 `workplace.usable` 是登记不是探活一个道理 —— 所以核这件事得挂在**每次开工那一刻**，
那正是时刻 + 规则。

**它不拦。** 规则炸了只炸它自己，内核记一行日志，这一站照跑。钩子挂在主路上，
让它把整步带停的话，一条写坏的规则能让所有任务都不动。所以它的作用是当场说清楚
哪儿不对，不是把闸拉了。

### 工具名撞了会怎样

`tool.name` 是模型看见的那个名字，**全系统唯一**。再接一个也报 `deck_state` 的 server：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "servers": [{ "name":"deck2", "command":"bun",
    "args":["examples/place/tab-server.ts","$LINK"], "tools": {} }] }
JSON
```
```json
{"error":"工具名撞了：deck_state 已经是 mcp:deck/deck_state 的了，server deck2 也报了一个（要换的话先把旧那行删掉 —— 悄悄顶掉的话没人看得出来）"}
```

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
"name":"deck_next","input":{}
…（一直翻）
"name":"deck_state","input":{}
"name":"deck_goto","input":{"page":9}
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
"body":"已结束。deck 现在停在**第 9 张，标题「出了什么问题」**（共 12 张）。"
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
[tab] 起来了，认 file:///E:/…/deck.html，调试端口 9222
[tab] 接上了 Q3 Review — 1/12 开场｜file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
[tab] deck_state → {"page":1,"total":12,"title":"开场"}
[tab] deck_next → {"page":2,"total":12,"title":"这一季干了什么"}
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
