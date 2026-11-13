# Examples

- [Basic usage and API](#quick-start): examples of tools, objectives, mechanisms, and tasks below.
- [Benchmark examples and experiments](benchmark/README.md).
- [Scientific research experiments](research/README.md).

## Quick start

Every example assumes this step has already been completed.

```bash
cd app && bun start
BASE=http://127.0.0.1:7801/api
```

```bash
curl -s $BASE/health
```
```json
{"ok":true,"db":"…/h2h.sqlite","tables":12,"write":true,"query":true,"uptimeMs":31}
```

## Declare the shared configuration

Declare one execution place, a minimal mechanism, and an agent. **Do this once**; the examples below share these declarations.

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes":  [{ "mode": "chat1", "cycles": [
              { "cycle":"ask", "apiMode":"chat", "from":[], "next":[], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name": "bot",
               "apis": [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]],
               "unit": "fn:api.deepseek" }]
}
JSON
```
```json
{"places":["local"],"modes":["chat1"],"cycles":1,"agents":["bot"],
 "handles":[],"tools":[],"rules":[],"skills":[],
 "tables":["task_chat1","agent_bot_ctx","agent_bot_msg"],"entries":{"chat1":["ask"]}}
```

`tables` lists the subtables created by this declaration. Tasks can be submitted immediately, without restarting.

## Submit a task

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1", "mode":"chat1", "agent":"bot", "place":"local",
  "source":"user", "description":"Describe who you are in one sentence." }
JSON
```
```json
{"id":"t-1","mode":"chat1","cycle":"ask","instance":"t-1#1","objective":false}
```

```bash
curl -s $BASE/tasks/t-1
```
```json
{"id":"t-1","state":"done",
 "objective":{"has":false,"agentReadable":false,"verdict":null},
 "solve":{"limitSeconds":1800,"elapsedMs":4210,"leftMs":1795790,"overdue":false},
 "units":[{"cycle":"ask","unit":1,"phase":"done","handle":"fn:api.deepseek",
           "expectMs":900000,"deadlineInMs":null,"chain":"chat1/ask#1"}]}
```

| phase | |
| --- | --- |
| `pending` | The outgoing row has not been persisted; this iteration should process it |
| `running` | The outgoing row is persisted, but its response is not |
| `done` | Both the outgoing row and response are persisted |

```bash
curl -s $BASE/tasks/t-1/messages
```
```json
{"total":3,"rows":[
 {"unit":1,"seq":1,"role":"user","kind":"user","human":true,
  "body":"[human] Describe who you are in one sentence.","text":"Describe who you are in one sentence."},
 {"unit":1,"seq":2,"role":"system","kind":"inject",
  "parsed":{"sent":true,"tools":["read","write","edit","glob","grep","bash"],"rules":[]}},
 {"unit":1,"seq":3,"role":"assistant","kind":"prompt","body":"I am…"}]}
```

If a task is not progressing:

```bash
curl -s $BASE/tasks/t-1/why
```
```json
{"id":"t-1","state":"done","movable":true,"problems":[],"stuckAt":null}
```

## API index

```bash
curl -s $BASE/help                # All 31 endpoints, readable in the terminal
curl -s "$BASE/help?q=tasks"      # Show only matching endpoints
curl -s "$BASE/help?format=json"  # Machine-readable output
```

## Examples

| | |
| --- | --- |
| [`tool/`](./tool/) | One tool implemented in two ways |
| [`meet-join/`](./meet-join/) | A tool that creates a new handle |
| [`meet-book/`](./meet-book/) | Create a real Google Meet meeting |
| [`benchmark/cmt/`](./benchmark/cmt/) | Run CMT-Benchmark: submit a batch through `/bench`, grade with G, and retry a different path after verdict 0. Baseline: **44 / 50** |
| [`benchmark/deepswe/`](./benchmark/deepswe/) | Run DeepSWE: one container per task, a dedicated place handle, and the official grader |
| [`rule/`](./rule/) | Rules (hooks when attached to lifecycle moments) |
| [`skill/`](./skill/) | skill |
| [`mode/`](./mode/) | Task mechanisms |
| [`place/`](./place/) | Execution places |

> Request bodies use `-d @- <<'JSON'`. Although `-d '{…}'` also works, Windows Git Bash
> can transcode Chinese command-line text and produce a body-length mismatch.
