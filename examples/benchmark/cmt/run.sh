#!/usr/bin/env bash
# Run cmtbench. **Every step is specified here.**
#
#   bash examples/benchmark/cmt/run.sh [count] [run-name]
#
# Prerequisites: setup.sh has prepared the corpus, official grader, and venv; the grader and engine are running. Otherwise use the three commands at the start of the README.
set -eu
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

BASE=${TGENGIN_BASE:-http://127.0.0.1:7801/api}
GRADER=${TGENGIN_CMT_GRADER:-http://127.0.0.1:7901}
HOW_MANY=${1:-5}
RUN=${2:-cmt-demo}
# **Number of concurrent problems.** 0 submits the whole batch immediately; the kernel consumes all arrivals, so 50 problems mean 50 concurrent calls.
# When set, submit individually and replenish each completed slot: 20 concurrent problems, not fixed batches of 20.
export TGENGIN_CMT_AT_ONCE=${TGENGIN_CMT_AT_ONCE:-0}
# **Whether to attach extensions.** Empty means attach them. A `bare` run is the no-extension baseline: identical mechanisms and problems, without domain hints. Compare against it to measure the extensions' contribution.
BARE=${TGENGIN_CMT_BARE:-}

step () { echo; echo "── $* ──"; }

# Check that `bun` is on PATH **before anything else**. Otherwise the script fails at extension registration after earlier steps have modified the database, appearing partly complete even though no batch was submitted.
command -v bun >/dev/null || { echo "bun is not on PATH (common in Git Bash); refresh PATH and retry"; exit 1; }

step "0 Check grading-service availability"
curl -sS "$GRADER/health"; echo

step "1 Base configuration: one place, two-cycle mode, one agent, and two grading handles"
curl -s -X POST "$BASE/declare" -H 'content-type: application/json' -d @- <<JSON
{ "places":[{"place":"local"}],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":35,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":35,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[
    {"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"},
    {"name":"searcher","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools",
     "knobs":{"reasoningEffort":"none"}}],
  "handles":[
    {"name":"$GRADER/parsed","expectMs":60000},
    {"name":"$GRADER/equiv", "expectMs":60000}] }
JSON
echo

step "2a Disable tools this task does not need"
# **A pure derivation problem does not need a filesystem.** These system tools are available to everyone without conditions and can distract the solver. In one run the model spent 12 execution units querying `python --version` through bash without writing an answer. Requests for computation reached no usable environment and exhausted the budget; computation is now available through `python_exec`, which is not in this list.
#
# Disable only the usable column, leaving `does` and `params` unchanged. Set 0 back to 1 to re-enable.
curl -s -X POST "$BASE/exec" -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "update tool set usable = 0 where name in ('bash','read','write','edit','glob','grep')" }
JSON
echo

# **Computation no longer needs declaration here.** `python_exec` ships with the binary (`app/src/tools/python.ts`, Pyodide in a worker) and is universally available like read/write. The previous container plus HTTP-handle setup only worked on machines with Docker-in-WSL.
# **Tool suppression at submission is also handled elsewhere.** It follows from DFS transitions: submission is a model station followed by another model station, so nobody executes tools requested there. Register those conditions with the tools (`tree/dfs.ts`, `objective/tool.ts`, `tree/view.ts`, `tools/python.ts`) and distribute them in the binary, rather than requiring every benchmark to write SQL.
if [ -z "$BARE" ]; then
  step "2 Attach extensions"
  bun examples/benchmark/cmt/parmeras/load.ts
else
  step "2 Skip extensions (extension-free baseline)"
  echo "  TGENGIN_CMT_BARE is set; no domain prompts attached for this run"
fi
step "2b Validate conditions"
curl -sS "$BASE/check"; echo

step "3 Submit batch (reject the whole batch if any task fails validation)"
bun examples/benchmark/cmt/send.ts "$HOW_MANY" "$RUN"

step "4 Wait for completion"
# Verdict-0 tasks are marked dead and retried on sibling paths. Completion therefore requires both running and open to reach zero, through acceptance or solveSeconds expiration and failed status.
for i in $(seq 1 400); do
  sleep 10
  r=$(curl -s "$BASE/bench/$RUN")
  left=$(echo "$r" | grep -o '"running":[0-9]*' | grep -o '[0-9]*$')
  open=$(echo "$r" | grep -o '"open":[0-9]*' | grep -o '[0-9]*$')
  [ $((i % 6)) -eq 0 ] && echo "  Running ${left:-?} | Unstarted ${open:-?} ($((i*10))s)"
  [ "${left:-1}" = "0" ] && [ "${open:-1}" = "0" ] && break
done

step "5 Scorecard"
curl -s "$BASE/bench/$RUN"
echo

step "6 Check extension injection"
for t in $(curl -s "$BASE/tasks?run=$RUN" | grep -o '"id":"[^"]*"' | grep -o 'cmt-[0-9]*'); do
  n=$(curl -s "$BASE/tasks/$t/messages?kind=skill" | grep -o '"total":[0-9]*' | grep -o '[0-9]*$')
  echo "  $t: ${n:-0} skill rows"
done
