import { createHash, timingSafeEqual } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, statfsSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { gzipSync } from "node:zlib";
import { freemem } from "node:os";
import { machine, type Machine } from "../../test/_lib.ts";
import { campaignComplete, checkedOutputTokens, classifyGeneration, completionFault, gradeFixedCandidate, reconcileReceiptCost, validTokenUsage, type ApiReceipt } from "./campaign-contract.ts";
import { acquirePaidCampaignLock } from "./paid-campaign-lock.ts";
import { loadChemiqProvenance } from "./chemiq-nextwave-contract.ts";
import { requestedWorkers, workerPreflight, roundRobinBenchmarks } from "./campaign-workers.ts";

const root = resolve(import.meta.dir, "../..");
const campaign = `repair-${new Date().toISOString().replace(/[:.]/g, "-")}`;
const output = join(root, "docs/repair-2026-10-08/campaigns", campaign);
const store = join(root, ".phase1-data/repair", campaign);
const paidLock = acquirePaidCampaignLock({ root, runId: campaign, entry: basename(import.meta.path) });
process.once("exit", () => { try { paidLock.release(); } catch {} });
mkdirSync(output, { recursive: true });
mkdirSync(store, { recursive: true });
const ports: Record<string, number> = { gpqa: 17903, cmt: 17901, aime: 17905, chembench: 17906, chemiq: 17918 };
const profile = process.argv[2] ?? "pilot";
const selected = (process.argv[3] ?? "gpqa,chembench,cmt").split(",");
const sizes = profile === "pilot" ? { gpqa: 10, chembench: 10, cmt: 10, aime: 10, chemiq: 10 }
  : { gpqa: 198, chembench: 500, cmt: 50, aime: 60, chemiq: 816 };
const overrideCount = process.env.OBJRUN_REPAIR_TASK_COUNT ? Number(process.env.OBJRUN_REPAIR_TASK_COUNT) : undefined;
if (overrideCount !== undefined) {
  if (profile !== "pilot" || !Number.isInteger(overrideCount) || overrideCount < 1 || overrideCount > 20) throw new Error("Only a 1–20 task pilot override is allowed");
  for (const name of Object.keys(sizes)) sizes[name as keyof typeof sizes] = overrideCount;
}
if (!["pilot", "full"].includes(profile) || selected.some(s => !(s in ports))) throw new Error("Invalid declared campaign profile");
const arms = (process.env.OBJRUN_REPAIR_ARMS ?? "U,R,F").split(",");
if (arms.some(a => !["U", "R", "F"].includes(a))) throw new Error("Invalid arm");
const requestedConcurrency = requestedWorkers(process.env.OBJRUN_REPAIR_WORKERS);
const diskPreflight = statfsSync(store);
const workerResources = workerPreflight({ requested: requestedConcurrency, freeMemoryBytes: freemem(), freeDiskBytes: diskPreflight.bavail * diskPreflight.bsize });
const concurrency = workerResources.selected;
const cap = Number(process.env.OBJRUN_REPAIR_BUDGET_USD ?? 15);
const maxTokens = 8192;
const key = process.env.DEEPSEEK_API_KEY;
if (!key) throw new Error("The project DeepSeek API credential is absent");
const sha = (text: string | Buffer) => createHash("sha256").update(text).digest("hex");
const save = (path: string, value: unknown) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(value, null, 2) + "\n"); };
type CaptureError = { stage: string; at: string; requestSha256?: string };
type CallReceipt = ApiReceipt & { route: string; startedAt: string; requestSha256: string; requestedModel: string; servedModel?: string; requestId?: string; usage?: Record<string, unknown>; requestFile?: string; responseFile?: string; responseSha256?: string; wireParameters?: Record<string, unknown>; providerAttempted: boolean; captureErrors?: CaptureError[]; providerFault?: string };
const calls: CallReceipt[] = [];
const captureErrors: CaptureError[] = [];
let spent = 0, reserved = 0, fatal: string | undefined;
const pending = new Map<string, number>();
function ledger() { save(join(output, "api-ledger.json"), { campaign, capUsd: cap, priorCampaignCostUpperBoundUsd: priorCampaignCost, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserved, fatal, pending: Object.fromEntries(pending), captureErrors, calls }); }
const authorization = `Bearer ${key}`;
if (!Number.isFinite(cap) || cap <= 0) throw new Error("A positive finite campaign budget is required");
let priorCampaignCost = 0;
const campaignRoot = dirname(output);
for (const name of readdirSync(campaignRoot)) {
  if (name === campaign) continue;
  const previous = join(campaignRoot, name, "api-ledger.json");
  if (!existsSync(previous)) continue;
  const data = JSON.parse(readFileSync(previous, "utf8"));
  const prior = data.recordedUsageUpperBoundUsd, outstanding = data.reservedUpperBoundUsd;
  if (typeof prior !== "number" || typeof outstanding !== "number" || !Number.isFinite(prior) || !Number.isFinite(outstanding) || prior < 0 || outstanding < -1e-9) throw new Error(`Invalid prior cost ledger: ${name}`);
  // Preserve old raw ledgers; numerical cancellation can leave a negative fraction of a nanodollar.
  priorCampaignCost += prior + Math.max(0, outstanding);
}
const proxy = Bun.serve({ hostname: "127.0.0.1", port: 0, maxRequestBodySize: 4 * 1024 * 1024,
  async fetch(request) {
    const supplied = request.headers.get("authorization") ?? "";
    const a = Buffer.from(supplied), b = Buffer.from(authorization);
    if (a.length !== b.length || !timingSafeEqual(a, b)) return Response.json({ error: { message: "Unauthorized local API proxy" } }, { status: 401 });
    const captureFailure = (stage: string, record?: CallReceipt) => {
      const error: CaptureError = { stage, at: new Date().toISOString(), ...(record ? { requestSha256: record.requestSha256 } : {}) };
      captureErrors.push(error);
      fatal ??= "local_evidence_error";
      if (record) {
        if (record.fault && record.fault !== "capture_error") record.providerFault ??= record.fault;
        record.fault = "capture_error";
        (record.captureErrors ??= []).push(error);
      }
    };
    const persistLedger = (stage: string, record?: CallReceipt) => {
      try { ledger(); return true; }
      catch { captureFailure(stage, record); return false; }
    };
    const url = new URL(request.url);
    if (request.method !== "POST" || !url.pathname.endsWith("/chat/completions")) return Response.json({ error: { message: "Unsupported local API route" } }, { status: 404 });
    const route = url.pathname.slice(1, -"/v1/chat/completions".length);
    const raw = await request.text();
    let body: Record<string, unknown>;
    try { body = JSON.parse(raw); } catch { return Response.json({ error: { message: "Invalid API request JSON" } }, { status: 400 }); }
    if (body.model !== "deepseek-flash" || body.stream === true) return Response.json({ error: { message: "Only the frozen non-streaming model route is permitted" } }, { status: 400 });
    let outputLimit: number;
    try { outputLimit = checkedOutputTokens(body); }
    catch { fatal = "invalid_request_output_limit"; persistLedger("invalid_limit_ledger"); return Response.json({ error: { message: "Invalid frozen output token limit" } }, { status: 400 }); }
    const inputUpper = Buffer.byteLength(raw) + 2048 + (Array.isArray(body.messages) ? body.messages.length * 256 : 0);
    const reserve = (inputUpper * 0.3 + outputLimit * 1.2) / 1e6;
    let disk;
    try { disk = statfsSync(store); }
    catch { captureFailure("disk_status"); persistLedger("disk_status_ledger"); return Response.json({ error: { message: "Campaign stopped: evidence storage unavailable" } }, { status: 503 }); }
    if (disk.bavail * disk.bsize < 512 * 1024 * 1024) { fatal = "local_disk_low"; persistLedger("disk_guard_ledger"); return Response.json({ error: { message: "Campaign stopped: insufficient evidence storage space" } }, { status: 507 }); }
    if (fatal || priorCampaignCost + spent + reserved + reserve > cap) {
      fatal ??= "local_budget_exhausted"; persistLedger("stopped_ledger");
      return Response.json({ error: { message: "Campaign stopped: infrastructure or local budget limit", code: "insufficient_quota" } }, { status: 402 });
    }
    const sequence = calls.length;
    const requestFile = join(store, `provider-${sequence}-request.json.gz`);
    const record: CallReceipt = { route, startedAt: new Date().toISOString(), requestSha256: sha(raw), requestedModel: String(body.model), requestFile, providerAttempted: false,
      wireParameters: Object.fromEntries(["model", "temperature", "seed", "reasoning_effort", "thinking", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"].filter(k => k in body).map(k => [k, body[k]])) };
    let allocated = false, forwarded = false;
    let stage = "request_reservation";
    let result = Response.json({ error: { message: "Campaign call did not complete" } }, { status: 503 });
    try {
      calls.push(record);
      reserved += reserve;
      pending.set(route, (pending.get(route) ?? 0) + 1);
      allocated = true;
      stage = "request_capture";
      writeFileSync(requestFile, gzipSync(raw));
      stage = "initial_ledger";
      ledger();
      stage = "provider_request";
      forwarded = true;
      record.providerAttempted = true;
      const response = await fetch("https://api.deepseek.com/chat/completions", { method: "POST", headers: { "content-type": "application/json", authorization }, body: raw, signal: AbortSignal.timeout(300000) });
      record.httpStatus = response.status;
      stage = "provider_response";
      const text = await response.text();
      record.responseFile = join(store, `provider-${sequence}-response.json.gz`);
      stage = "response_capture";
      writeFileSync(record.responseFile, gzipSync(text));
      record.responseSha256 = sha(text);
      stage = "provider_decision";
      let data: Record<string, unknown>;
      try { data = JSON.parse(text); } catch { record.fault = "InvalidProviderJSON"; fatal = record.fault; throw new Error(record.fault); }
      record.servedModel = typeof data.model === "string" ? data.model : undefined;
      record.requestId = typeof data.id === "string" ? data.id : undefined;
      if (data.usage && typeof data.usage === "object") record.usage = data.usage as Record<string, unknown>;
      spent += reconcileReceiptCost(record, reserve, { knownUncharged: !record.usage && [401, 402, 403].includes(response.status) }).deltaUsd;
      if (response.ok) {
        if (!validTokenUsage(record.usage)) throw new Error("MissingOrInvalidProviderTokenUsage");
        record.completionFault = completionFault(data);
        record.completionValid = !record.completionFault;
        if (record.completionFault) throw new Error(record.completionFault);
      } else if (![401, 402, 403].includes(response.status)) {
        record.fault = "ProviderUnsuccessfulResponse"; fatal = record.fault;
      }
      if ([401, 402, 403].includes(response.status)) fatal = `provider_http_${response.status}`;
      result = new Response(text, { status: response.status, headers: { "content-type": "application/json" } });
    } catch (error) {
      if (["request_reservation", "request_capture", "initial_ledger", "response_capture"].includes(stage)) captureFailure(stage, record);
      else {
        record.fault = error instanceof Error ? error.name + ":" + error.message : "ProviderTransportError";
        fatal ??= "unreconciled_provider_call";
      }
      // A local failure before forwarding is provably uncharged; an attempted
      // provider call can be charged without usage, so retain its reservation.
      spent += reconcileReceiptCost(record, reserve, { knownUncharged: !forwarded }).deltaUsd;
      result = Response.json({ error: { message: "Campaign call or evidence capture failed; further calls stopped" } }, { status: 503 });
    } finally {
      if (allocated) {
        reserved = Math.max(0, reserved - reserve);
        pending.set(route, Math.max(0, (pending.get(route) ?? 1) - 1));
      }
      record.finishedAt = new Date().toISOString();
      if (!persistLedger("final_ledger", record)) result = Response.json({ error: { message: "Campaign stopped: evidence ledger could not be saved" } }, { status: 503 });
    }
    return result;
  },
});

const sourcePath = join(output, "source.json");
execFileSync(process.execPath, [join(root, "scripts/phase1/source-snapshot.ts"), sourcePath], { cwd: root, windowsHide: true });
const source = JSON.parse(readFileSync(sourcePath, "utf8"));
// The legacy snapshot utility predates this execution directory: include it explicitly.
source.repairFiles = [basename(import.meta.path), "campaign-contract.ts", "paid-campaign-lock.ts", "chemiq-nextwave-contract.ts", "campaign-workers.ts", "freeze_source.py"].map(n => ({ path: `scripts/benchmark-repair/${n}`, sha256: sha(readFileSync(join(import.meta.dir, n))) }));
source.executionDigest = sha(JSON.stringify({ sourceDigest: source.sourceDigest, repairFiles: source.repairFiles }));
save(sourcePath, source);
const graderFiles = new Set([...selected.map(slug => `examples/benchmark/${slug}/${slug === "cmt" ? "grader.py" : "stand.py"}`), "examples/benchmark/_lib/gradelib.py"]);
let manifestSha256: string | undefined;
const chemiqProvenance = selected.includes("chemiq") ? loadChemiqProvenance(root, store) : undefined;
chemiqProvenance?.audit("startup");
if (chemiqProvenance) { source.graderProvenance = { chemiq: chemiqProvenance.metadata }; source.executionDigest = sha(JSON.stringify({ sourceDigest: source.sourceDigest, repairFiles: source.repairFiles, graderProvenance: source.graderProvenance })); save(sourcePath, source); }
for (const path of graderFiles) if (!source.files.some((file: { path: string }) => file.path === path)) throw new Error(`Grader source missing from snapshot: ${path}`);
const validateSource = () => {
  for (const file of [...source.files.filter((f: { path: string }) => f.path.startsWith("app/src/") || f.path === "test/_lib.ts" || graderFiles.has(f.path)), ...source.repairFiles]) {
    if (sha(readFileSync(join(root, file.path))) !== file.sha256) throw new Error(`Frozen execution source changed: ${file.path}`);
  }
  chemiqProvenance?.validate();
  if (manifestSha256 && sha(readFileSync(join(output, "manifest.json"))) !== manifestSha256) throw new Error("Frozen task schedule/manifest changed");
};
const plan: { benchmark: string; arm: string; replica: number; row: Record<string, unknown>; officialId: string; prompt: string }[] = [];
const datasets: Record<string, unknown> = {};
for (const slug of selected) {
  const grader = `http://127.0.0.1:${ports[slug]}`;
  const health = await fetch(`${grader}/health`);
  if (!health.ok) throw new Error(`${slug} grader health failed`);
  const endpoint = await health.json();
  if (slug === "chemiq" && (endpoint.opsin?.profile !== "local-2.8" || endpoint.opsin?.rest_fallback !== false || endpoint.length_policy !== "raw-input-length")) throw new Error("ChemIQ requires pinned local OPSIN, REST disabled and the declared raw-input-length policy");
  const result = await fetch(`${grader}/problems?n=${sizes[slug as keyof typeof sizes]}&seed=0`);
  if (!result.ok) throw new Error(`${slug} problem endpoint failed`);
  const rows = await result.json() as Record<string, unknown>[];
  if (rows.length !== sizes[slug as keyof typeof sizes]) throw new Error(`${slug} official task count does not match the frozen plan`);
  const publicTasks = rows.map((row, index) => {
    const officialId = String(row.id ?? `${slug}-${row.index ?? index}`);
    const choices = row.choices as Record<string, string> | undefined;
    const text = String(row.prompt ?? row.problem ?? row.question ?? "") + (choices ? "\n\n" + Object.entries(choices).map(([k, v]) => `${k}. ${v}`).join("\n") : "") + (slug === "cmt" ? `\nParameters: ${row.parameters ?? ""}\nFunctions: ${row.functions ?? ""}` : "");
    const format = slug === "gpqa" ? "End with exactly 'The correct answer is (X)', where X is A, B, C or D. Include the parentheses."
      : ["cmt", "aime"].includes(slug) ? "Put the final mathematical answer inside \\boxed{...}."
      : slug === "chemiq" ? `Use the requested ${row.answer_format ?? "short"} answer format. The final submitted answer must be a single line of at most 200 characters.` : "Preserve the required [ANSWER]...[/ANSWER] answer format.";
    const prompt = `${text}\n\n${format}\nSolve the task and submit your completed answer using submit. Search and filesystem tools are unavailable.`;
    for (const arm of arms) for (let replica = 0; replica < (arm === "R" ? 5 : 1); replica++) plan.push({ benchmark: slug, arm, replica, row, officialId, prompt });
    return { officialId, promptSha256: sha(prompt), row };
  });
  save(join(output, `${slug}-public-tasks.json`), publicTasks);
  datasets[slug] = { health: endpoint, selectedTaskIds: publicTasks.map(t => t.officialId), publicTaskDigest: sha(JSON.stringify(publicTasks)), source: JSON.parse(readFileSync(join(root, `.phase1-data/${slug}/source.json`), "utf8")), ...(slug === "chemiq" ? { graderProvenance: chemiqProvenance!.metadata } : {}) };
}
plan.splice(0, plan.length, ...roundRobinBenchmarks(plan, selected));
const taskSchedule = plan.map((task, index) => ({ index, benchmark: task.benchmark, arm: task.arm, replica: task.replica, officialId: task.officialId, promptSha256: sha(task.prompt) }));
source.taskScheduleSha256 = sha(JSON.stringify(taskSchedule));
source.executionDigest = sha(JSON.stringify({ sourceDigest: source.sourceDigest, repairFiles: source.repairFiles, graderProvenance: source.graderProvenance, taskScheduleSha256: source.taskScheduleSha256 }));
save(sourcePath, source);
const manifest = { schemaVersion: 2, acceptanceContract: source.repairFiles.find((f: {path: string}) => f.path.endsWith("campaign-contract.ts")), campaign, createdAt: new Date().toISOString(), profile, benchmarks: selected, arms, taskSchedule, taskScheduleSha256: source.taskScheduleSha256, scheduling: "Round robin across benchmarks, preserving each benchmark's fixed task/arm/replica order; synchronous shared index in one process", workerPreflight: workerResources, model: "deepseek-flash", provider: "https://api.deepseek.com", sourceExecutionDigest: source.executionDigest, temperature: 0, seed: 42, reasoningEffort: "none", maxTokensPerRequest: maxTokens, search: "disabled in every arm", allowedTools: ["submit", "verify only with mounted objective", "task_tree", "node_load"], checksPerAttempt: 5, maxDeadSiblingsF: 100000, maxBranchesF: 4, maxBranchesUR: 1, independentRReplicas: 5, taskSeconds: profile === "pilot" ? { default: 180, cmt: 180 } : { default: 600, cmt: 1800 }, concurrency, capUsd: cap, priorCampaignCostUpperBoundUsd: priorCampaignCost, pricingSource: "https://api-docs.deepseek.com/quick_start/pricing/", ratesPeakUsdPerMillion: { input: 0.3, cachedInput: 0.006, output: 1.2 }, taskSelection: "Fixed before any generation; official grader order, ChemBench seed0 first500 in full profile", datasets, protocolLimits: ["New current-model baseline; not the legacy0731 checkpoint", "R and F computation differs; report actual cost and comparison at common evaluation counts; no automatic pure feedback causality claim", "No paid search or local code tools; this freezes a new scientific protocol rather than silently recreating the old tool settings", "Declared decoding settings are also captured on the wire; provider determinism is not certified", "ChemIQ uses pinned local OPSIN2.8 and official RDKit equivalence; unknown legacy REST versions are not certified"] };
save(join(output, "manifest.json"), manifest);
manifestSha256 = sha(readFileSync(join(output, "manifest.json")));
execFileSync("python", ["-X", "utf8", join(import.meta.dir, "freeze_source.py"), campaign], { cwd: root, windowsHide: true });
const records: Record<string, unknown>[] = [];
const engines: Machine[] = [];
let next = 0;
function objectiveFor(slug: string) {
  const second = slug === "cmt" ? "equiv" : "correct";
  return { nodes: [{ name: "parsed", domain: "bool", moment: "done", handle: `http://127.0.0.1:${ports[slug]}/parsed` }, { name: second, domain: "bool", moment: "done", handle: `http://127.0.0.1:${ports[slug]}/${second}` }], edges: [{ src: "parsed", out: 0, dst: second }], sink: second, checks: 5, reuse: "text" };
}
function summary(completed: boolean) { save(join(output, "summary.json"), { campaign, completed, plannedTaskRuns: plan.length, recordedTaskRuns: records.length, generatedAt: new Date().toISOString(), recordedUsageUpperBoundUsd: spent, fatal, records }); }
async function worker(workerId: number) {
  const directory = join(store, `worker-${workerId}`);
  mkdirSync(directory, { recursive: true });
  const m = await machine({ maxTokens, retryTimes: 0, continueTimes: 0, reasoningEffort: "none", temperature: 0, seed: 42 }, { directory, keep: true });
  engines.push(m);
  await m.api("POST", "/exec", { sql: "insert or ignore into api (key_env,model,handle,modes,base_url,retry_on) select key_env,'deepseek-flash',handle,modes,base_url,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'" });
  await m.api("POST", "/declare", { handles: selected.flatMap(slug => ["parsed", slug === "cmt" ? "equiv" : "correct"].map(node => ({ name: `http://127.0.0.1:${ports[slug]}/${node}`, expectMs: 120000 }))), places: [{ place: "local" }], modes: [{ mode: "repair", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 12, from: [], next: ["act"], infer: "fn:infer.dfs" }, { cycle: "act", maxUnits: 12, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" }] }], agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-flash"]], unit: "fn:unit.tools" }] });
  await m.api("POST", "/exec", { sql: "update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')" });
  while (next < plan.length && !fatal) {
    validateSource();
    const index = next++, task = plan[index];
    const route = `${campaign}/${task.benchmark}/${task.arm}/${task.replica}/${encodeURIComponent(task.officialId)}`;
    await m.api("POST", "/exec", { sql: "update api set base_url=:endpoint,retry_on='[]' where key_env='DEEPSEEK_API_KEY' and model='deepseek-flash'", params: { endpoint: `http://127.0.0.1:${proxy.port}/${route}/v1` } });
    const id = `${campaign}/${task.benchmark}/${task.arm}${task.replica}/${task.officialId}`;
    const objective = objectiveFor(task.benchmark);
    const started = Date.now();
    const seconds = profile === "pilot" ? 180 : task.benchmark === "cmt" ? 1800 : 600;
    await m.api("POST", "/tasks", { id, run: campaign, mode: "repair", agent: "bot", place: "local", source: "user", description: task.prompt, ...(task.arm === "F" ? { objective, readable: false } : {}), solveSeconds: seconds, maxBranches: task.arm === "F" ? 4 : 1, maxDeadSiblings: task.arm === "F" ? 100000 : 1, noSearch: ["all"] });
    let terminal: { state: string; result: string | null } | undefined;
    let terminalAt = 0;
    while (Date.now() - started < (seconds + 150) * 1000) {
      const state = await m.api<{ state: string; result: string | null }>("GET", `/tasks/${encodeURIComponent(id)}`);
      const currentOutcome = state.result ? JSON.parse(state.result).outcome : undefined;
      const settling = ["finalization_pending", "finalization_error"].includes(currentOutcome);
      if (["done", "failed"].includes(state.state) && !settling && (state.result || task.arm !== "F")) {
        terminal = state; terminalAt ||= Date.now();
        // Let finalization and the API usage recorder settle before collecting the candidate.
        if (!(pending.get(route) ?? 0) && Date.now() - terminalAt > 2000) break;
      } else terminalAt = 0;
      await Bun.sleep(250);
    }
    if (!terminal) throw new Error(`${id}: no terminal result before hard deadline`);
    const trace = await m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", { sql: "select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like :prefix order by unit,seq", params: { prefix: `${id}#%` } });
    // Query the same final-candidate module used by both live and offline scoring.
    const { Database } = await import("bun:sqlite");
    const { finalCandidate } = await import("../../app/src/objective/candidate.ts");
    const db = new Database(join(directory, "data/h2h.sqlite"), { readonly: true });
    let candidate: { body: string; how: string } | undefined;
    let actualCreatedAt: number;
    try { actualCreatedAt = Number((db.query("select created_at from task where id = ?").get(id) as {created_at:number}).created_at); candidate = finalCandidate({ all: (sql: string, params?: unknown[]) => db.query(sql).all(...((params ?? []) as never[])), run() { throw new Error("read-only candidate extraction"); }, exec() { throw new Error("read-only candidate extraction"); }, close() {} } as never, id); } finally { db.close(); }
    const verdict = terminal.result ? JSON.parse(terminal.result) : { outcome: "unaided_generated", valid: true };
    const taskCalls = calls.filter(c => c.route === route);
    const generation = classifyGeneration({ runtimeVerdict: verdict, state: terminal.state, calls: taskCalls, trace: trace.rows, candidate: candidate?.body });
    const record = { index, benchmark: task.benchmark, arm: task.arm, replica: task.replica, officialId: task.officialId, taskId: id, state: terminal.state, runtimeVerdict: verdict, generationValid: generation.valid, generationClassification: generation, startedAt: new Date(started).toISOString(), seconds: (Date.now() - started) / 1000, actualCreatedAt, deadline: new Date(actualCreatedAt + seconds * 1000).toISOString(), answer: candidate?.body ?? "", candidateHow: candidate?.how ?? "none", candidateSha256: sha(candidate?.body ?? ""), promptSha256: sha(task.prompt), traceSha256: sha(JSON.stringify(trace.rows)), apiCalls: taskCalls, worker: workerId, workerPid: m.pid, acceptance: { valid: false, outcome: "pending_after_all_generation" } };
    save(join(output, `task-${index}.json`), { ...record, trace: trace.rows });
    records.push(record); summary(false);
    console.log(JSON.stringify({ campaign, benchmark: task.benchmark, arm: task.arm, replica: task.replica, index, officialId: task.officialId, state: terminal.state, outcome: verdict.outcome, seconds: record.seconds, usdUpperBound: spent }));
    if (!record.generationValid) { fatal ??= `invalid_generation:${task.benchmark}:${task.arm}:${verdict.outcome}`; ledger(); }
  }
}
let completed = false;
try {
  await Promise.all(Array.from({ length: concurrency }, (_, i) => worker(i)));
  validateSource();
  // Strict separation: R/U scores never affect generation, selection, revision, or stopping.
  for (const record of records) {
    const slug = String(record.benchmark), id = String(record.taskId), answer = String(record.answer);
    record.acceptance = await gradeFixedCandidate({ objective: objectiveFor(slug), task: { id }, candidate: record.candidateHow === "none" ? undefined : answer, generation: record.generationClassification as ReturnType<typeof classifyGeneration>, expectedCandidateSha256: String(record.candidateSha256) });
    const path = join(output, `task-${record.index}.json`);
    const old = JSON.parse(readFileSync(path, "utf8")); save(path, { ...old, acceptance: record.acceptance });
  }
  validateSource();
  chemiqProvenance?.audit("shutdown");
  completed = !fatal && campaignComplete(plan.length, records as { index: unknown; acceptance?: { valid?: unknown; passed?: unknown; outcome?: unknown } }[]);
  if (!completed && !fatal) { fatal = "incomplete_or_invalid_final_acceptance"; ledger(); }
  summary(completed);
  console.log(JSON.stringify({ output, completed, taskRuns: records.length, capUsd: cap, recordedUsageUpperBoundUsd: spent, fatal }));
} catch (error) {
  fatal ??= error instanceof Error ? error.message : "CampaignError";
  summary(false); ledger(); throw error;
} finally {
  for (const m of engines) await m.stop();
  void proxy.stop(true);
  paidLock.release();
}
process.exitCode = completed ? 0 : 1;
