# 任务机制

[← 例子](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · [place](../place/) · [rule](../rule/) · [skill](../skill/) · **mode** · [cmtbench](../benchmark/cmt/)

一种机制 = **一张图**（几个周期，靠 `from`/`next` 连起来）+ **一个推断函数**
（`infer`，决定这一站走完之后去哪儿）。图和推断函数都在外面，一行内核代码不用改。

```
  plan ──→ work ──→ wrap
             ↑         │
             └─────────┘      work 觉得没干完就自己转自己，够了才去 wrap
```

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

---

## 图先验，再写

**模式是一张图，而 insert 是一行一行的。** 写第三行的时候没人知道第一行的 `next`
指错了地方 —— 图的完整性只有全部写完才成立。所以整份收、整份验、一处不过整份不写。

`next` 指到一个不存在的周期：

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "handles":[{"name":"fn:infer.steps","expectMs":15000,"module":"$R/examples/mode/steps.ts#infer"}],
  "modes":[{"mode":"three","cycles":[
    {"cycle":"plan","apiMode":"chat","from":[],       "next":["work"],  "infer":"fn:infer.steps"},
    {"cycle":"work","apiMode":"chat","from":["plan"], "next":["shipit"],"infer":"fn:infer.steps"}]}] }
JSON
```
```json
{"error":"这份声明有 1 处不对，什么都没写",
 "problems":["mode three/work：next 指的 shipit 不在这个模式里"]}
```

每个周期的 `from` 都非空 —— 这张图没有入口：

```json
{"error":"这份声明有 4 处不对，什么都没写","problems":[
  "mode three：一个起点都没有（每个周期的 from 都非空），这个模式进不去",
  "mode three/plan：从起点走不到它 —— 这个周期永远不会被用上",
  "mode three/work：从起点走不到它 —— 这个周期永远不会被用上",
  "mode three/wrap：从起点走不到它 —— 这个周期永远不会被用上"]}
```

不验的话得到的是一台**看着像好的、实际走不通的机器**：任务发得出去，走到某一步停住，
状态永远是 `claimed`，零报错。

---

## 灌一张对的

[`steps.ts`](./steps.ts) 是推断函数。内核只认三种回答：

| 回什么 | 意思 |
| --- | --- |
| `null` | 到此为止 |
| `"周期名"` | 走那个周期，**从当前这一行接** |
| `{to, from_cycle, from_unit, status}` | 走那个周期，**从指定那一行接**，顺带给当前这一行盖个终止状态 |

第三种是给树用的：判死之后要在**同一个父**底下开兄弟，回退时要接到**祖先**上 ——
都不是「从当前行接」。内核只认这个形状，不认得「兄弟」「回退」是什么意思。

```ts
export async function infer(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  const here = a.cycle?.cycle;
  if (here === "plan") return "work";
  if (here === "work") return said(a.result, "收尾") ? "wrap" : "work";
  return null;                                   // wrap 是终点
}
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "places":[{"place":"local"}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:api.deepseek"}],
  "handles":[
    {"name":"fn:infer.steps","expectMs":15000,"module":"$R/examples/mode/steps.ts#infer"},
    {"name":"fn:infer.wild", "expectMs":15000,"module":"$R/examples/mode/steps.ts#wild"}],
  "modes":[
    {"mode":"three","cycles":[
      {"cycle":"plan","apiMode":"chat","maxUnits":1,"from":[],      "next":["work"],       "infer":"fn:infer.steps"},
      {"cycle":"work","apiMode":"chat","maxUnits":4,"from":["plan"],"next":["work","wrap"],"infer":"fn:infer.steps"},
      {"cycle":"wrap","apiMode":"chat","maxUnits":1,"from":["work"],"next":[],             "infer":"fn:infer.steps"}]},
    {"mode":"loose","cycles":[
      {"cycle":"one","apiMode":"chat","maxUnits":2,"from":[],     "next":["two"],"infer":"fn:infer.wild"},
      {"cycle":"two","apiMode":"chat","maxUnits":2,"from":["one"],"next":[],     "infer":"fn:infer.steps"}]}]
}
JSON
```
```json
{"handles":["fn:infer.steps","fn:infer.wild"],"modes":["three","loose"],"cycles":5,
 "places":["local"],"agents":["bot"],"servers":{},"tools":[],"rules":[],"skills":[],
 "tables":["task_loose","task_three","agent_bot_ctx","agent_bot_msg"],
 "entries":{"three":["plan"],"loose":["one"]}}
```

`tables` 是这一趟长出来的子表 —— **一个模式一张**。`entries` 是每个模式的入口周期，
不止一个的话发任务得指定 `cycle`。

```bash
curl -s $BASE/modes
```
```json
{"modes":[
  {"mode":"loose","cycles":2,"entries":["one"], "walkable":true,"agents":["bot"],"runningTasks":0},
  {"mode":"three","cycles":3,"entries":["plan"],"walkable":true,"agents":["bot"],"runningTasks":0}]}
```

---

## 走一趟

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1","mode":"three","agent":"bot","place":"local","source":"user","solveSeconds":300,
  "description":"先列个一句话的计划，然后干活。干活那一轮如果你觉得还没完就接着说，觉得可以了就在话里写上「收尾」两个字。" }
JSON
```
```json
{"id":"t-1","mode":"three","cycle":"plan","instance":"t-1#1","objective":false}
```

推断函数每一步说了什么（引擎 stdout）：

```
[steps] t-1 plan#1 → work（候选 work）
[steps] t-1 work#2 → work（候选 work、wrap）
[steps] t-1 work#3 → work（候选 work、wrap）
[steps] t-1 work#4 → wrap（候选 work、wrap）
```

```bash
curl -s $BASE/tasks/t-1/tree | grep -o '"chain":"[^"]*"'
```
```
"chain":"three/plan#1"
"chain":"three/plan#1 > three/work#2"
"chain":"three/plan#1 > three/work#2 > three/work#3"
"chain":"three/plan#1 > three/work#2 > three/work#3 > three/work#4"
"chain":"three/plan#1 > three/work#2 > three/work#3 > three/work#4 > three/wrap#5"
```

`work` 自己转了自己两次才去 `wrap`。**编号在一个任务里单调递增，不按周期重新数** ——
`maxUnits` 限的是「这个周期名下有几行」，跟编号无关。

---

## 内核不许它自由发挥

`fn:infer.wild` 推一个候选之外的周期出来：

```ts
export async function wild(arg: unknown): Promise<unknown> {
  return "nowhere";                              // 候选是 ["two"]
}
```

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2","mode":"loose","agent":"bot","place":"local","source":"user","solveSeconds":120,
  "description":"说句话" }
JSON
curl -s $BASE/tasks/t-2/why
```
```json
{"id":"t-2","state":"claimed","movable":false,"problems":[
  "整道题超过 solveSeconds=120s 了 —— 内核会判 failed",
  "one#1：内核推它的时候炸了 —— fn:infer.wild 推出来的 nowhere 不在候选里（候选是 two）"],
 "stuckAt":null}
```

**候选是数据里的 `next`，不是推断函数说了算。** 而且这句话是从接口上问出来的，
不用去翻服务器日志。

---

## 一条纯问答的机制里，工具没人跑

系统工具（`read` / `write` / `bash` 那一组）是**无条件挂上去的**，不看条件。
而这个机制每一站都是 `apiMode: chat`，没有哪一站走 `fn:unit.tools` —— 所以模型
请求的工具**没有人跑**：

```bash
curl -s "$BASE/tasks/t-1/messages?limit=200" | grep -o '"kind":"[a-z]*"' | sort | uniq -c
```
```
      5 "kind":"call"
      5 "kind":"inject"
      1 "kind":"user"
```

五站全是 `call`，一条 `tool` 都没有。模型说的话在 `call` 那一行的 `parsed.text` 里：

```bash
curl -s "$BASE/tasks/t-1/messages?kind=call" | grep -o '"parsed":{"text":"[^"]\{0,50\}'
```
```
"parsed":{"text":"我先列一句话计划，然后动手。\n\n**计划**：先探查当前工作区里有什么文件
"parsed":{"text":"好，先说计划。\n\n**一句话计划：** 先看项目结构和现有代码，理清需求
```

配不上 `tool` 的那一行**内核在拼上下文时会摘掉**（库里那一行不动）。不摘的话模型那边
一律要求「有 tool_call 就得有对应的 tool result」，缺了直接拒
（`Tool result is missing for tool call …`）—— 整条链路从此每一站都发不出去，
任务卡到超时，而错看着像模型那边的毛病。

要真跑工具，得给这个机制加一站 `apiMode` 留空的周期，走 `fn:unit.tools`。
见 [`../tool/`](../tool/) 里那个 `ask` / `act` 的两周期机制。

## 字段

`modes[].cycles[]`

| | |
| --- | --- |
| `cycle` | 周期名 |
| `apiMode` | 这一站要哪种调用形状（`chat` / `duplex` / …）。**留空 = 这一站不用模型，走 `agent.unit`** |
| `maxUnits` | 这个周期名下最多几行。默认 1 |
| `from` | 一般从哪几个周期转过来。**空 = 它是入口** |
| `next` | 一般下一个是哪几个。**空 = 到此为止**，而且这一站不会去调推断函数 |
| `infer` | 推断函数 → 一条句柄 |

推断函数收到 `{ agent, task, cycle, chain, place, next, result, sub, unit }` ——
`next` 是候选，`result` 是这一站模型回的那份。
