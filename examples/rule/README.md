# Rules

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · [place](../place/) · **rule** · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

Attach a rule to a moment to make a hook. **No separate table** is needed: a rule plus a `dim: "moment"` condition is a hook.

The kernel announces only the current moment; trigger conditions decide which rules attach to it. No rule names are embedded in the kernel.

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

The four moments announced by the kernel:

| | |
| --- | --- |
| `unit_start` | This station starts work |
| `pre_send` | The outbound row is persisted but not yet sent |
| `post_send` | The response row is persisted |
| `task_done` | The whole task has just transitioned to `done` |

---

## Two declaration-time rejections

Providing no conditions:

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "handles":[{"name":"fn:rule.audit","expectMs":10000,"module":"$R/examples/rule/hooks.ts#audit"}],
  "rules":[{"identity":"fn:rule.audit","does":"Run an audit","params":{},"writes":{},"scope":{}}] }
JSON
```
```json
{"error":"This declaration has 1 problem; nothing was written",
 "problems":["rule fn:rule.audit: no trigger conditions; it will never run"]}
```

**No conditions = never trigger, not always trigger.** The opposite default would activate anything whose conditions were accidentally omitted everywhere.

Attaching to a moment the kernel never announces:

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "handles":[{"name":"fn:rule.audit","expectMs":10000,"module":"$R/examples/rule/hooks.ts#audit"}],
  "rules":[{"identity":"fn:rule.audit","does":"Run an audit","params":{},"writes":{},"scope":{},
    "when":[[{"dim":"moment","op":"eq","value":"before_everything"}]]}] }
JSON
```
```json
{"error":"This declaration has 1 problem; nothing was written",
 "problems":["rule fn:rule.audit group 0: unknown moment before_everything (kernel moments are unit_start / pre_send / post_send / task_done)"]}
```

---

## Load two rules

[`hooks.ts`](./hooks.ts) exports two functions from one file. Both handles point to that file: one worker, one module state. Consequently, `archive` can see the counter incremented by `audit`.

```ts
let audited = 0;                       // Lives in this worker's memory, not the database

export async function audit(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  audited++;
  console.log(`[hooks] ${a.moment}｜${a.task?.id} station ${a.unit} | mode=${a.cycle?.api_mode} | chain=${a.chain}`);
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
    {"identity":"fn:rule.audit","does":"Record an audit before sending","params":{},"writes":{},
     "scope":{"table":"agent_*_msg","readonly":true},
     "when":[[{"dim":"moment","op":"eq","value":"pre_send"}]]},
    {"identity":"fn:rule.archive","does":"Archive when the task finishes","params":{},"writes":{},
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

The two `when` conditions for `archive` are in **the same group**, so they are ANDed: the moment is `task_done`, **and** the task came from a human.

```bash
curl -s $BASE/rules
```
```json
{"rules":[
  {"identity":"fn:rule.archive","does":"Archive when the task finishes","usable":true,
   "when":[[{"dim":"moment","key":"","op":"eq","value":"task_done"},
            {"dim":"task","key":"source","op":"eq","value":"user"}]],"neverFires":false},
  {"identity":"fn:rule.audit","does":"Record an audit before sending","usable":true,
   "when":[[{"dim":"moment","key":"","op":"eq","value":"pre_send"}]],"neverFires":false}]}
```

Hooks appear in this same list, without a separate table. `neverFires` is **computed**, making a rule with no conditions immediately visible.

---

## Did the rule fire at the right moment?

Being attached and being called at the right moment are different. It is equally important that **the rule is not called at other moments**. A cleanup-only rule running at every moment may raise no error while behaving completely differently from the intended design.

Submit two tasks, one from a human and one derived by an agent:

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1","mode":"chat1","agent":"bot","place":"local","source":"user",
  "description":"Say who you are in one sentence" }
JSON
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2","mode":"chat1","agent":"bot","place":"local","source":"agent",
  "description":"Say today's date in one sentence" }
JSON
```

English rendering of the captured engine stdout:

```
[hooks] pre_send｜t-1 station 1 | mode=chat | chain=chat1/ask#1
[hooks] task_done｜Archived t-1 → E:\sgu-bzhc\EACN_EX\TgEngin\examples\rule\done.log
[hooks] pre_send｜t-2 station 1 | mode=chat | chain=chat1/ask#1
```

`audit` fires once for each task, **only at `pre_send`**, not at `unit_start` or `post_send`. `archive` fires only once.

```bash
cat examples/rule/done.log
```
```json
{"at":"2026-08-29T20:20:11.297Z","task":"t-1","source":"user","audited":1,"result":""}
```

**Both tasks completed, but only t-1 was archived.** `t-2` has `source=agent`, so the second AND condition did not match. The conditions genuinely control invocation: the rule was never called, rather than called without writing.

---

## What a rule receives

```
{ agent, task, cycle, chain, place, moment, sub, unit, instance }
```

`moment` identifies the current moment, and `task.id` identifies the task being served. These are the same `facts` used to evaluate trigger conditions, so anything visible inside the rule can also be queried by `when`.

## Rules do not block execution

**A rule failure affects only that rule.** The kernel writes a `level:50` log entry and the station continues:

```
{"level":50,…,"msg":"Rule fn:rule.xxx failed at unit_start: …"}
```

Hooks run on the main path; if one could stop the whole step, a single broken rule could stall all tasks.

## Fields

`rules[]`

| | |
| --- | --- |
| `identity` | References a handle (`fn:` in process / `http://` out of process) |
| `does` | What it does |
| `writes` | Declares which tables it changes and how |
| `scope` | Rows it may change; structured match expressions, not SQL fragments |
| `access` | How an external rule accesses the database. **Store only environment-variable names for secrets** |
| `when` | When to invoke it. **Omitted = never invoke** |
| `usable` | Optional; enabled by default |

The `moment` dimension does not inspect attributes; leave `key` empty.
