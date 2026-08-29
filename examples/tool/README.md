# 注册工具

同一个骰子，两种写法，都注册进去，一个任务里都用上。
再往后是一个会给你新句柄的工具。

```bash
cp config.yaml dist/                     # 配置放 exe 旁边
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
curl -s $BASE/health
```
```json
{"ok":true,"db":"…/dist/data/h2h.sqlite","tables":13,"write":true,"query":true,"uptimeMs":5103}
```

底子（一个地方、两个周期、一个智能体）：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":8, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":8, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-chat"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## 写法一：进程内

[`dice-plugin.ts`](./dice-plugin.ts)

```ts
export async function run(arg: unknown): Promise<unknown> {
  const { sides = 6 } = ((arg ?? {}) as { args?: { sides?: number } }).args ?? {};
  const value = 1 + Math.floor(Math.random() * sides);
  console.log(`[dice-plugin] sides=${sides} → ${value}`);
  return { sides, value, 来自: "进程内插件" };
}
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "handles": [{ "name": "fn:tool.dice_in", "expectMs": 10000,
                "module": "E:/sgu-bzhc/EACN_EX/TgEngin/examples/tool/dice-plugin.ts#run" }],
  "tools": [{
    "name": "dice_in",
    "identity": "fn:tool.dice_in",
    "does": "掷一个 n 面骰子（进程内）",
    "params": { "type":"object", "properties": { "sides": {"type":"integer"} }, "required":["sides"] },
    "output": { "type":"object", "properties": { "sides":{"type":"integer"}, "value":{"type":"integer"} } },
    "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"骰子" }]]
  }]
}
JSON
```
```json
{"servers":{},"handles":["fn:tool.dice_in"],"places":[],"modes":[],"cycles":0,
 "agents":[],"tools":["dice_in"],"rules":[],"skills":[],"tables":[],"entries":{}}
```

## 写法二：进程外

[`dice-server.ts`](./dice-server.ts) —— 一个 MCP server，stdio 上的 JSON-RPC。

```ts
if (m.method === "tools/list") return reply({ tools: [TOOL] });

if (m.method === "tools/call") {
  const sides = Number(p.arguments?.sides ?? 6);
  const value = 1 + Math.floor(Math.random() * sides);
  process.stderr.write(`[dice-server] sides=${sides} → ${value}\n`);
  const out = { sides, value, 来自: "进程外 MCP server" };
  return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out });
}
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "servers": [{
    "name": "dice",
    "command": "bun",
    "args": ["examples/tool/dice-server.ts"],
    "tools": { "dice_out": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"骰子" }]] } }
  }]
}
JSON
```
```json
{"servers":{"dice":["dice_out"]},"handles":[],"places":[],"modes":[],"cycles":0,
 "agents":[],"tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

名字、描述、schema 都是 `tools/list` 报的，声明里没写。

## 两个都在

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select t.name, t.identity, h.module from tool t join handle h on h.name = t.identity where t.name like 'dice%' order by t.name" }
JSON
```
```json
{"count":2,"rows":[
  {"name":"dice_in", "identity":"fn:tool.dice_in",
   "module":"E:/sgu-bzhc/EACN_EX/TgEngin/examples/tool/dice-plugin.ts#run"},
  {"name":"dice_out","identity":"mcp:dice/dice_out","module":null}]}
```

---

## 一个任务，两个都用上

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-dice", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 180,
  "description": "用 dice_in 和 dice_out 各掷一次 20 面骰子，把两个点数都告诉我，然后就结束" }
JSON
```
```json
{"id":"t-dice","mode":"work","cycle":"ask","instance":"t-dice#1","objective":false}
```

```bash
curl -s "$BASE/tasks/t-dice/messages?kind=call" | grep -o '"name":"dice[^}]*}'
```
```
"name":"dice_in","input":{"sides":20}
"name":"dice_out","input":{"sides":20}
```

```bash
curl -s "$BASE/tasks/t-dice/messages?kind=tool" | grep -o '"value":{[^}]*}'
```
```
"value":{"sides":20,"value":10,"来自":"进程内插件"}
"value":{"sides":20,"value":14,"来自":"进程外 MCP server"}
```

```bash
curl -s "$BASE/tasks/t-dice/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"两个点数分别为：**10**（dice_in，进程内）和 **14**（dice_out，进程外）。\n\n结束。"
```

### 日志

引擎的 stdout 里有插件那条：

```
{"level":30,…,"msg":"插件：app/src/engine/plugin-host.ts"}
[dice-plugin] sides=20 → 10
```

`dice-server` 是子进程，它的 stderr 归引擎接管。

---

## 一个会给你新句柄的工具

[`meet-server.ts`](./meet-server.ts) 只有一个工具 `meet_join`。进会成功之后，
它回过头调 `/declare` 把 [`meet-live.ts`](./meet-live.ts) 接进来 —— 会里的
`say` 和 `screen` 就是那时候才有的。

```ts
const res = await fetch(`${BASE}/declare`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    servers: [{
      name: "meet-live",
      command: "bun",
      args: [LIVE, meetId],
      tools: {
        say:    { when: [[{ dim:"task", key:"description", op:"contains", value:"会议" }]] },
        screen: { when: [[{ dim:"task", key:"description", op:"contains", value:"会议" }]] },
      },
    }],
  }),
});
const handles = (got.servers?.["meet-live"] ?? []).map((t) => `mcp:meet-live/${t}`);
return { ok: true, meetId, handles };
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "servers": [{
    "name": "meet",
    "command": "bun",
    "args": ["examples/tool/meet-server.ts"],
    "tools": { "meet_join": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] } }
  }] }
JSON
```
```json
{"servers":{"meet":["meet_join"]}, …}
```

进会之前：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":2,"rows":[
  {"name":"mcp:dice/dice_out"},
  {"name":"mcp:meet/meet_join"}]}
```

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-meet", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 240,
  "description": "这是一个会议任务：先用 meet_join 进 https://meet.google.com/abc-defg-hij，进去之后用会里新出现的工具说一句「大家好」，再共享 file:///deck.html，然后就结束" }
JSON
```

进会之后：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":4,"rows":[
  {"name":"mcp:dice/dice_out"},
  {"name":"mcp:meet-live/say"},
  {"name":"mcp:meet-live/screen"},
  {"name":"mcp:meet/meet_join"}]}
```

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=call" | grep -o '"name":"[a-z_]*","input":[^}]*}'
```
```
"name":"meet_join","input":{"meetUrl":"https://meet.google.com/abc-defg-hij"}
"name":"say","input":{"text":"大家好"}
"name":"screen","input":{"url":"file:///deck.html"}
```

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=tool" | grep -o '"value":{[^{}]*}'
```
```
"value":{"ok":true,"meetId":"abc-defg-hij","handles":["mcp:meet-live/say","mcp:meet-live/screen"]}
"value":{"ok":true,"meet":"abc-defg-hij","说了":"大家好"}
```

`screen` 那条回的是嵌套对象（deck 的操作契约），上面这个 grep 不收。

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"任务已完成：\n\n1. ✅ **进入会议** — 通过 `meet_join` 成功加入了 https://meet.google.com/abc-defg-hij，并获得了 `say` 和 `screen` 工具。\n2. ✅ **说了「大家好」** — `say` 工具已发出该话。\n3. ✅ **共享了 file:///deck.html** — `screen` 工具返回了操作契约（deck 展示，共 12 页，支持 next / prev / goto）。\n\n会议任务全部完成。"
```

### 日志

```
[meet] 起来了
[meet] 进会 abc-defg-hij
[meet] 长出 mcp:meet-live/say、mcp:meet-live/screen
[meet-live abc-defg-hij] 起来了
[meet-live abc-defg-hij] say「大家好」
[meet-live abc-defg-hij] screen file:///deck.html
```

---

## 字段

`handles[]`

| | |
| --- | --- |
| `name` | `fn:…` 进程内，`http://…` 进程外 |
| `expectMs` | 调多久算死 |
| `module` | `fn:` 用：`路径#导出名` |

`tools[]`

| | |
| --- | --- |
| `name` `does` `params` `output` | 给模型看的 |
| `identity` | 指一条句柄 |
| `when` | 什么时候摆给模型 |
| `system` `usable` `concurrent` `prompt` | 可不给 |

`servers[]`

| | |
| --- | --- |
| `name` | 句柄名是 `mcp:<name>/<tool>` |
| `command` `args` `env` | stdio |
| `url` `headers` | HTTP |
| `tools.<工具名>` | `when` / `expectMs` / `system` / `usable` / `prompt` / `concurrent` |

`when`：`[[…],[…]]`，外层 or，内层 and。一条 = `{dim, key, op, value}`。

| dim | key |
| --- | --- |
| `task` `agent` `cycle` | 那张表的列名 |
| `chain` `moment` | 留空 |

`op`：`eq` `ne` `contains` `not_contains` `prefix` `suffix` `in`

### 进程内插件的生命周期

| | |
| --- | --- |
| 装 | 写 `handles` 那一行，下一圈生效 |
| 改 | 存文件就换新版本，不用重启 |
| 卸 | 删掉 `handle` 那一行，worker 连同它的内存和定时器一起收 |

worker 的宿主脚本 exe 里带着，但 exe 找不到自己的路径，所以开头那条命令给了
`TGENGIN_PLUGIN_HOST`。开机日志里 `插件：…` 那行就是它实际用的路径。跑源码时不用给。
