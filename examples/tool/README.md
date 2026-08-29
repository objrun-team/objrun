# 工具

`meet_join` —— 操作一台已登录的浏览器，进一个已预约的会。
同一个工具，**两种写法**：进程内 (`fn:`) 和进程外 (`http://`)。

## 快速启动

```bash
cd app && bun start
BASE=http://127.0.0.1:7801/api
curl -s $BASE/health
```
```json
{"ok":true,"db":"…/h2h.sqlite","tables":12,"write":true,"query":true,"uptimeMs":31}
```

出厂就有的六个工具（`system: true`，谁一上来都有，不看条件）：

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash"  "name":"edit"  "name":"glob"  "name":"grep"  "name":"read"  "name":"write"
```

跑起来的底子（每个例子都要，只灌一次）：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "handles": [{ "name":"http://127.0.0.1:7899/unit",  "expectMs":30000 },
              { "name":"http://127.0.0.1:7899/infer", "expectMs":10000 }],
  "places": [{ "place": "local" }],
  "modes":  [{ "mode": "demo", "cycles": [
              { "cycle":"ask", "from":[], "next":[], "infer":"http://127.0.0.1:7899/infer" }] }],
  "agents": [{ "name": "bot", "apis": [], "unit": "http://127.0.0.1:7899/unit" }]
}
JSON
```
```json
{"handles":["…/unit","…/infer"],"places":["local"],"modes":["demo"],"cycles":1,
 "agents":["bot"],"tools":[],"rules":[],"skills":[],
 "tables":["task_demo","agent_bot_ctx","agent_bot_msg"],"entries":{"demo":["ask"]}}
```

---

## 写法一：进程内 (`fn:`)

实现是内核进程里的一个函数。见 [`inproc.ts`](./inproc.ts)，抄进 `main.ts`，重新编译。

```ts
reg.register(db, "fn:tool.meet_join", 60_000, async (arg) => {
  const a = arg as { args?: { meetUrl?: string } };
  return await joinMeeting(String(a.args?.meetUrl ?? ""));
});
```

之后在声明里按名字引用它：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "tools": [{
    "name": "meet_join",
    "identity": "fn:tool.meet_join",
    "does": "进一个已经预约好的会",
    "params": { "type":"object", "properties": { "meetUrl":{"type":"string"} }, "required":["meetUrl"] },
    "output": { "type":"object", "properties": { "ok":{"type":"boolean"}, "meetId":{"type":"string"} } },
    "prompt": "进会只调 meet_join，别自己拼地址。",
    "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"会议" }]]
  }]
}
JSON
```

**外面不许注册 `fn:` 的名字。** 库里存的只是名字，函数只有那个进程持有得住；
从外面写一行 `fn:` 进去，库里就多了一条谁都认领不了的句柄。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "handles": [{ "name": "fn:tool.whatever", "expectMs": 1000 }] }
JSON
```
```json
{"problems":["handle fn:tool.whatever：外面只能注册 http:// 或 https:// 的句柄 —— fn: 是进程内的真函数，往库里写个名字换不出函数来"]}
```

## 写法二：进程外 (`http://`)

实现是另一个进程。见 [`meetkit.ts`](./meetkit.ts)。

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
      "params": { "type":"object", "properties": {} },
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
 "tools":["browser_status","meet_join"], …}
```

往库里写一行就算注册完了，内核下一圈醒来自己给它合成调用器。

| | 进程内 `fn:` | 进程外 `http://` |
| --- | --- | --- |
| 怎么注册 | 改代码 → 重新编译 → 重启 | `POST /declare` 一次 |
| 调用开销 | 同进程直接调 | 一次 HTTP |
| 跑在哪 | 只能是引擎那台机器 | 哪台都行 |
| 谁能加 | 只有能改内核的人 | 任何够得着接口的人 |
| `expectMs` | 一样，超过就判死 | 一样 |

---

## 参数

### `handles[]`

| 字段 | 必给 | |
| --- | --- | --- |
| `name` | ✔ | 句柄名，同时也是地址。**只能 `http://` / `https://`** |
| `expectMs` | ✔ | 调它多久算死。超了内核判死，内外一视同仁 |

### `tools[]`

| 字段 | 必给 | |
| --- | --- | --- |
| `name` | ✔ | 给模型看的名字，也是 `places[].tools` 白名单引用的那个 |
| `identity` | ✔ | 指一条句柄：`fn:…` 或 `http://…` |
| `does` | ✔ | **给模型看的**描述。空着它不知道这是干什么的 |
| `params` | ✔ | **给模型看的**参数 schema |
| `output` | ✔ | **给模型看的**返回值 schema |
| `prompt` | | 往系统提示里加的一段用法约定 |
| `when` | | 什么时候挂给智能体。见下 |
| `system` | | `true` = 所有智能体一上来就有，**不看 `when`** |
| `concurrent` | | 能不能跟别的工具同时跑 |
| `usable` | | 默认 `true`。`false` = 登记着但不挂 |

### `when`

`[[…],[…]]` —— 外层组间 **or**，组内 **and**。组号不用你编。

一条 = `{ dim, key, op, value }`：

| dim | key | 比的是 |
| --- | --- | --- |
| `task` / `agent` / `cycle` | 那张表的列名 | 那一行上的一个字段 |
| `chain` | 留空 | 链路串 `demo/ask#1 > demo/act#2` |
| `moment` | 留空 | 现在是哪一刻（钩子，见 [`../rule/`](../rule/)） |

| op | |
| --- | --- |
| `eq` `ne` | 相等 / 不等 |
| `contains` `not_contains` | 含 / 不含 |
| `prefix` `suffix` | 前缀 / 后缀 |
| `in` | 在这份列表里（`value` 是 JSON 数组） |

**一条都不给 = 从不触发**，不是「总是触发」：

```json
{"problems":["tool weather：不是系统工具，又一条触发条件都没有 —— 它永远不会被挂给任何一个智能体"]}
```

写错一个字母也当场拒 —— 不拦的话那条工具就静静地再也不会出现：

```json
{"problems":["tool meet_join 第 0 组：不认得的比法 contain（认得的是 eq / ne / contains / not_contains / prefix / suffix / in）"]}
```

---

## 校验：真的挂上去了吗

```bash
curl -s $BASE/tools | grep -o '"name":"[^"]*"'
```
```
"name":"bash" "name":"browser_status" "name":"edit" "name":"glob" "name":"grep"
"name":"meet_join" "name":"read" "name":"write"
```

发一个描述里有「会议」的任务：

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-meet", "mode":"demo", "agent":"bot", "place":"local",
  "source":"user", "description":"进那个已经预约好的会议做一次汇报" }
JSON
```
```json
{"id":"t-meet","mode":"demo","cycle":"ask","instance":"t-meet#1","objective":false}
```

`kind=inject` 那一行是内核出站前记下的凭据 —— 这一轮告诉了模型有哪些工具：

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=inject" | grep -o '"tools":\[[^]]*\]'
```
```
"tools":["read","write","edit","glob","grep","bash","browser_status","meet_join"]
```

换一个描述里没有「会议」的任务，那两个就不在里面。没命中时逐条问：

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

---

## 进会之后：新句柄长出来

`meet_join` 干完之后**回过头调 `/declare`**，把会里才有的那几样注册进去
（见 `meetkit.ts` 里那个 `会里的工具`）。走的是跟你一样的公开接口，没有后门。

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

多了 `meet_say` / `share_open` / `meet_leave`。**没进会的时候这几个根本不存在**，
模型也就不可能去调它们。

`share_open` 回的是那份材料的**操作契约** —— 能做哪些操作、各自对应什么键鼠输入。
操作工具包是格式无关的纯键鼠，认的就是这份契约：

```json
{"contract":{"type":"deck","state":{"page":1,"total":12,"heading":"开场"},
  "operations":[{"name":"next","input":"press('ArrowRight')"},
                {"name":"prev","input":"press('ArrowLeft')"},
                {"name":"goto","input":"type('12')"}]}}
```

会上说话要连续听说，那是另一条轨（`apiMode: "duplex"`）——见 [`../agent/`](../agent/)。

```bash
curl -s $BASE/check
```
```json
{"trigger":[],"data":[]}
```
