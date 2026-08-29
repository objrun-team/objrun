# 工具

工具走 MCP。先做 [`../`](../) 的快速启动。

## 引擎自己就是一个 MCP server

内置的六个工具从 `POST $BASE/mcp` 开出去，任何 MCP 客户端都能用。

```bash
curl -s -X POST $BASE/mcp -H 'content-type: application/json' -d @- <<'JSON'
{ "jsonrpc":"2.0", "id":1, "method":"initialize",
  "params": { "protocolVersion":"2026-07-28", "capabilities":{}, "clientInfo":{"name":"x","version":"1"} } }
JSON
```
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2026-07-28",
 "capabilities":{"tools":{"listChanged":false}},
 "serverInfo":{"name":"tgengin","version":"1.0.0"}}}
```

```bash
curl -s -X POST $BASE/mcp -H 'content-type: application/json' -d @- <<'JSON'
{ "jsonrpc":"2.0", "id":2, "method":"tools/list" }
JSON
```
```json
{"jsonrpc":"2.0","id":2,"result":{"tools":[
  {"name":"bash","description":"Run a shell command…","inputSchema":{…}},
  {"name":"edit"},{"name":"glob"},{"name":"grep"},{"name":"read"},{"name":"write"}]}}
```

```bash
curl -s -X POST $BASE/mcp -H 'content-type: application/json' -d @- <<'JSON'
{ "jsonrpc":"2.0", "id":3, "method":"tools/call",
  "params": { "name":"read", "arguments": { "file_path":".env.example" } } }
JSON
```
```json
{"jsonrpc":"2.0","id":3,"result":{
  "content":[{"type":"text","text":"{\"path\":\".env.example\",\"lines\":[…]}"}],
  "structuredContent":{"path":".env.example","lines":[…],"totalLines":7}}}
```

```bash
curl -s -X POST $BASE/mcp -H 'content-type: application/json' -d @- <<'JSON'
{ "jsonrpc":"2.0", "id":4, "method":"tools/call", "params": { "name":"nope" } }
JSON
```
```json
{"jsonrpc":"2.0","id":4,"error":{"code":-32602,"message":"没有这个工具：nope"}}
```

只开这台机器自己实现的（`identity` 是 `fn:`）；从别的 server 拉进来的不转发。

## 改内置工具的登记

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
```json
{"tools":["bash"],"servers":{},"handles":[],"places":[],"modes":[],"cycles":0,
 "agents":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

```bash
curl -s "$BASE/tasks/t-nobash/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep"]
```

## 接一个 MCP server

[`meetkit.ts`](./meetkit.ts) —— 操作已登录的浏览器，进已预约的会。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "servers": [{
    "name": "meetkit",
    "command": "bun",
    "args": ["examples/tool/meetkit.ts"],
    "tools": {
      "meet_join":      { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] },
      "browser_status": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] },
      "share_open":     { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] },
      "meet_leave":     { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] }
    }
  }]
}
JSON
```
```json
{"servers":{"meetkit":["browser_status","meet_join","share_open","meet_leave"]},
 "handles":[],"places":[],"modes":[],"cycles":0,"agents":[],
 "tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

声明里一个工具都没写 —— `tools/list` 是它自己报的。

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"browser_status" "name":"edit" "name":"glob" "name":"grep"
"name":"meet_join" "name":"meet_leave" "name":"read" "name":"share_open" "name":"write"
```

```bash
curl -s $BASE/tools | tr '}' '\n' | grep -A1 '"name":"meet_join"'
```
```json
{"name":"meet_join","identity":"mcp:meetkit/meet_join",
 "does":"进一个已经预约好的会","system":false,"concurrent":false,"usable":true,
 "when":[[{"dim":"task","key":"description","op":"contains","value":"会议"}]],
 "neverFires":false}
```

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name, expect_ms from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":4,"rows":[{"name":"mcp:meetkit/browser_status","expect_ms":120000},
                   {"name":"mcp:meetkit/meet_join","expect_ms":120000},
                   {"name":"mcp:meetkit/meet_leave","expect_ms":120000},
                   {"name":"mcp:meetkit/share_open","expect_ms":120000}]}
```

## 校验

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-meet", "mode":"chat1", "agent":"bot", "place":"local",
  "source":"user", "description":"进那个已经预约好的会议做一次汇报" }
JSON

curl -s "$BASE/tasks/t-meet/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep","bash","browser_status","meet_join","meet_leave","share_open"]
```

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=call" | grep -o '"name":"[^"]*","input":[^}]*}'
```
```
"name":"browser_status","input":{}
```

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' -d @- <<'JSON'
{ "kind":"tool", "owner":"meet_join", "task":"t-other" }
JSON
```
```json
{"fired":false,
 "groups":[[{"group":0,"dim":"task","key":"description","op":"contains","value":"会议",
             "got":"帮我算一下三加五","hit":false}]]}
```

```bash
curl -s $BASE/check
```
```json
{"trigger":[],"data":[]}
```

## 参数

### `servers[]`

| | |
| --- | --- |
| `name` | 必给。句柄名是 `mcp:<name>/<tool>`，所以不能带 `/` |
| `command` `args` `env` | stdio：起个子进程 |
| `url` `headers` | HTTP：POST JSON-RPC |
| `tools.<工具名>` | 见下。没提到的工具照 MCP 报的原样收 |

`command` 和 `url` **给一个**：

```json
{"problems":["server meetkit：要么给 command（起个子进程），要么给 url（HTTP），**给一个，不能都给也不能都不给**"]}
```

### `tools.<工具名>`

MCP 里没有这几样，都可以不给。

| | |
| --- | --- |
| `when` | 什么时候摆给模型 |
| `expectMs` | 调多久算死。默认 120000 |
| `system` | `true` = 谁都有，不看 `when` |
| `usable` | `false` = 登记着但不挂 |
| `prompt` | 往系统提示里加的一段 |
| `concurrent` | 能不能跟别的工具同时跑 |

MCP 报的原样落进来：`name` → `name`，`description` → `does`，
`inputSchema` → `params`，`outputSchema` → `output`。

### `when`

`[[…],[…]]`：外层组间 or，组内 and。组号不用编。

| dim | key | 比的是 |
| --- | --- | --- |
| `task` / `agent` / `cycle` | 那张表的列名 | 那一行上的一个字段 |
| `chain` | 留空 | `chat1/ask#1 > chat1/act#2` |
| `moment` | 留空 | 哪一刻（见 [`../rule/`](../rule/)） |

`op`：`eq` `ne` `contains` `not_contains` `prefix` `suffix` `in`

一条都不给 = 从不触发。

### 错

| | |
| --- | --- |
| JSON-RPC `error` | 没这个工具、请求形状不对 → 当调用失败 |
| `isError: true` | 参数不合理、业务上不成 → 当结果回给模型 |
