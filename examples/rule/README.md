# 规则

[← 例子](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · [place](../place/) · **rule** · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

挂在时刻上就是钩子。**不另开表** —— 一条规则 + 一条 `dim: "moment"` 的条件，就是钩子。

内核只喊「现在是哪一刻」，谁挂在这一刻上由触发条件说了算，所以内核里没有任何一个规则名。

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

内核会喊到的四刻：

| | |
| --- | --- |
| `unit_start` | 这一站开工 |
| `pre_send` | 出站那一行落了，还没发出去 |
| `post_send` | 回来那一行落了 |
| `task_done` | 整个任务刚推到 `done` |

---

## 两条拦在声明这一关的

一条条件都不给：

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "handles":[{"name":"fn:rule.audit","expectMs":10000,"module":"$R/examples/rule/hooks.ts#audit"}],
  "rules":[{"identity":"fn:rule.audit","does":"审一下","params":{},"writes":{},"scope":{}}] }
JSON
```
```json
{"error":"这份声明有 1 处不对，什么都没写",
 "problems":["rule fn:rule.audit：一条触发条件都没有 —— 它永远不会被跑到"]}
```

**一条都没有 = 永远不触发，不是「总是触发」。** 反过来定的话，忘了写条件的东西会到处乱开。

挂到一个内核根本不会喊的时刻上：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "handles":[{"name":"fn:rule.audit","expectMs":10000,"module":"$R/examples/rule/hooks.ts#audit"}],
  "rules":[{"identity":"fn:rule.audit","does":"审一下","params":{},"writes":{},"scope":{},
    "when":[[{"dim":"moment","op":"eq","value":"before_everything"}]]}] }
JSON
```
```json
{"error":"这份声明有 1 处不对，什么都没写",
 "problems":["rule fn:rule.audit 第 0 组：不认得的时刻 before_everything（内核会喊到的是 unit_start / pre_send / post_send / task_done）"]}
```

---

## 灌两条

[`hooks.ts`](./hooks.ts) 一个文件两个导出，两条句柄指同一个文件 —— 同一个 worker、
同一份模块状态，所以 `audit` 数的那个计数 `archive` 看得见。

```ts
let audited = 0;                       // 活在这个 worker 的内存里，不落库

export async function audit(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  audited++;
  console.log(`[hooks] ${a.moment}｜${a.task?.id} 第 ${a.unit} 站｜轨=${a.cycle?.api_mode}｜链路=${a.chain}`);
  return { audited };
}

export async function archive(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  await appendFile(LOG, JSON.stringify({ task: a.task?.id, source: a.task?.source, audited, … }) + "\n");
}
```

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "places":[{"place":"local"}],
  "modes":[{"mode":"chat1","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":4,"from":[],"next":[],"infer":"fn:infer.dfs"}]}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:api.deepseek"}],
  "handles":[
    {"name":"fn:rule.audit",  "expectMs":10000,"module":"$R/examples/rule/hooks.ts#audit"},
    {"name":"fn:rule.archive","expectMs":10000,"module":"$R/examples/rule/hooks.ts#archive"}],
  "rules":[
    {"identity":"fn:rule.audit","does":"出站前记一笔","params":{},"writes":{},
     "scope":{"table":"agent_*_msg","readonly":true},
     "when":[[{"dim":"moment","op":"eq","value":"pre_send"}]]},
    {"identity":"fn:rule.archive","does":"任务收尾时归档","params":{},"writes":{},
     "scope":{"table":"task","readonly":true},
     "when":[[{"dim":"moment","op":"eq","value":"task_done"},
              {"dim":"task","key":"source","op":"eq","value":"user"}]]}]
}
JSON
```
```json
{"handles":["fn:rule.audit","fn:rule.archive"],"rules":["fn:rule.audit","fn:rule.archive"],
 "places":["local"],"modes":["chat1"],"cycles":1,"agents":["bot"],
 "servers":{},"tools":[],"skills":[],
 "tables":["task_chat1","agent_bot_ctx","agent_bot_msg"],"entries":{"chat1":["ask"]}}
```

`archive` 那条 `when` 里两项在**同一组**，所以是 and：`task_done` 这一刻，**并且**
这个任务是真人发的。

```bash
curl -s $BASE/rules
```
```json
{"rules":[
  {"identity":"fn:rule.archive","does":"任务收尾时归档","usable":true,
   "when":[[{"dim":"moment","key":"","op":"eq","value":"task_done"},
            {"dim":"task","key":"source","op":"eq","value":"user"}]],"neverFires":false},
  {"identity":"fn:rule.audit","does":"出站前记一笔","usable":true,
   "when":[[{"dim":"moment","key":"","op":"eq","value":"pre_send"}]],"neverFires":false}]}
```

钩子就在这张清单里，不另开表。`neverFires` 是**算出来的** —— 一条条件都没有的规则
在这儿一眼看得见。

---

## 到点真被喊到了吗

「挂上了」和「到点被喊到」是两件事。更要紧的是**它不该在别的时刻被喊** ——
一条本该只在收尾时跑的规则，要是每一刻都跑，那不报错，只是行为完全不是你想的那样。

发两个任务，一个真人发的、一个智能体派生的：

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1","mode":"chat1","agent":"bot","place":"local","source":"user",
  "description":"用一句话说说你是谁" }
JSON
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2","mode":"chat1","agent":"bot","place":"local","source":"agent",
  "description":"用一句话说说今天几号" }
JSON
```

引擎 stdout：

```
[hooks] pre_send｜t-1 第 1 站｜轨=chat｜链路=chat1/ask#1
[hooks] task_done｜归档 t-1 → E:\sgu-bzhc\EACN_EX\TgEngin\examples\rule\done.log
[hooks] pre_send｜t-2 第 1 站｜轨=chat｜链路=chat1/ask#1
```

`audit` 两个任务各喊一次，**只在 `pre_send`** —— 没在 `unit_start`、`post_send`
上乱跑。`archive` 只喊了一次。

```bash
cat examples/rule/done.log
```
```json
{"at":"2026-08-29T20:20:11.297Z","task":"t-1","source":"user","audited":1,"result":""}
```

**两个任务都跑完了，归档只有 t-1。** `t-2` 是 `source=agent`，那条 and 的第二项没中。
条件真的在起作用 —— 不是「跑了但没写」，是压根没被喊到。

---

## 规则收到什么

```
{ agent, task, cycle, chain, place, moment, sub, unit, instance }
```

`moment` 是「现在是哪一刻」，`task.id` 是「在给谁干活」。跟触发条件比的是同一份东西
（`facts`），所以规则里看得到的，`when` 里就问得出来。

## 它不拦

**一条规则炸了只炸它自己**，内核记一行 `level:50` 的日志，这一站照跑：

```
{"level":50,…,"msg":"规则 fn:rule.xxx 在 unit_start 这一刻炸了：…"}
```

钩子挂在主路上，让它把整步带停的话，一条写坏的规则能让所有任务都不动。

## 字段

`rules[]`

| | |
| --- | --- |
| `identity` | 指一条句柄（`fn:` 进程内 / `http://` 进程外） |
| `does` | 干什么 |
| `writes` | 声明它会动哪几张表怎么动 |
| `scope` | 能动哪些行。结构化匹配式，不用 SQL 片段 |
| `access` | 外部规则够着库的办法。**密钥只存环境变量名** |
| `when` | 什么时候喊它。**不给 = 永远不喊** |
| `usable` | 可不给，默认可用 |

`moment` 这一维不看属性，`key` 留空。
