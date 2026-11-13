# A tool that provides new handles

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ [tool](../tool/) · **meet-join** · [meet-book](../meet-book/) · [place](../place/) · [rule](../rule/) · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

`meet_join` joins a meeting. Only after joining do the meeting-specific `say` and `screen` tools appear in the table.

Field descriptions are in [`../tool/`](../tool/).

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
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

## Initially, only one tool is connected

[`meet-server.ts`](./meet-server.ts) exposes only `meet_join`. After joining successfully, it calls `/declare` to connect [`meet-live.ts`](./meet-live.ts); that is when `say` and `screen` become available.

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
        say:    { when: [[{ dim:"task", key:"description", op:"contains", value:"meeting" }]] },
        screen: { when: [[{ dim:"task", key:"description", op:"contains", value:"meeting" }]] },
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
    "args": ["examples/meet-join/meet-server.ts"],
    "tools": { "meet_join": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"meeting" }]] } }
  }] }
JSON
```
```json
{"servers":{"meet":["meet_join"]},"handles":[],"places":[],"modes":[],"cycles":0,
 "agents":[],"tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

Before joining:

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":1,"rows":[{"name":"mcp:meet/meet_join"}]}
```

---

## Submit a task

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-meet", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 240,
  "description": "This is a meeting task: first use meet_join to join https://meet.google.com/abc-defg-hij, then use the newly available meeting tools to say 'Hello everyone' and share file:///deck.html, then finish." }
JSON
```

After joining:

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":3,"rows":[
  {"name":"mcp:meet-live/say"},
  {"name":"mcp:meet-live/screen"},
  {"name":"mcp:meet/meet_join"}]}
```

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=call" | grep -o '"name":"[a-z_]*","input":[^}]*}'
```
```
"name":"meet_join","input":{"meetUrl":"https://meet.google.com/abc-defg-hij"}
"name":"say","input":{"text":"Hello everyone"}
"name":"screen","input":{"url":"file:///deck.html"}
```

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=tool" | grep -o '"value":{[^{}]*}'
```
```
"value":{"ok":true,"meetId":"abc-defg-hij","handles":["mcp:meet-live/say","mcp:meet-live/screen"]}
"value":{"ok":true,"meet":"abc-defg-hij","said":"Hello everyone"}
```

The `screen` response is a nested object containing the deck's operation contract, so the grep above does not capture it.

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"Meeting task completed:\n\n1. ✅ **Joined the meeting**: joined https://meet.google.com/abc-defg-hij using `meet_join`\n2. ✅ **Said 'Hello everyone'**: spoke using the meeting's `say` tool\n3. ✅ **Shared file:///deck.html**: shared using `screen`, which returned an operation contract; the deck has 12 slides, is currently on slide 1, and supports arrow navigation or a slide number to jump\n\nAll requested work is complete."
```

### Logs

Both servers are subprocesses; the engine forwards their stderr unchanged. English rendering of the captured output:

```
[meet] Started
[meet] Joined meeting abc-defg-hij
[meet-live abc-defg-hij] Started
[meet] Added tools mcp:meet-live/say、mcp:meet-live/screen
[meet-live abc-defg-hij] say「Hello everyone」
[meet-live abc-defg-hij] screen file:///deck.html
```

The `meet-live` line appears before `[meet] Added tools`: `/declare` completes only after connecting to the new server and requesting `tools/list`, so the server starts first.
