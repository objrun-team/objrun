// @bun
// scripts/code-benchmarks/classeval/run.ts
import { createHash } from "crypto";
import { existsSync, mkdirSync as mkdirSync2, readFileSync as readFileSync2, readdirSync, writeFileSync as writeFileSync3, renameSync, unlinkSync, openSync, closeSync, fsyncSync } from "fs";
import { join as join3, resolve as resolve2, dirname } from "path";
import { spawn as spawn2 } from "child_process";
import { createServer } from "http";
import { Database } from "bun:sqlite";

// scripts/code-benchmarks/runtime-snapshot/test/_lib.ts
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { spawn } from "child_process";
var ROOT = join(import.meta.dir, "..");
async function freePort() {
  const s = Bun.serve({ port: 0, fetch: () => new Response("") });
  const p = s.port;
  await s.stop(true);
  if (p === undefined)
    throw new Error("cannot obtain a free port");
  return p;
}
async function machine(llm = {}, options = {}) {
  const dir = options.directory ?? mkdtempSync(join(tmpdir(), "tgengin-example-"));
  const port = await freePort();
  writeFileSync(join(dir, "config.yaml"), [
    `server: { host: 127.0.0.1, port: ${port}, bodyLimit: 1048576, shutdownTimeout: 2000 }`,
    `log: { level: warn }`,
    `db: { file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite,`,
    `      pragmas: { journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000 } }`,
    `api: { prefix: /api, token: , allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100 }`,
    `llm: { ${Object.entries({
      maxTokens: 16384,
      retryTimes: 3,
      continueTimes: 3,
      reasoningEffort: "high",
      temperature: 0,
      seed: 42,
      ...llm
    }).map(([k, v]) => `${k}: ${String(v)}`).join(", ")} }`,
    `cors: { enabled: false, origin: "*" }`,
    ""
  ].join(`
`), "utf8");
  const proc = spawn(process.execPath, [`--env-file=${join(ROOT, ".env")}`, join(ROOT, "app", "src", "main.ts")], { env: { ...process.env, TGENGIN_CONFIG: join(dir, "config.yaml") }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  const enginePid = proc.pid;
  if (enginePid === undefined)
    throw new Error("the test engine did not obtain a process ID");
  let log = "";
  proc.stdout?.on("data", (d) => log += d.toString());
  proc.stderr?.on("data", (d) => log += d.toString());
  const base = `http://127.0.0.1:${port}/api`;
  for (let i = 0;i < 100; i++) {
    try {
      if ((await fetch(`${base}/health`)).ok)
        break;
    } catch {}
    if (i === 99) {
      proc.kill();
      throw new Error(`the engine did not come up. It said:
${log}`);
    }
    await Bun.sleep(100);
  }
  const call = async (method, path, body) => {
    const res = await fetch(base + path, {
      method,
      ...body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
    });
    const text = await res.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      json = text;
    }
    return { res, json };
  };
  return {
    pid: enginePid,
    base,
    directory: dir,
    async api(method, path, body) {
      const { res, json } = await call(method, path, body);
      if (!res.ok)
        throw new Error(`${method} ${path} \u2192 ${res.status}
${JSON.stringify(json, null, 2)}`);
      return json;
    },
    async bad(method, path, body) {
      const { res, json } = await call(method, path, body);
      if (res.ok)
        throw new Error(`${method} ${path} should have been rejected, but returned ${res.status}`);
      return json;
    },
    async stop() {
      if (proc.exitCode === null && proc.signalCode === null) {
        await new Promise((resolve) => {
          const hard = setTimeout(() => {
            proc.kill("SIGKILL");
          }, 3000);
          proc.once("exit", () => {
            clearTimeout(hard);
            resolve();
          });
          proc.kill();
        });
      }
      if (options.keep)
        return;
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {}
    }
  };
}

// scripts/code-benchmarks/runtime-snapshot/app/src/H2H/db.ts
function all(db, sql, params) {
  return db.all(sql, params);
}
// scripts/code-benchmarks/runtime-snapshot/app/src/install/index.ts
var IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
function ident(s, what) {
  if (!IDENT.test(s))
    throw new Error(`illegal ${what}: ${s}`);
  return s;
}
function tableNameOf(pattern, value) {
  const safe = value.replace(/[^A-Za-z0-9_]/g, "_");
  const name = pattern.replace("{}", safe);
  return ident(name, "grown table name");
}

// scripts/code-benchmarks/runtime-snapshot/app/src/msg/deliver.ts
var HUMAN_MARK = "[human] ";
var HUMAN = new Set(["user", "voice"]);
var FROM = {
  user: { kind: "user", role: "user" },
  voice: { kind: "voice", role: "user" },
  world: { kind: "inject", role: "user" },
  skill: { kind: "skill", role: "skill" },
  tool: { kind: "tool", role: "tool" },
  agent: { kind: "prompt", role: "assistant" },
  kernel: { kind: "inject", role: "system" }
};
var HUMAN_KINDS = new Set([...HUMAN].map((b) => FROM[b].kind));
var ROLES = [...new Set(Object.values(FROM).map((f) => f.role))].sort();
var KINDS = [
  ["user", "Written by a person. Prefixed with " + HUMAN_MARK + " on the way out so it stays distinguishable from system injections"],
  ["voice", "Spoken by a person, transcribed from the realtime lane. Its role is also user; only kind tells speech apart from typing"],
  ["inject", "Injected by the system. Also goes out as role=user; only kind tells it apart"],
  ["skill", "A prompt placed by a skill"],
  ["tool", "A tool result"],
  ["prompt", "What the model itself said"],
  ["call", "The model requesting tools; the calls ride in body. Something still has to run these"],
  [
    "graded",
    "A call the system wrote down after the fact, not one the model asked for - an outside judgement, shaped like a call so the model can read it. Nothing runs these: they arrive with their result already attached"
  ],
  ["intervene", "A mark left by a user intervening while it runs"]
];

// scripts/code-benchmarks/runtime-snapshot/app/src/objective/store.ts
var CANDIDATE = {
  type: "object",
  properties: {
    answer: {
      type: "string",
      description: "The answer, verbatim (keep the \\boxed{} if the task asks for one). This exact text is what gets " + "graded, not your derivation."
    }
  },
  required: ["answer"]
};

// scripts/code-benchmarks/runtime-snapshot/app/src/tree/dfs.ts
var DEAD = new Set(["dead_failed", "dead_below_bar"]);
var SUBMIT = "submit";
var SUBMIT_TOOL = {
  name: SUBMIT,
  does: "Hand the work in: the answer passed here is what gets graded, exactly as written. Text that is not " + "passed here is not read as an answer.",
  params: CANDIDATE,
  output: { type: "object", properties: { handingIn: { type: "boolean" } } },
  prompt: "At the hand-in step no other tool is attached. The hand-in step is reached on its own once the working " + "budget runs out.",
  expectMs: 1e4
};

// scripts/code-benchmarks/runtime-snapshot/app/src/objective/candidate.ts
function finalCandidate(db, task) {
  const row = all(db, "select mode,created_at,solve_seconds from task where id = ?", [task])[0];
  if (!row?.mode)
    return;
  const limit = Number(row.solve_seconds);
  const deadline = Number.isFinite(limit) && limit > 0 ? Number(row.created_at) + limit * 1000 : Number.MAX_SAFE_INTEGER;
  const sub = tableNameOf("task_{}", String(row.mode));
  const units = all(db, `select agent,instance,unit from "${sub}" where task = ? order by unit desc`, [task]);
  for (const unit of units) {
    const messages = tableNameOf("agent_{}_msg", String(unit.agent));
    const calls = all(db, `select body from "${messages}" where instance = ? and unit = ? and kind = 'call' and at <= ? order by seq desc`, [unit.instance, unit.unit, deadline]);
    for (const call of calls) {
      try {
        const payload = JSON.parse(String(call.body));
        for (const item of [...payload.calls ?? []].reverse()) {
          if (item.name === SUBMIT)
            return { body: typeof item.input?.answer === "string" ? item.input.answer : "", how: "submitted" };
        }
      } catch {}
    }
  }
  if (all(db, "select 1 from cycle where mode = ? and cycle = ? limit 1", [row.mode, SUBMIT]).length)
    return;
  for (const unit of units) {
    const messages = tableNameOf("agent_{}_msg", String(unit.agent));
    const prompts = all(db, `select body from "${messages}" where instance = ? and unit = ? and kind = 'prompt' and at <= ? order by seq desc`, [unit.instance, unit.unit, deadline]);
    const said = prompts.find((message) => String(message.body ?? "").trim());
    if (said)
      return { body: String(said.body), how: "last words" };
  }
  return;
}

// scripts/code-benchmarks/runtime-snapshot/scripts/repair-2026-10-10/full-f/shared/digitalocean-provider.ts
import { readFileSync, mkdirSync, writeFileSync as writeFileSync2 } from "fs";
import { join as join2, resolve } from "path";
var BENCHMARK_PROVIDER = Object.freeze({
  kind: "openrouter-deepseek",
  model: "deepseek/deepseek-v4.1-flash",
  canonicalModel: "deepseek/deepseek-v4.1-flash-20260910",
  baseURL: "https://openrouter.ai/api/v1",
  endpoint: "https://openrouter.ai/api/v1/chat/completions",
  keyEnv: "OPENROUTER_API_KEY",
  currency: "USD",
  providerName: "DigitalOcean",
  providerSlug: "digitalocean",
  peakRates: Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 }),
  routing: Object.freeze({ only: ["digitalocean"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } }),
  forcedToolMode: "constrained-auto"
});
function benchmarkProviderKey(root) {
  const supplied = process.env.OPENROUTER_API_KEY?.trim();
  if (supplied)
    return supplied;
  for (const path of [join2(root, ".env")]) {
    let text;
    try {
      text = readFileSync(path, "utf8").replace(/^\uFEFF/, "");
    } catch {
      continue;
    }
    for (const line of text.split(/\r?\n/)) {
      const match = line.match(/^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$/);
      if (!match)
        continue;
      const value = match[1].replace(/^(['"])(.*)\1$/, "$2").trim();
      if (value)
        return value;
    }
  }
  throw new Error("OPENROUTER_API_KEY is missing in the process environment or the inner TgEngin/.env");
}
function officialOpenRouterFault(data, expectedProvider = BENCHMARK_PROVIDER.providerName) {
  if (data?.provider !== expectedProvider)
    return "UnexpectedOpenRouterProvider";
  if (![BENCHMARK_PROVIDER.model, BENCHMARK_PROVIDER.canonicalModel].includes(data?.model))
    return "UnexpectedOpenRouterModel";
  if (typeof data?.id !== "string" || !data.id)
    return "MissingOpenRouterGenerationId";
  const cost = data?.usage?.cost;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0)
    return "MissingOrInvalidOpenRouterUsdCost";
}

// scripts/code-benchmarks/runtime-snapshot/scripts/repair-2026-10-10/full-f/shared/digitalocean-inference.ts
var BENCHMARK_INFERENCE = Object.freeze({
  maxTokens: 16384,
  reasoningEffort: "high",
  temperature: 0,
  seed: 42,
  retryTimes: 3,
  continueTimes: 3
});
function benchmarkProviderRequest(body, profile = BENCHMARK_INFERENCE, provider) {
  const choice = body.tool_choice;
  const forced = choice === "required" || choice?.type === "function" && typeof choice.function?.name === "string";
  const effort = provider ? profile.reasoningEffort : forced ? "none" : profile.reasoningEffort;
  const thinking = forced ? "disabled" : "enabled";
  const limits = [body.max_tokens, body.max_completion_tokens].filter((value) => value !== undefined && value !== null);
  if (body.temperature !== profile.temperature || body.seed !== profile.seed && !(provider && body.seed === undefined) || body.reasoning_effort !== effort || !limits.length || limits.some((value) => value !== profile.maxTokens) || body.thinking !== undefined && body.thinking?.type !== (provider ? "enabled" : thinking)) {
    throw new Error("Wire parameters differ from the benchmark inference profile");
  }
  const wire = { ...body, thinking: { type: thinking }, max_tokens: profile.maxTokens };
  delete wire.max_completion_tokens;
  if (provider) {
    if (body.model !== provider.model || profile.reasoningEffort !== "high")
      throw Error("OpenRouter V4.1 Flash high-thinking profile required");
    if (forced) {
      const name = choice?.function?.name;
      if (typeof name !== "string")
        throw Error("Constrained auto submission requires a named tool");
      wire.tools = (body.tools ?? []).filter((tool) => tool.type === "function" && tool.function?.name === name);
      if (wire.tools.length !== 1)
        throw Error("The required submit tool is absent or duplicated");
      wire.tool_choice = "auto";
    }
    wire.provider = { ...BENCHMARK_PROVIDER.routing };
    wire.reasoning = { enabled: true, effort: "high", exclude: false };
    delete wire.thinking;
    delete wire.reasoning_effort;
    delete wire.seed;
  }
  return wire;
}

// scripts/code-benchmarks/classeval/interface-policy.ts
function requestTimeoutMs(deadline, now) {
  const remaining = deadline === undefined ? 600000 : Math.floor(deadline - now);
  if (remaining <= 0)
    throw Error("ProviderSolveDeadlineReached");
  return Math.min(600000, remaining);
}
function canaryReady(arm, records) {
  const record = records.find((r) => r.arm === arm);
  return !!record?.grade?.valid && (arm === "baseline" || record.candidateHow === "submitted");
}
function retainedTaskAttempts(previous) {
  return previous?.taskAttempts ?? 0;
}

// scripts/code-benchmarks/classeval/task-slots.ts
class TaskSlots {
  limit;
  used = 0;
  waiting = [];
  constructor(limit) {
    this.limit = limit;
    if (!Number.isInteger(limit) || limit < 1)
      throw Error("InvalidTaskConcurrency");
  }
  async run(job) {
    if (this.used >= this.limit)
      await new Promise((resolve2) => this.waiting.push(resolve2));
    else
      this.used++;
    try {
      return await job();
    } finally {
      const next = this.waiting.shift();
      if (next)
        next();
      else
        this.used--;
    }
  }
}

// scripts/code-benchmarks/classeval/wire-provider.ts
function withProviderRoute(wire, route) {
  if (typeof route?.providerName !== "string" || typeof route?.providerSlug !== "string" || route.routing?.allow_fallbacks !== false || JSON.stringify(route.routing.only) !== JSON.stringify([route.providerSlug]))
    throw Error("InvalidPinnedProviderRoute");
  if (route.model && route.model !== wire.model)
    throw Error("ProviderModelChanged");
  return { ...wire, provider: { ...route.routing } };
}

// scripts/code-benchmarks/classeval/run.ts
var SRC = import.meta.dir;
var ROOT2 = resolve2(SRC, "../../..");
var OUT = join3(ROOT2, "docs/newbench-20261014/classeval");
var read = (p) => JSON.parse(readFileSync2(p, "utf8").replace(/^\uFEFF/, ""));
var cfg = read(join3(SRC, "experiment.json"));
var catalog = read(join3(SRC, "public-tasks.json"));
var OBJRUN_PROVIDER = cfg.objrunProvider ?? BENCHMARK_PROVIDER;
var CONCURRENCY = Number(cfg.concurrency ?? cfg.initialConcurrency);
var taskSlots = new TaskSlots(CONCURRENCY);
var hash = (x) => createHash("sha256").update(x).digest("hex");
function save(p, v) {
  mkdirSync2(dirname(p), { recursive: true });
  const tmp = p + "." + process.pid + ".tmp";
  writeFileSync3(tmp, JSON.stringify(v, null, 2) + `
`);
  renameSync(tmp, p);
}
function durable(p, v) {
  mkdirSync2(dirname(p), { recursive: true });
  const fd = openSync(p, "wx");
  try {
    writeFileSync3(fd, JSON.stringify(v, null, 2) + `
`);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}
function walk(d) {
  return existsSync(d) ? readdirSync(d, { withFileTypes: true }).flatMap((x) => x.isDirectory() ? walk(join3(d, x.name)) : [join3(d, x.name)]) : [];
}
function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
function pins() {
  const files = [...walk(SRC).filter((p) => /\.(ts|py|json|ps1)$/.test(p) && !p.includes("source-pins.json") && !p.includes("__pycache__")), ...walk(join3(SRC, "../runtime-snapshot/app/src")).filter((p) => p.endsWith(".ts")), join3(SRC, "../runtime-snapshot/test/_lib.ts"), ...walk(join3(SRC, "../runtime-snapshot/scripts")).filter((p) => p.endsWith(".ts")), join3(SRC, "../runtime-snapshot/app/bun.lock"), join3(SRC, "../runtime-snapshot/app/package.json")];
  return [...new Set(files)].filter(existsSync).map((p) => ({ path: resolve2(p), sha256: hash(readFileSync2(p)) }));
}
var command = process.argv[2] ?? "run";
mkdirSync2(OUT, { recursive: true });
if (command === "pin") {
  save(join3(OUT, "source-pins.json"), { atUtc: new Date().toISOString(), files: pins() });
  console.log("Pinned ClassEval sources");
  process.exit(0);
}
function frozen() {
  const audit = read(join3(SRC, "catalog-audit.json"));
  if (catalog.length !== 100 || hash(readFileSync2(join3(SRC, "public-tasks.json"))) !== audit.publicCatalogSha256)
    throw Error("PublicCatalogChanged");
  for (const p of read(join3(OUT, "source-pins.json")).files)
    if (hash(readFileSync2(p.path)) !== p.sha256)
      throw Error("SourceChanged:" + p.path);
  if (cfg.model !== BENCHMARK_PROVIDER.model || cfg.provider !== BENCHMARK_PROVIDER.providerName || cfg.maxTokens !== 16384 || cfg.checks !== 5 || cfg.solveSeconds !== 600 || cfg.cyclesMaxUnits !== 12 || cfg.maxBranches !== 4)
    throw Error("ExperimentProfileChanged");
}
var key = benchmarkProviderKey(ROOT2);
process.env.OPENROUTER_API_KEY = key;
function allowedTaskAttempts(arm, taskId) {
  const policyPath = join3(OUT, "interface-recovery.json"), probePath = join3(OUT, "tool-probe-latest.json");
  if (arm !== "objrun" || taskId !== "ClassEval_0" || !existsSync(policyPath) || !existsSync(probePath))
    return 2;
  const policy = read(policyPath), probe = read(probePath);
  if (![3, 4].includes(policy.maxTaskAttempts) || policy.taskId !== taskId || !probe.healthy || probe.generationId !== policy.healthProbeGenerationId || probe.provider !== OBJRUN_PROVIDER.providerName || probe.model !== cfg.model)
    throw Error("InvalidBoundedInterfaceRecoveryPolicy");
  return policy.maxTaskAttempts;
}
var lock = join3(OUT, "runner-lock.json");
if (existsSync(lock)) {
  const prior = read(lock);
  if (alive(prior.pid))
    throw Error("RunnerAlreadyLive:" + prior.pid);
  renameSync(lock, lock + ".closed-" + Date.now());
}
for (const p of walk(join3(OUT, "tasks")).filter((p2) => p2.endsWith("engine-process.json"))) {
  const prior = read(p);
  if (alive(prior.pid) && !existsSync(join3(dirname(p), "engine-stopped.json")))
    throw Error("PriorEngineStillLive:" + prior.pid);
}
durable(lock, { pid: process.pid, atUtc: new Date().toISOString(), command: process.argv });
var originPath = join3(OUT, "experiment-origin.json");
if (!existsSync(originPath))
  durable(originPath, { atUtc: new Date().toISOString(), experiment: cfg, catalogSha256: hash(readFileSync2(join3(SRC, "public-tasks.json"))) });
var stage = "preflight";
var fatal;
var attention = false;
var stopped = false;
var active = [];
var grader = "";
var graderPid;
var records = () => walk(join3(OUT, "results")).filter((p) => p.endsWith(".json")).map(read);
var receipts = () => walk(join3(OUT, "calls")).filter((p) => p.endsWith("/receipt.json") || p.endsWith("\\receipt.json")).map(read);
function costs() {
  const rr = receipts(), unresolved = walk(join3(OUT, "calls")).filter((p) => p.endsWith("dispatch.json") && !existsSync(join3(dirname(p), "receipt.json"))).map(read);
  return { modelCalls: rr.length + unresolved.length, actualCostUsd: rr.reduce((n, r) => n + (r.actualCostUsd ?? 0), 0), unknownCostCount: rr.filter((r) => r.unknownCost).length + unresolved.length, unknownCostUpperBoundUsd: rr.filter((r) => r.unknownCost).reduce((n, r) => n + r.upperBoundUsd, 0) + unresolved.reduce((n, r) => n + r.upperBoundUsd, 0), unresolvedDispatchCount: unresolved.length, successfulModelResponses: rr.filter((r) => r.httpStatus === 200 && !r.fault).length };
}
function status() {
  const rr = records(), arms = Object.fromEntries(cfg.arms.map((arm) => {
    const x = rr.filter((r) => r.arm === arm), valid = x.filter((r) => r.grade?.valid);
    return [arm, { total: 100, completed: x.length, valid: valid.length, passed: valid.filter((r) => r.grade.passed).length, exceptions: x.filter((r) => !r.grade?.valid).length, passRateCompleted: valid.length ? valid.filter((r) => r.grade.passed).length / valid.length : null }];
  }));
  save(join3(OUT, "status.json"), { dataset: "classeval", stage, pid: process.pid, graderPid, grader, atUtc: new Date().toISOString(), startedAtUtc: read(originPath).atUtc, active, arms, ...costs(), fatal, attention, protocol: "baseline single model attempt; objrun native machine with official-test feedback", sourceCommit: "90825141e640418ae6dc8257397345ee3ac36cbc", concurrency: CONCURRENCY, baselineProvider: cfg.provider, objrunProvider: OBJRUN_PROVIDER.providerName, providerFallbacks: false, perTaskDollarCap: null, monetaryStopPolicy: "Only actual account/API key availability; no task dollar cap" });
}
function shouldStop() {
  if (existsSync(join3(OUT, "stop-after-current-tasks.json")))
    stopped = true;
  return stopped;
}
function updateRunning() {
  writeFileSync3(join3(OUT, "RUNNING.md"), `# ClassEval 2026-10-14

Stage: ${stage}. Runner PID: ${process.pid}. Grader PID: ${graderPid ?? "starting"}. Total shared task concurrency: ${CONCURRENCY}; grader concurrency: ${cfg.graderConcurrency ?? 2}. User requested concurrency 8 on 2026-10-14.

Entry: scripts/code-benchmarks/classeval/start.ps1 (resume safely with the same command).
Status: docs/newbench-20261014/classeval/status.json.

Baseline: one successful model response per task, no test feedback before final grading. ObjRun: the frozen native machine, declare/tasks/submit/verify/finalCandidate, c5 / 600 seconds / 12 units / 4 branches. ObjRun receives clipped official-test statistics; this is a test-feedback protocol and differs from standard single-attempt evaluation.

Model: ${cfg.model}; OpenRouter baseline provider: ${cfg.provider}; ObjRun provider: ${OBJRUN_PROVIDER.providerName}; reasoning: enabled/high; temperature: 0; max_tokens: 16384; fallbacks: false. Official ClassEval v1.0.0 commit 90825141e640418ae6dc8257397345ee3ac36cbc; 100 fixed tasks per arm. Imports are supplied from import_statement. No tests or reference code are included in real model context.

Canary: ClassEval_0 in each arm. A valid baseline canary permits baseline to continue independently; ObjRun continues after its canary has a valid grade and a native submitted final candidate. API failures are isolated to the affected arm. Valid canary results count toward the 100 and are not rerun.

Results/candidates: results/ and tasks/. Raw key-free requests/responses and cost receipts: calls/. Scoring cache/logs: grader/. Account/key observations: observations/. Source pins: source-pins.json.

Containers: existing pinned image, org.objrun.owner=newbench-20261014, 2 CPU / 2 GiB, non-root, no network, read-only root and private temporary directories. Only created containers are deleted. Model keys remain in local process environment.

User requirement (2026-10-14): no per-task dollar budget or spending cap. A task's accumulated cost never stops it, reduces its 16k output allowance, or truncates retries. Only account/API key availability can stop further spending; existing non-monetary limits and finite interface retries remain. No account/key limits are changed.

Finite API retries and one task recovery are retained with all charges/unknown costs. ClassEval_0 has three retained failed DigitalOcean attempts. The user then explicitly authorized trying another supplier on 2026-10-14; a successful Fireworks tool probe permits one native Fireworks canary, for a strict maximum of four task attempts in interface-recovery.json. ObjRun is pinned to Fireworks with no automatic fallback; baseline remains DigitalOcean and its 100 valid results are retained. This provider difference must be reported in any comparison. Additional attempts are not unlimited. All retries and request timeouts in an ObjRun attempt are bounded by that native task's 600-second solve deadline. Valid results never rerun; recovered candidates are regraded without generation. Exceptions do not count as wrong answers. A stop-after-current-tasks.json file requests a checkpoint. Insufficient credits stop further dispatch; no top-up, key-limit change, provider switch, or duplicate automation is performed.

${fatal ? "Attention: " + fatal + `
` : ""}`, "utf8");
}
var balance;
async function observation() {
  const dir = join3(OUT, "observations", String(Date.now()));
  mkdirSync2(dir, { recursive: true });
  const get = async (url) => {
    for (let n = 0;n < 3; n++) {
      try {
        const r = await fetch(url, { headers: { authorization: "Bearer " + key }, proxy: cfg.localProxy, signal: AbortSignal.timeout(30000) });
        const v = await r.json();
        if (!r.ok)
          throw Error("ObservationHttp:" + r.status);
        return v;
      } catch (e) {
        if (n === 2)
          throw e;
        await Bun.sleep(500 * (n + 1));
      }
    }
  };
  const credit = await get(BENCHMARK_PROVIDER.baseURL + "/credits"), k = await get(BENCHMARK_PROVIDER.baseURL + "/key");
  if (!Number.isFinite(credit.data?.total_credits) || !Number.isFinite(credit.data?.total_usage))
    throw Error("InvalidCreditObservation");
  const accountRemainingUsd = credit.data.total_credits - credit.data.total_usage;
  const keyRemainingUsd = k.data?.limit_remaining ?? (typeof k.data?.limit === "number" ? k.data.limit - (k.data.usage ?? 0) : null);
  balance = { atUtc: new Date().toISOString(), accountRemainingUsd, keyRemainingUsd, remainingUsd: Math.min(accountRemainingUsd, keyRemainingUsd ?? Infinity), rateLimit: k.data?.rate_limit ?? null, readOnly: true };
  save(join3(dir, "balance.json"), balance);
  save(join3(OUT, "balance-latest.json"), balance);
  if (!Number.isFinite(balance.remainingUsd) || balance.remainingUsd < 0)
    throw Error("InvalidAvailableBalance");
  if (!existsSync(join3(OUT, "prices.json"))) {
    const data = await get(BENCHMARK_PROVIDER.baseURL + "/models/" + cfg.model + "/endpoints");
    const endpoint = data.data?.endpoints?.find((e) => e.provider_name === cfg.provider && e.tag === cfg.providerSlug);
    if (!endpoint)
      throw Error("PinnedProviderEndpointUnavailable");
    save(join3(dir, "endpoints.json"), data);
    const prices = [endpoint.pricing, ...endpoint.pricing.overrides ?? []], rates = { input: Math.max(...prices.map((p) => Number(p.prompt ?? endpoint.pricing.prompt))) * 1e6, output: Math.max(...prices.map((p) => Number(p.completion ?? endpoint.pricing.completion))) * 1e6 };
    if (!Number.isFinite(rates.input) || !Number.isFinite(rates.output) || rates.input > 0.3 + 0.000000000001 || rates.output > 1.2 + 0.000000000001)
      throw Error("ProviderTariffExceedsPinnedCeiling");
    save(join3(OUT, "prices.json"), { atUtc: new Date().toISOString(), model: cfg.model, provider: cfg.provider, rates, source: "https://openrouter.ai/api/v1/models/" + cfg.model + "/endpoints" });
  }
  return balance;
}
function estimate() {
  const r = records();
  const byArm = Object.fromEntries(cfg.arms.map((arm) => {
    const x = r.filter((v) => v.arm === arm && v.grade?.valid), pending = 100 - x.length;
    const mean = x.length ? x.reduce((n, v) => n + v.actualCostUsd, 0) / x.length : null;
    return [arm, { valid: x.length, pending, meanObservedUsd: mean, estimatedRemainingUsd: mean === null ? null : pending * mean * 1.5 }];
  }));
  const values = Object.values(byArm);
  save(join3(OUT, "cost-estimate.json"), { atUtc: new Date().toISOString(), byArm, estimatedRemainingUsd: values.every((x) => x.estimatedRemainingUsd !== null) ? values.reduce((n, x) => n + x.estimatedRemainingUsd, 0) : null, safetyMultiplier: 1.5, balance, unknownCosts: costs().unknownCostUpperBoundUsd, estimateOnly: true });
  return byArm;
}
var reservedUsd = 0;
var spentSinceObservation = 0;
async function model(dir, body, deadline, provider = BENCHMARK_PROVIDER) {
  const wire = withProviderRoute(benchmarkProviderRequest({ ...body, model: cfg.model, stream: false, temperature: 0, reasoning_effort: "high", max_tokens: 16384 }, BENCHMARK_INFERENCE, BENCHMARK_PROVIDER), provider);
  const closeSchema = (v) => {
    if (!v || typeof v !== "object")
      return v;
    if (Array.isArray(v))
      return v.map(closeSchema);
    const r = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, closeSchema(x)]));
    if (r.type === "object")
      r.additionalProperties = false;
    return r;
  };
  if (wire.tools)
    wire.tools = wire.tools.map((t) => ({ ...t, function: { ...t.function, parameters: closeSchema(t.function.parameters) } }));
  const rawReq = JSON.stringify(wire), upperBoundUsd = (Buffer.byteLength(rawReq) * provider.peakRates.input + 16384 * provider.peakRates.output) / 1e6;
  for (let n = 0;n < 3; n++) {
    const d = join3(dir, "attempt-" + n), receiptPath = join3(d, "receipt.json");
    let receipt, raw;
    if (existsSync(receiptPath)) {
      receipt = read(receiptPath);
      if (receipt.requestSha256 !== hash(rawReq))
        throw Error("SavedRequestMismatch");
      raw = existsSync(join3(d, "response.json")) ? readFileSync2(join3(d, "response.json"), "utf8") : "";
    } else {
      if (existsSync(join3(d, "dispatch.json")))
        throw Error("UnresolvedPriorDispatch:" + d);
      frozen();
      if (stopped)
        throw Error("StoppedBeforeDispatch");
      const timeoutMs = requestTimeoutMs(deadline, Date.now());
      if (balance.remainingUsd - spentSinceObservation - reservedUsd < upperBoundUsd + 0.01) {
        stopped = true;
        fatal = "InsufficientBalance";
        throw Error(fatal);
      }
      reservedUsd += upperBoundUsd;
      durable(join3(d, "request.json"), wire);
      durable(join3(d, "dispatch.json"), { atUtc: new Date().toISOString(), pid: process.pid, requestSha256: hash(rawReq), upperBoundUsd });
      const begin = Date.now();
      let status2 = 0, v, transportError;
      raw = "";
      try {
        const response = await fetch(BENCHMARK_PROVIDER.endpoint, { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + key, "X-OpenRouter-Title": "ObjRun ClassEval 20261014" }, body: rawReq, signal: AbortSignal.timeout(timeoutMs), proxy: cfg.localProxy });
        status2 = response.status;
        raw = await response.text();
        writeFileSync3(join3(d, "response.json"), raw, { flag: "wx" });
        try {
          v = JSON.parse(raw);
        } catch {
          v = {};
        }
      } catch (e) {
        transportError = String(e);
        v = {};
      }
      const actualCostUsd = typeof v?.usage?.cost === "number" && Number.isFinite(v.usage.cost) && v.usage.cost >= 0 ? v.usage.cost : null;
      const explicitlyRejected = status2 !== 200 && !v.id && !v.usage && [400, 401, 402, 403, 404, 429].includes(status2);
      const fault = transportError ?? v.error?.message ?? (status2 === 200 ? officialOpenRouterFault(v, provider.providerName) : "ProviderHttp:" + status2);
      receipt = { atUtc: new Date().toISOString(), requestSha256: hash(rawReq), responseSha256: raw ? hash(raw) : null, httpStatus: status2, generationId: v.id ?? null, model: v.model ?? null, provider: v.provider ?? null, usage: v.usage ?? null, actualCostUsd: explicitlyRejected ? 0 : actualCostUsd, upperBoundUsd: explicitlyRejected ? 0 : upperBoundUsd, unknownCost: !explicitlyRejected && actualCostUsd === null, fault, seconds: (Date.now() - begin) / 1000, requestedProviderName: provider.providerName, requestedProviderSlug: provider.providerSlug, officialCatalogQuantization: provider.quantization ?? "unknown" };
      durable(receiptPath, receipt);
      reservedUsd -= upperBoundUsd;
      spentSinceObservation += receipt.actualCostUsd ?? receipt.upperBoundUsd;
      console.log(JSON.stringify({ event: "model_receipt", atUtc: receipt.atUtc, generationId: receipt.generationId, status: status2, provider: receipt.provider, cost: receipt.actualCostUsd, fault }));
      statusUpdate();
    }
    if (receipt.httpStatus === 402) {
      stopped = true;
      fatal = "ProviderInsufficientCredits";
      throw Error(fatal);
    }
    const accepted = !receipt.fault || receipt.fault === "MissingOrInvalidOpenRouterUsdCost";
    if (receipt.httpStatus === 200 && accepted && JSON.parse(raw).choices?.length)
      return { raw, status: 200, receipt };
    const retryable = receipt.httpStatus === 0 || receipt.httpStatus === 429 || receipt.httpStatus >= 500 || /timeout|timed out|temporar|overload/i.test(receipt.fault ?? "");
    if (!retryable || n === 2)
      throw Error("ProviderFault:" + receipt.fault);
    await Bun.sleep(1000 * (n + 1));
  }
  throw Error("FiniteApiRetriesExhausted");
}
var statusUpdate = () => status();
async function grade(tid, answer) {
  for (let n = 0;n < 3; n++) {
    try {
      const r = await fetch(grader + "/grade", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ task_id: tid, code: answer }), signal: AbortSignal.timeout(180000) });
      const v = await r.json();
      if (v.valid || n === 2)
        return v;
    } catch (e) {
      if (n === 2)
        return { valid: false, passed: false, errorType: "GraderTransport", diagnostic: String(e) };
    }
    await Bun.sleep(1000 * (n + 1));
  }
}
async function startGrader() {
  mkdirSync2(join3(OUT, "grader"), { recursive: true });
  const prior = existsSync(join3(OUT, "grader/process.json")) ? read(join3(OUT, "grader/process.json")) : undefined;
  const port = prior?.base ? new URL(prior.base).port : "0";
  const proc = spawn2("python", ["-u", join3(SRC, "grader_service.py"), "--port", port, "--output", join3(OUT, "grader"), "--runner-pid", String(process.pid)], { cwd: ROOT2, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  let log = "";
  proc.stderr.on("data", (d) => {
    log += d;
    writeFileSync3(join3(OUT, "grader/stderr.log"), log);
  });
  const ready = await new Promise((accept, reject) => {
    let buf = "";
    const timer = setTimeout(() => reject(Error("GraderStartupTimeout:" + log)), 30000);
    proc.stdout.on("data", (d) => {
      buf += d;
      writeFileSync3(join3(OUT, "grader/stdout.log"), buf);
      if (buf.includes(`
`)) {
        try {
          const v = JSON.parse(buf.split(`
`)[0]);
          clearTimeout(timer);
          accept(v);
        } catch (e) {
          reject(e);
        }
      }
    });
    proc.once("exit", (code) => {
      clearTimeout(timer);
      reject(Error("GraderExit:" + code + ":" + log));
    });
  });
  grader = "http://127.0.0.1:" + ready.port;
  graderPid = proc.pid;
  save(join3(OUT, "grader/process.json"), { pid: graderPid, runnerPid: process.pid, base: grader, atUtc: new Date().toISOString() });
  return async () => {
    if (proc.exitCode === null && proc.signalCode === null) {
      await new Promise((accept) => {
        proc.once("exit", () => accept());
        proc.kill();
      });
    }
  };
}
async function native(task, dir, callRoot, mockCode) {
  const engineDir = join3(dir, "engine");
  mkdirSync2(engineDir, { recursive: true });
  let engine, interfaceError, pending = 0, counter = 0;
  let deadline;
  const events = [];
  const proxy = createServer(async (req, res) => {
    pending++;
    try {
      const chunks = [];
      for await (const chunk of req)
        chunks.push(Buffer.from(chunk));
      const body = JSON.parse(Buffer.concat(chunks).toString());
      const invoke = async (request, protocolAttempt) => {
        const digest = hash(JSON.stringify(request));
        let r2;
        if (mockCode !== undefined) {
          const handIn2 = request.tools?.length === 1 && request.tools[0].function.name === "submit";
          const tool = handIn2 || counter++ > 0 ? "submit" : "verify";
          r2 = { status: 200, receipt: { mock: true }, raw: JSON.stringify({ id: "control-" + Date.now(), object: "chat.completion", choices: [{ index: 0, finish_reason: "tool_calls", message: { role: "assistant", content: null, tool_calls: [{ id: "control-call-" + Date.now(), type: "function", function: { name: tool, arguments: JSON.stringify({ answer: mockCode }) } }] } }], usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 } }) };
        } else
          r2 = await model(join3(callRoot, digest), request, deadline, OBJRUN_PROVIDER);
        events.push({ atUtc: new Date().toISOString(), protocolAttempt, requestSha256: digest, generationId: r2.receipt.generationId ?? null, mock: mockCode !== undefined });
        save(join3(dir, "submit-response-attempts.json"), events);
        return r2;
      };
      let r = await invoke(body, 0);
      const handIn = body.tools?.length === 1 && body.tools[0]?.function?.name === "submit";
      if (mockCode === undefined && handIn && r.status === 200) {
        const v = JSON.parse(r.raw), choice = v.choices?.[0], calls = choice?.message?.tool_calls ?? [];
        if (choice?.finish_reason !== "length" && !(calls.length === 1 && calls[0]?.function?.name === "submit"))
          r = await invoke({ ...body, messages: [...body.messages ?? [], { role: "user", content: "Your preceding response did not invoke submit and was not handed in. Invoke the available submit tool exactly once with the complete Python code in its answer argument. Earlier verify or plain text does not complete this hand-in." }] }, 1);
      }
      res.writeHead(r.status, { "content-type": "application/json" });
      res.end(r.raw);
    } catch (e) {
      interfaceError = String(e);
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: { message: String(e) } }));
    } finally {
      pending--;
    }
  });
  proxy.requestTimeout = 0;
  proxy.timeout = 0;
  await new Promise((accept) => proxy.listen(0, "127.0.0.1", () => accept()));
  const port = proxy.address().port;
  const id = "classeval-20261014/" + (mockCode !== undefined ? "control" : "objrun") + "/" + task.officialId;
  try {
    engine = await machine({ ...BENCHMARK_INFERENCE, retryTimes: 0, continueTimes: 3 }, { directory: engineDir, keep: true });
    save(join3(dir, "engine-process.json"), { pid: engine.pid, base: engine.base, runnerPid: process.pid, atUtc: new Date().toISOString() });
    const nodes = [{ name: "parsed", domain: "bool", moment: "done", handle: grader + "/parsed" }, { name: "correct", domain: "bool", moment: "done", handle: grader + "/correct" }];
    await engine.api("POST", "/declare", { handles: nodes.map((n) => ({ name: n.handle, expectMs: 180000 })), places: [{ place: "local" }], modes: [{ mode: "repair", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 12, from: [], next: ["act"], infer: "fn:infer.dfs" }, { cycle: "act", maxUnits: 12, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" }] }], agents: [{ name: "bot", apis: [["OPENROUTER_API_KEY", cfg.model]], unit: "fn:unit.tools" }] });
    await engine.api("POST", "/exec", { sql: "update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')" });
    await engine.api("POST", "/exec", { sql: "update api set base_url=:endpoint,retry_on='[]' where key_env=:key and model=:model", params: { endpoint: "http://127.0.0.1:" + port + "/v1", key: "OPENROUTER_API_KEY", model: cfg.model } });
    const exists = await engine.api("POST", "/query", { sql: "select * from task where id=:id", params: { id } });
    if (mockCode === undefined)
      deadline = exists.rows.length ? Number(exists.rows[0].created_at) + cfg.solveSeconds * 1000 : Date.now() + cfg.solveSeconds * 1000;
    if (!exists.rows.length)
      await engine.api("POST", "/tasks", { id, run: "classeval-20261014", mode: "repair", agent: "bot", place: "local", source: "user", description: task.prompt + `
Use submit to hand in your complete Python implementation. verify returns clipped official-test status, error types and test-group statistics. No filesystem or search tools are available.`, objective: { nodes, edges: [{ src: "parsed", out: 0, dst: "correct" }], sink: "correct", checks: 5, reuse: "text" }, readable: false, solveSeconds: 600, maxBranches: 4, maxDeadSiblings: 1e5, noSearch: ["all"] });
    const begin = Date.now();
    let t, why;
    while (Date.now() - begin < 1260000) {
      if (interfaceError)
        throw Error(interfaceError);
      t = await engine.api("GET", "/tasks/" + encodeURIComponent(id) + "/status");
      why = await engine.api("GET", "/tasks/" + encodeURIComponent(id) + "/why");
      if (interfaceError)
        throw Error(interfaceError);
      if (pending === 0 && (why.problems ?? []).some((p) => /kernel threw while advancing/i.test(String(p)) && /timed out|fetch failed|closed/i.test(String(p)))) {
        save(join3(dir, "native-interface-evidence.json"), { status: t, why });
        throw Error("NativeInterfaceTimeout");
      }
      if (JSON.stringify(why.problems).includes("The required submit tool was not called exactly once")) {
        save(join3(dir, "native-interface-evidence.json"), { status: t, why });
        break;
      }
      if (["done", "failed"].includes(t.state) && t.result && !["finalization_pending", "finalization_error"].includes(JSON.parse(t.result).outcome))
        break;
      await Bun.sleep(1000);
    }
    const trace = await engine.api("POST", "/query", { sql: "select * from agent_bot_msg order by instance,unit,seq limit 100000" });
    save(join3(dir, "trace.json"), trace.rows);
    const state = await engine.api("POST", "/query", { sql: "select * from task where id=:id", params: { id } });
    save(join3(dir, "native-task.json"), state.rows[0]);
    const db = new Database(join3(engineDir, "data/h2h.sqlite"), { readonly: true });
    let candidate;
    try {
      candidate = finalCandidate({ all: (sql, params = []) => {
        const q = db.prepare(sql);
        try {
          return q.all(...params);
        } finally {
          q.finalize();
        }
      }, run() {
        throw Error("readonly");
      }, exec() {
        throw Error("readonly");
      }, close() {} }, id);
    } finally {
      db.close();
    }
    if (!t?.result && !candidate && !JSON.stringify(why?.problems).includes("The required submit tool"))
      throw Error("NativeDeadlineWithoutFinalization");
    const nativeVerdict = t?.result ? JSON.parse(t.result) : null;
    if (nativeVerdict?.valid === false || nativeVerdict?.outcome === "grader_error")
      throw Error("NativeGraderEnvironmentError");
    return { answer: candidate?.body ?? "", candidateHow: candidate?.how ?? "none", engineState: t.state, engineVerdict: nativeVerdict, modelProtocolFailure: !candidate, enginePid: engine.pid };
  } finally {
    await engine?.stop();
    if (engine)
      save(join3(dir, "engine-stopped.json"), { pid: engine.pid, atUtc: new Date().toISOString() });
    const waitBegin = Date.now();
    while (pending > 0 && Date.now() - waitBegin < 605000)
      await Bun.sleep(100);
    await new Promise((accept) => proxy.close(() => accept()));
  }
}
async function controls() {
  const path = join3(OUT, "controls.json");
  if (existsSync(path) && read(path).allPassed)
    return;
  const rows = read(join3(SRC, "upstream/data/ClassEval_data.json"));
  const rr = [];
  for (const index of [0, 45, 92]) {
    const row2 = rows[index], reference = await grade(row2.task_id, row2.solution_code), wrong = await grade(row2.task_id, row2.skeleton);
    rr.push({ taskId: row2.task_id, reference, wrong });
    if (!reference.valid || !reference.passed || !wrong.valid || wrong.passed)
      throw Error("ScoringControlFailed:" + row2.task_id);
  }
  const row = rows[0], control = await native(catalog[0], join3(OUT, "controls/native"), join3(OUT, "controls/calls"), row.solution_code);
  const trace = read(join3(OUT, "controls/native/trace.json")), called = (name) => trace.some((r) => r.kind === "call" && JSON.parse(r.body).calls?.some((c) => c.name === name));
  const finalGrade = await grade(row.task_id, control.answer), allPassed = control.candidateHow === "submitted" && finalGrade.valid && finalGrade.passed && called("verify") && called("submit");
  save(path, { atUtc: new Date().toISOString(), allPassed, scoring: rr, native: { candidateHow: control.candidateHow, engineState: control.engineState, engineVerdict: control.engineVerdict, finalGrade, verifyCalled: called("verify"), submitCalled: called("submit"), modelCalls: 0 } });
  if (!allPassed)
    throw Error("NativeSubmitOrFinalCandidateControlFailed");
}
async function taskRun(task, arm) {
  const p = join3(OUT, "results", arm, task.officialId + ".json");
  if (existsSync(p) && read(p).grade?.valid)
    return;
  return taskSlots.run(() => taskRunInside(task, arm));
}
async function taskRunInside(task, arm) {
  const path = join3(OUT, "results", arm, task.officialId + ".json");
  if (existsSync(path) && read(path).grade?.valid)
    return;
  const began = Date.now(), dir = join3(OUT, "tasks", arm, task.officialId);
  mkdirSync2(dir, { recursive: true });
  active.push({ arm, taskId: task.officialId, atUtc: new Date().toISOString() });
  status();
  const previous = existsSync(path) ? read(path) : undefined;
  const attempts = retainedTaskAttempts(previous);
  const maxTaskAttempts = allowedTaskAttempts(arm, task.officialId);
  if (previous)
    durable(join3(OUT, "recovery/result-history", arm + "-" + task.officialId + "-" + Date.now() + ".json"), previous);
  let result = { taskId: task.officialId, arm, promptSha256: task.promptSha256, taskAttempts: attempts, maxTaskAttempts }, lastError = previous?.error;
  try {
    for (let attempt = 0;attempt < maxTaskAttempts; attempt++) {
      const ownDir = join3(dir, "attempt-" + attempt), candidatePath = join3(ownDir, "candidate.json");
      if (attempt < attempts && !existsSync(candidatePath))
        continue;
      try {
        let candidate;
        if (existsSync(candidatePath))
          candidate = read(candidatePath);
        else if (arm === "baseline") {
          const r = await model(join3(OUT, "calls", arm, task.officialId, "single"), { model: cfg.model, messages: [{ role: "user", content: task.prompt }] });
          const v = JSON.parse(r.raw);
          candidate = { answer: v.choices[0].message.content ?? "", candidateHow: "single_model_response", finishReason: v.choices[0].finish_reason };
          save(candidatePath, candidate);
        } else {
          candidate = await native(task, ownDir, join3(OUT, "calls", arm, task.officialId, "task-attempt-" + attempt));
          save(candidatePath, candidate);
        }
        result = { ...result, ...candidate, taskAttempts: attempt + 1 };
        result.grade = candidate.modelProtocolFailure ? { valid: true, passed: false, errorType: "ModelSubmissionProtocolFailure" } : await grade(task.officialId, candidate.answer);
        if (result.grade.valid)
          break;
        lastError = Error(result.grade.errorType);
        if (attempt === maxTaskAttempts - 1)
          break;
      } catch (e) {
        lastError = e;
        result = { ...result, taskAttempts: attempt + 1 };
        save(join3(ownDir, "error.json"), { atUtc: new Date().toISOString(), error: String(e) });
        if (/ProviderFault|Unresolved|Insufficient|SourceChanged|SavedRequestMismatch/.test(String(e)) || stopped)
          break;
      }
    }
    if (!result.grade)
      result.grade = { valid: false, passed: false, errorType: /Provider|Dispatch/.test(String(lastError)) ? "ProviderError" : "RunnerEnvironmentError" };
    if (!result.grade.valid)
      result.error = String(lastError ?? "FiniteTaskRecoveryExhausted");
  } finally {
    const own = walk(join3(OUT, "calls", arm, task.officialId)).filter((p) => p.endsWith("receipt.json")).map(read);
    result = { ...result, atUtc: new Date().toISOString(), seconds: (Date.now() - began) / 1000, actualCostUsd: own.reduce((n, r) => n + (r.actualCostUsd ?? 0), 0), modelCalls: own.length, unknownCostCount: own.filter((r) => r.unknownCost).length };
    save(path, result);
    active = active.filter((x) => x.arm !== arm || x.taskId !== task.officialId);
    status();
    console.log(JSON.stringify({ event: "task_completed", taskId: task.officialId, arm, valid: result.grade?.valid, passed: result.grade?.passed, seconds: result.seconds, cost: result.actualCostUsd, error: result.error }));
  }
}
async function runBatch(jobs, concurrency = CONCURRENCY) {
  await observation();
  spentSinceObservation = 0;
  estimate();
  let index = 0;
  await Promise.all(Array.from({ length: concurrency }, async () => {
    while (index < jobs.length && !shouldStop()) {
      const job = jobs[index++];
      await taskRun(job.task, job.arm);
    }
  }));
  estimate();
}
async function main() {
  frozen();
  await observation();
  status();
  updateRunning();
  const stopGrader = await startGrader();
  const timer = setInterval(() => status(), 15000);
  try {
    stage = "scoring_and_native_controls";
    status();
    updateRunning();
    await controls();
    stage = "baseline_full_objrun_canary";
    status();
    updateRunning();
    await Promise.all(cfg.arms.map(async (arm) => {
      await runBatch([{ task: catalog[0], arm }], 1);
      const path = join3(OUT, "results", arm, catalog[0].officialId + ".json"), first = read(path);
      if (!canaryReady(arm, [first])) {
        attention = true;
        fatal = fatal ?? "CanaryInvalidOrNoNativeFinalSubmission:" + arm;
        save(join3(OUT, "canary-" + arm + ".json"), { atUtc: new Date().toISOString(), passed: false, record: first, boundedRecoveryExhausted: first.taskAttempts >= allowedTaskAttempts(arm, first.taskId) });
        stage = "running_with_interface_exception";
        status();
        updateRunning();
        return;
      }
      save(join3(OUT, "canary-" + arm + ".json"), { atUtc: new Date().toISOString(), passed: true, taskId: first.taskId, arm, valid: first.grade.valid, candidateHow: first.candidateHow, cost: first.actualCostUsd, reusedInFull: true });
      const jobs = catalog.map((task) => ({ task, arm })).filter((j) => {
        const p = join3(OUT, "results", arm, j.task.officialId + ".json");
        return !existsSync(p) || !read(p).grade?.valid;
      });
      for (let i = 0;i < jobs.length && !shouldStop(); i += CONCURRENCY * 2)
        await runBatch(jobs.slice(i, i + CONCURRENCY * 2), CONCURRENCY);
    }));
  } finally {
    clearInterval(timer);
    await stopGrader();
    const rr = records();
    stage = attention || stopped ? "needs_attention" : rr.length === 200 && rr.every((r) => r.grade?.valid) ? "complete" : rr.length === 200 ? "complete_with_exceptions" : "needs_attention";
    status();
    updateRunning();
    estimate();
  }
}
main().catch((e) => {
  fatal = String(e);
  stage = "needs_attention";
  status();
  updateRunning();
  console.error(fatal);
  process.exitCode = 1;
}).finally(() => {
  if (existsSync(lock))
    unlinkSync(lock);
});
