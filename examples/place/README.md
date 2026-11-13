# Places to work

Instructions and illustrative declarations are in English. Captured responses and logs below are English renderings of earlier Chinese-language output, preserving IDs, timestamps, paths, and numbers. Original archived evidence is unchanged.

[← Examples](../) ｜ [tool](../tool/) · [meet-join](../meet-join/) · [meet-book](../meet-book/) · **place** · [rule](../rule/) · [skill](../skill/) · [mode](../mode/) · [cmtbench](../benchmark/cmt/)

Register an open local browser tab as a place. **Execution units at this place receive that page's tools; units elsewhere do not.**

This example covers places only. Tool registration is described in [`../tool/`](../tool/).

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
BASE=http://127.0.0.1:7801/api
```

Start the browser with a debugging port and open the deck in a tab:

```bash
chrome --remote-debugging-port=9222 \
       --user-data-dir=/tmp/deck-profile \
       file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
```

> **A browser started this way has no audio/video input.** Since Chrome 136, remote debugging is disallowed on the default profile, so a separate `--user-data-dir` is required. That empty profile has no login and no camera/microphone permissions for any site. Probe the tab to see this:
>
> ```
> enumerateDevices  [{"kind":"audioinput","label":"","id":"empty"},
>                    {"kind":"videoinput","label":"","id":"empty"}, …]
> getUserMedia      (hangs without returning: the permission dialog awaits a click, and no one clicks)
> ```
>
> Empty `label` and `deviceId` mean no device is authorized. This approach therefore suits **pages that need neither camera nor microphone**, such as this deck. A browser that can join meetings and speak requires the extension approach in the user's own profile, rather than a debugging port.

Base setup (two cycles, one agent):

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes": [{ "mode":"work", "cycles":[
    { "cycle":"ask", "apiMode":"chat", "maxUnits":12, "from":[], "next":["act"], "infer":"fn:infer.dfs" },
    { "cycle":"act",                   "maxUnits":12, "from":["ask"], "next":["ask"], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name":"bot", "apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]], "unit":"fn:unit.tools" }]
}
JSON
```

---

## Register the place

One declaration contains three things: **the URL identifying the place**, **the tools it provides**, and **a rule that checks both**.

Use `dim: "place"` in the tool's `when`; this dimension asks **where the execution unit is**.

```bash
R=E:/sgu-bzhc/EACN_EX/TgEngin
LINK=file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{
  "places": [{ "place": "tab:deck" }],
  "servers": [{
    "name": "deck",
    "command": "bun",
    "args": ["examples/place/tab-server.ts", "$LINK"],
    "tools": {
      "deck_state": { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_next":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_prev":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] },
      "deck_goto":  { "when":[[{ "dim":"place","op":"eq","value":"tab:deck" }]] }
    }
  }],
  "handles": [{ "name":"fn:rule.deck_contract", "expectMs":15000,
                "module":"\$R/examples/place/deck-contract.ts#run" }],
  "rules": [{
    "identity": "fn:rule.deck_contract",
    "does": "When this station is at tab:deck, check that the page is still open and all required tools are present",
    "params": {}, "writes": {}, "scope": {},
    "when": [[{ "dim":"moment","op":"eq","value":"unit_start" },
              { "dim":"place", "op":"eq","value":"tab:deck" }]]
  }]
}
JSON
```
```json
{"servers":{"deck":["deck_state","deck_next","deck_prev","deck_goto"]},
 "handles":["fn:rule.deck_contract"],"places":["tab:deck"],"rules":["fn:rule.deck_contract"],
 "modes":[],"cycles":0,"agents":[],"tools":[],"skills":[],"tables":[],"entries":{}}
```

Supply the complete URL, not a fragment to guess from: **the URL is this place's identity**. With two decks open, guessing can connect to the wrong one without an obvious sign.

The two conditions in `when` belong to **the same group**, so they are ANDed: the moment is `unit_start`, **and** this station is at `tab:deck`.

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select place, forward, usable from workplace order by place" }
JSON
```
```json
{"count":2,"rows":[
  {"place":"local",   "forward":0,"usable":1},
  {"place":"tab:deck","forward":0,"usable":1}]}
```

`forward` is disabled. These tools are already local: they connect to the browser on local port 9222, so nothing needs forwarding elsewhere. **`forward` determines which machine executes tools; the place name determines where the station is.** Only places with `forward` enabled require a hop-chain name (`wsl` / `ssh://box-7` / `wsl/docker:build-01`). Without forwarding, a name is simply a name.

The engine calls it `tab:deck`; server arguments determine its browser URL. Each side uses its own identity, linked by this declaration.

## Check that the place still exists

[`deck-contract.ts`](./deck-contract.ts) implements the rule above. Before each execution unit starts here, it checks that the URL is still open and all four tools remain in the table.

When all checks pass (captured engine stdout; the message says the four tools are present):

```
[deck-contract] tab:deck complete: deck_goto, deck_next, deck_prev, deck_state | t-deck station 1
```

Navigate the tab away, then submit another task. The captured error says the page is no longer open and reports its current URL:

```
{"level":50,…,"msg":"Rule fn:rule.deck_contract failed at unit_start: place tab:deck is invalid (t-gone station 8): page is not open: file:///E:/…/deck.html (currently open: about:blank)"}
```

**Why this must be a rule**: declaration-time checks cover only that moment. Tabs are live objects: a user can close one while its `tool` rows remain intact in the database. The next execution unit still offers `deck_next` to the model, which calls it and receives isError. Registration and current availability are different, just as `workplace.usable` is a registration flag rather than a health probe. Check availability **whenever work starts**, using a moment and a rule.

**The rule does not block execution.** Its failure affects only itself; the kernel logs one line and the station continues. Hooks run on the main path; allowing a hook to stop the entire step would let one broken rule stall every task. Its role is to explain the problem immediately, not close a gate.

### What if tool names collide?

`tool.name` is the name shown to the model and is **globally unique**. Connect another server that also reports `deck_state`:

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<JSON
{ "servers": [{ "name":"deck2", "command":"bun",
    "args":["examples/place/tab-server.ts","$LINK"], "tools": {} }] }
JSON
```
```json
{"error":"Tool-name collision: deck_state already belongs to mcp:deck/deck_state, and server deck2 also reports it (delete the old row before replacing it; silent replacement would be invisible)"}
```

## Is the tool available here?

Ask without submitting a task:

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
  -d '{"kind":"tool","owner":"deck_next","place":"tab:deck"}'
```
```json
{"fired":true,"groups":[[{"group":0,"dim":"place","key":"","op":"eq","value":"tab:deck","got":"tab:deck","hit":true}]]}
```

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
  -d '{"kind":"tool","owner":"deck_next","place":"local"}'
```
```json
{"fired":false,"groups":[[{"group":0,"dim":"place","key":"","op":"eq","value":"tab:deck","got":"local","hit":false}]]}
```

---

## A task at this place

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-deck", "mode":"work", "agent":"bot", "place":"tab:deck", "source":"user",
  "solveSeconds": 300,
  "description": "Which slide is this deck currently on? Navigate to 'What went wrong', tell me its slide number, then finish." }
JSON
```

Tools available to this station:

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=inject" | grep -o '"tools":\[[^]]*\]' | head -1
```
```
"tools":["read","write","edit","glob","grep","bash","deck_goto","deck_next","deck_prev","deck_state"]
```

The first six have `system = 1` and are available everywhere; the last four come from this place.

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=call" | grep -o '"name":"deck[^}]*}'
```
```
"name":"deck_state","input":{}
"name":"deck_next","input":{}
… (continues advancing)
"name":"deck_state","input":{}
"name":"deck_goto","input":{"page":9}
```

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=tool" | grep -o '"value":{[^{}]*}'
```
```
"value":{"page":1,"total":12,"title":"Opening"}
"value":{"page":2,"total":12,"title":"What we did this quarter"}
…
"value":{"page":9,"total":12,"title":"What went wrong"}
```

```bash
curl -s "$BASE/tasks/t-deck/messages?kind=prompt" | grep -o '"body":"[^"]*"' | tail -1
```
```
"body":"Finished. The deck is now on **slide 9, titled 'What went wrong'** (12 slides total)."
```

The browser really is now on slide 9. Completing the task does not reset it: **page state lives in the page, not the database**. The next execution unit at this place continues from slide 9.

## The same task at another place

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-deck-local", "mode":"work", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 180,
  "description": "Which slide is this deck currently on? Navigate to 'What went wrong', tell me its slide number, then finish." }
JSON
```
```bash
curl -s "$BASE/tasks/t-deck-local/messages?kind=inject" | grep -o '"tools":\[[^]]*\]' | head -1
```
```
"tools":["read","write","edit","glob","grep","bash"]
```

The four deck tools are absent. The description and agent are identical; only the place differs. The model therefore uses `read` to inspect `deck.html` and answers **what the file says**, rather than **the page's current position**:

```
"body":"I've found the deck file. It's a JavaScript-powered presentation with 12 slides.
The titles are: 1. Opening … 12. Q&A\n\nThe deck starts on page 1, and the slide …"
```

“Starts on page 1” is the initial value in source, not the current tab state, which the model cannot access.

---

## Logs

English rendering of the captured output; slide titles match the English labels in the current deck.

```
[tab] Started, matching file:///E:/…/deck.html; debugging port 9222
[tab] Connected to Q3 Review — 1/12 Opening｜file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html
[tab] deck_state → {"page":1,"total":12,"title":"Opening"}
[tab] deck_next → {"page":2,"total":12,"title":"What we did this quarter"}
[tab] deck_next → {"page":3,"total":12,"title":"Revenue"}
```

## Fields

`places[]`

| | |
| --- | --- |
| `place` | Name; a hop chain is required only with `forward` enabled |
| `forward` | Whether to forward tool calls there; disabled by default |
| `runtime` | Runtime sent when forwarding (local file path) |
| `tools` | Forwarding allowlist; each entry is `{tool, policy}`, with policy `always` / `agent` |
| `usable` | **Registered** availability, not a health probe |

Health probes run on demand and do not write back to the database:

```bash
curl -s -X POST $BASE/places/tab:deck/ping
```
```json
{"place":"tab:deck","alive":true,"ms":0,"why":"This place does not forward; there is no connection to probe"}
```

The `place` dimension in `when` does not inspect attributes; leave `key` empty. It compares **this execution unit's** workspace, not `task.place`: after branching, two stations of the same task may occupy different places.
