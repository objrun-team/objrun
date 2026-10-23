/** Separate ChemIQ F900 entry. Preparation is metadata-only; paid/cold operations require explicit run. */
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, statfsSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { freemem } from 'node:os';
import { gunzipSync, gzipSync } from 'node:zlib';
import { finalCandidate } from '../../app/src/objective/candidate.ts';
import { graderFetch } from '../../app/src/engine/registry.ts';
import { createCampaignJournal, inspectCampaignJournal } from './campaign-journal.ts';
import { classifyGeneration, gradeFixedCandidate } from './campaign-contract.ts';
import { ScientificJournalProxy, captureProviderResponse, type TaskReceipt } from './scientific-journal-proxy.ts';
import { createCnyCashShadow } from './cny-cash-shadow-v2.ts';
import { loadChemiqProvenance } from './chemiq-nextwave-contract.ts';
import { scientificWorkerResources } from './scientific-journal-resources.ts';
import { actualPin, demand, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_FAMILY, CHEMIQ_F_ROOT, CHEMIQ_F_SETTINGS, ChemiqRouteSeal, assertChemiqRecordSet, chemiqObjective, chemiqOutput, chemiqStore,
  loadChemiqFPlan, validateChemiqRecipe, type ChemiqFPlan, type ChemiqFRecipe, type ChemiqFScope } from './chemiq-f-journal-contract-v2.ts';
import { acquireChemiqPaidResource, durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';
import { observeChemiqOwned } from './chemiq-f-owned-v2.ts';
import { ChemiqGradingRecorder } from './chemiq-f-grading-recorder-v2.ts';
import { createChemiqModelWitness } from './chemiq-f-model-witness-v2.ts';
import { auditChemiqFArtifacts } from './audit-chemiq-f-journal-v2.ts';

const ROOT = CHEMIQ_F_ROOT, DOC = join(ROOT, 'docs/repair-2026-10-08'), PYTHON = 'D:/ProgramData/anaconda3/python.exe';
const PRIVATE_ORIGIN = 'http://127.0.0.1:17918';
const now = () => new Date().toISOString();
export const CHEMIQ_F_EXECUTION_FILES = ['chemiq-f-journal-campaign-v2.ts', 'chemiq-f-journal-contract-v2.ts', 'chemiq-f-paid-admission-v2.ts', 'chemiq-f-owned-v2.ts', 'chemiq-f-grading-recorder-v2.ts', 'audit-chemiq-f-journal-v2.ts',
  'chemiq-f-model-witness-v2.ts', 'chemiq-private-boundary-v2.ts', 'chemiq-cold96-v2.ts', 'chemiq-resource-readonly-v2.py', 'chemiq-provider-readonly-v2.ts', 'chemiq-official-price-v2.ts', 'chemiq-other-paid-discovery-v2.ts',
  'chemiq-f-paid-admission-v1.ts', 'chemiq-f-journal-contract.ts', 'audit-chemiq-f-journal.ts', 'chemiq-f-owned.ts',
  'campaign-journal.ts', 'campaign-contract.ts', 'scientific-journal-proxy.ts', 'scientific-journal-plan.ts', 'campaign-workers.ts', 'scientific-journal-resources.ts',
  'chemiq-nextwave-contract.ts', 'chemiq-grader-provenance.py', 'freeze-scientific-journal.py', 'paid-resource-admission-v2.ts', 'paid-resource-proof-v2.ts', 'cny-cash-shadow-v2.ts',
  'scientific-startup-proof.ts', 'financial-interruption-closure-v1.ts', 'financial-interruption-release.ts', 'jpg-paid-resource-admission-v1.ts', 'jpg-journal-contract.ts'].map(n => 'scripts/benchmark-repair/' + n);
function files(path: string): string[] { return readdirSync(path, { withFileTypes: true }).flatMap(e => e.isDirectory() ? files(join(path, e.name)) : e.isFile() ? [join(path, e.name)] : []); }
function sourcePins(extra: Pin[] = []) {
  for (const pin of extra) verifyPin(pin);
  const list = [...files(join(ROOT, 'app/src')).filter(p => /\.(ts|html)$/.test(p)), ...['test/_lib.ts', 'app/package.json', 'app/bun.lock', 'app/tsconfig.json', 'examples/benchmark/_lib/gradelib.py',
    'examples/benchmark/chemiq/stand.py', ...CHEMIQ_F_EXECUTION_FILES].map(p => join(ROOT, p)), ...extra.map(p => p.path)];
  return [...new Set(list)].sort().map(actualPin);
}
export function chemiqAdditionalExecutionFiles(pins: Pin[]) {
  return [...new Set([...CHEMIQ_F_EXECUTION_FILES, ...pins.filter(p => resolve(p.path).startsWith(resolve(ROOT, 'scripts/benchmark-repair') + '\\')).map(p => p.path.slice(ROOT.length + 1).replaceAll('\\', '/'))])];
}
export function prepareChemiqF(scope: ChemiqFScope = 'pilot16', runId = 'repair-' + now().replace(/[:.]/g, '-'), seed?: Partial<ChemiqFRecipe>) {
  const plan = loadChemiqFPlan(runId, scope), directory = join(DOC, 'chemiq-f-journal-preparations-v2', runId);
  demand(!existsSync(directory), 'chemiq_prepare_never_overwrites'); mkdirSync(directory, { recursive: true });
  const pins = sourcePins(seed?.jpgDScanner?.executionPins), recipe: ChemiqFRecipe = {
    protocol: 'chemiq-f-journal-recipe-v2', family: CHEMIQ_F_FAMILY, runId, scope, mode: seed ? 'real-provider' : 'prepare', createdAtUtc: now(), settings: CHEMIQ_F_SETTINGS,
    taskScheduleSha256: plan.taskScheduleSha256, output: chemiqOutput(runId), store: chemiqStore(runId), sourcePins: pins, sourceExecutionDigest: hash(JSON.stringify(pins)),
    hostExecutors: { bun: actualPin(process.execPath), python: actualPin(PYTHON) }, balance: seed?.balance,
    prices: seed?.prices ?? actualPin(join(DOC, 'deepseek-cny-price-readonly.json')), modelAvailability:seed?.modelAvailability, runtimeGate: seed?.runtimeGate, fullAuthorization: seed?.fullAuthorization,
    financialBoundary: seed?.financialBoundary, deferredFault: actualPin(join(DOC, 'scientific-campaign-deferred-fault.json')),
    originalPidClosure: actualPin(join(DOC, 'science1220-oom-original-process-closure.json')), requestedNewEnvelopeCny: seed?.requestedNewEnvelopeCny,
    headroomCny: seed?.headroomCny ?? '30', userResourceDirective: seed?.userResourceDirective, capUsd: seed?.capUsd, priorCampaignCostUpperBoundUsd: seed?.priorCampaignCostUpperBoundUsd,
    workers: seed?.workers ?? 4, modelCallsByPreparation: 0, providerForwardingEnabled: false, jpgDScanner: seed?.jpgDScanner, preparationInventory: [],
  };
  const manifestPin = durableChemiqJson(join(directory, 'manifest.json'), { protocol: 'chemiq-f-preparation-v2', family: CHEMIQ_F_FAMILY, runId, scope,
    taskSchedule: plan.taskSchedule, taskScheduleSha256: plan.taskScheduleSha256, originalQuestionDenominator: 816, plannedTaskRuns: plan.tasks.length,
    settings: CHEMIQ_F_SETTINGS, providerForwardingEnabled: false, modelCalls: 0, paidLockTaken: false, formalPaidReady: false });
  const publicPin = durableChemiqJson(join(directory, 'public-tasks.json'), plan.tasks.map(({ officialId, promptSha256, row }) => ({ officialId, promptSha256, row })));
  recipe.preparationInventory = [manifestPin, publicPin]; validateChemiqRecipe(recipe);
  const recipePin = durableChemiqJson(join(directory, 'recipe.json'), recipe);
  return { recipePin, manifestPin, publicPin, scope, plannedTaskRuns: plan.tasks.length, modelCalls: 0, formalPaidReady: false, executedSourceDigest: recipe.sourceExecutionDigest };
}
async function pythonOperation(args: string[], timeoutMs = 120000) {
  return await new Promise<void>((resolve, reject) => {
    const child = spawn(PYTHON, ['-B', '-X', 'utf8', ...args], { cwd: ROOT, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '', timeout = false; child.stdout.on('data', () => {}); child.stderr.on('data', b => { stderr += b.toString(); if (stderr.length > 65536) child.kill('SIGKILL'); });
    const timer = setTimeout(() => { timeout = true; child.kill('SIGKILL'); }, timeoutMs);
    child.once('error', e => { clearTimeout(timer); reject(e); }); child.once('close', code => { clearTimeout(timer); code === 0 && !timeout ? resolve() : reject(Error('ChemIQ native operation failed:' + code + ':' + (timeout ? 'timeout' : stderr.slice(0, 2048)))); });
  });
}
function validateFreeze(output: string, dependencies = false) {
  const source = jsonPin(actualPin(join(output, 'source.json'))), archive = jsonPin(actualPin(join(output, 'frozen-source.json')));
  for (const p of [...source.files, ...source.repairFiles, ...(dependencies ? archive.dependencyFiles : [])]) verifyPin({ ...p, path: join(ROOT, p.path) });
  if (dependencies) verifyPin({ path: archive.archive, bytes: archive.archiveBytes, sha256: archive.archiveSha256 }); return { source, archive };
}
function requestBytes(path: string, bytes: Buffer) {
  const data = gzipSync(bytes), fd = openSync(path, 'wx', 0o600); try { writeFileSync(fd, data); fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(path).equals(data), 'chemiq_unadmitted_capture_readback'); return actualPin(path);
}
function captureStoppedTask(directory: string, task: ChemiqFPlan['tasks'][number], target: string) {
  const { Database } = require('bun:sqlite'), database = join(directory, 'data/h2h.sqlite'), db = new Database(database, { readonly: true });
  const tracePath = join(target, `trace-${task.index}.jsonl`), fd = openSync(tracePath, 'wx', 0o600), classifyTrace: any[] = [];
  let traceRows = 0, explicitVerifyCalls = 0; const invoke = (sql: string, params: any[] = []) => db.query(sql).all(...params);
  try {
    for (const row of db.query('select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like ? order by unit,seq').iterate(task.taskId + '#%')) {
      writeFileSync(fd, JSON.stringify(row) + '\n'); traceRows++;
      if (row.role === 'system' && row.kind === 'inject') classifyTrace.push({ role: row.role, kind: row.kind, body: row.body });
      if (row.kind === 'call') try { explicitVerifyCalls += JSON.parse(row.body).calls?.filter((c: any) => c.name === 'verify').length ?? 0; } catch {}
    }
    fsyncSync(fd);
    const candidate = finalCandidate({ all: invoke, run() { throw Error('readonly'); }, exec() { throw Error('readonly'); }, close() {} } as never, task.taskId);
    const rows = invoke('select state,result,created_at,solve_seconds from task where id=?', [task.taskId]); demand(rows.length === 1 && rows[0].solve_seconds === 900, 'chemiq_stopped_task_identity');
    return { candidate, terminal: rows[0], classifyTrace, traceRows, explicitVerifyCalls, tracePin: actualPin(tracePath) };
  } finally { closeSync(fd); db.close(); }
}
function secretAudit(plan: ChemiqFPlan, output: string, store: string, values: string[]) {
  const distinct = [...new Set(values)]; demand(distinct.length >= 2 && distinct.every(v => v.length >= 16), 'chemiq_secrets_available_for_scan');
  const findings: any[] = []; let checkedFiles = 0;
  for (const path of [...files(output), ...files(store)].filter(path => !/frozen-source\.zip$/.test(path))) {
    // Configs contain only key-env names, but scan them too; no config is put in the source ZIP.
    const bytes = readFileSync(path), payload = path.endsWith('.gz') ? gunzipSync(bytes, { maxOutputLength: 65 * 1024 ** 2 }) : bytes; checkedFiles++;
    distinct.forEach((secret, i) => { if (payload.includes(Buffer.from(secret))) findings.push({ path, valueIndex: i }); });
  }
  // Source archive contains only exact public execution/dependency members. Scan their real bytes too.
  const source = jsonPin(actualPin(join(output, 'source.json'))), archive = jsonPin(actualPin(join(output, 'frozen-source.json')));
  for (const record of [...source.files, ...source.repairFiles, ...archive.dependencyFiles]) {
    const bytes = readFileSync(join(ROOT, record.path)); distinct.forEach((secret, i) => { if (bytes.includes(Buffer.from(secret))) findings.push({ publicSource: record.path, valueIndex: i }); });
  }
  return durableChemiqJson(join(output, 'secret-audit.json'), { protocol: 'chemiq-f-evidence-secret-audit-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId,
    passed: findings.length === 0, valuesChecked: distinct.length, valueHashes: distinct.map(hash), findings, checkedFiles, sourceAndDependencyMembersChecked: source.files.length + source.repairFiles.length + archive.dependencyFiles.length,
    rawGzipExpanded: true, headersArchived: false, privateConfigArchived: false, limits: ['Archive contents are bound by source freeze SHA; public source/dependency file bytes were scanned.', 'Only the actual model and grader header secrets used by this entry are claimed; unrelated host secrets are not certified.'] });
}

export async function runChemiqF(recipePin: Pin) {
  const recipe = jsonPin(recipePin) as ChemiqFRecipe, plan = validateChemiqRecipe(recipe, true);
  const providerKey = process.env.DEEPSEEK_API_KEY, graderToken = process.env.TGENGIN_GRADER_TOKEN;
  demand(providerKey && graderToken && providerKey.length >= 16 && graderToken.length >= 16, 'chemiq_host_credentials_absent');
  const trusted = (process.env.TGENGIN_GRADER_ORIGINS ?? '').split(',').map(s => s.trim()); demand(trusted.includes(PRIVATE_ORIGIN), 'chemiq_explicit_private_origin');
  const memory = scientificWorkerResources({ requested: recipe.workers, freeMemoryBytes: freemem() }); demand(memory.selected === recipe.workers, 'chemiq_frozen_worker_memory');
  const diskVolumes = ['C:/', ROOT].map(path => { const observed = statfsSync(path); return { path, freeBytes: observed.bavail * observed.bsize }; });
  const startupResource = durableChemiqJson(join(dirname(recipePin.path), `startup-resource-${Date.now()}.json`), {
    protocol: 'chemiq-f-startup-resource-observation-v2', observedAtUtc: now(), modelCalls: 0, paidLockTaken: false,
    diskVolumes, diskFloorBytes: 1024 ** 3, memory, sourcePin: actualPin(import.meta.path),runId:plan.runId,family:CHEMIQ_F_FAMILY,
    validated: diskVolumes.every(d => d.freeBytes >= 1024 ** 3) && memory.selected === recipe.workers,
  });
  demand(jsonPin(startupResource).validated === true, 'chemiq_startup_actual_volume_floor');
  for (const p of Object.values(recipe.hostExecutors)) verifyPin(p);
  const lease = await acquireChemiqPaidResource(recipe);
  const output = recipe.output, store = recipe.store; mkdirSync(store, { recursive: true });
  const gate = new ChemiqRouteSeal(), registrations: Pin[] = [], workerClosures: any[] = [], records = new Map<number, any>(), engines = new Map<number, any>();
  let modelForwardingEnabled = false, fatal: string | undefined, generationClosedAtUtc: string | undefined, next = 0, financialStopReason: string | undefined;
  let providerServer: ReturnType<typeof Bun.serve> | undefined, gradeServer: ReturnType<typeof Bun.serve> | undefined;
  let providerPort=0,gradePort=0;
  let journal: ReturnType<typeof createCampaignJournal> | undefined, cash: ReturnType<typeof createCnyCashShadow> | undefined, proxy: ScientificJournalProxy | undefined;
  let recorder: ChemiqGradingRecorder | undefined, provenance: ReturnType<typeof loadChemiqProvenance> | undefined;
  let rejected = 0;
  const validate = () => { verifyPin(recipePin); lease.validateForwardSource(); validateFreeze(output); provenance?.validate(); };
  const disk = () => { for (const path of [output, store]) demand(statfsSync(path).bavail * statfsSync(path).bsize >= 1024 * 1024 ** 2, 'chemiq_owned_evidence_disk_floor'); };
  try {
    disk(); provenance = loadChemiqProvenance(ROOT, store); provenance.audit('startup');
    const health = await graderFetch(PRIVATE_ORIGIN + '/health', { signal: AbortSignal.timeout(120000) }); demand(health.ok, 'chemiq_private_grader_health');
    const profile = await health.json(); demand(profile.items === 816 && profile.level === 0 && profile.opsin.profile === 'local-2.8' && profile.opsin.rest_fallback === false && profile.length_policy === 'raw-input-length', 'chemiq_live_profile');
    const problems = await graderFetch(PRIVATE_ORIGIN + '/problems?n=816', { signal: AbortSignal.timeout(120000) }); demand(problems.ok, 'chemiq_live_book');
    const publicRows = await problems.json(), byId = new Map(publicRows.map((r: any) => [r.id, r])); demand(publicRows.length === 816 && byId.size === 816, 'chemiq_live_denominator');
    const { scientificPrompt } = await import('./scientific-journal-plan.ts');
    for (const task of plan.tasks) demand(byId.has(task.officialId) && hash(scientificPrompt('chemiq', byId.get(task.officialId)!)) === task.promptSha256, 'chemiq_live_prompt');
    const manifest = { protocol: 'chemiq-f-journal-manifest-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, campaign: plan.runId, createdAt: now(), scope: plan.scope,
      profile: plan.scope, benchmarks: ['chemiq'], arms: ['F'], providerKind: 'real-provider', model: 'deepseek-flash', provider: 'https://api.deepseek.com',
      recipePin, startupResourcePin:startupResource, taskSchedule: plan.taskSchedule, taskScheduleSha256: plan.taskScheduleSha256, fullDenominator: 816, plannedTaskRuns: plan.tasks.length, taskSeconds: 900,
      settings: CHEMIQ_F_SETTINGS, requestedCycleMaxUnits: 12, allowedTools: ['submit', 'verify', 'task_tree', 'node_load'], freshMachinePerTask: true,
      concurrency: recipe.workers, journalDirectory: store, capUsd: recipe.capUsd, priorCampaignCostUpperBoundUsd: recipe.priorCampaignCostUpperBoundUsd,
      hostExecutors: { bun: { path: process.execPath, version: Bun.version }, python: { path: PYTHON } }, additionalExecutionFiles: chemiqAdditionalExecutionFiles(recipe.sourcePins),
      graderProvenance: { chemiq: provenance.metadata }, recipeExecutionDigest: recipe.sourceExecutionDigest,
      limits: ['NewF900 protocol, not all legacy settings reproduced', 'Explicit verify5 is not allphysicalG', 'Trial16 cannot be claimed816', 'Root-owned private grader stays running; only ownedmodelengines/proxy/recordinggateway close'] };
    durableChemiqJson(join(output, 'manifest.json'), manifest);
    await pythonOperation([join(import.meta.dir, 'freeze-scientific-journal.py'), output, store]);
    const frozen = validateFreeze(output, true), manifestPin = actualPin(join(output, 'manifest.json'));
    journal = createCampaignJournal({ directory: store, campaign: plan.runId, capUsd: recipe.capUsd!, priorCampaignCostUpperBoundUsd: recipe.priorCampaignCostUpperBoundUsd!, outputDirectory: output });
    cash = createCnyCashShadow({ directory: join(store, 'currency'), runId: plan.runId, providerKind: 'real-provider', admission: lease, prices: recipe.prices,
      journal: { directory: store, configPin: actualPin(join(store, 'journal-config.json')), sourcePin: actualPin(join(import.meta.dir, 'campaign-journal.ts')) } });
    recorder = new ChemiqGradingRecorder(plan, join(store, 'physical-grading'), PRIVATE_ORIGIN, graderToken!);
    gradeServer = Bun.serve({ hostname: '127.0.0.1', port: 0, maxRequestBodySize: 4 * 1024 ** 2, fetch: request => recorder!.handle(request) });
    gradePort=gradeServer.port;
    const gradeOrigin = 'http://127.0.0.1:' + gradeServer.port;
    process.env.TGENGIN_GRADER_ORIGINS = [...new Set([...trusted, gradeOrigin])].join(',');
    proxy = createChemiqModelWitness({ runId: plan.runId, journal, cash, seal: gate, routes: new Set(plan.tasks.map(t => t.route)), failureDirectory: join(store, 'journal-failures'),
      beforeAdmission() { validate(); verifyPin(manifestPin); disk(); }, onFinancialStop(reason) { financialStopReason = reason; },
      transport: async raw => captureProviderResponse(await fetch('https://api.deepseek.com/chat/completions', { method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + providerKey }, body: raw, signal: AbortSignal.timeout(300000) })) });
    providerServer = Bun.serve({ hostname: '127.0.0.1', port: 0, maxRequestBodySize: 4 * 1024 ** 2, async fetch(request) {
      const got = Buffer.from(request.headers.get('authorization') ?? ''), want = Buffer.from('Bearer ' + providerKey);
      if (got.length !== want.length || !timingSafeEqual(got, want)) return Response.json({ error: 'Unauthorized host provider proxy' }, { status: 401 });
      const path = new URL(request.url).pathname;
      if (request.method !== 'POST' || !path.endsWith('/v1/chat/completions')) return new Response('Unplanned route', { status: 404 });
      const route = path.slice(1, -'/v1/chat/completions'.length), raw = await request.text();
      try { gate.check(route); } catch {
        const ordinal = rejected++, gzipPin = requestBytes(join(store, `unadmitted-${ordinal}-request.json.gz`), Buffer.from(raw));
        durableChemiqJson(join(store, `unadmitted-${ordinal}.json`), { family: CHEMIQ_F_FAMILY, runId: plan.runId, route, requestPin: gzipPin, requestRawSha256: hash(raw), providerAttempted: false, confirmedNoForward: true, why: 'route_sealed_or_deadline', observedAtUtc: now() });
        return Response.json({ error: 'Model route sealed or deadline exceeded' }, { status: 409 });
      }
      const result = await proxy!.handle(route, raw); return new Response(result.rawResponse, { status: result.httpStatus, headers: { 'content-type': 'application/json' } });
    } });
    const objective = chemiqObjective(gradeOrigin), { machine } = await import('../../test/_lib.ts');
    providerPort=providerServer.port;
    process.env.BUN_JSC_forceRAMSize = String(512 * 1024 ** 2); modelForwardingEnabled = true;
    async function worker() {
      while (next < plan.tasks.length && !fatal && !proxy!.state().stopReason) {
        const task = plan.tasks[next++], directory = join(store, `task-${task.index}`); mkdirSync(directory);
        let engine: Awaited<ReturnType<typeof machine>> | undefined, routeOpened = false;
        try {
          validate(); disk(); engine = await machine({ maxTokens: 8192, retryTimes: 0, continueTimes: 0, reasoningEffort: 'none', temperature: 0, seed: 42 }, { directory, keep: true }); engines.set(task.index, engine);
          const registered = durableChemiqJson(join(output, `paid-process-${task.index}.json`), { protocol: 'paid-owned-process-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, ownerNonce: lease.owned.ownerNonce,
            taskIndex: task.index, pid: engine.pid, base: engine.base, startedAtUtc: now(), role: 'native Bun owned cold task engine' }); lease.registerOwnedProcess(registered); registrations.push(registered);
          await engine.api('POST', '/exec', { sql: "insert or ignore into api (key_env,model,handle,modes,base_url,retry_on) select 'DEEPSEEK_API_KEY','deepseek-flash',handle,modes,base_url,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'" });
          await engine.api('POST', '/declare', { handles: objective.nodes.map(n => ({ name: n.handle, expectMs: 120000 })), places: [{ place: 'local' }], modes: [{ mode: 'repair', cycles: [{ cycle: 'ask', apiMode: 'chat', maxUnits: 12, from: [], next: ['act'], infer: 'fn:infer.dfs' }, { cycle: 'act', maxUnits: 12, from: ['ask'], next: ['ask'], infer: 'fn:infer.dfs' }] }], agents: [{ name: 'bot', apis: [['DEEPSEEK_API_KEY', 'deepseek-flash']], unit: 'fn:unit.tools' }] });
          await engine.api('POST', '/exec', { sql: "update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')" });
          await engine.api('POST', '/exec', { sql: "update api set base_url=:endpoint,retry_on='[]' where key_env='DEEPSEEK_API_KEY' and model='deepseek-flash'", params: { endpoint: `http://127.0.0.1:${providerServer!.port}/${task.route}/v1` } });
          const started = Date.now(); gate.open(task.route, started); routeOpened = true;
          await engine.api('POST', '/tasks', { id: task.taskId, run: plan.runId, mode: 'repair', agent: 'bot', place: 'local', source: 'user', description: task.prompt, objective, readable: false, solveSeconds: 900, maxBranches: 4, maxDeadSiblings: 100000, noSearch: ['all'] });
          let terminal: any, creationBound = false;
          while (Date.now() - started < 1050000) {
            const state = await engine.api<any>('GET', `/tasks/${encodeURIComponent(task.taskId)}/status`);
            if (!creationBound) { gate.bindCreation(task.route, state.created_at); creationBound = true; }
            const result = state.result ? JSON.parse(state.result) : undefined;
            if (['done', 'failed'].includes(state.state) && result && !['finalization_pending', 'finalization_error'].includes(result.outcome)) { terminal = state; break; }
            if (Date.now() >= state.created_at + 900000) { gate.seal(task.route, 'declared_deadline'); }
            await Bun.sleep(250);
          }
          gate.seal(task.route, terminal ? 'terminal_status' : 'hard_deadline'); await proxy!.drain(task.route);
          await Promise.race([engine.stop(), new Promise<never>((_, reject) => setTimeout(() => reject(Error('Owned engine stop timeout')), 10000))]); engines.delete(task.index);
          workerClosures.push({ taskIndex: task.index, pid: engine.pid, base: engine.base, stopReturned: true, observedAtUtc: now() });
          const captured = captureStoppedTask(directory, task, output), calls = proxy!.takeTaskReceipts(task.route), runtime = captured.terminal.result ? JSON.parse(captured.terminal.result) : { outcome: 'finalization_pending', valid: false };
          const generation = classifyGeneration({ runtimeVerdict: runtime, state: captured.terminal.state, calls, trace: captured.classifyTrace, candidate: captured.candidate?.body });
          const dbPath = join(directory, 'data/h2h.sqlite'), taskDatabasePin = actualPin(dbPath), taskWalPin = existsSync(dbPath + '-wal') ? actualPin(dbPath + '-wal') : null;
          const record = { family: CHEMIQ_F_FAMILY, runId: plan.runId, index: task.index, benchmark: 'chemiq', arm: 'F', replica: 0, officialId: task.officialId, taskId: task.taskId,
            state: captured.terminal.state, runtimeVerdict: runtime, generationValid: generation.valid, generationClassification: generation,
            actualCreatedAt: captured.terminal.created_at, declaredDeadlineAt: captured.terminal.created_at + 900000, candidateDeadlinePolicy: 'frozen-finalCandidate-at<=created+solve_seconds',
            startedAtUtc: new Date(started).toISOString(), seconds: (Date.now() - started) / 1000, answer: captured.candidate?.body ?? '', candidateHow: captured.candidate?.how ?? 'none', candidateSha256: hash(captured.candidate?.body ?? ''),
            promptSha256: task.promptSha256, tracePin: captured.tracePin, traceSha256: captured.tracePin.sha256, traceRows: captured.traceRows, explicitVerifyCalls: captured.explicitVerifyCalls,
            callIds: calls.map(r => r.requestSeq), journalRefs: calls.map(r => r.journalRef), engineRegistrationPin: registered, taskDatabasePin, taskWalPin, shmNotDataIdentity: true,
            acceptance: { valid: false, outcome: 'pending_after_all_generation' } };
          durableChemiqJson(join(output, `task-${task.index}.json`), record); records.set(task.index, record);
          if (!generation.valid) { fatal ??= 'generation_invalid:' + generation.outcome; proxy!.stop(fatal); }
        } catch (error) {
          fatal ??= error instanceof Error ? error.name + ':' + error.message : 'worker_failure'; proxy!.stop('worker_failure');
          durableChemiqJson(join(output, `worker-${task.index}-failure.json`), { family: CHEMIQ_F_FAMILY, runId: plan.runId, taskIndex: task.index, observedAtUtc: now(), error: fatal, completed: false });
        } finally {
          if (routeOpened) gate.seal(task.route, 'worker_finally'); await proxy!.drain(task.route);
          if (engine && engines.has(task.index)) { try { await Promise.race([engine.stop(), new Promise<never>((_, reject) => setTimeout(() => reject(Error('Owned engine stop timeout')), 10000))]); engines.delete(task.index); } catch { fatal ??= 'owned_stop_failed'; } }
        }
      }
    }
    await Promise.allSettled(Array.from({ length: recipe.workers }, () => worker()));
    proxy.stop('all_generation_closed'); await proxy.drain(); await providerServer.stop(false); await recorder.drain(); generationClosedAtUtc = now();
    const exported = journal.exportLegacyLedger(); durableChemiqJson(join(output, 'journal-export.json'), exported);
    const actualDifferentTasksForwarded=new Set(jsonPin(exported).calls.filter((r:any)=>r.providerAttempted===true).map((r:any)=>r.route)).size;
    if(actualDifferentTasksForwarded!==plan.tasks.length) fatal??='not_all_selected_tasks_forwarded_to_real_provider';
    if (!fatal && records.size === plan.tasks.length) {
      recorder.finalPhase();
      for (const task of plan.tasks) {
        const record = records.get(task.index)!; record.acceptance = await gradeFixedCandidate({ objective, task: { id: task.taskId }, candidate: record.candidateHow === 'none' ? undefined : record.answer,
          generation: record.generationClassification, expectedCandidateSha256: record.candidateSha256 }); durableChemiqJson(join(output, `task-${task.index}.json`), record, true);
      }
      try { assertChemiqRecordSet(plan, [...records.values()]); } catch (e) { fatal ??= String(e); }
    } else fatal ??= 'incomplete_fixed_schedule';
    await recorder.drain(); await gradeServer.stop(false); journal.close(); provenance.audit('shutdown'); validate(); validateFreeze(output, true);
    const cashClosed = cash.close(), cashResult = jsonPin(cashClosed); demand(cashResult.releasePermitted === true, 'chemiq_financial_accounting_not_closed');
    durableChemiqJson(join(output, 'currency-close.json'), { protocol: 'chemiq-f-currency-close-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, cashClosePin: cashClosed });
    const gradingPin = recorder.closeArtifact(join(output, 'grading-close.json'));
    const actorPin = await observeChemiqOwned(output, registrations, [providerPort, gradePort], 'close');
    const ownedPin = durableChemiqJson(join(output, 'owned-close.json'), { protocol: 'chemiq-f-owned-close-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, closed: true,
      registrationPins: registrations, observationPin: actorPin, proxyPort: providerPort, gradePort, workerClosures, privateSharedGraderRemoved: false });
    const sourcePin = durableChemiqJson(join(output, 'source-close.json'), { protocol: 'chemiq-f-source-close-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, pins: recipe.sourcePins, recipeExecutionDigest: recipe.sourceExecutionDigest });
    const inspection = inspectCampaignJournal(store), rawPin = durableChemiqJson(join(output, 'raw-close.json'), { protocol: 'chemiq-f-raw-close-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId,
      journalPrefix: inspection.prefix, recordedUsageUpperBoundUsd: inspection.snapshot!.recordedUsageUpperBoundUsd, ledgerPin: actualPin(join(output, 'api-ledger.json')), unadmittedCount: rejected });
    const secrets = secretAudit(plan, output, store, [providerKey!, graderToken!]);
    const financialOnly = !!fatal && ['cash_envelope_exhausted', 'fee_cap'].includes(financialStopReason ?? journal.snapshot().stopReason ?? '');
    const kind = financialOnly ? 'financial-abort' : 'score';
    const summaryPin = durableChemiqJson(join(output, 'summary.json'), { protocol: 'chemiq-f-operational-summary-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, scope: plan.scope,
      plannedTaskRuns: plan.tasks.length, recordedTaskRuns: records.size, actualDifferentTasksForwarded, fatal: fatal ?? null, financialOnly, financialStopReason: financialStopReason ?? journal.snapshot().stopReason ?? null,
      operationalComplete: !fatal && records.size === plan.tasks.length, formalFull816Score: false, scoreCertificateValid: false, generationClosedAtUtc,
      providerForwardingClosed: true, gradeServerClosed: true, sealRecords: gate.records(), proxyState: proxy.state(), gradeState: recorder.state(), activeEngines: engines.size, secretAuditPin: secrets,
      physicalGCalls: recorder.state().receipts, explicitVerifyCalls: [...records.values()].reduce((n, r) => n + r.explicitVerifyCalls, 0), createdAtUtc: now() });
    const audit = auditChemiqFArtifacts(output, kind), auditorPin = durableChemiqJson(join(output, 'independent-audit.json'), audit);
    const cert = durableChemiqJson(join(output, 'close-certificate.json'), { protocol: 'chemiq-f-close-certificate-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, scope: plan.scope, kind,
      createdAtUtc: now(), financialClosed: true, scoreCertificateValid: kind === 'score', full816ScoreCertified: audit.full816ScoreCertified,
      summary: summaryPin, source: sourcePin, owned: ownedPin, cash: cashClosed, grading: gradingPin,
      journal: actualPin(join(store, 'journal-config.json')), raw: rawPin, auditor: auditorPin, auditorSourcePin: actualPin(join(import.meta.dir, 'audit-chemiq-f-journal-v2.ts')), originalUnknownSettled: false });
    await lease.release({ certification: cert, sourceClosed: sourcePin, ownedClosed: ownedPin, cashClosed: cashClosed });
    return { family: CHEMIQ_F_FAMILY, runId: plan.runId, completed: kind === 'score', financialOnly, recordedTaskRuns: records.size, full816ScoreCertified: audit.full816ScoreCertified, output };
  } catch (error) {
    proxy?.stop('closing_failure'); try { await proxy?.drain(); } catch {}
    for (const engine of engines.values()) try { await Promise.race([engine.stop(), new Promise<never>((_, reject) => setTimeout(() => reject(Error('Owned engine stop timeout')), 10000))]); } catch {}
    try { await providerServer?.stop(false); } catch {} try { await recorder?.drain(); await gradeServer?.stop(false); } catch {} try { journal?.close(); } catch {}
    durableChemiqJson(join(output, 'failure.json'), { protocol: 'chemiq-f-failure-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, observedAtUtc: now(), error: error instanceof Error ? error.name + ':' + error.message : 'failure',
      modelForwardingEnabled, recordedTaskRuns: records.size, proxy: proxy?.state(), cash: cash?.snapshot(), originalUnknownSettled: false, lockRetained: true }); throw error;
  }
}
if (import.meta.main) {
  const [mode = 'prepare', value = 'pilot16', seedFile] = process.argv.slice(2);
  if (mode === 'prepare') console.log(JSON.stringify(prepareChemiqF(value as ChemiqFScope, undefined, seedFile ? JSON.parse(readFileSync(seedFile, 'utf8')) : undefined)));
  else if (mode === 'run') { demand(value && value !== 'pilot16', 'chemiq_explicit_recipe_file'); console.log(JSON.stringify(await runChemiqF(actualPin(resolve(value))))); }
  else throw Error('Use explicit prepare pilot16 [reviewed-resource-seed.json], or run <reviewed-recipe.json>');
}
