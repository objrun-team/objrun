# skill

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · [place](../place/) · [rule](../rule/) · **skill** · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

The key difference from tools is that **the model does not select a skill**. Tools are offered for the model to decide whether to call; a skill is **injected into context** as soon as its conditions match. The model sees only the already-injected result.

Two forms:

| | |
| --- | --- |
| Fixed `body` | A fixed passage. **No handle needed** |
| Empty `body` | Generated dynamically: call the handle when triggered to obtain a passage |

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

---

## Two declaration-time rejections

Requesting dynamic generation without anything that can generate it:

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "skills":[{"identity":"fn:skill.recap","does":"Recap the task","params":{},"role":"user",
    "when":[[{"dim":"task","key":"source","op":"eq","value":"user"}]]}] }
JSON
```
```json
{"error":"This declaration has 1 problem; nothing was written",
 "problems":["skill fn:skill.recap: body is empty (dynamic generation), but handle fn:skill.recap is missing; in-process fn: handles are registered by code, and external http:// handles belong in the same declaration's handles; nothing can generate the content"]}
```

Providing no conditions:

```json
{"problems":["skill fn:skill.recap: no trigger conditions; it will never be injected"]}
```

As with rules, **no conditions = never inject, not always inject**.

---

## Load two skills

[`recap.ts`](./recap.ts) implements the dynamic skill. It receives this round's **facts**, the same data used to evaluate triggers, so it can tailor its text to this task and station.

```ts
export async function run(arg: unknown): Promise<unknown> {
  const { facts } = (arg ?? {}) as { facts?: { task?: {…}; place?: string } };
  const t = facts?.task;
  return `[Generated now] Task ${t?.id}, from ${t?.source}, at ${facts?.place}: ${t?.description}`;
}
```

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "places":[{"place":"local"}],
  "modes":[{"mode":"chat1","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":4,"from":[],"next":[],"infer":"fn:infer.dfs"}]}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:api.deepseek"}],
  "handles":[{"name":"fn:skill.recap","expectMs":10000,
              "module":"$R/examples/skill/recap.ts#run"}],
  "skills":[
    {"identity":"house","does":"House rules","params":{},"role":"user",
     "body":"[Fixed text] Explain the basis for your answer when finished.",
     "when":[[{"dim":"task","key":"source","op":"eq","value":"user"}]]},
    {"identity":"fn:skill.recap","does":"Recap the task","params":{},"role":"user",
     "when":[[{"dim":"task","key":"description","op":"contains","value":"recap"}]]}]
}
JSON
```
```json
{"handles":["fn:skill.recap"],"skills":["house","fn:skill.recap"],
 "places":["local"],"modes":["chat1"],"cycles":1,"agents":["bot"],
 "servers":{},"tools":[],"rules":[],
 "tables":["task_chat1","agent_bot_ctx","agent_bot_msg"],"entries":{"chat1":["ask"]}}
```

The fixed skill's `identity` is only a name, not a handle reference; nothing needs to call it.

```bash
curl -s $BASE/skills
```
```json
{"skills":[
  {"identity":"fn:skill.recap","does":"Recap the task","role":"user","dynamic":true,"usable":true,
   "when":[[{"dim":"task","key":"description","op":"contains","value":"recap"}]],"neverFires":false},
  {"identity":"house","does":"House rules","role":"user","dynamic":false,"usable":true,
   "when":[[{"dim":"task","key":"source","op":"eq","value":"user"}]],"neverFires":false}]}
```

`dynamic` is **computed** from whether `body` is empty, rather than supplied explicitly.

---

## Was the skill actually injected?

Successful registration alone proves nothing; inspect the context row.

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1","mode":"chat1","agent":"bot","place":"local","source":"user",
  "description":"First recap what I asked, then say who you are" }
JSON
curl -s "$BASE/tasks/t-1/messages?kind=skill"
```
```json
{"total":2,"limit":200,"offset":0,"rows":[
 {"instance":"t-1#1","unit":1,"seq":2,"role":"user","kind":"skill","human":false,
  "body":"[Generated now] Task t-1, from user, at local: first recap what I asked, then say who you are"},
 {"instance":"t-1#1","unit":1,"seq":3,"role":"user","kind":"skill","human":false,
  "body":"[Fixed text] Explain the basis for your answer when finished."}]}
```

The dynamic skill is assembled at invocation: it includes this task's ID, source, place, and original wording. The same sentence appears in captured engine stdout:

```
[recap] [Generated now] Task t-1, from user, at local: first recap what I asked, then say who you are
```

Try another task whose description does not contain “recap”:

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2","mode":"chat1","agent":"bot","place":"local","source":"user",
  "description":"Say who you are in one sentence" }
JSON
curl -s "$BASE/tasks/t-2/messages?kind=skill"
```
```json
{"total":1,"limit":200,"offset":0,"rows":[
 {"instance":"t-2#1","unit":1,"seq":2,"role":"user","kind":"skill","human":false,
  "body":"[Fixed text] Explain the basis for your answer when finished."}]}
```

**The fixed skill remains; the dynamic skill is absent.** Conditions control whether injection occurs, rather than merely changing injected content.

`kind` is `skill`, not `user`, so injected content and human text remain distinguishable in the database. Both become `role: user` when sent to the model; the message list alone cannot distinguish them, which is why the database records the difference.

## Fields

`skills[]`

| | |
| --- | --- |
| `identity` | Must reference a handle when `body` is empty; otherwise just a name |
| `does` | What it does |
| `body` | Fixed passage. **Empty = dynamic generation** |
| `role` | Role assigned to the injected content |
| `when` | When to inject. **Omitted = never inject** |
| `usable` | Optional; enabled by default |

The dynamic handle receives `{ facts }`, the same data used to evaluate trigger conditions.
