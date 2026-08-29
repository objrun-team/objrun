# 注册工具

**一个工具就是 `tool` 表里的一行。** 行上的 `identity` 指一条句柄，句柄只有一条轴：

| 句柄 | 实现在哪 | 外面能注册吗 |
| --- | --- | --- |
| `fn:…` | 内核进程里，随二进制发 | 不能（函数传不过来）。但能引用已有的 |
| `http://…` | 另一个进程 | 能，写一行就是了 |

**注册就是写那一行。** 写法有两种，落到库里是同样的行：

| | |
| --- | --- |
| [一条一条写](#一条一条写) | `tools[]`，自己给 `identity` / `does` / `params` / `output` |
| [让 server 自己报](#让-server-自己报) | `servers[]`，声明一个 MCP server，它用 `tools/list` 报一堆 |

MCP 不是第三类句柄，是这两边**说话的方式** —— 协议本身进程内外都支持，
决定边界的是传输（内存 / stdio 子进程 / HTTP）。

先做 [`../`](../) 的快速启动。

---

## 出厂就有的

六个工具随二进制发，`identity` 是 `fn:tool.*`，`system: true` —— 谁都有，不看条件。

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"edit" "name":"glob" "name":"grep" "name":"read" "name":"write"
```

它同时是一个 MCP server，别的客户端也能用：

```bash
curl -s -X POST $BASE/mcp -H 'content-type: application/json' -d @- <<'JSON'
{ "jsonrpc":"2.0", "id":1, "method":"tools/list" }
JSON
```
```json
{"jsonrpc":"2.0","id":1,"result":{"tools":[
  {"name":"bash","description":"Run a shell command…","inputSchema":{…},"outputSchema":{…}},
  {"name":"edit"},{"name":"glob"},{"name":"grep"},{"name":"read"},{"name":"write"}]}}
```

```bash
curl -s -X POST $BASE/mcp -H 'content-type: application/json' -d @- <<'JSON'
{ "jsonrpc":"2.0", "id":2, "method":"tools/call",
  "params": { "name":"read", "arguments": { "file_path":".env.example", "limit":3 } } }
JSON
```
```json
{"jsonrpc":"2.0","id":2,"result":{
  "content":[{"type":"text","text":"{\"path\":\".env.example\",\"lines\":[…]}"}],
  "structuredContent":{"path":".env.example","totalLines":7,"truncated":true,"lines":[…]}}}
```

运行时加不了新的（函数在二进制里），但登记能改：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "tools": [{ "name":"bash", "identity":"fn:tool.bash",
              "does":"Run a shell command and return its stdout, stderr and exit code.",
              "params":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]},
              "output":{"type":"object","properties":{"stdout":{"type":"string"},"code":{"type":"number"}}},
              "system": false,
              "when": [[{"dim":"task","key":"description","op":"contains","value":"跑一下"}]] }] }
JSON
```

### 案例

发一个描述里没有「跑一下」的任务：

```bash
curl -s "$BASE/tasks/t-1/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep"]
```

---

## 一条一条写

实现在进程外：先声明句柄，再写工具那一行。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "handles": [{ "name": "http://127.0.0.1:7898/dice", "expectMs": 10000 }],
  "tools": [{
    "name": "dice",
    "identity": "http://127.0.0.1:7898/dice",
    "does": "掷一个 n 面骰子",
    "params": { "type":"object", "properties": { "sides": {"type":"integer"} }, "required":["sides"] },
    "output": { "type":"object", "properties": { "value": {"type":"integer"} } },
    "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"骰子" }]]
  }]
}
JSON
```
```json
{"handles":["http://127.0.0.1:7898/dice"],"tools":["dice"],
 "servers":{},"places":[],"modes":[],"cycles":0,"agents":[],
 "rules":[],"skills":[],"tables":[],"entries":{}}
```

那个地址收一份 JSON、回一份 JSON：

```jsonc
// 收到
{ "args": { "sides": 20 }, "place": "local", "agent": "bot", "instance": "t-b#1", "unit": 2 }
// 回
{ "sides": 20, "value": 1 }
```

### 案例

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-b", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "description":"帮我掷一个 20 面的骰子，把点数告诉我，然后就结束" }
JSON

curl -s "$BASE/tasks/t-b/messages?kind=tool" | grep -o '"value":{[^}]*}'
curl -s "$BASE/tasks/t-b/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"value":{"sides":20,"value":1}
"body":"掷出的点数是 **1**。\n\n结束。"
```

---

## 让 server 自己报

[`meetkit.ts`](./meetkit.ts) 是个普通 MCP server —— 操作已登录的浏览器，进已预约的会。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "servers": [{
    "name": "meetkit",
    "command": "bun",
    "args": ["examples/tool/meetkit.ts"],
    "tools": {
      "meet_join":      { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] },
      "browser_status": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] },
      "share_open":     { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] },
      "meet_leave":     { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] }
    }
  }] }
JSON
```
```json
{"servers":{"meetkit":["browser_status","meet_join","share_open","meet_leave"]},
 "handles":[],"places":[],"modes":[],"cycles":0,"agents":[],
 "tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

声明里一个工具都没写 —— 名字、描述、schema 是 `tools/list` 报的。

### 案例

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-c", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "description":"先看一下浏览器状态，这是会议相关的准备，看完就结束" }
JSON

curl -s "$BASE/tasks/t-c/messages?kind=inject" | grep -o '"tools":\[[^]]*\]' | head -1
curl -s "$BASE/tasks/t-c/messages?kind=tool"   | grep -o '"value":{[^}]*}'
```
```
"tools":["read","write","edit","glob","grep","bash","browser_status","meet_join","meet_leave","share_open"]
"value":{"running":true,"profile":"meetkit-chrome","loggedIn":true}
```

---

## 换个位置跑

远程没有第二种含义：**命令前缀**。

```jsonc
{ "command": "ssh",     "args": ["box-7", "/opt/thing/server"] }
{ "command": "wsl.exe", "args": ["--", "/tmp/tgengin-runtime"] }
{ "command": "docker",  "args": ["exec", "-i", "build-01", "/tmp/tgengin-runtime"] }
{ "url": "http://10.0.0.7:7899" }
```

`workplace` 就是把这段前缀包起来：给一个位置串，它负责把运行时送过去、拼命令。
运行时（`dist/tgengin-runtime-linux-x64`）也是个 MCP server，装的是同一批工具。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "places": [{
    "place": "wsl",
    "runtime": "E:/sgu-bzhc/EACN_EX/TgEngin/dist/tgengin-runtime-linux-x64",
    "forward": true,
    "tools": [{ "tool": "bash", "policy": "always" }] }] }
JSON

curl -s -X POST $BASE/places/wsl/ping
```
```json
{"place":"wsl","alive":true,"ms":3614}
```

### 案例

两个周期：`ask` 问模型，`act` 把它请求的工具跑掉，再回 `ask`。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":6, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":6, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],

  "agents": [{ "name":"bot",
               "apis":[["DEEPSEEK_API_KEY","deepseek-chat"]],
               "unit":"fn:unit.tools" }]
}
JSON
```

`apiMode` 留空的那一站走 `agent.unit`；`fn:unit.tools` 就是「把上一站请求的工具跑掉」。

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-loop", "mode":"work", "agent":"bot", "place":"wsl", "source":"user",
  "solveSeconds": 180,
  "description": "用 bash 跑一下 uname -s -r，把输出原样告诉我，然后就结束" }
JSON
```

```bash
curl -s $BASE/tasks/t-loop | grep -o '"cycle":"[a-z]*","unit":[0-9]*'
```
```
"cycle":"ask","unit":1
"cycle":"act","unit":2
"cycle":"ask","unit":3
```

```bash
curl -s $BASE/tasks/t-loop/messages | tr '{' '\n' | grep -oE '"unit":[0-9]+,"seq":[0-9]+,"role":"[a-z]+","kind":"[a-z]+"'
```
```
"unit":1,"seq":1,"role":"user","kind":"user"
"unit":1,"seq":2,"role":"system","kind":"inject"
"unit":1,"seq":3,"role":"assistant","kind":"call"
"unit":2,"seq":1,"role":"system","kind":"inject"
"unit":2,"seq":2,"role":"tool","kind":"tool"
"unit":2,"seq":3,"role":"system","kind":"inject"
"unit":3,"seq":1,"role":"system","kind":"inject"
"unit":3,"seq":2,"role":"assistant","kind":"prompt"
```

```bash
curl -s "$BASE/tasks/t-loop/messages?kind=tool" | grep -o 'Linux[^\\"]*'
curl -s "$BASE/tasks/t-loop/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
Linux 6.18.33.2-microsoft-standard-WSL2
"body":"输出：\n\n```\nLinux 6.18.33.2-microsoft-standard-WSL2\n```"
```

工具在 WSL 里跑，结果回到上下文，模型看着它作答。

---

## 参数

### `servers[]`

| | |
| --- | --- |
| `name` | 句柄名是 `mcp:<name>/<tool>`，不能带 `/` |
| `command` `args` `env` | stdio |
| `url` `headers` | HTTP |
| `tools.<工具名>` | 见下，都可不给 |

`command` 和 `url` 给一个：

```json
{"problems":["server meetkit：要么给 command（起个子进程），要么给 url（HTTP），**给一个，不能都给也不能都不给**"]}
```

MCP 报的原样落进来：`name`→`name`，`description`→`does`，
`inputSchema`→`params`，`outputSchema`→`output`。

### `tools.<工具名>`

MCP 里没有这几样，是这边加的。

| | |
| --- | --- |
| `when` | 什么时候摆给模型 |
| `expectMs` | 调多久算死。默认 120000 |
| `system` | `true` = 谁都有，不看 `when` |
| `usable` | `false` = 登记着但不挂 |
| `prompt` | 往系统提示里加的一段 |
| `concurrent` | 能不能跟别的工具同时跑 |

### `when`

`[[…],[…]]`：外层组间 or，组内 and。组号不用编。

| dim | key | 比的是 |
| --- | --- | --- |
| `task` / `agent` / `cycle` | 那张表的列名 | 那一行上的一个字段 |
| `chain` | 留空 | `work/ask#1 > work/act#2` |
| `moment` | 留空 | 哪一刻（见 [`../rule/`](../rule/)） |

`op`：`eq` `ne` `contains` `not_contains` `prefix` `suffix` `in`

一条都不给 = 从不触发：

```json
{"problems":["tool meet_join：不是系统工具，又一条触发条件都没有 —— 它永远不会被挂给任何一个智能体"]}
```

没命中时：

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' -d @- <<'JSON'
{ "kind":"tool", "owner":"meet_join", "task":"t-1" }
JSON
```
```json
{"fired":false,
 "groups":[[{"group":0,"dim":"task","key":"description","op":"contains","value":"会议",
             "got":"你好","hit":false}]]}
```

### 错

| | |
| --- | --- |
| JSON-RPC `error` | 没这个工具、请求形状不对 → 当调用失败 |
| `isError: true` | 参数不合理、业务上不成 → 当结果回给模型 |
