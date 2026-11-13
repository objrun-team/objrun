# Register tools

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ **tool** · [meet-join](../meet-join/) · [meet-book](../meet-book/) · [place](../place/) · [rule](../rule/) · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

Two implementations of the same die: register both and use both in one task.

```bash
cp config.yaml dist/                     # Put configuration beside the executable
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
curl -s $BASE/health
```
```json
{"ok":true,"db":"…/dist/data/h2h.sqlite","tables":13,"write":true,"query":true,"uptimeMs":5103}
```

Base setup (one place, two cycles, one agent):

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":8, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":8, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## Style one: in process

[`dice-plugin.ts`](./dice-plugin.ts)

```ts
export async function run(arg: unknown): Promise<unknown> {
  const { sides = 6 } = ((arg ?? {}) as { args?: { sides?: number } }).args ?? {};
  const value = 1 + Math.floor(Math.random() * sides);
  console.log(`[dice-plugin] sides=${sides} → ${value}`);
  return { sides, value, from: "fn" };
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
    "does": "Roll an n-sided die (in process)",
    "params": { "type":"object", "properties": { "sides": {"type":"integer"} }, "required":["sides"] },
    "output": { "type":"object", "properties": { "sides":{"type":"integer"}, "value":{"type":"integer"} } },
    "when": [[{ "dim":"task", "key":"description", "op":"contains", "value":"dice" }]]
  }]
}
JSON
```
```json
{"servers":{},"handles":["fn:tool.dice_in"],"places":[],"modes":[],"cycles":0,
 "agents":[],"tools":["dice_in"],"rules":[],"skills":[],"tables":[],"entries":{}}
```

## Style two: out of process

[`dice-server.ts`](./dice-server.ts) is an MCP server using JSON-RPC over stdio.

```ts
if (m.method === "tools/list") return reply({ tools: [TOOL] });

if (m.method === "tools/call") {
  const sides = Number(p.arguments?.sides ?? 6);
  const value = 1 + Math.floor(Math.random() * sides);
  process.stderr.write(`[dice-server] sides=${sides} → ${value}\n`);
  const out = { sides, value, from: "mcp" };
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
    "tools": { "dice_out": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"dice" }]] } }
  }]
}
JSON
```
```json
{"servers":{"dice":["dice_out"]},"handles":[],"places":[],"modes":[],"cycles":0,
 "agents":[],"tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

Names, descriptions, and schemas come from `tools/list`; they are not specified in the declaration.

## Both are registered

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

## One task uses both tools

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-dice", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 180,
  "description": "Roll 20-sided dice once with dice_in and once with dice_out, report both values, then finish" }
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
"value":{"sides":20,"value":1,"from":"fn"}
"value":{"sides":20,"value":14,"from":"mcp"}
```

```bash
curl -s "$BASE/tasks/t-dice/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"Both 20-sided dice have been rolled:\n\n- **dice_in** (in process): **1**\n- **dice_out** (out of process): **14**\n\nFinished."
```

### Logs

Plugin output appears on engine stdout. English rendering of the captured output:

```
{"level":30,…,"msg":"Plugin: app/src/engine/plugin-host.ts"}
[dice-plugin] sides=20 → 1
```

`dice-server` is a subprocess and logs to stderr. A stdio server uses stderr for logs; the engine forwards it unchanged:

```
[dice-server] Started
[dice-server] sides=20 → 14
```

---

## Fields

`handles[]`

| | |
| --- | --- |
| `name` | `fn:…` in process, `http://…` out of process |
| `expectMs` | Duration before the call is considered dead |
| `module` | For `fn:`: `path#export-name` |

`tools[]`

| | |
| --- | --- |
| `name` `does` `params` `output` | Shown to the model |
| `identity` | References a handle |
| `when` | When to offer it to the model |
| `system` `usable` `concurrent` `prompt` | Optional |

`servers[]`

| | |
| --- | --- |
| `name` | Handle name is `mcp:<name>/<tool>` |
| `command` `args` `env` | stdio |
| `url` `headers` | HTTP |
| `tools.<tool-name>` | `when` / `expectMs` / `system` / `usable` / `prompt` / `concurrent` |

`when`: `[[…],[…]]`, OR between outer groups, AND within each group. One condition = `{dim, key, op, value}`.

| dim | key |
| --- | --- |
| `task` `agent` `cycle` | Column name in that table |
| `chain` `moment` `place` | Empty |

`op`：`eq` `ne` `contains` `not_contains` `prefix` `suffix` `in`

### In-process plugin lifecycle

| | |
| --- | --- |
| Load | Insert the `handles` row; takes effect on the next loop |
| Update | Save the file to load the new version; no restart |
| Unload | Delete the `handle` row; the worker is collected with its memory and timers |

The executable bundles the worker host script, but cannot locate its own path, so the startup command supplies `TGENGIN_PLUGIN_HOST`. The startup log line labeled `Plugin: …` in the English rendering shows the actual path used. This setting is unnecessary when running from source.
