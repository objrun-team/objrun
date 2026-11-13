# Task modes

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · [place](../place/) · [rule](../rule/) · [skill](../skill/) · **mode** · [cmtbench](../benchmark/cmt/)

A mode = **a graph** (cycles connected by `from`/`next`) + **an inference function** (`infer`, deciding where to go after this station completes). Both the graph and inference function are external; no kernel code changes are needed.

```
  plan ──→ work ──→ wrap
             ↑         │
             └─────────┘      work loops until ready, then enters wrap
```

```bash
cp config.yaml dist/
TGENGIN_PLUGIN_HOST=app/src/engine/plugin-host.ts dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

---

## Validate the graph before writing it

**A mode is a graph, but inserts happen one row at a time.** Writing the third row cannot reveal that the first row's `next` points to the wrong place; graph integrity exists only once all rows are present. Accept and validate the whole declaration; if any part fails, write none of it.

A `next` reference to a nonexistent cycle:

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
{"error":"This declaration has 1 problem; nothing was written",
 "problems":["mode three/work: next references shipit, which is not in this mode"]}
```

Every cycle has a nonempty `from`, so the graph has no entry point:

```json
{"error":"This declaration has 4 problems; nothing was written","problems":[
  "mode three: no entry point (every cycle has a nonempty from); this mode cannot be entered",
  "mode three/plan: unreachable from any entry point; this cycle will never be used",
  "mode three/work: unreachable from any entry point; this cycle will never be used",
  "mode three/wrap: unreachable from any entry point; this cycle will never be used"]}
```

Without validation, the result **looks functional but has no traversable path**: tasks can be submitted, then stall at a step, remaining `claimed` forever without an error.

---

## Load a valid graph

[`steps.ts`](./steps.ts) supplies the inference function. The kernel recognizes only three return shapes:

| Return value | Meaning |
| --- | --- |
| `null` | Stop here |
| `"cycle-name"` | Enter that cycle, **continuing from the current row** |
| `{to, from_cycle, from_unit, status}` | Enter that cycle, **continuing from the specified row**, and mark the current row with a terminal status |

The third shape supports trees: after marking a node dead, create a sibling under **the same parent**; when backtracking, reconnect to an **ancestor**. Neither continues from the current row. The kernel understands this shape, not the meanings of “sibling” or “backtracking.”

```ts
export async function infer(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  const here = a.cycle?.cycle;
  if (here === "plan") return "work";
  if (here === "work") return said(a.result, "wrap up") ? "wrap" : "work";
  return null;                                   // wrap is terminal
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

`tables` lists child tables created by this declaration, **one per mode**. `entries` lists each mode's entry cycles; if there is more than one, task submission must specify `cycle`.

```bash
curl -s $BASE/modes
```
```json
{"modes":[
  {"mode":"loose","cycles":2,"entries":["one"], "walkable":true,"agents":["bot"],"runningTasks":0},
  {"mode":"three","cycles":3,"entries":["plan"],"walkable":true,"agents":["bot"],"runningTasks":0}]}
```

---

## Run through the graph

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1","mode":"three","agent":"bot","place":"local","source":"user","solveSeconds":300,
  "description":"First give a one-sentence plan, then do the work. During a work round, continue speaking if more remains; when ready, include the literal phrase 'wrap up' in your text." }
JSON
```
```json
{"id":"t-1","mode":"three","cycle":"plan","instance":"t-1#1","objective":false}
```

What inference returned at each step (English rendering of captured engine stdout; labels identify candidate cycles):

```
[steps] t-1 plan#1 → work (candidate work)
[steps] t-1 work#2 → work (candidates work, wrap)
[steps] t-1 work#3 → work (candidates work, wrap)
[steps] t-1 work#4 → wrap (candidates work, wrap)
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

`work` looped back to itself twice before entering `wrap`. **Numbers increase monotonically within a task; they do not restart per cycle.** `maxUnits` limits the number of rows under this cycle name, independently of their numbers.

---

## The kernel constrains inference

`fn:infer.wild` returns a cycle outside the candidate set:

```ts
export async function wild(arg: unknown): Promise<unknown> {
  return "nowhere";                              // Candidates are ["two"]
}
```

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-2","mode":"loose","agent":"bot","place":"local","source":"user","solveSeconds":120,
  "description":"Say something" }
JSON
curl -s $BASE/tasks/t-2/why
```
```json
{"id":"t-2","state":"claimed","movable":false,"problems":[
  "The whole task exceeded solveSeconds=120s; the kernel will mark it failed",
  "one#1: kernel advancement failed; fn:infer.wild returned nowhere, outside the candidate set (candidate: two)"],
 "stuckAt":null}
```

**Candidates come from `next` in the data; the inference function cannot redefine them.** This explanation is available through the API, without searching server logs.

---

## A chat-only mode has no tool executor

System tools (`read` / `write` / `bash` and the rest) are **attached unconditionally**, without checking triggers. Every station in this mode uses `apiMode: chat`; none runs `fn:unit.tools`, so **nothing executes** the tools requested by the model:

```bash
curl -s "$BASE/tasks/t-1/messages?limit=200" | grep -o '"kind":"[a-z]*"' | sort | uniq -c
```
```
      5 "kind":"call"
      5 "kind":"inject"
      1 "kind":"user"
```

All five stations contain `call` records, with no `tool` records. The model's text is in the `call` row's `parsed.text`:

```bash
curl -s "$BASE/tasks/t-1/messages?kind=call" | grep -o '"parsed":{"text":"[^"]\{0,50\}'
```
```
"parsed":{"text":"I will give a one-sentence plan, then start.\n\n**Plan**: first inspect files in the current workspace
"parsed":{"text":"First, the plan.\n\n**One-sentence plan:** inspect the project structure and existing code to clarify the requirements
```

**When assembling context, the kernel removes a call without a matching `tool` result** (leaving the database row intact). Otherwise model providers require a tool result for every tool_call and reject the request with `Tool result is missing for tool call …`. No subsequent station in the chain can send a request, and the task stalls until timeout while the error appears to be a model-side fault.

To actually execute tools, add a cycle with `apiMode` left empty that runs `fn:unit.tools`. See the two-cycle `ask` / `act` mode in [`../tool/`](../tool/).

## Fields

`modes[].cycles[]`

| | |
| --- | --- |
| `cycle` | Cycle name |
| `apiMode` | Call shape for this station (`chat` / `duplex` / …). **Empty = no model call; run `agent.unit`** |
| `maxUnits` | Maximum rows under this cycle name; default 1 |
| `from` | Cycles that normally precede this one. **Empty = entry point** |
| `next` | Normal candidate successors. **Empty = stop here**; the station does not call inference |
| `infer` | Inference function → a handle |

The inference function receives `{ agent, task, cycle, chain, place, next, result, sub, unit }`: `next` contains candidates, and `result` is this station's model response.
