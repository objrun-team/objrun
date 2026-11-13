# DeepSWE

[Datacurve’s DeepSWE](https://github.com/datacurve-ai/deep-swe): 113 **original** long-horizon engineering tasks across 91 repositories and five languages (TypeScript 35 / Go 34 / Python 34 / JavaScript 5 / Rust 5). Each task has a pinned container image and hand-written behavioral verifiers. Reference solutions are written from scratch, never copied from PRs or merged upstream.

Leaderboard (official `pier` + `mini-swe-agent`): GPT-5.6 Sol **72.70**, GPT-5.5 70%±3, GPT-5.4 56%±2, Claude Opus 4.7 54%±5, Claude Sonnet 4.6 32%±2.

Three commands: run the first in WSL, where Docker is installed, and the latter two on the engine host.

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/deepswe/setup.sh 10 0"
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/deepswe && python3 stand.py --level 2"
cd app && bun run start
```

Once the service and engine are running:

```bash
bash examples/benchmark/deepswe/run.sh 10 dsw-l2 0
```

---

## 1. Setup

`setup.sh` performs five idempotent steps:

| | |
| --- | --- |
| 1 | Clone the corpus to `$HOME/.cache/tgengin-deepswe/deep-swe` (**outside the repository**: `tasks/<id>/solution/` contains reference solutions) |
| 2 | Copy `dist/tgengin-runtime-linux-x64` into the home directory (snap Docker cannot access `/mnt` or `/tmp`) |
| 3 | Select tasks for this run using `(n, seed)` |
| 4 | Pull task images and build grader images |
| 5 | **Self-test**: submit each task’s reference solution to its official grader; it should score 1, while an empty patch should score 0. Skip with `TGENGIN_DSW_SELFTEST=0` |

```bash
ssh wsl "bash …/setup.sh [count] [seed]"
ssh wsl "TGENGIN_DSW_SELFTEST=0 bash …/setup.sh 0 0"   # All 113 tasks: prepare images without self-tests.
```

`count = 0` selects all tasks. Each self-test grades twice, so the full set takes hours; disable it if only preparing images.

Proxy: NAT-mode WSL cannot reach Windows at `127.0.0.1:7890`, so the script calculates the gateway with `ip route`. **The gateway changes on every restart**, so it is not hardcoded.

The Docker daemon has separate proxy configuration:

```bash
systemctl show snap.docker.dockerd.service -p Environment
# Environment=HTTP_PROXY=http://172.20.48.1:7890 HTTPS_PROXY=… NO_PROXY=localhost,127.0.0.1,::1
```

### Storage budget

Measured after pulling the full set (113 task images + 113 grader images):

| | |
| --- | --- |
| Images (deduplicated) | **99.59 GB** |
| Build cache | 25.04 GB, **reclaimable** with `docker builder prune`; left by grader-image builds |
| Work-container writable layers | Start at 60 MB each and grow with modifications |
| Grading logs | `$HOME/.cache/tgengin-deepswe/logs/<task>-<patch16>/`, hundreds of KB per grading call |
| Corpus | 30 MB |
| Pull duration | 52 minutes on this machine through the gateway proxy |

Individual images are 3.7–11.1 GB, but all 113 **share the `swe-bench-202605` base**, keeping the deduplicated total below 100 GB. Multiplying one image size by 113 overestimates by more than 2×. The ten-task subset occupies 18.03 GB.

Images reside in **`E:\wsl\Ubuntu\ext4.vhdx`**, WSL’s sparsely growing virtual disk:

```
/var/snap/docker/common/var-lib-docker   Docker-reported root (snap, overlayfs)
  └─ /dev/sdd                          1 TB block device inside WSL
       └─ E:\wsl\Ubuntu\ext4.vhdx      Backing file
```

```bash
docker system df                       # Image / container / build-cache usage.
df -h /                                # Remaining space inside WSL.
docker builder prune -f                # Reclaim 25 GB without removing built images.
```

**The VHDX grows but does not shrink automatically**: deleting files inside it does not return space to drive E. After `wsl --shutdown`,
compact it with `Optimize-VHD` or `diskpart`. Check drive E before pulling to avoid running out of space midway.

## 2. Service

One process runs in WSL with Docker access. The engine sees **three handles**:

```
http://127.0.0.1:7902/place       Where to work: forward tool calls into the task container.
http://127.0.0.1:7902/applies     First node of G: does the submitted patch apply?
http://127.0.0.1:7902/resolved    Root of G: does the official grader report success?
```

```bash
python3 stand.py [--port 7902] [--level 2] [--selftest [TASK_ID...]]
```

### Why place handling lives here

The handle referenced by `workplace.identity` **resolves addresses and forwards calls**. The kernel’s built-in
`fn:place.hops` reads `wsl` / `ssh` / `docker` hop strings, which fail at three points on this machine:

```
wsl.exe -- docker ps        docker: command not found (snap; only on login-shell PATH)
ship() handles outer hop   Runtime copied into WSL /tmp, not the container
docker cp /tmp/…            lstat: no such file (snap cannot access /tmp)
```

This example therefore supplies its own handle and `dsw:<task-id>` address scheme. Container startup and runtime transfer stay in this process. **No kernel changes are needed.**

Forwarded tools **still use the kernel’s implementation**: the container receives `dist/tgengin-runtime-linux-x64`, an MCP server containing the tools from `app/src/tools/`.

### Containers

| | |
| --- | --- |
| Work | `dsw-<task-id>`, the task’s pinned image, `--network none --cpus 2 --memory 8g`; repository at `/app`. **Restarting after being marked dead does not roll back state** |
| Startup | Transfer the runtime and configure Git (`user.email` / `user.name` / `safe.directory`); images lack an identity, so the first `git commit` would otherwise fail with `Please tell me who you are` |
| Grading | Fresh each time, `--rm`, image = same task image + hidden tests baked into `/tests`, `--network none` |

Resource limits follow official `task.toml` (`cpus = 2`, `memory_mb = 8192`); grading timeout is 1800 seconds.

### Feedback levels

`--level` controls detail in `note`. **Each level is a separate experiment**; the engine knows nothing about it, and G keeps the same shape.

| Level | Contents of `note` |
| --- | --- |
| 0 | Empty |
| 1 | Failed stage + counts |
| 2 | + Failed test names, at most 60 |
| 3 | + Raw failure messages, at most 40, each limited to 2000 characters |

An actual level-2 response for a partially implemented patch:

```json
{ "stage": "tests",
  "new_behaviours": "15 of 20 pass",
  "existing_tests": "3 of 3 still pass",
  "failing": ["[f2p] …repl.TestChallengeBeginReplScriptModeWithModulePathFlag", "…"] }
```

## 3. Engine

Step 2 of `run.sh` sends a declaration. The place entries are the important part:

```json
{ "handles": [
    {"name": "http://127.0.0.1:7902/place",    "expectMs": 300000},
    {"name": "http://127.0.0.1:7902/applies",  "expectMs": 1800000},
    {"name": "http://127.0.0.1:7902/resolved", "expectMs": 1800000}],
  "places": [
    {"place": "local"},
    {"place": "dsw:abs-module-cache-flags",
     "identity": "http://127.0.0.1:7902/place",
     "forward": true,
     "tools": [{"tool":"bash","policy":"always"}, {"tool":"read","policy":"always"},
               {"tool":"write","policy":"always"},{"tool":"edit","policy":"always"},
               {"tool":"glob","policy":"always"}, {"tool":"grep","policy":"always"}]}],
  "modes": [{"mode": "solve", "cycles": [
    {"cycle":"ask","apiMode":"chat","maxUnits":70,"from":[],     "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":70,"from":["ask"],"next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents": [{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"}] }
```

**One place row per task**: `task.place` references `workplace.place`, giving each task its own container.

Disable two tools in step 3 by changing the data-only `usable` column:

```sql
update tool set usable = 0 where name in ('web_search','python_exec')
```

Disable `web_search` because both official sides use `no-network`, while this tool bypasses workplace forwarding and reaches the real network, where reference solutions are public on GitHub. Disable `python_exec` because all execution should use `bash` inside the container with its own toolchain.

## 4. Task shape

Request constructed by `send.ts`:

```json
{ "id": "abs-module-cache-flags",
  "mode": "solve", "agent": "bot",
  "place": "dsw:abs-module-cache-flags",
  "source": "user", "domain": "software", "workdir": "/app",
  "solveSeconds": 10800,
  "maxBranches": 4, "maxDeadSiblings": 8,
  "noSearch": ["deepswe solution", "datacurve deep-swe", "abs-module-cache-flags solution"],
  "description": "<instruction.md>\n\nYou are working in a git repository at /app…",
  "readable": true,
  "objective": {
    "nodes": [
      {"name":"applies", "moment":"task_done","domain":"bool","handle":"http://127.0.0.1:7902/applies"},
      {"name":"resolved","moment":"task_done","domain":"bool","handle":"http://127.0.0.1:7902/resolved"}],
    "edges": [{"src":"applies","out":0,"dst":"resolved"}],
    "sink": "resolved",
    "checks": 6 } }
```

| Setting | Value | Source |
| --- | --- | --- |
| `solveSeconds` | 10800 | Official `task.toml` `agent.timeout_sec` |
| `checks` | 6 | Grading takes 3–97 seconds, with an 1800-second cap; cost is not the issue |
| `maxBranches` | 4 | Leave time as the sole gate |
| `maxDeadSiblings` | 8 | Same rationale |
| `readable` | true | The target should be visible |
| Environment variables | `TGENGIN_DSW_CHECKS` / `TGENGIN_DSW_SECONDS` / `TGENGIN_DSW_SEED` | Override the settings above |

### G splits the official criterion into two stages

Official grading formula:

```
reward = 1  ⟺  |f2p| > 0  ∧  every f2p passes  ∧  no p2p fails
```

If the patch does not apply, write `apply_failed=1` and **skip tests**: that is stage zero. G follows this split:

```
applies ──→ resolved            root = resolved
```

The root **must have an incoming edge** (`objective/spec.ts`: otherwise its value is candidate-independent, G is constant, and the objective is invalid). One grading run produces `reward.json` + `ctrf.json`; both nodes read the same result, cached by patch SHA256.

### Submit a commit SHA

The official collection hook uses `git diff --binary <base> HEAD`, **including binary hunks**. Making the model reproduce this from tool output is costly and unreliable. Submit its commit SHA instead; the service runs the same command inside the container, replacing only `HEAD` with that SHA.

A SHA is immutable and identifies one tree. `graded` in the `verify` receipt echoes it.

## 5. Run a batch

```bash
bash examples/benchmark/deepswe/run.sh [count] [run-name] [seed]
```

Selection is deterministic: the same `(n, seed)` always selects the same batch. These two numbers reproduce the selection.

```bash
curl -s "$STAND/problems?n=10&seed=0" | grep -o '"id":"[^"]*"'
```

Scorecard:

```bash
curl -s http://127.0.0.1:7801/api/bench/dsw-l2
```

## Service self-test

Verify the grader installation by execution:

```bash
python3 stand.py --selftest abs-module-cache-flags adaptix-name-mapping-aliases \
                            arktype-json-schema-refs-dependencies \
                            boa-hierarchical-evaluation-cancellation \
                            csstree-shorthand-expansion-compression
```

One task per language: every reference solution scores 1, and every empty patch scores 0. Measured wall times:

| Task | Language | f2p / p2p | Image | Empty patch | Reference solution |
| --- | --- | --- | --- | --- | --- |
| abs-module-cache-flags | go | 20 / 3 | 3.90 GB | 14s | 14s |
| adaptix-name-mapping-aliases | python | 44 / 2738 | 3.71 GB | 19s | 29s |
| arktype-json-schema-refs-dependencies | typescript | 25 / 1679 | 5.24 GB | 75s | 76s |
| boa-hierarchical-evaluation-cancellation | rust | 17 / 7 | 9.92 GB | 12s | 97s |
| csstree-shorthand-expansion-compression | javascript | 79 / 16715 | 3.72 GB | 3s | 4s |

Grading cost is almost unrelated to test count (16715 tests in 4 seconds versus 7 tests in 97 seconds); the expensive step is **compiling a modified tree**.

Container cold start (startup + runtime transfer + MCP handshake) takes 1.5 seconds.

## Our baseline

Not run yet. After the first run, document the configuration, score, key breakdowns, and data location here.

## Files

```
setup.sh     Idempotent corpus, runtime, image, and self-test setup.
stand.py     Service: three handles (place + two G nodes), running in WSL with Docker.
send.ts      Assemble tasks with G and submit a batch.
run.sh       Declare → disable tools → submit batch → wait → scorecard.
```

The corpus, reference solutions, images, and grading logs stay under `$HOME/.cache/tgengin-deepswe/` (WSL home), outside the repository.
