# 一个会给你新句柄的工具

[← 例子](../) ｜ [tool](../tool/) · **meet-join** · [meet-book](../meet-book/) · [place](../place/) · [rule](../rule/) · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

`meet_join` 进会。进去之后，会里才有的 `say` 和 `screen` 才出现在表里。

字段说明在 [`../tool/`](../tool/)。

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
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
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## 接进来的只有一个工具

[`meet-server.ts`](./meet-server.ts) 只有 `meet_join`。进会成功之后，它回过头调
`/declare` 把 [`meet-live.ts`](./meet-live.ts) 接进来 —— `say` 和 `screen`
就是那时候才有的。

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
    "args": ["examples/meet-join/meet-server.ts"],
    "tools": { "meet_join": { "when": [[{ "dim":"task","key":"description","op":"contains","value":"会议" }]] } }
  }] }
JSON
```
```json
{"servers":{"meet":["meet_join"]},"handles":[],"places":[],"modes":[],"cycles":0,
 "agents":[],"tools":[],"rules":[],"skills":[],"tables":[],"entries":{}}
```

进会之前：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select name from handle where name like 'mcp:%' order by name" }
JSON
```
```json
{"count":1,"rows":[{"name":"mcp:meet/meet_join"}]}
```

---

## 发任务

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
"name":"say","input":{"text":"大家好"}
"name":"screen","input":{"url":"file:///deck.html"}
```

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=tool" | grep -o '"value":{[^{}]*}'
```
```
"value":{"ok":true,"meetId":"abc-defg-hij","handles":["mcp:meet-live/say","mcp:meet-live/screen"]}
"value":{"ok":true,"meet":"abc-defg-hij","said":"大家好"}
```

`screen` 那条回的是嵌套对象（deck 的操作契约），上面这个 grep 不收。

```bash
curl -s "$BASE/tasks/t-meet/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"已完成会议任务：\n\n1. ✅ **进入会议**：通过 `meet_join` 加入了 https://meet.google.com/abc-defg-hij\n2. ✅ **在会里说「大家好」**：已通过会里的 `say` 工具发言\n3. ✅ **共享 file:///deck.html**：已通过 `screen` 共享，返回了操作契约，deck 共 12 页，当前在第 1 页，可用左右箭头翻页、输入页码跳转\n\n任务已全部完成。"
```

### 日志

两个 server 都是子进程，它们的 stderr 引擎原样转出来：

```
[meet] 起来了
[meet] 进会 abc-defg-hij
[meet-live abc-defg-hij] 起来了
[meet] 长出 mcp:meet-live/say、mcp:meet-live/screen
[meet-live abc-defg-hij] say「大家好」
[meet-live abc-defg-hij] screen file:///deck.html
```

`meet-live` 那行比 `[meet] 长出` 先出来 —— `/declare` 那一趟要连上新 server 问
`tools/list` 才算完，所以 server 是先起来的。
