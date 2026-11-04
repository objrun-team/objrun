<p align="center">
  <strong>English</strong> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="site/media/objrun-poster.png" alt="ObjRun" width="720">
</p>

<h1 align="center">ObjRun</h1>

<p align="center"><b>Objective Engineering for Agentic Science</b><br>You define the objective. AI uses feedback to work toward it.</p>

<p align="center">
  <a href="https://objrun.imontlaji.workers.dev/">Website</a> ·
  <a href="site/paper.pdf">Paper</a> ·
  <a href="https://objrun.imontlaji.workers.dev/runs">Run Replay</a> ·
  <a href="https://objrun.imontlaji.workers.dev/blog/">Case Studies</a> ·
  <a href="site/media/objrun-film-en-1080p60.mp4">Overview Video</a>
</p>

---

ObjRun is an objective runtime. Users specify what counts as correct: wrap a domain checker as an evaluator, seal it, and declare how many queries each attempt may make and how much information a rejection may reveal. Models, tools, and search strategies are declared as data. The agent can access the evaluation criteria only through a port that returns verdicts. After a rejected submission, it restarts with its history retained. Every verdict is written to the database, and all scores are computed from those records.

The kernel contains no domain, model, or tool names. All 20 benchmarks in the paper were integrated without modifying the kernel; each required only an objective record and a wrapper around the official grader.

## How It Works

<p align="center">
  <img src="paper/current/figs/main-0-system.png" alt="ObjRun system overview (paper Fig. 2)" width="760">
</p>

<p align="center"><sub><b>Fig. 2</b>　ObjRun overview. a: The author defines task d, objective G, and the harness declarations; G is sealed after validation. b: The solver queries the same sealed objective through an access port, up to c times per attempt, receiving feedback at information level L. A rejected submission triggers a restart within the limits of K and T, retaining history and resetting the query allowance. c: Calls, verdicts, history, and usage are stored durably, and results are computed from these records.</sub></p>

The lifecycle of a task:

1. **Publish**: Define task d and objective G. The kernel validates G's graph: valid edges, no cycles, a single exit with a Boolean output, and every port connected. If any condition fails, the entire batch is rejected. Otherwise, G's definition is written to a separate sealed store that the main database API cannot read.
2. **Attempt**: The agent calls tools and may query G up to c times during an attempt. Each query returns a verdict and the feedback declared in advance.
3. **Restart**: After a rejected submission, the agent restarts with its history retained and its query allowance reset.
4. **Finish**: The task ends when a submission is accepted, the budget is exhausted, or time runs out. The final submission is evaluated again to determine the final result.

For a step-by-step description, see [docs/loop.md](docs/loop.md).

## Main Results

The results below use DeepSeek V4.1 Flash. U is a single response from the same model; F is a run with an attached objective.

<p align="center">
  <img src="paper/current/figs/fig1-vs-published.png" alt="U, published reference results, and F across 20 benchmarks (paper Fig. 1)" width="820">
</p>

<p align="center"><sub><b>Fig. 1</b>　Single-response results (light gray), published reference results (dark gray), and ObjRun (blue) across 20 benchmarks.</sub></p>

See the paper's appendix for all 20 results, budgets, and evaluation protocols.

### Scientific Case Studies

The paper also examines four scientific problems from recent papers. Each had a five-hour time limit, and the results were independently verified by checkers on the host machine. Model calls across the four cases cost a total of $5.62.

| Problem | Reference | Result | Verification |
| --- | --- | --- | --- |
| DNA codes (n = 10, d = 4, GC = 5) | 676 codewords | 1,688 codewords | Two independent integer implementations |
| Low-storage Runge–Kutta (5 stages, order 3, 2N) | Error norm 0.015632 | 0.013967, optimal over the fixed feasible set | Exact rational interval arithmetic |
| Spherical designs (24 unit vectors in R⁶) | Conjecture | 4 nonglobal local minima | Interval arithmetic certificates |
| RNA designability (Repetitious Sequences 8/10) | Upper bound 0.18740 | Upper bound 0.15770 | Envelope enumeration over all assignments |

<p align="center">
  <img src="paper/current/figs/discovery-runs.png" alt="Verification results for the four scientific case studies" width="820">
</p>

Read the [case study blog](https://objrun.imontlaji.workers.dev/blog/) for the process behind each result.

## Quick Start

### Requirements

- [Bun](https://bun.sh). The runtime executes `.ts` files directly, without a compilation step, and uses Bun's built-in `bun:sqlite` for SQLite.
- An API key for at least one model provider.

### Install and Run

```bash
cp .env.example .env
```

Add your keys to `.env`. This file is excluded from version control:

```
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=
```

```bash
cd app
bun install
bun start
```

By default, the service listens on `127.0.0.1:7801`, with API endpoints under `/api` and the built-in interface at `/ui`. If a required key is missing, the program reports an error and identifies it.

Check the service status:

```bash
curl -s http://127.0.0.1:7801/api/health
```

See [examples/](examples/README.md) for declaring an agent, sending your first task, and integrating individual benchmarks.

### Configuration

`config.yaml` is the program's single configuration file. It defines the port, log level, and locations of the main and sealed databases, among other settings. Paths are resolved relative to the directory containing `config.yaml`, regardless of the working directory at startup. Starting the program from any repository subdirectory therefore opens the same database. Values can use `${VAR}` to read environment variables. The code retains the original `TGENGIN_*` environment variable names.

### Packaging

```bash
cd app && bun run build
```

Build outputs go to `dist/`, with a standalone executable for each platform (win-x64, mac-arm64, and mac-x64). The target machine does not need a runtime installed; place `config.yaml` beside the executable. `bun run verify` runs type checking followed by the build.

The project has no native dependencies, so macOS binaries can be cross-compiled from Windows in a single build. New dependencies must likewise be non-native and must not be tied to a specific runtime.

## Project Structure

```
config.yaml          Single configuration file
app/src/
  main.ts            Entry point: configuration, databases, API, handlers, and shutdown
  H2H/               State: databases and external API
  engine/            Main read–process–write loop
  objective/         Objective G; definitions live in the sealed store, outside the main database's reach
  tree/              Attempt tree: child creation, sibling attempts after failure, and backtracking
  llm/               Model integration: chat and duplex modes
  tools/             read / write / edit / glob / grep / bash
  place/             Execution locations: forwarding layer and remote runtime
  ui/                Built-in interface, accessing the engine only through /api
examples/            Runnable examples and benchmark integrations
experiments/         Benchmark sources and experiment record indexes
paper/current/       Paper source, figures, and plotting data
scripts/             Shared runners, maintenance, and record tools
site/                Website, run replays, and case study blog
docs/                Architecture, execution loop, schemas, and reproducibility documentation
test/                Unit, integration and benchmark tests; see test/README.md
```

## Website

Live site: [objrun.imontlaji.workers.dev](https://objrun.imontlaji.workers.dev/)
