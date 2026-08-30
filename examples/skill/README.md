# skill

跟工具最大的分别：**模型不挑它**。工具是摆出来让模型自己决定调不调；skill 是条件一命中
就**塞进上下文**，模型只会看到已经塞好的结果。

两种写法：

| | |
| --- | --- |
| `body` 写死 | 固定的一段话。**不用句柄** |
| `body` 留空 | 动态生成 —— 触发那一刻去调那条句柄，它现给一段 |

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

---

## 两条拦在声明这一关的

说好要动态生成，却没人能生成：

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "skills":[{"identity":"fn:skill.recap","does":"复述一下题目","params":{},"role":"user",
    "when":[[{"dim":"task","key":"source","op":"eq","value":"user"}]]}] }
JSON
```
```json
{"error":"这份声明有 1 处不对，什么都没写",
 "problems":["skill fn:skill.recap：body 留空（动态生成），但没有 fn:skill.recap 这个句柄 —— 进程内的 fn: 由代码注册；外面的 http:// 在同一份声明的 handles 里一起给 —— 没人能把内容现给出来"]}
```

一条条件都不给：

```json
{"problems":["skill fn:skill.recap：一条触发条件都没有 —— 它永远不会被塞进去"]}
```

跟规则一样：**一条都没有 = 永远不塞，不是「总是塞」。**

---

## 灌两个

[`recap.ts`](./recap.ts) 是动态那个。它拿到的是这一轮的**事实** —— 跟触发条件比的是
同一份，所以能按这个任务、这一站的具体情况说话。

```ts
export async function run(arg: unknown): Promise<unknown> {
  const { facts } = (arg ?? {}) as { facts?: { task?: {…}; place?: string } };
  const t = facts?.task;
  return `【现生成的】这道题是 ${t?.id}（${t?.source} 发的，在 ${facts?.place}）：${t?.description}`;
}
```

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "places":[{"place":"local"}],
  "modes":[{"mode":"chat1","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":4,"from":[],"next":[],"infer":"fn:infer.dfs"}]}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-chat"]],"unit":"fn:api.deepseek"}],
  "handles":[{"name":"fn:skill.recap","expectMs":10000,
              "module":"$R/examples/skill/recap.ts#run"}],
  "skills":[
    {"identity":"house","does":"家规","params":{},"role":"user",
     "body":"【写死的】答完记得说清依据。",
     "when":[[{"dim":"task","key":"source","op":"eq","value":"user"}]]},
    {"identity":"fn:skill.recap","does":"复述一下题目","params":{},"role":"user",
     "when":[[{"dim":"task","key":"description","op":"contains","value":"复述"}]]}]
}
JSON
```
```json
{"handles":["fn:skill.recap"],"skills":["house","fn:skill.recap"],
 "places":["local"],"modes":["chat1"],"cycles":1,"agents":["bot"],
 "servers":{},"tools":[],"rules":[],
 "tables":["task_chat1","agent_bot_ctx","agent_bot_msg"],"entries":{"chat1":["ask"]}}
```

写死那条的 `identity` 就是个名字，不指句柄 —— 没人要调它。

```bash
curl -s $BASE/skills
```
```json
{"skills":[
  {"identity":"fn:skill.recap","does":"复述一下题目","role":"user","dynamic":true,"usable":true,
   "when":[[{"dim":"task","key":"description","op":"contains","value":"复述"}]],"neverFires":false},
  {"identity":"house","does":"家规","role":"user","dynamic":false,"usable":true,
   "when":[[{"dim":"task","key":"source","op":"eq","value":"user"}]],"neverFires":false}]}
```

`dynamic` 是**算出来的**（`body` 空不空），不是填的。

---

## 真塞进去了吗

「注册成功」什么也证明不了 —— 看的是上下文里那一行。

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1","mode":"chat1","agent":"bot","place":"local","source":"user",
  "description":"先复述一下我问了什么，再说说你是谁" }
JSON
curl -s "$BASE/tasks/t-1/messages?kind=skill"
```
```json
{"total":2,"limit":200,"offset":0,"rows":[
 {"instance":"t-1#1","unit":1,"seq":2,"role":"user","kind":"skill","human":false,
  "body":"【现生成的】这道题是 t-1（user 发的，在 local）：先复述一下我问了什么，再说说你是谁"},
 {"instance":"t-1#1","unit":1,"seq":3,"role":"user","kind":"skill","human":false,
  "body":"【写死的】答完记得说清依据。"}]}
```

动态那条真是现拼的 —— 里面有这个任务的 id、来源、地方和原话。引擎 stdout 上同一句：

```
[recap] 【现生成的】这道题是 t-1（user 发的，在 local）：先复述一下我问了什么，再说说你是谁
```

换一个描述里没有「复述」的任务：

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2","mode":"chat1","agent":"bot","place":"local","source":"user",
  "description":"用一句话说说你是谁" }
JSON
curl -s "$BASE/tasks/t-2/messages?kind=skill"
```
```json
{"total":1,"limit":200,"offset":0,"rows":[
 {"instance":"t-2#1","unit":1,"seq":2,"role":"user","kind":"skill","human":false,
  "body":"【写死的】答完记得说清依据。"}]}
```

**写死那条还在，动态那条没进来。** 条件真的在起作用 —— 不是塞了但内容不同，
是压根没塞。

`kind` 是 `skill`，不是 `user` —— 塞进去的和人写的在库里分得开。压给模型的时候
两者都是 `role: user`，光看消息列表分不出来，所以得在库里标着。

## 字段

`skills[]`

| | |
| --- | --- |
| `identity` | `body` 留空时必须是一条句柄；写死的话就是个名字 |
| `does` | 干什么 |
| `body` | 写死的那一段。**留空 = 动态生成** |
| `role` | 塞进去算哪个 role |
| `when` | 什么时候塞。**不给 = 永远不塞** |
| `usable` | 可不给，默认可用 |

动态那条句柄收到的是 `{ facts }` —— 跟触发条件比的是同一份东西。
