# 注册工具的三种方式

| | 实现在哪 | 怎么注册 |
| --- | --- | --- |
| [内置 `fn:`](#一内置-fn) | 内核进程里，随二进制发 | 出厂就在，只能改登记 |
| [MCP server · stdio](#二mcp-serverstdio) | 一个子进程 | `POST /declare` 给 `command` |
| [MCP server · HTTP](#三mcp-serverhttp) | 另一台机器 | `POST /declare` 给 `url` |

先做 [`../`](../) 的快速启动。

---

## 一、内置 `fn:`

出厂就有六个，`system: true` —— 谁都有，不看条件。

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"edit" "name":"glob" "name":"grep" "name":"read" "name":"write"
```

实现在内核进程里，运行时加不了新的。能改的是**登记**：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "tools": [{
    "name": "bash",
    "identity": "fn:tool.bash",
    "does": "Run a shell command and return its stdout, stderr and exit code.",
    "params": { "type":"object", "properties":{"command":{"type":"string"}}, "required":["command"] },
    "output": { "type":"object", "properties":{"stdout":{"type":"string"},"code":{"type":"number"}} },
    "system": false,
    "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"跑一下" }]]
  }] }
JSON
```
```json
{"tools":["bash"],"servers":{},"handles":[],"places":[],"modes":[],"cycles":0,
 "agents":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

### 案例

发一个描述里**没有**「跑一下」的任务，`bash` 应该不在这一轮的工具里。

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1", "mode":"chat1", "agent":"bot", "place":"local",
  "source":"user", "description":"你好" }
JSON

curl -s "$BASE/tasks/t-1/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep"]
```

`bash` 不在了。

---

## 二、MCP server（stdio）

实现是一个子进程。见 [`meetkit.ts`](./meetkit.ts) —— 操作已登录的浏览器，进已预约的会。

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

声明里一个工具都没写 —— 名字、描述、参数 schema 是 server 用 `tools/list` 报的。

### 案例

发一个描述里**有**「会议」的任务。

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2", "mode":"chat1", "agent":"bot", "place":"local",
  "source":"user", "description":"进那个已经预约好的会议做一次汇报" }
JSON

curl -s "$BASE/tasks/t-2/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep","browser_status","meet_join","meet_leave","share_open"]
```

```bash
curl -s "$BASE/tasks/t-2/messages?kind=call" | grep -o '"name":"[^"]*","input":[^}]*}'
```
```
"name":"browser_status","input":{}
```

模型真调了它。

---

## 三、MCP server（HTTP）

同一个 server，换 HTTP 传输 —— 可以在别的机器上。

```bash
bun examples/tool/meetkit.ts --http        # :7899
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "servers": [{
    "name": "meetweb",
    "url": "http://127.0.0.1:7899",

    "tools": {
      "meet_join": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"远端会议" }]] }
    }
  }] }
JSON
```
```json
{"servers":{"meetweb":["browser_status","meet_join","share_open","meet_leave"]}, …}
```

### 案例

两个 server 各自一套句柄，名字带 server 名，不会撞：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":8,"rows":[
  {"name":"mcp:meetkit/browser_status"},{"name":"mcp:meetkit/meet_join"},
  {"name":"mcp:meetkit/meet_leave"},{"name":"mcp:meetkit/share_open"},
  {"name":"mcp:meetweb/browser_status"},{"name":"mcp:meetweb/meet_join"},
  {"name":"mcp:meetweb/meet_leave"},{"name":"mcp:meetweb/share_open"}]}
```

---

## 反过来：内置工具怎么给外面用

引擎自己就是个 MCP server，`POST $BASE/mcp`。

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
  "params": { "name":"read", "arguments": { "file_path":".env.example" } } }
JSON
```
```json
{"jsonrpc":"2.0","id":2,"result":{
  "content":[{"type":"text","text":"{\"path\":\".env.example\",\"lines\":[…]}"}],
  "structuredContent":{"path":".env.example","totalLines":7,"lines":[…]}}}
```

只开这台机器自己实现的（`fn:`）；从别的 server 拉进来的不转发。

---

## 参数

### `tools[]`（方式一）

| | |
| --- | --- |
| `name` | 给模型看的名字 |
| `identity` | 指一条句柄。内置的是 `fn:tool.<名字>` |
| `does` `params` `output` | 给模型看的描述和 schema |
| `prompt` | 往系统提示里加的一段 |
| `system` | `true` = 谁都有，不看 `when` |
| `usable` | `false` = 登记着但不挂 |
| `concurrent` | 能不能跟别的工具同时跑 |
| `when` | 见下 |

### `servers[]`（方式二、三）

| | |
| --- | --- |
| `name` | 句柄名是 `mcp:<name>/<tool>`，不能带 `/` |
| `command` `args` `env` | stdio |
| `url` `headers` | HTTP |
| `tools.<工具名>` | `when` / `expectMs` / `system` / `usable` / `prompt` / `concurrent`，都可不给 |

`command` 和 `url` 给一个：

```json
{"problems":["server meetkit：要么给 command（起个子进程），要么给 url（HTTP），**给一个，不能都给也不能都不给**"]}
```

MCP 报的原样落进来：`name`→`name`，`description`→`does`，
`inputSchema`→`params`，`outputSchema`→`output`。

### `when`

`[[…],[…]]`：外层组间 or，组内 and。组号不用编。

| dim | key | 比的是 |
| --- | --- | --- |
| `task` / `agent` / `cycle` | 那张表的列名 | 那一行上的一个字段 |
| `chain` | 留空 | `chat1/ask#1 > chat1/act#2` |
| `moment` | 留空 | 哪一刻（见 [`../rule/`](../rule/)） |

`op`：`eq` `ne` `contains` `not_contains` `prefix` `suffix` `in`

一条都不给 = 从不触发：

```json
{"problems":["tool meet_join：不是系统工具，又一条触发条件都没有 —— 它永远不会被挂给任何一个智能体"]}
```

没命中时问它：

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
