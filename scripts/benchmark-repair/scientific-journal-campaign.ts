import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { BENCHMARK_INFERENCE } from "./benchmark-inference.ts";
import { BENCHMARK_PROVIDER,benchmarkProviderKey,benchmarkFetch,type BenchmarkProvider } from "./benchmark-provider.ts";
import { execFileSync } from "node:child_process";
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, statSync, statfsSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { freemem } from "node:os";
import { machine, type Machine } from "../../test/_lib.ts";
import { finalCandidate } from "../../app/src/objective/candidate.ts";
import { graderFetch } from "../../app/src/engine/registry.ts";
import { createCampaignJournal, inspectCampaignJournal } from "./campaign-journal.ts";
import { campaignComplete, classifyGeneration, gradeFixedCandidate } from "./campaign-contract.ts";
import { requestedWorkers, workerPreflight } from "./campaign-workers.ts";
import { loadChemiqProvenance } from "./chemiq-nextwave-contract.ts";
import { digest, fixedScientificPlan, scientificPrompt, SCIENCE_PORTS, type PlannedTask } from "./scientific-journal-plan.ts";
import { ScientificJournalProxy, captureProviderResponse, type TaskReceipt } from "./scientific-journal-proxy.ts";
import { scientificWorkerResources } from "./scientific-journal-resources.ts";
import { validateScientificStore } from "./scientific-journal-storage.ts";
import { acquirePaidCampaignLock } from "./paid-campaign-lock.ts";
import { scientificLiveId } from "./scientific-startup-proof.ts";

const root = resolve(import.meta.dir, "../..");
const now = () => new Date().toISOString();
const python = join(root, ".phase1-data/venv/Scripts/python.exe");
export const executionFiles = [basename(import.meta.path), "scientific-journal-plan.ts", "scientific-journal-proxy.ts", "scientific-journal-admission.ts", "scientific-startup-proof.ts", "scientific-journal-resources.ts", "scientific-journal-storage.ts", "prepare-scientific-journal-store.ps1", "paid-resource-admission-v2.ts", "cny-cash-shadow-v2.ts", "paid-resource-proof-v2.ts", "paid-campaign-lock.ts", "campaign-journal.ts", "campaign-contract.ts", "campaign-workers.ts", "chemiq-nextwave-contract.ts", "chemiq-grader-provenance.py", "freeze-scientific-journal.py", "audit-scientific-journal.py", "audit-journal-canonical.ts", "audit-scientific-campaign.py", "full-gpqa-inflight-audit.py"].map(name => `scripts/benchmark-repair/${name}`);
executionFiles.push(...["benchmark-inference.ts", "benchmark-provider.ts", "benchmark-usd-cash.ts", "openrouter-paid-admission.ts", "openrouter-scientific-admission.ts"].map(name => "scripts/benchmark-repair/" + name));
function save(path: string, value: unknown) {
  mkdirSync(dirname(path), { recursive: true });
  const fd = openSync(path, "w", 0o600);
  try { writeFileSync(fd, JSON.stringify(value, null, 2) + "\n"); fsyncSync(fd); } finally { closeSync(fd); }
}
function pin(path: string) { return { path, bytes: statSync(path).size, sha256: digest(readFileSync(path)) }; }
function syncExisting(path: string) { const fd = openSync(path, "r+"); try { fsyncSync(fd); } finally { closeSync(fd); } return pin(path); }
function objective(slug: string) {
  const second = slug === "cmt" ? "equiv" : "correct", origin = `http://127.0.0.1:${SCIENCE_PORTS[slug]}`;
  return { nodes: [{ name: "parsed", domain: "bool", moment: "done", handle: `${origin}/parsed` }, { name: second, domain: "bool", moment: "done", handle: `${origin}/${second}` }], edges: [{ src: "parsed", out: 0, dst: second }], sink: second, checks: 5, reuse: "text" };
}
function initialManifest(campaign: string, profile: string, selected: string[], plan: ReturnType<typeof fixedScientificPlan>) {
  return { schemaVersion: 2, campaign, createdAt: now(), profile, benchmarks: selected, arms: ["U", "F"], taskSchedule: plan.taskSchedule,
    taskScheduleSha256: plan.taskScheduleSha256, scheduling: "Prospective fixed complete schedule; round robin benchmarks, preserving official U/F order", datasets: plan.datasets,
    model: BENCHMARK_PROVIDER.model, provider: BENCHMARK_PROVIDER.baseURL, providerName: BENCHMARK_PROVIDER.providerName, providerSlug: BENCHMARK_PROVIDER.providerSlug, currency:"USD", providerKind: "real-provider", ...BENCHMARK_INFERENCE, thinking: { type: "enabled" }, maxTokensPerRequest: BENCHMARK_INFERENCE.maxTokens,
    ratesPeakUsdPerMillion: { input: .3, cachedInput: .006, output: 1.2 }, pricingSource: "https://api-docs.deepseek.com/quick_start/pricing/",
    search: "disabled in every arm", allowedTools: ["submit", "verify only with mounted objective", "task_tree", "node_load"], checksPerAttempt: 5,
    maxDeadSiblingsF: 100000, maxBranchesF: 4, maxBranchesUR: 1, independentRReplicas: 5, taskSeconds: { default: 600, cmt: 1800 },
    hostExecutors: { bun: { path: process.execPath, version: Bun.version }, python: { path: python } },
    statusEndpoint: "/tasks/:id/status", accountingProtocol: "campaign-api-journal-openrouter-v1", additionalExecutionFiles: executionFiles,
    calibration: plan.calibration, scope: "New prospective baseline. The old OOM batch remains a distinct incomplete diagnostic, and no prior correctness result chooses this schedule.",
    protocolLimits: ["R is not run in this U/F protocol", "Explicit verify per node, runtime auto grades and independent final grades must be reported separately", "U is graded only after all generation is over", "Operator fee guards are not user limits; USD guard is not CNY balance", "Full GET still expands all units; only the independent status endpoint is used for polling"] };
}
function validateFrozen(output: string, includeDependencies = false) {
  const source = JSON.parse(readFileSync(join(output, "source.json"), "utf8"));
  const archive = JSON.parse(readFileSync(join(output, "frozen-source.json"), "utf8"));
  for (const value of [...source.files, ...source.repairFiles, ...(includeDependencies ? archive.dependencyFiles : [])]) {
    if (digest(readFileSync(join(root, value.path))) !== value.sha256) throw new Error("Frozen source changed: " + value.path);
  }
  if (includeDependencies && digest(readFileSync(archive.archive)) !== archive.archiveSha256) throw new Error("Frozen archive changed");
  if (includeDependencies) {
    const manifest = JSON.parse(readFileSync(join(output, "manifest.json"), "utf8"));
    for (const runtime of Object.values(manifest.hostExecutors) as { path: string; sha256: string }[]) if (digest(readFileSync(runtime.path)) !== runtime.sha256) throw new Error("Frozen host executor changed");
  }
  return { source, archive };
}
export function prepareScientificJournal(profile: string, selected: string[], campaign = `repair-${now().replace(/[:.]/g, "-")}`) {
  const plan = fixedScientificPlan(root, campaign, profile, selected);
  const output = join(root, "docs/repair-2026-10-08/journal-preparations", campaign), store = join(root, ".scratch/scientific-journal-preparations", campaign);
  mkdirSync(dirname(output), { recursive: true });
  mkdirSync(output, { recursive: false }); mkdirSync(store, { recursive: true });
  const manifest = { ...initialManifest(campaign, profile, selected, plan), mode: "prepare", providerForwardingEnabled: false, externalModelCalls: 0,
    operatorGuardSelected: false, cashAdmissionRequiredBeforeRun: true, requestedWorkers: 4, plannedTaskRuns: plan.tasks.length };
  save(join(output, "manifest.json"), manifest);
  for (const slug of selected) save(join(output, `${slug}-public-tasks.json`), plan.catalogs[slug]);
  execFileSync(python, ["-B", "-X", "utf8", join(import.meta.dir, "freeze-scientific-journal.py"), output, store], { cwd: root, windowsHide: true });
  const proof = validateFrozen(output, true);
  if (readdirSync(store).join(",") !== "frozen-source.zip") throw new Error("Prepare contains unexpected live request evidence");
  const entrySource = proof.source.repairFiles.find((value: { path: string }) => value.path === `scripts/benchmark-repair/${basename(import.meta.path)}`);
  save(join(output, "preparation.json"), { protocol: "scientific-journal-preparation-v1", mode: "prepare", prepared: true, campaign,
    providerForwardingEnabled: false, externalModelCalls: 0, plannedTaskRuns: plan.tasks.length,
    manifestPin: pin(join(output, "manifest.json")), sourcePin: pin(join(output, "source.json")), entrySourcePin: { ...entrySource, path: join(root, entrySource.path) },
    zeroRequestStoreInventory: { directory: store, entries: [pin(join(store, "frozen-source.zip"))], ledgerOrJournalOrRawOrCashOrSummaryPresent: false },
    taskScheduleSha256: plan.taskScheduleSha256, sourceExecutionDigest: proof.source.executionDigest, controlsOrResultsCertified: false });
  return { output, store, campaign, plannedTaskRuns: plan.tasks.length, taskScheduleSha256: plan.taskScheduleSha256 };
}

/** The separately reviewed admission adapter must enforce both CNY cash shadow and the shared canonical paid lock. */
export interface ScientificPaidAdmission {
  provider?: BenchmarkProvider;
  priorCampaignCostUpperBoundUsd: number; capUsd: number; metadata: Record<string, unknown>; executionFiles: string[];
  acquireLock(input: { root: string; runId: string; entry: string }): Promise<{ path: string; release(proof: Record<string, unknown>): void | Promise<void> }>;
  prepareStore(input: { root: string; campaign: string; output: string }): Promise<{ path: string; bytes?: number; sha256: string }>;
  registerWorker(input: { worker: number; pid: number; base: string; output: string }): void | Promise<void>;
  beforeForward(admitted: { admitted: true; requestSeq: number; reservationUsd: number; requestSha256: string; requestFile: string }, prefix: Record<string, unknown>, raw: string, route: string): void | Promise<void>;
  afterDurableFinish(receipt: TaskReceipt): void | Promise<void>;
  afterFailedJournalCapture(request: unknown, finish: unknown, evidence: Record<string, unknown>): void | Promise<void>;
  certify(input: Record<string, unknown>): unknown | Promise<unknown>;
  failed(input: Record<string, unknown>): void | Promise<void>;
}
const NATIVE_FIXTURE_BRAND = Symbol("F-only native mock");
type NativeFixture = { brand: symbol; root: string; key: string; keyEnv: string; origin: string;
  plan: (campaign: string) => ReturnType<typeof fixedScientificPlan>;
  transport: (raw: string) => Promise<{ httpStatus: number; rawResponse: string }> };
export async function runScientificJournal(profile: string, selected: string[], admission: ScientificPaidAdmission, fixture?: NativeFixture) {
  const projectRoot = resolve(import.meta.dir, "../..");
  if (fixture && (fixture.brand !== NATIVE_FIXTURE_BRAND || !resolve(fixture.root).startsWith(join(projectRoot, ".scratch", "scientific-native-four-engine-") ) || !/^http:\/\/127\.0\.0\.1:\d+$/.test(fixture.origin))) throw new Error("Only the internal strict F localhost fixture is permitted");
  const root = fixture?.root ?? projectRoot;
  let modelPhaseEnabled = false;
  if (!Number.isFinite(admission.capUsd) || !Number.isFinite(admission.priorCampaignCostUpperBoundUsd) || admission.capUsd <= admission.priorCampaignCostUpperBoundUsd || admission.priorCampaignCostUpperBoundUsd < 0 || !admission.metadata || !admission.executionFiles?.length || typeof admission.prepareStore !== "function" || typeof admission.registerWorker !== "function") throw new Error("A reviewed actual-liability, owned store and CNY cash admission adapter is required");
  const prospective = admission.metadata.prospectiveRunId;
  if (!fixture && prospective !== undefined && (typeof prospective !== "string" || !/^repair-[0-9TZ-]+$/.test(prospective))) throw new Error("Invalid fixed prospective recipe run identity");
  const campaign = typeof prospective === "string" ? prospective : `repair-${now().replace(/[:.]/g, "-")}`, plan = fixture ? fixture.plan(campaign) : fixedScientificPlan(root, campaign, profile, selected);
  if (!fixture && admission.metadata.taskScheduleSha256 !== undefined && admission.metadata.taskScheduleSha256 !== plan.taskScheduleSha256) throw new Error("Recipe task schedule differs from current fixed full plan");
  const objectiveFor = (slug: string) => fixture ? { ...objective(slug), nodes: objective(slug).nodes.map(node => ({ ...node, handle: fixture.origin + "/" + node.name })) } : objective(slug);
  const routeProvider=fixture?undefined:BENCHMARK_PROVIDER;
  if(!fixture && admission.provider?.kind!==BENCHMARK_PROVIDER.kind)throw Error("Regenerate the scientific recipe with OpenRouter USD admission");
  const model=routeProvider?.model??"deepseek-flash";
  const keyEnv = fixture?.keyEnv ?? "OPENROUTER_API_KEY";
  const output = join(root, "docs/repair-2026-10-08/campaigns", campaign);
  const lock = await admission.acquireLock({ root, runId: campaign, entry: basename(import.meta.path) });
  try {
  mkdirSync(output, { recursive: true });
  const storePin = await admission.prepareStore({ root, campaign, output });
  const validateStore = () => fixture ? (() => {
    const receipt = JSON.parse(readFileSync(storePin.path, "utf8"));
    if (digest(readFileSync(storePin.path)) !== storePin.sha256 || receipt.protocol !== "scientific-native-store-v1" || receipt.campaign !== campaign || receipt.physicalStore !== join(root, ".phase1-data/repair", campaign)) throw new Error("Native fixture store changed");
    return { physicalStore: receipt.physicalStore, logicalStore: receipt.physicalStore, receipt: storePin };
  })() : validateScientificStore(root, campaign, storePin);
  const storage = validateStore(), store = storage.physicalStore;
  const wanted = Number(admission.metadata.frozenWorkers ?? requestedWorkers(process.env.OBJRUN_REPAIR_WORKERS));
  const resources = workerPreflight({ requested: wanted, freeMemoryBytes: freemem(), freeDiskBytes: statfsSync(store).bavail * statfsSync(store).bsize });
  const independentMemory = scientificWorkerResources({ requested: resources.selected, freeMemoryBytes: resources.freeMemoryBytes });
  resources.selected = independentMemory.selected;
  if (admission.metadata.frozenWorkers !== undefined && resources.selected !== wanted) throw new Error("Actual resources do not support frozen worker count");
  const key = fixture?.key ?? benchmarkProviderKey(root);
  if (!key) throw new Error("The host project model credential is absent; keep owned lock for failure review");
  const authorization = `Bearer ${key}`;
  const chemiq = selected.includes("chemiq") ? loadChemiqProvenance(root, store) : undefined;
  let manifest = { ...initialManifest(campaign, profile, selected, plan), mode: fixture ? "native-local-mock-fixture" : "run", providerKind: fixture ? "local-mock" : "real-provider",
    model,provider: fixture ? "localhost synthetic producer only" : BENCHMARK_PROVIDER.baseURL,providerName:routeProvider?.providerName,providerSlug:routeProvider?.providerSlug,currency:fixture?"CNY":"USD", formalResultsCertified: false,
    scope: fixture ? "Four synthetic10s tasks; same worker/closing path, no formal1220 result or real provider" : "Independent whole prospective cohort",
    journalDirectory: store, logicalStore: storage.logicalStore,
    storageLayout: storage.receipt, workerPreflight: resources, independentMemoryPreflight: independentMemory, concurrency: resources.selected,
    capUsd: admission.capUsd, priorCampaignCostUpperBoundUsd: admission.priorCampaignCostUpperBoundUsd,
    paidResourceAdmission: admission.metadata, additionalExecutionFiles: [...executionFiles, ...admission.executionFiles],
    graderProvenance: chemiq ? { chemiq: chemiq.metadata } : undefined };
  save(join(output, "manifest.json"), manifest);
  for (const slug of selected) save(join(output, `${slug}-public-tasks.json`), plan.catalogs[slug]);
  // Live grader preflight occurs only under explicit run, before any model request.
  for (const slug of selected) {
    const origin = fixture?.origin ?? `http://127.0.0.1:${SCIENCE_PORTS[slug]}`;
    const health = await graderFetch(`${origin}/health`, { signal: AbortSignal.timeout(120000) });
    if (!health.ok) throw new Error("Grader health failed: " + slug);
    const endpoint = await health.json();
    if (slug === "chemiq" && (endpoint.opsin?.profile !== "local-2.8" || endpoint.opsin?.rest_fallback !== false || endpoint.length_policy !== "raw-input-length")) throw new Error("ChemIQ revised grader profile differs");
    const response = await graderFetch(`${origin}/problems?n=${slug === "chemiq" ? 816 : plan.catalogs[slug].length}&seed=0`, { signal: AbortSignal.timeout(120000) });
    if (!response.ok) throw new Error("Public grader book unavailable");
    const rows = await response.json() as Record<string, unknown>[];
    const byId = new Map(rows.map(row => [scientificLiveId(slug, row, Boolean(fixture)), row]));
    if (rows.length !== (slug === "chemiq" ? 816 : plan.catalogs[slug].length) || byId.size !== rows.length) throw new Error("Live official book denominator/ID changed");
    for (const task of plan.catalogs[slug]) if (!byId.has(task.officialId) || digest(scientificPrompt(slug, byId.get(task.officialId)!)) !== task.promptSha256) throw new Error("Live public prompt differs from fixed plan");
    (manifest.datasets[slug] as Record<string, unknown>).health = endpoint;
  }
  chemiq?.audit("startup");
  save(join(output, "manifest.json"), manifest);
  execFileSync(python, ["-B", "-X", "utf8", join(import.meta.dir, "freeze-scientific-journal.py"), output, store], { cwd: root, windowsHide: true });
  const sourceProof = validateFrozen(output, true), manifestSha = digest(readFileSync(join(output, "manifest.json")));
  const validate = () => { validateFrozen(output); validateStore(); chemiq?.validate(); if (digest(readFileSync(join(output, "manifest.json"))) !== manifestSha) throw new Error("Frozen manifest changed"); };
  const journal = createCampaignJournal({ directory: store, campaign, capUsd: admission.capUsd, priorCampaignCostUpperBoundUsd: admission.priorCampaignCostUpperBoundUsd, outputDirectory: output,provider:routeProvider });
  const proxy = new ScientificJournalProxy(journal, { inference: BENCHMARK_INFERENCE, provider:routeProvider, routes: new Set(plan.tasks.map(task => task.route)), failureDirectory: join(store, "journal-failures"),
    beforeAdmission() {
      validate();
      for (const path of [store, output]) { const disk = statfsSync(path); if (disk.bavail * disk.bsize < 512 * 1024 * 1024) throw new Error("Physical raw or F metadata evidence disk guard"); }
    },
    beforeForward: (call, prefix, raw, route) => admission.beforeForward(call, prefix, raw, route), afterDurableFinish: receipt => admission.afterDurableFinish(receipt),
    afterFailedJournalCapture: (call, finish, evidence) => admission.afterFailedJournalCapture(call, finish, evidence),
    transport: fixture?.transport ?? (async raw => { const response = await benchmarkFetch(raw,key!); return captureProviderResponse(response); }) });
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, maxRequestBodySize: 4 * 1024 * 1024,
    async fetch(request) {
      const a = Buffer.from(request.headers.get("authorization") ?? ""), b = Buffer.from(authorization);
      if (a.length !== b.length || !timingSafeEqual(a, b)) return Response.json({ error: { message: "Unauthorized host proxy" } }, { status: 401 });
      const path = new URL(request.url).pathname;
      if (request.method !== "POST" || !path.endsWith("/v1/chat/completions")) return new Response("Unsupported route", { status: 404 });
      const result = await proxy.handle(path.slice(1, -"/v1/chat/completions".length), await request.text());
      return new Response(result.rawResponse, { status: result.httpStatus, headers: { "content-type": "application/json" } });
    } });
  let next = 0, fatal: string | undefined, completed = false, operationallyComplete = false;
  let resourceClosure: unknown;
  const indexes: number[] = [], engines = new Map<number, Machine>(), workerClosures: Record<string, unknown>[] = [];
  const hotSummary = () => save(join(output, "progress.json"), { campaign, completed: false, plannedTaskRuns: plan.tasks.length, recordedTaskRuns: indexes.length, completedIndices: indexes, fatal, journal: journal.snapshot() });
  const readRecord = (index: number) => JSON.parse(readFileSync(join(output, `task-${index}.json`), "utf8"));
  async function worker(workerId: number) {
    let current: PlannedTask | undefined, engine: Machine | undefined;
    try {
      const directory = join(store, `worker-${workerId}`); mkdirSync(directory, { recursive: true });
      engine = await machine(BENCHMARK_INFERENCE, { directory, keep: true });
      engines.set(workerId, engine);
      await admission.registerWorker({ worker: workerId, pid: engine.pid, base: engine.base, output });
      await engine.api("POST", "/exec", { sql: "insert or ignore into api (key_env,model,handle,modes,base_url,retry_on) select :key,:model,handle,modes,base_url,'[]' from api where key_env=:sourceKey and model=:sourceModel", params: { key: keyEnv,model,sourceKey:fixture?"DEEPSEEK_API_KEY":"OPENROUTER_API_KEY",sourceModel:fixture?"deepseek-v4-flash":model } });
      await engine.api("POST", "/declare", { handles: selected.flatMap(slug => objectiveFor(slug).nodes.map(node => ({ name: node.handle, expectMs: 120000 }))), places: [{ place: "local" }], modes: [{ mode: "repair", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 12, from: [], next: ["act"], infer: "fn:infer.dfs" }, { cycle: "act", maxUnits: 12, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" }] }], agents: [{ name: "bot", apis: [[keyEnv, model]], unit: "fn:unit.tools" }] });
      await engine.api("POST", "/exec", { sql: "update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')" });
      while (next < plan.tasks.length && !fatal && !proxy.state().stopReason) {
        validate(); current = plan.tasks[next++];
        await engine.api("POST", "/exec", { sql: "update api set base_url=:endpoint,retry_on='[]' where key_env=:key and model=:model", params: { key: keyEnv,model, endpoint: `http://127.0.0.1:${server.port}/${current.route}/v1` } });
        const started = Date.now();
        await engine.api("POST", "/tasks", { id: current.taskId, run: campaign, mode: "repair", agent: "bot", place: "local", source: "user", description: current.prompt,
          ...(current.arm === "F" ? { objective: objectiveFor(current.benchmark), readable: false } : {}), solveSeconds: current.seconds, maxBranches: current.arm === "F" ? 4 : 1, maxDeadSiblings: current.arm === "F" ? 100000 : 1, noSearch: ["all"] });
        let terminal: { state: string; result: string | null; created_at: number } | undefined, terminalAt = 0;
        while (Date.now() - started < (current.seconds + (fixture ? 5 : 150)) * 1000) {
          const state = await engine.api<typeof terminal & { state: string; result: string | null; created_at: number }>("GET", `/tasks/${encodeURIComponent(current.taskId)}/status`);
          const outcome = state.result ? JSON.parse(state.result).outcome : undefined;
          if (["done", "failed"].includes(state.state) && !["finalization_pending", "finalization_error"].includes(outcome) && (state.result || current.arm === "U")) {
            terminal = state; terminalAt ||= Date.now();
            if (!proxy.pending(current.route) && Date.now() - terminalAt > 2000) break;
          } else { terminalAt = 0; terminal = undefined; }
          await Bun.sleep(250);
        }
        if (!terminal) throw new Error("No complete terminal state before hard deadline");
        await proxy.drain(current.route);
        const trace = await engine.api<{ rows: Record<string, unknown>[] }>("POST", "/query", { sql: "select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like :prefix order by unit,seq", params: { prefix: `${current.taskId}#%` } });
        const { Database } = await import("bun:sqlite"), db = new Database(join(directory, "data/h2h.sqlite"), { readonly: true });
        let candidate;
        try { candidate = finalCandidate({ all: (sql: string, params?: unknown[]) => {
          const stmt = db.prepare(sql); try { return stmt.all(...((params ?? []) as never[])); } finally { stmt.finalize(); }
        }, run() { throw new Error("readonly"); }, exec() { throw new Error("readonly"); }, close() {} } as never, current.taskId); } finally { db.close(); }
        const calls = proxy.takeTaskReceipts(current.route), verdict = terminal.result ? JSON.parse(terminal.result) : { outcome: "unaided_generated", valid: true };
        const generation = classifyGeneration({ runtimeVerdict: verdict, state: terminal.state, calls, trace: trace.rows, candidate: candidate?.body });
        save(join(output, `task-${current.index}.json`), { index: current.index, benchmark: current.benchmark, arm: current.arm, replica: 0, officialId: current.officialId,
          taskId: current.taskId, state: terminal.state, runtimeVerdict: verdict, generationValid: generation.valid, generationClassification: generation,
          startedAt: new Date(started).toISOString(), seconds: (Date.now() - started) / 1000, actualCreatedAt: terminal.created_at,
          deadline: new Date(terminal.created_at + current.seconds * 1000).toISOString(), answer: candidate?.body ?? "", candidateHow: candidate?.how ?? "none",
          candidateSha256: digest(candidate?.body ?? ""), promptSha256: current.promptSha256, traceSha256: digest(JSON.stringify(trace.rows)), apiCalls: calls.map(({ requestSeq, journalRef, ...receipt }) => receipt),
          callIds: calls.map(call => call.requestSeq), journalRefs: calls.map(call => call.journalRef), trace: trace.rows, worker: workerId, workerPid: engine.pid,
          acceptance: { valid: false, outcome: "pending_after_all_generation" } });
        indexes.push(current.index); hotSummary();
        if (!generation.valid) { fatal ??= "Invalid generation: " + generation.outcome; proxy.stop(fatal); }
      }
    } catch (error) {
      fatal ??= error instanceof Error ? error.name + ":" + error.message : "WorkerError"; proxy.stop("worker_failure");
      save(join(output, `worker-${workerId}-failure.json`), { worker: workerId, taskIndex: current?.index, observedAt: now(), error: fatal, completed: false });
      throw error;
    } finally {
      if (current) await proxy.drain(current.route);
      if (engine) { await engine.stop(); workerClosures.push({ worker: workerId, pid: engine.pid, stopReturned: true, observedAt: now() }); engines.delete(workerId); }
    }
  }
  try {
    modelPhaseEnabled = true;
    const workerResults = await Promise.allSettled(Array.from({ length: resources.selected }, (_, index) => worker(index)));
    proxy.stop("generation_phase_closed"); await proxy.drain();
    save(join(output, "worker-closure.json"), { allSettled: workerResults.map(value => ({ status: value.status })), workerClosures, activeEngines: engines.size, proxy: proxy.state() });
    if (workerResults.some(value => value.status === "rejected")) fatal ??= "worker_failure";
    const exported = journal.exportLegacyLedger();
    save(join(output, "journal-export.json"), exported);
    if (!exported.eligibleForScoreCertification || proxy.anomalies.length) fatal ??= "journal_or_cash_evidence_invalid";
    validate(); validateFrozen(output, true);
    if (!fatal && indexes.length === plan.tasks.length) {
      for (const index of indexes) {
        const record = readRecord(index);
        record.acceptance = await gradeFixedCandidate({ objective: objectiveFor(record.benchmark), task: { id: record.taskId }, candidate: record.candidateHow === "none" ? undefined : record.answer,
          generation: record.generationClassification, expectedCandidateSha256: record.candidateSha256 });
        save(join(output, `task-${index}.json`), record);
      }
      validate(); validateFrozen(output, true); chemiq?.audit("shutdown");
      const proof = inspectCampaignJournal(store);
      resourceClosure = await admission.certify({ campaign, output, store, sourceExecutionDigest: sourceProof.source.executionDigest, journal: proof.snapshot, export: exported, workers: workerClosures, modelTransportActive: proxy.state().activeHandlers });
      save(join(output, "paid-resource-closure.json"), resourceClosure);
      if (!resourceClosure || (resourceClosure as { valid?: unknown }).valid !== true || (resourceClosure as { accountingClosed?: unknown }).accountingClosed !== true) throw new Error("Cash/resource closure did not certify actual closed accounting");
      operationallyComplete = campaignComplete(plan.tasks.length, indexes.map(readRecord));
      if (!operationallyComplete) fatal ??= "incomplete_or_invalid_final_acceptance";
    } else fatal ??= "incomplete_generation_schedule";
  } catch (error) { fatal ??= error instanceof Error ? error.name + ":" + error.message : "CampaignError"; proxy.stop("campaign_failure"); }
  finally {
    proxy.stop("closing"); await proxy.drain();
    // Worker allSettled is complete before this branch; never release a lock on an invalid/poisoned run.
    const remaining = [...engines.values()], engineStops = await Promise.allSettled(remaining.map(engine => engine.stop()));
    if (engineStops.some(value => value.status === "rejected")) { operationallyComplete = false; fatal ??= "engine_close_failure"; }
    const summary = (done: boolean, stage: string, provisionalPins?: unknown) => {
      const fd = openSync(join(output, "summary.json"), "w", 0o600);
      try {
        const state = { campaign, completed: done, certificationPhase: stage, provisionalIntegrityPins: provisionalPins,
          plannedTaskRuns: plan.tasks.length, recordedTaskRuns: indexes.length, generatedAt: now(), recordedUsageUpperBoundUsd: journal.snapshot().recordedUsageUpperBoundUsd, fatal };
        writeFileSync(fd, JSON.stringify(state, null, 2).slice(0, -1) + ',\n  "records": [\n');
        for (let position = 0; position < indexes.length; position++) { const value = readRecord(indexes[position]); delete value.trace; writeFileSync(fd, JSON.stringify(value) + (position + 1 < indexes.length ? ",\n" : "\n")); }
        writeFileSync(fd, "  ]\n}\n"); fsyncSync(fd);
      } finally { closeSync(fd); }
    };
    const audit = (provisional: boolean) => {
      execFileSync(python, ["-B", "-X", "utf8", join(import.meta.dir, "audit-scientific-journal.py"), "--run", campaign, ...(provisional ? ["--provisional"] : []), ...(fixture ? ["--fixture-root", root, "--fixture-integrity"] : [])], { cwd: root, windowsHide: true, maxBuffer: 1024 * 1024 });
      const oldPin = syncExisting(join(output, "independent-closing-audit.json")), journalPin = syncExisting(join(output, "independent-journal-closing-audit.json"));
      const old = JSON.parse(readFileSync(oldPin.path, "utf8")), extra = JSON.parse(readFileSync(journalPin.path, "utf8"));
      if (old.integrityValid !== true || extra.integrityValid !== true || (!provisional && (old.scoreCertificateValid !== true || (fixture ? extra.localMockIntegrityCertified !== true || extra.scoreCertificateValid !== false : extra.scoreCertificateValid !== true)))) throw new Error("Mandatory independent audit failed");
      return { originalAuditor: oldPin, extraAuditor: journalPin };
    };
    try {
      // Both actual transports and native handles close before any mandatory closing audit.
      try { await server.stop(false); } finally { journal.close(); }
      save(join(output, "failure-and-transport-state.json"), { completed: false, fatal, proxy: proxy.state(), anomalies: proxy.anomalies, workerClosures, engineStops: engineStops.map(value => value.status), lockRetained: true });
      summary(false, "provisional_integrity");
      if (!fatal && operationallyComplete) {
        validate(); validateFrozen(output, true);
        const provisional = audit(true);
        // Preserve both provisional reports before the final mandatory passes write their own reports.
        const copyExact = (source: string, target: string) => { const raw = readFileSync(source), fd = openSync(target, "wx", 0o600); try { writeFileSync(fd, raw); fsyncSync(fd); } finally { closeSync(fd); } return pin(target); };
        const provisionalPins = { summary: copyExact(join(output, "summary.json"), join(output, "provisional-summary.json")),
          originalAuditor: copyExact(provisional.originalAuditor.path, join(output, "provisional-originalAuditor-audit.json")),
          extraAuditor: copyExact(provisional.extraAuditor.path, join(output, "provisional-extraAuditor-audit.json")) };
        summary(true, "operational_complete_final_audit_pending", provisionalPins);
        const liveAudits = audit(false), finalAudits = { originalAuditor: copyExact(liveAudits.originalAuditor.path, join(output, "final-originalAuditor-audit.json")),
          extraAuditor: copyExact(liveAudits.extraAuditor.path, join(output, "final-extraAuditor-audit.json")) };
        validate(); validateFrozen(output, true);
        const certificate = { protocol: fixture ? "scientific-journal-native-fixture-certificate-v1" : "scientific-journal-final-certificate-v1", campaign,
          completed: !fixture, mockWorkflowCompleted: Boolean(fixture), scoreCertificateValid: !fixture, externalModelCalls: fixture ? 0 : undefined,
          auditedSummary: pin(join(output, "summary.json")), source: pin(join(output, "source.json")), manifest: pin(join(output, "manifest.json")),
          export: pin(join(output, "journal-export.json")), ledger: pin(join(output, "api-ledger.json")), workers: pin(join(output, "worker-closure.json")),
          currency: pin(join(output, "paid-resource-closure.json")), auditors: finalAudits, provisionalPins, externalModelCallsByThisAuditor: 0 };
        save(join(output, "final-certificate.json"), certificate);
        await lock.release({ campaign, output, store, certificate: pin(join(output, "final-certificate.json")), ...certificate });
        completed = true;
      }
      if (!completed) {
        summary(false, "failed_closed");
        await admission.failed({ campaign, output, journal: journal.snapshot(), anomalies: proxy.anomalies, workerClosures, lockPath: lock.path });
      }
    } catch (error) {
      completed = false; fatal ??= error instanceof Error ? error.name + ":" + error.message : "ClosingEvidenceError";
      try { summary(false, "closing_error"); save(join(output, "closing-failure.json"), { campaign, completed: false, fatal, lockRetained: true }); } catch {}
      try { await admission.failed({ campaign, output, fatal, journal: journal.snapshot(), lockPath: lock.path }); } catch {}
    }
  }
  return { output, campaign, completed: fixture ? false : completed, mockWorkflowCompleted: fixture ? completed : undefined, formalResultsCertified: fixture ? false : completed, recordedTaskRuns: indexes.length, fatal };
  } catch (error) {
    const evidence = { campaign, observedAt: now(), completed: false, phase: "startup_or_closing_error", lockRetained: true,
      note: "No provider forwarding occurs before journal/proxy startup. On a later closing error, do not infer zero fee; retain journal and raw evidence.",
      modelPhaseEnabled, confirmedNoProviderForward: !modelPhaseEnabled,
      error: error instanceof Error ? error.name + ":" + error.message : "CampaignFailure" };
    try { save(join(output, "startup-or-closing-failure.json"), evidence); } catch {}
    try { await admission.failed({ ...evidence, output, lockPath: lock.path }); } catch {}
    throw error;
  }
}
if (import.meta.main) {
  const [mode = "prepare", profile = "full", list = "chembench,aime,cmt"] = process.argv.slice(2);
  if (mode === "prepare") console.log(JSON.stringify(prepareScientificJournal(profile, list.split(","))));
  else if (mode === "fixture" && profile === "--local-mock-only") console.log(JSON.stringify(await runScientificNativeFixture()));
  else if (mode === "recipe") {
    const { prepareOpenRouterScientific } = await import("./openrouter-scientific-admission.ts");
    if (!profile || !list) throw new Error("recipe requires <profile> <comma-separated-benchmarks> [capUsd]");
    console.log(JSON.stringify(await prepareOpenRouterScientific(profile, list.split(","), process.argv[5] === undefined ? undefined : Number(process.argv[5]))));
  }
  else if (mode === "run") {
    const recipeFile = process.argv[5];
    if (!recipeFile || profile !== "full" || list !== "chembench,aime,cmt") throw new Error("Explicit run full 'chembench,aime,cmt' <reviewed-recipe.json> required");
    if (process.env.OBJRUN_SCIENCE_GRADER_TOKEN_FILE) {
      const token = readFileSync(resolve(process.env.OBJRUN_SCIENCE_GRADER_TOKEN_FILE), "utf8").trim();
      if (!token || token.length > 4096 || /[\r\n\0]/.test(token)) throw new Error("Invalid host-only grader token file");
      process.env.TGENGIN_GRADER_TOKEN = token;
    }
    if (process.env.TGENGIN_GRADER_TOKEN && !process.env.TGENGIN_GRADER_ORIGINS) throw new Error("Explicit nonsecret trusted grader origins are required");
    const { scientificPaidAdmission } = await import("./scientific-journal-admission.ts");
    console.log(JSON.stringify(await runScientificJournal(profile, list.split(","), scientificPaidAdmission(recipeFile))));
  }
  else throw new Error("Use explicit prepare or run");
}

/** Same worker/closing code; strict new F namespace, synthetic4/10s, no production admission or real provider. */
export async function runScientificNativeFixture() {
  const { createCnyCashShadow, verifyCashClosure } = await import("./cny-cash-shadow-v2.ts");
  const { actualPin } = await import("./paid-resource-proof-v2.ts");
  const area = join(root, ".scratch", "scientific-native-four-engine-" + randomUUID()); mkdirSync(area, { recursive: true });
  const rows = Array.from({ length: 4 }, (_, index) => ({ id: `public-native-${index}`, prompt: `Public synthetic engine lifecycle task${index}. Submit one fixed public string. This is not a benchmark result.` }));
  const keyEnv = "OBJRUN_SCIENTIFIC_NATIVE_KEY", key = "local-only-" + randomUUID(), graderToken = "local-grader-" + randomUUID();
  const previous = new Map([keyEnv, "TGENGIN_GRADER_TOKEN", "TGENGIN_GRADER_ORIGINS", "OBJRUN_REPAIR_WORKERS"].map(name => [name, process.env[name]]));
  let forwarded = 0, active = 0, peak = 0, grades = 0, standClosed = false;
  let firstFourReady!: () => void; const firstFour = new Promise<void>(resolve => firstFourReady = resolve);
  const stand = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/health") return Response.json({ fixture: true, externalModelCalls: 0 });
    if (path === "/problems") return Response.json(rows);
    if (request.method === "POST" && ["/parsed", "/correct"].includes(path)) {
      if (request.headers.get("x-objrun-grader-token") !== graderToken) return new Response("Unauthorized synthetic grader", { status: 401 });
      grades++; return Response.json({ value: true, valid: true, note: "Synthetic positive control only" });
    }
    return new Response("Unsupported synthetic route", { status: 404 });
  } });
  const origin = `http://127.0.0.1:${stand.port}`;
  process.env[keyEnv] = key; process.env.TGENGIN_GRADER_TOKEN = graderToken; process.env.TGENGIN_GRADER_ORIGINS = origin; process.env.OBJRUN_REPAIR_WORKERS = "4";
  const plan = (campaign: string) => {
    const catalogs = { chembench: rows.map(row => ({ officialId: row.id, row, promptSha256: digest(scientificPrompt("chembench", row)) })) };
    const tasks = catalogs.chembench.map((task, index) => ({ ...task, index, benchmark: "chembench", arm: index % 2 ? "F" as const : "U" as const, replica: 0 as const,
      prompt: scientificPrompt("chembench", task.row), seconds: 10, route: `${campaign}/chembench/${index % 2 ? "F" : "U"}/0/${task.officialId}`, taskId: `${campaign}/chembench/${index % 2 ? "F" : "U"}0/${task.officialId}` }));
    const taskSchedule = tasks.map(({ index, benchmark, arm, replica, officialId, promptSha256 }) => ({ index, benchmark, arm, replica, officialId, promptSha256 }));
    return { tasks, catalogs, datasets: { chembench: { selectedTaskIds: rows.map(row => row.id), fixture: true, fullOfficialDenominator: 500, officialDatasetNotRun: true } },
      calibration: undefined, taskSchedule, taskScheduleSha256: digest(JSON.stringify(taskSchedule)), fullScientificRuns: 1220 };
  };
  let state: { campaign: string; output: string; store: string } | undefined, cash: ReturnType<typeof createCnyCashShadow> | undefined;
  const tickets = new Map<number, Parameters<ReturnType<typeof createCnyCashShadow>["finish"]>[0]>(), registrations: Record<string, unknown>[] = [];
  const ensureCash = () => cash ??= createCnyCashShadow({ directory: join(state!.store, "currency"), runId: state!.campaign, providerKind: "local-mock",
    prices: actualPin(join(root, "docs/repair-2026-10-08/deepseek-cny-price-readonly.json")),
    journal: { directory: state!.store, configPin: actualPin(join(state!.store, "journal-config.json")), sourcePin: actualPin(join(import.meta.dir, "campaign-journal.ts")) } });
  const admission: ScientificPaidAdmission = {
    capUsd: 100, priorCampaignCostUpperBoundUsd: 0, metadata: { scope: "F-only private native owner; not production canonical admission", realCostUsd: 0, realCostCny: 0, syntheticUsage: true },
    executionFiles: ["paid-campaign-lock.ts", "cny-cash-shadow-v2.ts", "paid-resource-proof-v2.ts"].map(name => `scripts/benchmark-repair/${name}`),
    async acquireLock(input) {
      if (input.root !== area) throw new Error("Fixture cannot acquire the production root");
      const owned = acquirePaidCampaignLock(input);
      return { path: owned.path, async release(proof) {
        const certificate = JSON.parse(readFileSync((proof.certificate as { path: string }).path, "utf8"));
        if (certificate.protocol !== "scientific-journal-native-fixture-certificate-v1" || certificate.mockWorkflowCompleted !== true || certificate.scoreCertificateValid !== false) throw new Error("Mock certificate cannot claim a provider score");
        for (const item of Object.values(certificate.auditors) as { path: string }[]) if (JSON.parse(readFileSync(item.path, "utf8")).integrityValid !== true) throw new Error("Mock independent integrity audit failed");
        const closure = JSON.parse(readFileSync(certificate.currency.path, "utf8")); verifyCashClosure(closure.cashClosePin);
        const pids = registrations.map(row => row.pid as number), script = `$out=@();foreach($n in @(${pids.join(",")})){try{$p=Get-Process -Id $n -ErrorAction Stop;$out+=[pscustomobject]@{pid=$n;present=$true}}catch{if($_.FullyQualifiedErrorId -like 'NoProcessFoundForGivenId*'){$out+=[pscustomobject]@{pid=$n;present=$false}}else{throw}}};ConvertTo-Json -Compress -InputObject $out`;
        const closed = JSON.parse(execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { windowsHide: true }).toString());
        if (closed.length !== 4 || closed.some((row: { present: boolean }) => row.present)) throw new Error("Owned native PID remains live");
        for (const row of registrations) { let responding = false; try { responding = (await fetch(String(row.base) + "/health", { signal: AbortSignal.timeout(300) })).ok; } catch {} if (responding) throw new Error("Owned native port remains open"); }
        await stand.stop(false); standClosed = true;
        save(join(state!.output, "native-owned-close.json"), { protocol: "native-local-owned-close-v1", processes: closed, enginePortsClosed: true, mockGraderClosed: true, externalModelCalls: 0 });
        owned.release();
      } };
    },
    async prepareStore(input) {
      const store = join(area, ".phase1-data/repair", input.campaign); mkdirSync(store, { recursive: true }); state = { campaign: input.campaign, output: input.output, store };
      const path = join(input.output, "native-store.json"); save(path, { protocol: "scientific-native-store-v1", campaign: input.campaign, physicalStore: store }); return pin(path);
    },
    registerWorker(input) { registrations.push(input); save(join(input.output, `native-process-${input.worker}.json`), { protocol: "native-local-process-v1", ...input, observedAt: now() }); },
    beforeForward(admitted, prefix, raw, route) {
      const value = ensureCash().beforeForward({ id: `${state!.campaign}/${admitted.requestSeq}`, route, rawRequest: Buffer.from(raw), capturedRequest: actualPin(admitted.requestFile), journal: { admitted, startPrefix: prefix as never } });
      tickets.set(admitted.requestSeq, value.ticket); if (!value.admitted) throw new Error(value.reason);
    },
    afterDurableFinish(receipt) { ensureCash().finish(tickets.get(receipt.requestSeq)!, { kind: "journal-finish", journalRef: receipt.journalRef as never }); },
    afterFailedJournalCapture(request, _finish, evidence) {
      const seq = (request as { requestSeq?: number } | undefined)?.requestSeq;
      if (seq === undefined || !tickets.has(seq)) { cash?.poison("source_admission_fault"); return; }
      const files = evidence.files as { path: string; sha256: string }[], responsePin = files.find(file => file.path.endsWith("response.json.gz"));
      ensureCash().finish(tickets.get(seq)!, { kind: "failed-capture", requestSeq: seq, evidence: { files, responsePin, rawResponseSha256: evidence.rawResponseSha256 as string | undefined,
        usage: evidence.usage, httpStatus: evidence.httpStatus as number | undefined, providerAttempted: evidence.providerAttempted as boolean, originalPrefix: (evidence.journalSnapshot as { durablePrefix: never }).durablePrefix, reason: "native_source_capture_failure" } });
    },
    certify() { const cashClosePin = ensureCash().close(), value = JSON.parse(readFileSync(cashClosePin.path, "utf8"));
      return { valid: value.releasePermitted === true, accountingClosed: value.snapshot.pendingCount === 0 && value.snapshot.newUnknownCount === 0,
        providerKind: "local-mock", actualCostUsd: 0, actualCostCny: 0, externalModelCalls: 0, cashClosePin }; },
    failed(input) { cash?.poison("native_fixture_failure"); if (state) save(join(state.output, "native-failure.json"), { ...input, actualCostUsd: 0, externalModelCalls: 0 }); },
  };
  try {
    const result = await runScientificJournal("native-fixture", ["chembench"], admission, { brand: NATIVE_FIXTURE_BRAND, root: area, key, keyEnv, origin, plan,
      transport: async () => { const id = forwarded++; active++; peak = Math.max(peak, active); if (forwarded === 4) firstFourReady();
        try {
          if (id < 4) await Promise.race([firstFour, Bun.sleep(5000).then(() => { throw new Error("Four-engine first request barrier timed out"); })]);
          await Bun.sleep(100);
          return { httpStatus: 200, rawResponse: JSON.stringify({ id: `local-native-${id}`, model: "local-mock", choices: [{ message: { role: "assistant", content: null,
            tool_calls: [{ id: `submit-${id}`, type: "function", function: { name: "submit", arguments: JSON.stringify({ answer: "fixed public synthetic answer" }) } }] }, finish_reason: "tool_calls" }], usage: { prompt_tokens: 10, completion_tokens: 2 } }) };
        } finally { active--; }
      } });
    const report = { ...result, area, realProviderRequests: 0, actualCostUsd: 0, actualCostCny: 0, syntheticCompletionCalls: forwarded, providerPeak: peak, active,
      distinctEnginePids: registrations.map(row => row.pid), physicalMockGCalls: grades, sameProductionWorkerAndClosingCode: true,
      plannedSyntheticTasks: 4, syntheticSeconds: 10, productionPlanUnchanged: "Full1220;600/1800s", observedAt: now(), standClosed, privateOwnerOnly: true };
    save(join(area, "native-fixture-report.json"), report); return report;
  } finally {
    try { if (!standClosed) await stand.stop(true); } finally { for (const [name, value] of previous) if (value === undefined) delete process.env[name]; else process.env[name] = value; }
  }
}
