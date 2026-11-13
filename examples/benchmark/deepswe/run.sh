#!/usr/bin/env bash
# Run DeepSWE. **Every step is specified here.**
#
#   bash examples/benchmark/deepswe/run.sh [count] [run-name] [seed]
#
# Requires completed setup.sh (corpus, images, grader self-tests), a running grader, and a running engine. Otherwise use the three commands at the start of the README.
set -eu
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

BASE=${TGENGIN_BASE:-http://127.0.0.1:7801/api}
STAND=${TGENGIN_DSW_STAND:-http://127.0.0.1:7902}
HOW_MANY=${1:-10}
RUN=${2:-dsw-demo}
SEED=${3:-0}

step () { echo; echo "── $* ──"; }

# Check that bun is on PATH **first**. Otherwise submission fails with command not found after earlier steps have already modified the database.
command -v bun >/dev/null || { echo "bun is not on PATH (common in Git Bash); refresh PATH and retry"; exit 1; }

step "0 Check service availability"
curl -sS "$STAND/health"; echo

step "1 Select tasks for this run"
# Selection is **deterministic**: the same (n, seed) always selects the same batch, using the shared rule in the grader and sender.
# **Allow spaces after the JSON colon.** Default json.dumps emits `{"id": "…"}`. Matching `"id":"` yields no IDs without an error, so no places are declared and /bench rejects the batch with a workplace-related message.
IDS=$(curl -s "$STAND/problems?n=$HOW_MANY&seed=$SEED" | grep -o '"id": *"[^"]*"' | sed 's/.*: *"\(.*\)"/\1/')
[ -n "$IDS" ] || { echo "The service returned no tasks: $STAND/problems?n=$HOW_MANY&seed=$SEED"; exit 1; }
echo "$IDS" | sed 's/^/  /'

step "2 Base configuration: places, mode, agent, and three service handles"
# **Each place row needs identity.** Its handle defines how to reach that place. The built-in fn:place.hops reads wsl/ssh/docker hop strings, which do not work here (three observed failures are documented in stand.py). Point to the grader, which also parses dsw:<task-id>.
#
# **One row per problem, including the run name.** task.place references workplace.place, and each run gets a fresh container. Omitting the run name would reuse a previous workspace when changing levels, making the experiments different. Submit one combined declaration because declarations are validated atomically.
TOOLS='[{"tool":"bash","policy":"always"},{"tool":"read","policy":"always"},{"tool":"write","policy":"always"},{"tool":"edit","policy":"always"},{"tool":"glob","policy":"always"},{"tool":"grep","policy":"always"}]'
PLACES='{"place":"local"}'
for t in $IDS; do
  PLACES="$PLACES,{\"place\":\"dsw:$RUN/$t\",\"identity\":\"$STAND/place\",\"forward\":true,\"tools\":$TOOLS}"
done

curl -s -X POST "$BASE/declare" -H 'content-type: application/json' -d @- <<JSON
{ "handles":[
    {"name":"$STAND/place",   "expectMs":300000},
    {"name":"$STAND/applies", "expectMs":1800000},
    {"name":"$STAND/resolved","expectMs":1800000}],
  "places":[$PLACES],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":70,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":70,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[
    {"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"}] }
JSON
echo

step "3 Disable the two unused tools"
# **Disable search.** Both official environments are no-network, while search is not forwarded to the workplace. It would provide real network access to reference solutions published on GitHub and searchable by problem ID.
#
# The tool is **web_search, not search**. A misspelled name makes SQL match zero rows legally and silently, leaving search enabled. Step 3c therefore checks the actual remaining tool set.
#
# Also disable python_exec: these problems span five languages, including Go/TS/Rust/Python, and must use their container toolchains through bash. Engine-side Pyodide is unrelated.
# Only change usable; preserve does and params.
curl -s -X POST "$BASE/exec" -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "update tool set usable = 0 where name in ('web_search','python_exec')" }
JSON
echo

step "3c Confirm tools are disabled"
# A wrong tool name makes SQL match zero rows without error, so it does not prove disabling succeeded. Check **which tools remain**, not the affected-row count.
ON=$(curl -s -X POST "$BASE/query" -H 'content-type: application/json' -d @- <<'JSON' | grep -o '"name":"[^"]*"' | cut -d'"' -f4
{ "sql": "select name from tool where usable = 1 order by name" }
JSON
)
echo "$ON" | sed 's/^/  Enabled /'
for banned in web_search python_exec; do
  if echo "$ON" | grep -qx "$banned"; then
    echo "  ✗ $banned is still enabled; stop without submitting a batch"
    exit 1
  fi
done
echo "  ✓ web_search / python_exec are both disabled"

step "3b Validate conditions"
curl -sS "$BASE/check"; echo

step "4 Submit batch (reject the whole batch if any task fails validation)"
bun examples/benchmark/deepswe/send.ts "$HOW_MANY" "$RUN" "$SEED"

step "5 Wait for completion"
# Verdict-0 tasks are marked dead and retried on sibling paths. Completion requires both running and open to reach zero, through success or solveSeconds expiration and failed status.
for i in $(seq 1 1200); do
  sleep 10
  r=$(curl -s "$BASE/bench/$RUN")
  left=$(echo "$r" | grep -o '"running":[0-9]*' | grep -o '[0-9]*$')
  open=$(echo "$r" | grep -o '"open":[0-9]*' | grep -o '[0-9]*$')
  [ $((i % 30)) -eq 0 ] && echo "  Running ${left:-?} | Unstarted ${open:-?} ($((i*10))s)"
  [ "${left:-1}" = "0" ] && [ "${open:-1}" = "0" ] && break
done

step "6 Scorecard"
curl -s "$BASE/bench/$RUN"
echo

step "7 Cleanup: retain work containers and their artifacts; grading containers already use --rm"
echo "  docker ps --filter name=dsw- --format '{{.Names}}'"
