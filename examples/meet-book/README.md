# Create a real Google Meet meeting

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · **meet-book** · [place](../place/) · [rule](../rule/) · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

Two tools: one starts authorization, the other creates a meeting. **Try both implementation styles.**

Authorization is itself a tool: call it if authorization is missing, give the link to the user, then continue after they click it. No one needs to run a separate script.

Field descriptions are in [`../tool/`](../tool/).

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

An OAuth client must exist on disk, created as a **Desktop app** in Google Cloud Console:

```bash
mkdir -p ~/.tgengin && cp client_secret.json ~/.tgengin/
```

After authorization, credentials are automatically saved to `~/.tgengin/google.json`.

Base setup (one place, two cycles, one agent):

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":20, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":20, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## Style one: in process

[`book-plugin.ts`](./book-plugin.ts) exports two functions; both handles point to the same file:

```ts
export async function login(): Promise<unknown> {
  const got = await authStart();
  console.log(`[book-plugin] Authorization: ${got.note}`);
  return { ...got, from: "fn" };
}

export async function book(arg: unknown): Promise<unknown> {
  const a = ((arg ?? {}) as { args?: Record<string, unknown> }).args ?? {};
  const got = await create(a as Parameters<typeof create>[0]);
  return { ...got, from: "fn" };
}
```

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "handles": [
    { "name":"fn:tool.google_login_in", "expectMs":30000,
      "module":"$R/examples/meet-book/book-plugin.ts#login" },
    { "name":"fn:tool.meet_book_in", "expectMs":240000,
      "module":"$R/examples/meet-book/book-plugin.ts#book" }],
  "tools": [
    { "name":"google_login_in", "identity":"fn:tool.google_login_in",
      "does":"Start Google authorization and return a link for the user to click (in process)",
      "params":{ "type":"object", "properties":{} },
      "output":{ "type":"object", "properties":{
        "ok":{"type":"boolean"}, "authUrl":{"type":"string"}, "note":{"type":"string"} } },
      "when":[[{ "dim":"task","key":"description","op":"contains","value":"meeting" }]] },
    { "name":"meet_book_in", "identity":"fn:tool.meet_book_in",
      "does":"Create a Google meeting and return its Meet URL (in process)",
      "params":{ "type":"object", "properties":{
        "summary":{"type":"string"}, "minutesFromNow":{"type":"integer"}, "minutes":{"type":"integer"} } },
      "output":{ "type":"object", "properties":{
        "meetUrl":{"type":"string"}, "eventId":{"type":"string"} } },
      "when":[[{ "dim":"task","key":"description","op":"contains","value":"meeting" }]] }]
}
JSON
```
```json
{"servers":{},"handles":["fn:tool.google_login_in","fn:tool.meet_book_in"],
 "places":[],"modes":[],"cycles":0,"agents":[],
 "tools":["google_login_in","meet_book_in"],"rules":[],"skills":[],"tables":[],"entries":{}}
```

The two `expectMs` values differ: authorization returns immediately, whereas meeting creation waits for the user to click the link, so it gets 240s.

## Style two: out of process

[`book-server.ts`](./book-server.ts) is an MCP server exposing two tools. **Their implementations are the same code as in style one**: both import [`google.ts`](./google.ts).

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "servers": [{
    "name": "book",
    "command": "bun",
    "args": ["examples/meet-book/book-server.ts"],
    "tools": {
      "google_login_out": { "expectMs":30000,
        "when":[[{ "dim":"task","key":"description","op":"contains","value":"meeting" }]] },
      "meet_book_out": { "expectMs":240000,
        "when":[[{ "dim":"task","key":"description","op":"contains","value":"meeting" }]] }
    }
  }]
}
JSON
```
```json
{"servers":{"book":["google_login_out","meet_book_out"]},"handles":[],
 "places":[],"modes":[],"cycles":0,"agents":[],"tools":[],"rules":[],"skills":[],
 "tables":[],"entries":{}}
```

## All four are registered

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select t.name, t.identity, h.expect_ms from tool t join handle h on h.name = t.identity order by t.name" }
JSON
```
```json
{"count":4,"rows":[
  {"name":"google_login_in", "identity":"fn:tool.google_login_in", "expect_ms":30000},
  {"name":"google_login_out","identity":"mcp:book/google_login_out","expect_ms":30000},
  {"name":"meet_book_in",    "identity":"fn:tool.meet_book_in",    "expect_ms":240000},
  {"name":"meet_book_out",   "identity":"mcp:book/meet_book_out",  "expect_ms":240000}]}
```

---

## Before authorization

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-book", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 900,
  "description": "Create a meeting for me. First call google_login_in and show its authorization URL unchanged. Immediately call meet_book_in to create a meeting titled 'In process'; this tool waits until I finish authorization, so do not stop to ask me. Then call meet_book_out to create a meeting titled 'Out of process'. Both meetings start in 15 minutes and last 30 minutes. Give me both Meet URLs, then finish." }
JSON
```

Include “do not stop to ask me.” Otherwise the model may say “tell me when you have clicked it” and submit; `fn:infer.dfs` treats that round as terminal and ends the task. **Waiting for a person requires the tool to block that call**, rather than expecting the model to wait.

```bash
curl -s "$BASE/tasks/t-book/messages?kind=tool" | grep -o '"value":{"ok":[^{}]*}' | head -1
```
```
"value":{"ok":false,"authUrl":"https://accounts.google.com/o/oauth2/v2/auth?client_id=…&redirect_uri=http%3A%2F%2Flocalhost%3A56459&response_type=code&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.events&access_type=offline&prompt=consent","note":"Give this link to the user; authorization completes when they click it","from":"fn"}
```

The `redirect_uri` port is a newly selected free port each time. The callback listener lives in the plugin worker. Once the link is sent, the `meet_book_in` call blocks in `authWait`.

Clicking the link displays a message that authorization succeeded and work can resume; the blocked call wakes and continues creating the meeting. **If no one clicks, it gives up after 180s**:

```bash
curl -s "$BASE/tasks/t-book/messages?kind=tool" | grep -o '"value":{"error":[^{}]*}'
```
```
"value":{"error":"Not authorized yet: first call the authorization-start tool and give the user the link to click"}
```
```
  "state":"done"（185s）
```

The error is returned to the model as a result, so it can see the cause, rather than facing an unexplained silent tool failure.

## With authorization already present

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-book3", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 600,
  "description": "Create a meeting titled 'In process' using meet_book_in, then a meeting titled 'Out of process' using meet_book_out. Both start in 15 minutes and last 30 minutes. Give me both Meet URLs, then finish." }
JSON
```
```bash
curl -s "$BASE/tasks/t-book3/messages?kind=call" | grep -o '"name":"[a-z_]*","input":[^}]*}'
```
```
"name":"meet_book_in","input":{"summary":"In process","minutesFromNow":15,"minutes":30}
"name":"meet_book_out","input":{"summary":"Out of process","minutesFromNow":15,"minutes":30}
```

```bash
curl -s "$BASE/tasks/t-book3/messages?kind=tool" | grep -o '"value":{"meetUrl":[^{}]*}'
```
```
"value":{"meetUrl":"https://meet.google.com/nii-tnnb-toz","eventId":"qjfqjqmvmhfal53fupna37b1rk","summary":"In process","start":"2026-08-30T00:57:35+08:00","end":"2026-08-30T01:27:35+08:00","htmlLink":"https://www.google.com/calendar/event?eid=…","from":"fn"}
"value":{"meetUrl":"https://meet.google.com/nui-kzuf-qni","eventId":"g9r0r1v1ludi1a1i582bcu0148","summary":"Out of process","start":"2026-08-30T00:57:36+08:00","end":"2026-08-30T01:27:36+08:00","htmlLink":"https://www.google.com/calendar/event?eid=…","from":"mcp"}
```
```
  "state":"done"（10s）
```

Both links are real, and the calendar contains two actual events. This run never invoked authorization: credentials reside in `~/.tgengin/google.json`, **on the machine, not inside a process**. Authorization obtained by the in-process tool is usable by the out-of-process tool. The engine knows the tool exists; it does not know whose account the tool uses to create meetings.

Check separately whether authorization is still available:

```bash
curl -s "$BASE/tasks/t-book2/messages?kind=tool" | grep -o '"value":{"ok":[^{}]*}'
```
```
"value":{"ok":true,"note":"Already authorized; create the meeting directly","from":"fn"}
```

### Logs

Plugin output goes to stdout. English rendering of the captured output:

```
[book-plugin] Authorization: Already authorized; create the meeting directly
[book-plugin] Create meeting {"summary":"In process","minutesFromNow":15,"minutes":30}
[book-plugin] → https://meet.google.com/nii-tnnb-toz
```

Server output goes to stderr:

```
[book-server] Started
[book-server] Create meeting {"summary":"Out of process","minutesFromNow":15,"minutes":30}
[book-server] → https://meet.google.com/nui-kzuf-qni
```

---

## Two common pitfalls

Without `conferenceDataVersion=1`, Google silently drops the entire `conferenceData` object: the event is created without a meeting link, **with no error**.

Without `prompt=consent`, a second authorization returns only an access token, not a `refresh_token`; the saved credentials expire after one hour.

## Lifecycle

Both handles point to one file, so they run **in the same worker**. This lets `book` wait for the callback listener started by `login`. Realms are divided by file, not handle. Only when the last handle for that file is deleted is the worker collected together with its memory and listeners.
