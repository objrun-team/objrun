# 开一个真的谷歌会议

[← 例子](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · **meet-book** · [place](../place/)

两个工具：一个发起授权，一个开会。**两种写法各来一遍。**

授权本身也是工具 —— 没授权就调它，把链接给人，人点完接着干，中间不用谁去跑脚本。

字段说明在 [`../tool/`](../tool/)。

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

磁盘上要有一个 OAuth 客户端，Google Cloud 控制台里建的**桌面应用**类型：

```bash
mkdir -p ~/.tgengin && cp client_secret.json ~/.tgengin/
```

授权之后的凭证它自己写到 `~/.tgengin/google.json`。

底子（一个地方、两个周期、一个智能体）：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":20, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":20, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-chat"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## 写法一：进程内

[`book-plugin.ts`](./book-plugin.ts) 导出两个函数，两条句柄指的是同一个文件：

```ts
export async function login(): Promise<unknown> {
  const got = await authStart();
  console.log(`[book-plugin] 授权：${got.note}`);
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
      "does":"发起谷歌授权，回一个链接让用户点（进程内）",
      "params":{ "type":"object", "properties":{} },
      "output":{ "type":"object", "properties":{
        "ok":{"type":"boolean"}, "authUrl":{"type":"string"}, "note":{"type":"string"} } },
      "when":[[{ "dim":"task","key":"description","op":"contains","value":"开会" }]] },
    { "name":"meet_book_in", "identity":"fn:tool.meet_book_in",
      "does":"开一个谷歌会议，返回 Meet 链接（进程内）",
      "params":{ "type":"object", "properties":{
        "summary":{"type":"string"}, "minutesFromNow":{"type":"integer"}, "minutes":{"type":"integer"} } },
      "output":{ "type":"object", "properties":{
        "meetUrl":{"type":"string"}, "eventId":{"type":"string"} } },
      "when":[[{ "dim":"task","key":"description","op":"contains","value":"开会" }]] }]
}
JSON
```
```json
{"servers":{},"handles":["fn:tool.google_login_in","fn:tool.meet_book_in"],
 "places":[],"modes":[],"cycles":0,"agents":[],
 "tools":["google_login_in","meet_book_in"],"rules":[],"skills":[],"tables":[],"entries":{}}
```

`expectMs` 那两个数不一样：授权是马上回的，开会那个要等人点完链接，所以给到 240s。

## 写法二：进程外

[`book-server.ts`](./book-server.ts) 一个 MCP server，报两个工具。**工具体跟写法一
是同一份代码** —— 都 import [`google.ts`](./google.ts)。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "servers": [{
    "name": "book",
    "command": "bun",
    "args": ["examples/meet-book/book-server.ts"],
    "tools": {
      "google_login_out": { "expectMs":30000,
        "when":[[{ "dim":"task","key":"description","op":"contains","value":"开会" }]] },
      "meet_book_out": { "expectMs":240000,
        "when":[[{ "dim":"task","key":"description","op":"contains","value":"开会" }]] }
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

## 四个都在

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

## 还没授权

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-book", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 900,
  "description": "帮我开会。一、调 google_login_in 拿授权链接，把链接原样写出来。二、紧接着调 meet_book_in 开一个标题叫「进程内」的会 —— 这个工具会一直等到我点完授权为止，别停下来问我。三、调 meet_book_out 开一个标题叫「进程外」的会。两个会都是 15 分钟后开、开 30 分钟。最后把两个 Meet 链接都告诉我，然后结束" }
JSON
```

「别停下来问我」这句得写。不写的话模型问一句「点完告诉我」就交卷了，那一轮
`fn:infer.dfs` 判它到终点，任务就结束了 —— **等人得靠工具堵住那次调用**，不是靠模型等。

```bash
curl -s "$BASE/tasks/t-book/messages?kind=tool" | grep -o '"value":{"ok":[^{}]*}' | head -1
```
```
"value":{"ok":false,"authUrl":"https://accounts.google.com/o/oauth2/v2/auth?client_id=…&redirect_uri=http%3A%2F%2Flocalhost%3A56459&response_type=code&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.events&access_type=offline&prompt=consent","note":"把这个链接给用户，点完就成了","from":"fn"}
```

`redirect_uri` 的端口是每次现挑的空端口，回调监听就在插件那个 worker 里活着。
链接一发出去，`meet_book_in` 那次调用就堵在 `authWait` 上等。

链接点掉，页面回一句「授权好了，回去接着干」，堵着的那次调用同时醒过来接着建会。
**没人点的话它等满 180s 就放弃**：

```bash
curl -s "$BASE/tasks/t-book/messages?kind=tool" | grep -o '"value":{"error":[^{}]*}'
```
```
"value":{"error":"还没授权 —— 先调那个发起授权的工具，把链接给用户点一下"}
```
```
  "state":"done"（185s）
```

错当结果给模型，它看得见原因 —— 不是「工具没跑」那种查不出来的沉默。

## 授权在了

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-book3", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 600,
  "description": "帮我开会。用 meet_book_in 开一个标题叫「进程内」的会，再用 meet_book_out 开一个标题叫「进程外」的会，两个都是 15 分钟后开、开 30 分钟。把两个 Meet 链接都告诉我，然后结束" }
JSON
```
```bash
curl -s "$BASE/tasks/t-book3/messages?kind=call" | grep -o '"name":"[a-z_]*","input":[^}]*}'
```
```
"name":"meet_book_in","input":{"summary":"进程内","minutesFromNow":15,"minutes":30}
"name":"meet_book_out","input":{"summary":"进程外","minutesFromNow":15,"minutes":30}
```

```bash
curl -s "$BASE/tasks/t-book3/messages?kind=tool" | grep -o '"value":{"meetUrl":[^{}]*}'
```
```
"value":{"meetUrl":"https://meet.google.com/nii-tnnb-toz","eventId":"qjfqjqmvmhfal53fupna37b1rk","summary":"进程内","start":"2026-08-30T00:57:35+08:00","end":"2026-08-30T01:27:35+08:00","htmlLink":"https://www.google.com/calendar/event?eid=…","from":"fn"}
"value":{"meetUrl":"https://meet.google.com/nui-kzuf-qni","eventId":"g9r0r1v1ludi1a1i582bcu0148","summary":"进程外","start":"2026-08-30T00:57:36+08:00","end":"2026-08-30T01:27:36+08:00","htmlLink":"https://www.google.com/calendar/event?eid=…","from":"mcp"}
```
```
  "state":"done"（10s）
```

两个链接都是真的，日历里也真躺着两个事件。这一趟一次都没调授权 —— 凭证落在
`~/.tgengin/google.json`，**在机器上，不在哪个进程里**。进程内那个工具授的权，
进程外那个工具用得上；引擎只知道有这么一个工具，不知道它拿谁的账号在开会。

再单独问一次授权还在不在：

```bash
curl -s "$BASE/tasks/t-book2/messages?kind=tool" | grep -o '"value":{"ok":[^{}]*}'
```
```
"value":{"ok":true,"note":"已经授权过了，直接开会就行","from":"fn"}
```

### 日志

插件那边在 stdout：

```
[book-plugin] 授权：已经授权过了，直接开会就行
[book-plugin] 开会 {"summary":"进程内","minutesFromNow":15,"minutes":30}
[book-plugin] → https://meet.google.com/nii-tnnb-toz
```

server 那边在 stderr：

```
[book-server] 起来了
[book-server] 开会 {"summary":"进程外","minutesFromNow":15,"minutes":30}
[book-server] → https://meet.google.com/nui-kzuf-qni
```

---

## 两处容易踩的

`conferenceDataVersion=1` 少给一个，谷歌把 `conferenceData` 整段吞掉：事件建出来了，
但没有会议链接，**而且不报错**。

`prompt=consent` 不给的话，第二次授权只回 access token 不回 `refresh_token`，
存下来的凭证一小时后就废了。

## 生命周期

两条句柄落在同一个文件上，它们在**同一个 worker 里**——`login` 起的那个回调监听，
`book` 才等得到。realm 按文件分，不按句柄分；同一个文件上最后一条句柄被删掉，
worker 才连同它的内存和监听一起收。
