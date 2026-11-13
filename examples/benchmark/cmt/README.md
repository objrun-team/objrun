# cmtbench

[← Examples](../../) ｜ [tool](../../tool/) · [meet-join](../../meet-join/) · [meet-book](../../meet-book/) · [place](../../place/) · [rule](../../rule/) · [skill](../../skill/) · [mode](../../mode/) · **cmtbench**

[CMT-Benchmark](https://arxiv.org/abs/2510.05228): 50 research-level condensed-matter theory problems.
This example sends the entire batch to the engine, grades with the official LaTeX→Sympy pipeline, and produces a scorecard.
The final section records our measured baseline.

```
Windows                                      WSL
┌────────────────────────────────────────┐   ┌──────────────────────────────────────────────────┐
│ Engine tgengin-win-x64.exe             │   │ Grading service: grader.py                       │
│ place=local: agent solves here         │──▶│ Official cmtbench grader                         │
│ Two G nodes = two HTTP handles         │   │ Dataset: cmt_data.jsonl                          │
└────────────────────────────────────────┘   └──────────────────────────────────────────────────┘
```

The grading service runs in WSL only because the official grader requires Python ≥3.12. With a full Python installation on Windows,
it can run there directly without any engine changes: the engine knows only the two URLs.

**The dataset contains reference answers, so it stays on the grading-service side** (the WSL home directory or a container),
outside this directory and repository. The submission script cannot read it either; it fetches problems over HTTP.

---

## 1. Setup

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt/setup.sh"
```

If `ssh wsl` is unavailable, use the equivalent `wsl.exe -d Ubuntu-24.04 -- bash -lc "..."`.

[`setup.sh`](./setup.sh) is idempotent and installs all three components under `~/.cache/tgengin-cmt/`:

| Location | Source |
| --- | --- |
| `cmt_data.jsonl` | HuggingFace `JVRoggeveen/cmt_benchmark`, 50 rows |
| `vendor/cmt_benchmark_data/` | GitHub `JamesRoggeveen/cmt_benchmark_data`, pinned to `c114183` |
| `venv` | sympy 1.13.3 / numpy 2.2.5 / regex 2024.11.6 |

```
── Self-test: can the official grader load and grade correctly? ──
  √ cmt-0 (HF)parsed=True equiv=True
  ...
  Ground truth submitted as answers: 5 of 5 graded equivalent
```

Follow the official version pins: custom LaTeX normalization would make scores incomparable with the paper’s table. Install only those three packages;
the official `pyproject.toml` also lists openai / anthropic / google-genai / datasets / matplotlib
for model execution and plotting, which grading does not need.

## 2. Grading service

```bash
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt \
         && ~/.cache/tgengin-cmt/venv/bin/python grader.py"
```
```
[cmt] Grading service ready: http://0.0.0.0:7901/{parsed,equiv} | 50 tasks
```

[`grader.py`](./grader.py) implements no grading decisions: it receives HTTP, selects evaluators using the same branches
as official `scripts/evaluate.py`, and caches results. It returns the official `success` / `is_equivalent` fields.

**Check from Windows**, using the same route as the engine:

```bash
curl -s http://127.0.0.1:7901/health
curl -s -X POST http://127.0.0.1:7901/equiv -H 'content-type: application/json' \
  -d '{"input":{"task":{"id":"cmt-0","result":"So the answer is $\\boxed{\\frac{U_1}{2}}$"}}}'
curl -s 'http://127.0.0.1:7901/problems?n=1'
```
```
{"ok": true, "items": 50}
  U_1/2 → parsed=true equiv=true      (cmt-0 ground truth is U_1/2)
[{"index":0,"prompt":"Consider a spinful electron system…","parameters":"$U_0;U_1$","functions":"","type":"HF"}]
```

`/problems` **has no `solution` field**: answers never leave this process.

### Container alternative (bundle the dataset and grader)

```bash
docker compose -f examples/benchmark/cmt/compose.yaml up -d --build
```

[`Dockerfile`](./Dockerfile) packages the dataset, official grader, three Python packages, and `grader.py` into an image,
running `--selftest` during the build (expected 5/5). The engine remains unchanged and knows only the two URLs.

Keep the `127.0.0.1:` prefix in `compose.yaml`’s `127.0.0.1:7901:7901`; removing it publishes
the port on every network interface.

Three points for snap Docker in WSL:

```bash
# 1. Strict snap confinement allows reads only under $HOME: copy the build context there first.
mkdir -p ~/build && cp Dockerfile grader.py ~/build/ && cd ~/build && docker build .

# 2. dockerd is a systemd service and cannot inherit shell proxy settings; it fetches base images itself.
sudo mkdir -p /etc/systemd/system/snap.docker.dockerd.service.d
printf '[Service]\nEnvironment="HTTP_PROXY=http://%s:7890"\nEnvironment="HTTPS_PROXY=http://%s:7890"\nEnvironment="NO_PROXY=localhost,127.0.0.1,::1"\n' \
  "$(ip route show default | awk '{print $3}')" "$(ip route show default | awk '{print $3}')" \
  | sudo tee /etc/systemd/system/snap.docker.dockerd.service.d/proxy.conf
sudo systemctl daemon-reload && sudo snap restart docker
docker info | grep -i proxy      # The HTTP Proxy: line confirms configuration.
```

Use **WSL’s default gateway**, not `localhost`; it changes after `wsl --shutdown`.

3. A `# syntax=` directive fetches the frontend from Docker Hub and can fail at `auth.docker.io` on an unstable network;
omit it when unnecessary. The Dockerfile installs no apt packages (`deb.debian.org` uses plaintext HTTP,
which returned 502 behind the proxy). Python’s built-in `urllib` + `tarfile` suffice to fetch the two files.

## 3. Engine

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
```
```
models: fn:api.deepseek, fn:api.dashscope | 16384 output tokens (up to 3 continuations) | reasoning medium
db …\data\h2h.sqlite | write on | token none
```

This example is sensitive to the following settings under `llm:` in `config.yaml`:

| | |
| --- | --- |
| `reasoningEffort` | Seven levels: `none` · `minimal` · `low` · `medium` · `high` · `xhigh` · `max`. **Record this alongside the task, model, and time limit in the scorecard**: the same task can take orders of magnitude longer at another level. Individual agents can pin their level through `agent.knobs` (`searcher` pins `none`) |
| `maxTokens: 16384` | Reasoning alone can exhaust the allowance. In the 8192-token run, 12 of 19 execution units produced no answer text |
| `continueTimes: 3` | On `finish_reason = length`, feed the existing output back (**including chain of thought**) and continue, at most three times |
| `retryTimes: 3` | Retry failed calls, waiting an additional `5n` seconds before retry n. `api.retry_on` determines retryable errors |

Keep WSL alive before running: the grading service is inside it, and WSL2 reclaims the whole VM when idle.

```bash
wsl.exe -d Ubuntu-24.04 -- sleep infinity &
```

## 4. Run a batch

```bash
TGENGIN_CMT_BARE=1 TGENGIN_CMT_AT_ONCE=20 bash examples/benchmark/cmt/run.sh 0 cmt-run
```

| Parameter | |
| --- | --- |
| First positional argument | Task count. `0` submits every task available from the service |
| Second positional argument | Run name |
| `TGENGIN_CMT_BARE=1` | Disable domain extensions (extension-free baseline) |
| `TGENGIN_CMT_AT_ONCE=20` | Run 20 tasks concurrently, replacing each completed task. Empty = submit the entire batch at once |
| `TGENGIN_CMT_ONLY=3,5,8` | Submit only these dataset indices. Empty = no selection |
| `TGENGIN_CMT_SECONDS=900` | Time per task; default 3600 |

[`run.sh`](./run.sh) combines the steps below.

### Base configuration

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "places":[{"place":"local"}],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":35,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":35,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[
    {"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"},
    {"name":"searcher","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools",
     "knobs":{"reasoningEffort":"none"}}],
  "handles":[
    {"name":"http://127.0.0.1:7901/parsed","expectMs":60000},
    {"name":"http://127.0.0.1:7901/equiv", "expectMs":60000}] }
JSON
```

A handle’s name is its address; no additional registration is needed. `ask` invokes the model, and `act` executes its requested tools.
`infer: fn:infer.dfs` selects tree traversal: after a score of 0, open a sibling under the same parent and try another route.

Pure derivation problems do not need a filesystem, so disable those system tools by changing the data-only `usable` column:

```bash
curl -s -X POST $BASE/exec -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "update tool set usable = 0 where name in ('bash','read','write','edit','glob','grep')" }
JSON
```

An incorrect condition raises no error; it simply never triggers. Check before submitting a batch:

```bash
curl -s $BASE/check          # {"trigger":[],"data":[]} = all checks pass
```

### G for each task

```json
{ "nodes": [
    { "name":"parsed", "moment":"task_done", "domain":"bool", "handle":"http://127.0.0.1:7901/parsed" },
    { "name":"equiv",  "moment":"task_done", "domain":"bool", "handle":"http://127.0.0.1:7901/equiv"  }],
  "edges": [{ "src":"parsed", "out":0, "dst":"equiv" }],
  "sink": "equiv",
  "checks": 10 }
```

The two nodes match the two fields reported by the original benchmark. The root must have an incoming edge; otherwise publication rejects it:
`Output node … has no incoming edges — its value is independent of the candidate, making G constant and the objective invalid.`

`checks` is **the number of proactive G queries per round** through `verify`. Restarting after being marked dead begins a new round.

### Task shape

[`send.ts`](./send.ts) fetches tasks from `/problems` and constructs the `POST /bench` request:

```json
{ "id":"cmt-0", "mode":"solve", "agent":"bot", "place":"local", "source":"user",
  "domain":"physics",
  "solveSeconds": 3600,
  "maxBranches": 4,
  "maxDeadSiblings": 8,
  "maxSearches": 5,
  "noSearch": ["cmt benchmark", "cmt dataset", "cmt jsonl"],
  "description":"Consider a spinful electron system in a two-dimensional triangular lattice…\n\nSymbols: $U_0;U_1$\n\nPut the final answer inside \\boxed{}.",
  "objective": { "…definition above…": null },
  "readable": true }
```

| | |
| --- | --- |
| `solveSeconds` | Time per task. Must exceed a single call’s deadline (the model handle’s `expect_ms` is 15 minutes), or a stalled call can never progress to marking the execution unit dead and switching routes |
| `maxSearches: 5` | Five searches per execution unit. Restarting after being marked dead gives a fresh allowance; blocked and over-limit requests do not consume it |
| `noSearch` | Block access to this benchmark itself. Each entry is **a group of words**, all required for a match. A match anywhere in the search result (answer, queries, opened pages) discards the whole result; the model receives `Forbidden access` |
| `readable: true` | Explicitly required with G; no default. `true` appends G’s definition to the task description. Hide ground truth, not the criterion |
| `source: "user"` | Only `user` tasks may carry G; agent-derived tasks may not |
| `domain: "physics"` | Routes extensions; distinct from `mode`, which selects the reasoning mechanism |

If any task fails validation, submit none of the batch. Partial submission gives the scorecard a wrong denominator and hides which tasks are missing.

### Scorecard

```bash
curl -s $BASE/bench/cmt-run
```
```json
{"run":"cmt-run","total":50,"passed":44,"failed":6,"running":0,"open":0,
 "tasks":[{"id":"cmt-0","state":"done","result":"{\"pass\":1,\"why\":\"\"}"}]}
```

Scores are counted, not stored. Inspect `why` for `failed`: `equiv evaluated to false` means G actually returned 0;
`over solve_seconds=…` means time expired first.

---

## Our baseline

`cmt-medium-s5b`, 2026-09-01. **All 50 tasks, one hour per task, `medium` reasoning, no extensions,
5 searches per execution unit, and 20 concurrent tasks.**

```bash
TGENGIN_CMT_BARE=1 TGENGIN_CMT_AT_ONCE=20 bash examples/benchmark/cmt/run.sh 0 cmt-medium-s5b
```

### 44 / 50

The six failures (`cmt-2` `cmt-11` `cmt-37` `cmt-44` `cmt-46` `cmt-49`) all have the same verdict:
`over solve_seconds=3600s; equiv evaluated to false`: **the full hour elapsed with an answer in hand,
but the answer was wrong**. None failed to submit an answer.

Of the 44 correct tasks, **19** were correct on the first answer submitted to G; the remaining 25 needed multiple checks.
The latter combine two behaviors: correcting a derivation after seeing false, and submitting choices one by one.
For choice questions, the answer space is smaller than the 10-check allowance per round. The budget is fixed (`checks: 10`; only a restart after being marked dead starts a new round),
and the solver chooses how to use it. Both counts are recorded as `pass` and `first_answer_pass` in `export/csv/tasks.csv`.

### Where the hour goes

| | |
| --- | --- |
| Model calls | 762 × 62 seconds = **65%** |
| Waiting for search | 153 × 133 seconds = **28%** |
| Other tools | 559 × 8 seconds = 6% |

There were 1,474 execution units and 102 searches across 34 tasks; one task searched 8 times, and the per-unit limit of 5 was hit 7 times.
Each call averaged 98,011 input tokens (88% cache hits) and 6,842 output tokens, including 6,398 reasoning tokens.

### Data

`data/runs/cmt-medium-s5b/` (`data/` is outside version control):

| | |
| --- | --- |
| `h2h.sqlite` | Complete database for this run |
| `engine.log` · `run.log` | Engine and batch logs |
| `RESULT.md` | Full conclusions for this run |
| `export/csv/{tasks,stations,verify,searches}.csv` | Tables at four granularities |
| `export/FIELDS.md` | Column definitions |

---

## Files

| | |
| --- | --- |
| [`setup.sh`](./setup.sh) | Idempotent dataset + official grader + venv setup for the non-container route |
| [`Dockerfile`](./Dockerfile) · [`compose.yaml`](./compose.yaml) | Bundle the grading service and dataset for the alternative container route |
| [`grader.py`](./grader.py) | HTTP wrapper around the official grader, plus `/problems` for problem statements |
| [`send.ts`](./send.ts) | Fetch tasks from `/problems` and construct `POST /bench` |
| [`run.sh`](./run.sh) | Declare → disable unused tools → attach extensions → submit batch → wait → scorecard |
| [`parmeras/`](./parmeras/) | Skill and registration script migrated from the old repository (`TGENGIN_CMT_BARE` disables it) |

The dataset and official grader live outside this directory, under `~/.cache/tgengin-cmt/` (WSL home) or inside the container.
