# 工具

**就是 MCP 的 tool，多了几个字段。** 先做 [`../`](../) 的快速启动。

| MCP | 这边 | |
| --- | --- | --- |
| `name` | `name` | 一样 |
| `description` | `does` | 一样 |
| `inputSchema` | `params` | 一样，JSON Schema |
| `outputSchema` | `output` | 一样 |
| —— | `identity` | **实现在哪**：`fn:…`（进程内）或 `http://…`（进程外） |
| —— | `when` | **什么时候摆给模型**。MCP 里 `tools/list` 回什么由 server 自己定，这边是数据 |
| —— | `system` | `true` = 谁都有，不看 `when` |
| —— | `usable` | 登记着但不挂 |
| —— | `concurrent` | 能不能跟别的工具同时跑 |
| —— | `expectMs` | 在 `handles` 上。调多久算死 |

`tools/call` 那一步这边不用你管：模型请求哪个工具、参数是什么，内核落库之后按
`identity` 转发过去。

---

## 内置（进程内 `fn:`）

随二进制发的六个，出厂就在，`system: true`。相当于 MCP host 自己进程里注册的
那批 —— **运行时加不了新的**，函数只有那个进程持有得住，要加只能换二进制。

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"edit" "name":"glob" "name":"grep" "name":"read" "name":"write"
```

能改的是它们的**登记**。比如把 `bash` 从「谁都有」改成按条件挂：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "tools": [{
    "name": "bash",
    "identity": "fn:tool.bash",
    "does": "Run a shell command and return its stdout, stderr and exit code.",
    "params": { "type":"object", "properties": { "command":{"type":"string"} }, "required":["command"] },
    "output": { "type":"object", "properties": { "stdout":{"type":"string"}, "code":{"type":"number"} } },
    "system": false,
    "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"跑一下" }]]
  }]
}
JSON
```
```json
{"tools":["bash"],"handles":[],"places":[],"modes":[],"cycles":0,"agents":[],
 "rules":[],"skills":[],"tables":[],"entries":{}}
```

```bash
curl -s $BASE/tools | tr '}' '\n' | grep -A1 '"name":"bash"'
```
```json
{"name":"bash","identity":"fn:tool.bash","does":"Run a shell command…",
 "system":false,"concurrent":false,"usable":true,
 "when":[[{"dim":"task","key":"description","op":"contains","value":"跑一下"
]],"neverFires":false
```

发一个描述里没有「跑一下」的任务，它就不在这一轮的工具里了：

```bash
curl -s "$BASE/tasks/t-nobash/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep"]
```

**外面不许注册 `fn:` 的句柄**：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "handles": [{ "name": "fn:tool.whatever", "expectMs": 1000 }] }
JSON
```
```json
{"problems":["handle fn:tool.whatever：外面只能注册 http:// 或 https:// 的句柄 —— fn: 是进程内的真函数，往库里写个名字换不出函数来"]}
```

---

## 外置（进程外 `http://`）

相当于一个 MCP server，只是传输是普通 HTTP：一个地址，收一份 JSON，回一份 JSON。
**注册一次就行，不动内核、不重启。**

例子：操作一台已登录的浏览器，进一个已预约的会。实现见 [`meetkit.ts`](./meetkit.ts)。

```bash
bun examples/tool/meetkit.ts        # :7899
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "handles": [
    { "name": "http://127.0.0.1:7899/browser_status", "expectMs": 10000 },
    { "name": "http://127.0.0.1:7899/meet_join",      "expectMs": 60000 }],

  "tools": [
    { "name": "browser_status",
      "identity": "http://127.0.0.1:7899/browser_status",
      "does": "那台常驻浏览器连上没有、登录没有",
      "params": { "type":"object", "additionalProperties": false },
      "output": { "type":"object", "properties": { "running":{"type":"boolean"}, "loggedIn":{"type":"boolean"} } },
      "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"会议" }]] },

    { "name": "meet_join",
      "identity": "http://127.0.0.1:7899/meet_join",
      "does": "进一个已经预约好的会",
      "params": { "type":"object", "properties": { "meetUrl":{"type":"string"} }, "required":["meetUrl"] },
      "output": { "type":"object", "properties": { "ok":{"type":"boolean"}, "meetId":{"type":"string"} } },
      "prompt": "进会只调 meet_join，别自己拼地址。",
      "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"会议" }]] }]
}
JSON
```
```json
{"handles":["http://127.0.0.1:7899/browser_status","http://127.0.0.1:7899/meet_join"],
 "tools":["browser_status","meet_join"],
 "places":[],"modes":[],"cycles":0,"agents":[],"rules":[],"skills":[],
 "tables":[],"entries":{}}
```

一条句柄被调到时收到的：

```json
{ "args": { "meetUrl": "https://meet.google.com/abc-defg-hij" },
  "place": "local", "agent": "bot", "instance": "t-meet#1", "unit": 1 }
```

`args` 是模型给的那份（对着 `params`）；外面那层是内核加的上下文。回什么对着
`output`，直接是那个 JSON —— 没有 MCP 的 `content` / `structuredContent` 那层包装。

| | 内置 `fn:` | 外置 `http://` |
| --- | --- | --- |
| 实现在哪 | 内核进程里 | 另一个进程，哪台机器都行 |
| 运行时能加吗 | **不能**，只能换二进制 | 能，`POST /declare` 一次 |
| 调用开销 | 同进程直接调 | 一次 HTTP |
| 你能改什么 | 只有登记 | 登记和实现都能改 |

---

## `when`

MCP 里「这次给模型看哪些工具」由 server 决定；这边是**数据**，写在 `when` 上。

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

一条都不给 = 从不触发：

```json
{"problems":["tool meet_join：不是系统工具，又一条触发条件都没有 —— 它永远不会被挂给任何一个智能体"]}
```

---

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
"tools":["read","write","edit","glob","grep","bash","browser_status","meet_join"]
```

```bash
curl -s "$BASE/tasks/t-other/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep","bash"]
```

没命中时逐条问，`got` 是实际取到的值：

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

---

## 工具清单会变

MCP 里这是 `notifications/tools/list_changed`。这边就是**再调一次 `/declare`** ——
`meet_join` 干完之后回过头把会里才有的那几样注册进去（见 `meetkit.ts` 的 `会里的工具`）。

```bash
curl -s -X POST http://127.0.0.1:7899/meet_join -H 'content-type: application/json' -d @- <<'JSON'
{ "args": { "meetUrl": "https://meet.google.com/abc-defg-hij" }, "place": "local" }
JSON
```
```json
{"ok":true,"meetId":"abc-defg-hij","长出来的工具":["meet_say","share_open","meet_leave"]}
```

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"browser_status" "name":"edit" "name":"glob" "name":"grep"
"name":"meet_join" "name":"meet_leave" "name":"meet_say" "name":"read"
"name":"share_open" "name":"write"
```

没进会的时候 `meet_say` 根本不存在。

MCP 的 Stateful Tools 那一节建议「创建型工具回一个 handle，后续调用带着它」。
这边两条都可以：`meet_join` 回了 `meetId`（handle），同时把会里的工具注册进来。

`share_open` 回的是那份材料的**操作契约** —— 能做哪些操作、各自对应什么键鼠输入：

```json
{"contract":{"type":"deck","state":{"page":1,"total":12,"heading":"开场"},
  "operations":[{"name":"next","input":"press('ArrowRight')"},
                {"name":"prev","input":"press('ArrowLeft')"},
                {"name":"goto","input":"type('12')"}]}}
```

会上连续听说是另一条轨（`apiMode: "duplex"`），见 [`../agent/`](../agent/)。
