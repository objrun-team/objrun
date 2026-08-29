# 工具

**工具走 MCP。** 注册的是一个 server，有哪些工具是它自己用 `tools/list` 报的 ——
你不用一个个写。我们只补几个 MCP 里没有的字段。

先做 [`../`](../) 的快速启动。

## 内置

随二进制发的六个，出厂就在，`system: true`（谁都有，不看条件）。

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"edit" "name":"glob" "name":"grep" "name":"read" "name":"write"
```

它们的实现在内核进程里（`identity` 是 `fn:tool.*`）。运行时能改的是**登记** ——
比如把 `bash` 从「谁都有」改成按条件挂：

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

## 加一个 MCP server

实现见 [`meetkit.ts`](./meetkit.ts) —— 一个标准 MCP server（`initialize` →
`tools/list` → `tools/call`），操作一台已登录的浏览器、进一个已预约的会。

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

`servers` 那一项就是 server 报回来的工具名 —— 声明里一个工具都没写。

`command` / `args` / `env` 和 `url` / `headers` 跟 `claude_desktop_config.json` 里
那个 `mcpServers` 一个形状，抄过来就能用。

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

`does` 和参数 schema 都是 server 报的，不是你写的。句柄名是 `mcp:<server>/<工具>`：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name, expect_ms from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":4,"rows":[{"name":"mcp:meetkit/browser_status","expect_ms":120000},
                   {"name":"mcp:meetkit/meet_join","expect_ms":120000}, …]}
```

## 字段

MCP 那边的原样收下：

| MCP `tools/list` | 这边 |
| --- | --- |
| `name` | `name` |
| `description` | `does` |
| `inputSchema` | `params` |
| `outputSchema` | `output` |

server 怎么起，跟 MCP 客户端配置一样：

| | |
| --- | --- |
| `command` `args` `env` | 起个子进程，JSON-RPC 走 stdio |
| `url` `headers` | POST 一条 JSON-RPC 过去 |

**给一个，不能都给也不能都不给**：

```json
{"problems":["server meetkit：要么给 command（起个子进程），要么给 url（HTTP），**给一个，不能都给也不能都不给**"]}
```

`tools.<工具名>` 是我们补的，**MCP 里没有这几样**，都可以不给：

| | |
| --- | --- |
| `when` | 什么时候把它摆给模型。MCP 里 `tools/list` 回什么由 client 自己定，这边是数据 |
| `expectMs` | 调多久算死。不给是 120000 |
| `system` | `true` = 谁都有，不看 `when` |
| `usable` | `false` = 登记着但不挂 |
| `prompt` | 往系统提示里加的一段用法约定 |
| `concurrent` | 能不能跟别的工具同时跑 |

### `when`

`[[…],[…]]` —— 外层组间 **or**，组内 **and**。组号不用你编。
一条 = `{ dim, key, op, value }`。

| dim | key | 比的是 |
| --- | --- | --- |
| `task` / `agent` / `cycle` | 那张表的列名 | 那一行上的一个字段 |
| `chain` | 留空 | 链路串 `chat1/ask#1 > chat1/act#2` |
| `moment` | 留空 | 现在是哪一刻（见 [`../rule/`](../rule/)） |

| op | |
| --- | --- |
| `eq` `ne` | 相等 / 不等 |
| `contains` `not_contains` | 含 / 不含 |
| `prefix` `suffix` | 前缀 / 后缀 |
| `in` | 在这份列表里（`value` 是 JSON 数组） |

一条都不给 = 从不触发，不是总是触发。

## 校验

`kind=inject` 那一行是内核出站前记下的凭据 —— 这一轮告诉了模型有哪些工具。

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

换一个描述里没有「会议」的任务，那四个就不在了。没命中时逐条问：

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

`got` = 实际取到的值。

```bash
curl -s $BASE/check
```
```json
{"trigger":[],"data":[]}
```

## 工具执行错

MCP 分两种错，这边照收：

| MCP | 什么时候 | 怎么回 |
| --- | --- | --- |
| 协议错（JSON-RPC `error`） | 没这个工具、请求形状不对 | 当成调用失败 |
| 工具执行错（`isError: true`） | 参数不合理、业务上不成 | **当结果回给模型**，它看了能自己改 |

```bash
curl -s -X POST $BASE/tasks/t-meet/messages -H 'content-type: application/json' -d @- <<'JSON'
{ "body": "会议地址是 zoom.us/j/123，进去" }
JSON
```

`meet_join` 会回 `isError: true` 加一句「这不是一个 Meet 地址，形如
https://meet.google.com/xxx-xxxx-xxx」—— 那句话进上下文，模型据它改。
