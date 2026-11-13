<p align="center">
  <strong>English</strong> | <a href="README.zh-CN.md">简体中文</a>
</p>

<h1 align="center">ObjRun</h1>

<p align="center">Objective Engineering for Agentic Science</p>

<p align="center">
  <a href="https://objrun-team.github.io/#video">
    <img src="https://objrun-team.github.io/media/objrun-poster.png" alt="Watch the ObjRun overview video" width="720">
  </a>
</p>

<p align="center">
  <a href="https://objrun-team.github.io/">Website</a> ·
  <a href="https://objrun-team.github.io/paper.pdf">Paper</a> ·
  <a href="https://objrun-team.github.io/#video">Video</a> ·
  <a href="https://objrun-team.github.io/runs/">Run Replays</a> ·
  <a href="https://objrun-team.github.io/blog/">Case Studies</a>
</p>

---

ObjRun is a runtime for AI agents working toward verifiable objectives. You provide a checker and set the feedback, query, retry, and time limits. ObjRun manages attempts, carries feedback into retries, and records every verdict.

Models, tools, and search strategies are declared as data. All 20 benchmarks in the paper were integrated without changing the kernel: each uses an objective record and a wrapper around the official grader.

## Quick Start

Requires [Git](https://git-scm.com/), [Bun](https://bun.sh), and an API key for the model provider you use.

```bash
git clone https://github.com/objrun-team/objrun.git
cd objrun
cp .env.example .env
```

Set the keys you need in `.env`, which is excluded from version control. The basic examples use `DEEPSEEK_API_KEY`; `DASHSCOPE_API_KEY` is available for examples that use DashScope.

```dotenv
DEEPSEEK_API_KEY=your-api-key
```

Start the service:

```bash
cd app
bun install
bun start
```

Open [the built-in interface](http://127.0.0.1:7801/ui). The API listens at `http://127.0.0.1:7801/api`. In a second terminal, check that the service is ready:

```bash
curl http://127.0.0.1:7801/api/health
```

Follow the [examples](examples/README.md) to declare an agent and send your first task. Missing provider keys are reported when required.

## How It Works

<p align="center">
  <a href="https://objrun-team.github.io/paper.pdf">System overview (paper Fig. 2)</a>
</p>

<p align="center"><sub>Define and seal the objective → attempt, check, and retry → compute results from recorded verdicts.</sub></p>

1. **Publish** — Define the task and its objective. The kernel validates the objective graph and stores it in a sealed database outside the main database API's reach.
2. **Attempt** — The agent uses tools and queries the objective within its allowance. Each query returns a verdict and only the feedback declared in advance.
3. **Retry** — A rejected submission starts another attempt while retry and time budgets remain. History is retained and the query allowance resets.
4. **Finish** — Stop on acceptance or when a budget is exhausted. Verdicts, calls, history, and usage are stored; scores are computed from these records.

See the [execution loop](docs/loop.md) for validation rules, submission handling, and final evaluation.

## Main Results

The headline runs use DeepSeek V4.1 Flash. **U** is the single-attempt baseline; **F** is a run with an attached objective and a budget for checks and retries. Seventeen benchmarks have local U/F comparisons using the same model. DeepSWE, Terminal-Bench 2.1, and SkillsBench 1.1 use external single-attempt references.

<p align="center">
  <a href="https://objrun-team.github.io/paper.pdf">Benchmark comparison (paper Fig. 1)</a>
</p>

<p align="center"><sub><b>Fig. 1</b>　Single-response results (light gray), published reference results (dark gray), and ObjRun (blue) across 20 benchmarks.</sub></p>

These are not equal-compute comparisons. See the [paper's appendix](https://objrun-team.github.io/paper.pdf) for all 20 results, budgets, and evaluation protocols.

### Scientific Case Studies

The paper also examines four scientific problems from recent papers. Each had a five-hour time limit, and the results were independently verified by checkers on the host machine. Model calls across the four cases cost a total of $5.62.

| Problem | Reference | Result | Verification |
| --- | --- | --- | --- |
| DNA codes (n = 10, d = 4, GC = 5) | 676 codewords | 1,688 codewords | Two independent integer implementations |
| Low-storage Runge–Kutta (5 stages, order 3, 2N) | Error norm 0.015632 | 0.013967, optimal over the fixed feasible set | Exact rational interval arithmetic |
| Spherical designs (24 unit vectors in R⁶) | Conjecture | 4 nonglobal local minima | Interval arithmetic certificates |
| RNA designability (Repetitious Sequences 8/10) | Upper bound 0.18740 | Upper bound 0.15770 | Envelope enumeration over all assignments |

<p align="center">
  <a href="https://objrun-team.github.io/paper.pdf">Verification of the four scientific case studies</a>
</p>

Read the [case study blog](https://objrun-team.github.io/blog/) for the process behind each result.

## Configuration

[`config.yaml`](config.yaml) controls the server, logging, model defaults, and database locations. Paths resolve relative to this file, so changing the startup directory does not change the database. Use `${VAR}` to read environment variables; existing `TGENGIN_*` names remain supported.

Bun runs the TypeScript source directly and provides SQLite through `bun:sqlite`.

## Build

From `app/`, run:

```bash
bun run build
```

Outputs go to `dist/`: standalone executables for Windows x64 and macOS arm64/x64, a Linux x64 remote runtime, and the `pyodide/` assets. Distribute `config.yaml` and `pyodide/` alongside the application executable; the target machine does not need Bun installed.

Run `bun run verify` from `app/` to type-check and build. See [test/README.md](test/README.md) for the test suites.

## Project Structure

```
app/src/             Runtime, API, tools, and built-in interface
config.yaml          Runtime configuration
examples/            Runnable examples and benchmark integrations
experiments/         Benchmark sources and experiment records
scripts/             Shared runners and maintenance tools
docs/                Architecture, execution loop, and database schemas
test/                Unit, integration, and benchmark tests
```

The full local checkout also contains `site/` and `paper/`, which are excluded from this public repository. The [website](https://objrun-team.github.io/) and [paper PDF](https://objrun-team.github.io/paper.pdf) are published separately.

## Documentation

- [Examples](examples/README.md) — agents, tasks, tools, and objectives.
- [Architecture and API](docs/README.md) — execution loop, protocols, and data tables.
- [Experiments](experiments/README.md) — benchmark sources and recorded runs.
- [Paper (PDF)](https://objrun-team.github.io/paper.pdf) — methods, figures, and experimental results.
