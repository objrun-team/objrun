# 注册工具

同一个骰子，两种写法，都注册进去，一个任务里都用上。

```bash
cd app && bun start
BASE=http://127.0.0.1:7801/api
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
{"handles":["fn:tool.dice_in"],"tools":["dice_in"],"servers":{},
 "places":[],"modes":[],"cycles":0,"agents":[],"rules":[],"skills":[],
 "tables":[],"entries":{}}
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
{"servers":{"dice":["dice_out"]},"handles":[],"tools":[],
 "places":[],"modes":[],"cycles":0,"agents":[],"rules":[],"skills":[],
 "tables":[],"entries":{}}
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
"value":{"sides":20,"value":1,"来自":"进程内插件"}
"value":{"sides":20,"value":15,"来自":"进程外 MCP server"}
```

```bash
curl -s "$BASE/tasks/t-dice/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"两个点数是：\n\n- **dice_in**（进程内）：**1**\n- **dice_out**（进程外）：**15**\n\n结束。"
```

### 日志

引擎的 stdout：

```
{"level":30,…,"msg":"插件：E:\\…\\app\\src\\engine\\plugin-host.ts"}
[dice-plugin] sides=20 → 1
```

`dice-server` 是子进程，它的 stderr 归引擎接管；单独起它就看得见：

```bash
bun examples/tool/dice-server.ts
```
```
[dice-server] 起来了
[dice-server] sides=20 → 15
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

worker 那个文件的位置：直接跑源码时自动找得到；**编译成的二进制要给
`TGENGIN_PLUGIN_HOST`**，指到 `app/src/engine/plugin-host.ts`。开机日志里那行
`插件：…` 就是它实际用的路径。
