import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statfsSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import { freemem } from 'node:os';

const root = resolve(import.meta.dir, '../..');
const mode = process.argv[2] ?? 'preflight';
if (!['preflight', 'run', 'resume'].includes(mode)) throw new Error('Expected preflight, run, or resume');
const resuming = mode === 'resume';
if (resuming && !/^gpqa-binary-[0-9TZ-]+$/.test(process.argv[3] ?? '')) throw new Error('Explicit run ID required for resume');
const runId = resuming ? process.argv[3]! : `gpqa-binary-${new Date().toISOString().replace(/[:.]/g, '-')}`;
const segment = new Date().toISOString().replace(/[:.]/g, '-');
const output = join(root, 'docs/gpqa', runId);
const store = join(root, '.phase1-data/gpqa-binary', runId);
const runtime = join(store, 'runtime');
const python = join(root, 'scripts/benchmark-campaign/full-f/gpqa/.runtime/venv/Scripts/python.exe');
const key = process.env.DEEPSEEK_API_KEY?.trim();
if (!key) throw new Error('DEEPSEEK_API_KEY is absent; load the project env without printing it');
const cap = 15, concurrency = 8, maxTokens = 8192, seconds = 600;
const sha = (v: string | Buffer) => createHash('sha256').update(v).digest('hex');
function save(path: string, value: unknown) {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = path + '.tmp';
  writeFileSync(tmp, JSON.stringify(value, null, 2) + '\n');
  renameSync(tmp, path);
}
mkdirSync(output, { recursive: true }); mkdirSync(runtime, { recursive: true });
if (freemem() < 3 * 1024 ** 3 || statfsSync(root).bavail * statfsSync(root).bsize < 2 * 1024 ** 3)
  throw new Error('Insufficient memory or disk for the fixed eight-worker run');

// Freeze the actual engine source before any generation. Never copy .env or answer data.
if (!resuming) for (const name of ['app/src', 'app/package.json', 'app/bun.lock', 'app/tsconfig.json', 'test/_lib.ts',
  'scripts/benchmark-repair/campaign-contract.ts', 'examples/benchmark/gpqa/stand.py', 'scripts/gpqa-binary']) {
  mkdirSync(dirname(join(runtime, name)), { recursive: true });
  cpSync(join(root, name), join(runtime, name), { recursive: true });
}
if (!resuming) symlinkSync(join(root, 'app/node_modules'), join(runtime, 'app/node_modules'), 'junction');
const pins: { path: string; sha256: string; bytes: number }[] = [];
function pinTree(path: string) {
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '__pycache__') continue;
    const file = join(path, entry.name);
    if (entry.isDirectory()) pinTree(file);
    else { const raw = readFileSync(file); pins.push({ path: relative(runtime, file).replaceAll('\\', '/'), sha256: sha(raw), bytes: raw.length }); }
  }
}
pinTree(runtime);
const sourceDigest = sha(JSON.stringify(pins));
if (resuming) {
  const original = JSON.parse(readFileSync(join(output, 'source.json'), 'utf8'));
  if (sourceDigest !== original.sourceDigest) throw new Error('Frozen runtime changed; cannot resume');
  const controller = readFileSync(import.meta.path);
  writeFileSync(join(output, `resume-controller-${segment}.ts`), controller, { flag: 'wx' });
  save(join(output, `resume-${segment}.json`), { at: new Date().toISOString(), reason: 'Execution session interrupted after the first completed task; retain its outcome and continue uncompleted fixed tasks', controllerSha256: sha(controller), runtimeSourceDigest: sourceDigest });
} else save(join(output, 'source.json'), { sourceDigest, pins, runtime, dependencies: 'Installed app/node_modules linked; package and lockfile pinned', credentialsCopied: false });

const graderEnv = { ...process.env, TGENGIN_GPQA_HOME: join(root, '.phase1-data/gpqa'), TGENGIN_GPQA_SEED: '0', TGENGIN_GPQA_LEVEL: '0', PYTHONDONTWRITEBYTECODE: '1' };
const readyPath = join(store, `grader-ready-${segment}.json`);
const graderArgs = [join(runtime, 'scripts/gpqa-binary/stand_binary.py'), '--source', join(runtime, 'examples/benchmark/gpqa/stand.py'), '--ready', readyPath, '--events', join(output, 'grader-events.jsonl')];
const graderSelftest = JSON.parse(execFileSync(python, [...graderArgs, '--selftest'], { env: graderEnv, encoding: 'utf8', windowsHide: true }).trim());
save(join(output, 'grader-selftest.json'), graderSelftest);
const officialHeaders = { authorization: `Bearer ${key}` };
const modelsResponse = await fetch('https://api.deepseek.com/models', { headers: officialHeaders, signal: AbortSignal.timeout(30000) });
const models = await modelsResponse.json() as any;
if (!modelsResponse.ok || !models.data?.some((m: any) => m.id === 'deepseek-flash')) throw new Error(`Official model-list preflight failed: HTTP ${modelsResponse.status}`);
save(join(output, resuming ? `official-models-${segment}.json` : 'official-models.json'), { observedAt: new Date().toISOString(), endpoint: 'https://api.deepseek.com/models', response: models });
const balanceResponse = await fetch('https://api.deepseek.com/user/balance', { headers: officialHeaders, signal: AbortSignal.timeout(30000) });
const balance = await balanceResponse.json() as any;
if (!balanceResponse.ok || balance.is_available !== true) throw new Error(`Official account unavailable: HTTP ${balanceResponse.status}`);
save(join(store, resuming ? `balance-resume-${segment}.json` : 'balance-before.json'), { observedAt: new Date().toISOString(), response: balance });

const manifest: any = { runId, createdAt: new Date().toISOString(), mode, benchmark: 'GPQA Diamond', taskCount: 198, arm: 'F-binary',
  provider: 'https://api.deepseek.com', model: 'deepseek-flash', modelVersionFromOfficialDocs: 'DeepSeek-V4.1-Flash-1017',
  thinking: { type: 'disabled' }, search: false, temperature: 0, requestedSeed: 42, datasetShuffleSeed: 0, maxTokensPerRequest: maxTokens,
  feedback: 'one answer-dependent bit; format failure and incorrect choice have identical rejection; no explanation or correct answer',
  checksPerAttempt: 5, maxBranches: 4, maxDeadSiblings: 100000, solveSeconds: seconds, concurrency, capUsd: cap,
  allowedTools: ['submit', 'verify', 'task_tree', 'node_load'], sourceDigest,
  ratesPeakUsdPerMillion: { input: 0.3, cachedInput: 0.006, output: 1.2 },
  pricingSource: 'https://api-docs.deepseek.com/quick_start/pricing/', thinkingSource: 'https://api-docs.deepseek.com/guides/thinking_mode/',
  costMeaning: 'Frozen peak-rate token-cost upper bound, not invoiced charges; unknown transport cost retains the request reservation',
  datasetSource: JSON.parse(readFileSync(join(root, '.phase1-data/gpqa/source.json'), 'utf8')),
  datasetSha256: sha(readFileSync(join(root, '.phase1-data/gpqa/dataset/gpqa_diamond.csv'))),
  limits: ['Official model alias is not a pinned checkpoint; no same-model causal comparison with October 8.',
    'Four answer choices are enumerable within this verification budget; this measures verifier-assisted solving, not pass@1.',
    'The API seed is requested, not a claim of provider determinism.'] };
if (resuming) {
  const original = JSON.parse(readFileSync(join(output, 'manifest.json'), 'utf8'));
  for (const field of ['model', 'capUsd', 'checksPerAttempt', 'maxBranches', 'maxDeadSiblings', 'solveSeconds', 'concurrency', 'datasetSha256', 'sourceDigest'])
    if (manifest[field] !== original[field]) throw new Error(`Resume protocol mismatch: ${field}`);
} else save(join(output, 'manifest.json'), manifest);
save(join(output, 'status.json'), { runId, stage: mode === 'preflight' ? 'preflight_passed' : 'starting', completed: 0, planned: 198, modelRequests: 0, costUpperBoundUsd: 0 });
console.log(JSON.stringify({ runId, output, mode, graderSelftest, officialApiAvailable: true, capUsd: cap }));
if (mode === 'preflight') process.exit(0);

const { machine } = await import(join(runtime, 'test/_lib.ts'));
const { campaignComplete, classifyGeneration, completionFault, gradeFixedCandidate, reconcileReceiptCost, validTokenUsage } = await import(join(runtime, 'scripts/benchmark-repair/campaign-contract.ts'));
const { finalCandidate } = await import(join(runtime, 'app/src/objective/candidate.ts'));
const { Database } = await import('bun:sqlite');
const grader = spawn(python, graderArgs, { env: graderEnv, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
let graderLog = '';
grader.stdout.on('data', d => { graderLog += d.toString(); });
grader.stderr.on('data', d => { graderLog += d.toString(); });
for (let i = 0; !existsSync(readyPath); i++) {
  if (i > 300 || grader.exitCode !== null) throw new Error(`Binary grader failed to start: ${graderLog.slice(-2000)}`);
  await Bun.sleep(100);
}
const graderPort = JSON.parse(readFileSync(readyPath, 'utf8')).port;
const graderURL = `http://127.0.0.1:${graderPort}`;
const objective = { nodes: [{ name: 'ready', domain: 'bool', moment: 'done', handle: `${graderURL}/ready` }, { name: 'correct', domain: 'bool', moment: 'done', handle: `${graderURL}/correct` }], edges: [{ src: 'ready', out: 0, dst: 'correct' }], sink: 'correct', checks: 5, reuse: 'text' };
const rows = await (await fetch(`${graderURL}/problems`)).json() as any[];
if (rows.length !== 198) throw new Error('Wrong dataset size');
const plan = rows.map((row, index) => ({ index, officialId: `gpqa-${row.index}`, prompt: `${row.question}\n\n${Object.entries(row.choices).map(([k, v]) => `${k}. ${v}`).join('\n')}\n\nEnd with exactly 'The correct answer is (X)', where X is A, B, C or D. Include the parentheses.\nSolve the task and submit your completed answer using submit. Search and filesystem tools are unavailable.` }));
manifest.tasks = plan.map(t => ({ index: t.index, officialId: t.officialId, promptSha256: sha(t.prompt) }));
manifest.graderHealth = await (await fetch(`${graderURL}/health`)).json();
manifest.objective = objective;
save(join(output, resuming ? `manifest-resume-${segment}.json` : 'manifest.json'), manifest);
save(join(store, 'public-tasks.json'), plan);
let spent = 0, reserved = 0, fatal: string | undefined, next = 0;
const calls: any[] = [], records: any[] = [], engines: any[] = [];
if (resuming) {
  const previousLedger = JSON.parse(readFileSync(join(output, 'api-ledger.json'), 'utf8'));
  const previousSummary = JSON.parse(readFileSync(join(output, 'summary.json'), 'utf8'));
  if (previousLedger.calls.some((c: any) => !c.finishedAt || c.fault) || previousLedger.reservedUpperBoundUsd > 1e-8)
    throw new Error('Unsettled previous API calls require reconciliation before resume');
  calls.push(...previousLedger.calls); records.push(...previousSummary.records);
  spent = previousLedger.recordedUsageUpperBoundUsd;
  if (records.some(r => !r.acceptance?.valid)) throw new Error('Invalid completed task requires diagnosis before resume');
}
const completedIndices = new Set(records.map(r => r.index));
const pending = new Map<string, number>();
const ledger = () => save(join(output, 'api-ledger.json'), { runId, capUsd: cap, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserved, fatal, calls });
function status(stage: string) { save(join(output, 'status.json'), { runId, stage, updatedAt: new Date().toISOString(), completed: records.length, planned: plan.length, modelRequests: calls.length, costUpperBoundUsd: spent, reservedUpperBoundUsd: reserved, fatal, passed: records.filter(r => r.acceptance?.passed).length, workers: engines.map(m => m.pid) }); }
function summary(completed: boolean) { save(join(output, 'summary.json'), { runId, completed, plannedTaskRuns: plan.length, recordedTaskRuns: records.length, generatedAt: new Date().toISOString(), recordedUsageUpperBoundUsd: spent, fatal, records }); }
const localAuth = `Bearer ${key}`;
const proxy = Bun.serve({ hostname: '127.0.0.1', port: 0, maxRequestBodySize: 4 * 1024 ** 2,
  async fetch(req) {
    const a = Buffer.from(req.headers.get('authorization') ?? ''), b = Buffer.from(localAuth);
    if (a.length !== b.length || !timingSafeEqual(a, b)) return new Response('Unauthorized', { status: 401 });
    const url = new URL(req.url);
    if (req.method !== 'POST' || !url.pathname.endsWith('/v1/chat/completions')) return new Response('Unsupported', { status: 404 });
    const route = url.pathname.slice(1, -'/v1/chat/completions'.length);
    const body = await req.json() as any;
    if (body.model !== 'deepseek-flash' || body.stream === true || body.max_tokens !== maxTokens ||
      (body.tools ?? []).some((t: any) => !manifest.allowedTools.includes(t.function?.name))) {
      fatal = 'request_protocol_violation'; ledger(); return Response.json({ error: { message: fatal } }, { status: 400 });
    }
    // Explicit official Chat Completions toggle, not an assumption about reasoning_effort=none.
    body.thinking = { type: 'disabled' }; delete body.reasoning_effort;
    const raw = JSON.stringify(body);
    const reservation = ((Buffer.byteLength(raw) + 2048 + body.messages.length * 256) * 0.3 + maxTokens * 1.2) / 1e6;
    if (fatal || spent + reserved + reservation > cap) { fatal ??= 'budget_exhausted'; ledger(); return Response.json({ error: { message: fatal } }, { status: 402 }); }
    reserved += reservation; pending.set(route, (pending.get(route) ?? 0) + 1);
    const seq = calls.length;
    const record: any = { sequence: seq, route, startedAt: new Date().toISOString(), requestSha256: sha(raw), requestFile: join(store, `request-${seq}.json.gz`),
      wireParameters: { model: body.model, thinking: body.thinking, temperature: body.temperature, seed: body.seed, max_tokens: body.max_tokens, tool_choice: body.tool_choice, tools: (body.tools ?? []).map((t: any) => t.function.name) } };
    calls.push(record);
    try {
      writeFileSync(record.requestFile, gzipSync(raw)); ledger();
      const response = await fetch('https://api.deepseek.com/chat/completions', { method: 'POST', headers: { ...officialHeaders, 'content-type': 'application/json' }, body: raw, signal: AbortSignal.timeout(300000) });
      record.httpStatus = response.status;
      const text = await response.text();
      record.responseFile = join(store, `response-${seq}.json.gz`); writeFileSync(record.responseFile, gzipSync(text)); record.responseSha256 = sha(text);
      const data = JSON.parse(text);
      record.servedModel = data.model; record.requestId = data.id; record.systemFingerprint = data.system_fingerprint;
      if (data.usage) record.usage = data.usage;
      spent += reconcileReceiptCost(record, reservation, { knownUncharged: !data.usage && [401, 402, 403, 429].includes(response.status) }).deltaUsd;
      record.reasoningContentPresent = (data.choices ?? []).some((c: any) => !!c.message?.reasoning_content || !!c.message?.reasoning);
      record.finishReasons = (data.choices ?? []).map((c: any) => c.finish_reason);
      if (!response.ok) throw new Error(`provider_http_${response.status}`);
      if (!validTokenUsage(data.usage)) throw new Error('invalid_provider_usage');
      if (record.reasoningContentPresent || (data.usage?.completion_tokens_details?.reasoning_tokens ?? 0) > 0) throw new Error('thinking_was_not_disabled');
      record.completionFault = completionFault(data); record.completionValid = !record.completionFault;
      if (record.completionFault) throw new Error(record.completionFault);
      return new Response(text, { status: response.status, headers: { 'content-type': 'application/json' } });
    } catch (error) {
      record.fault = error instanceof Error ? error.message : 'provider_error';
      spent += reconcileReceiptCost(record, reservation).deltaUsd;
      fatal ??= record.fault;
      return Response.json({ error: { message: 'Experiment provider request failed; subsequent calls stopped' } }, { status: 503 });
    } finally {
      reserved = Math.max(0, reserved - reservation); pending.set(route, Math.max(0, (pending.get(route) ?? 1) - 1));
      record.finishedAt = new Date().toISOString(); ledger(); status('running');
    }
  }
});

async function worker(workerId: number, limit = Infinity) {
  const directory = join(store, resuming ? `resume-${segment}` : '.', `worker-${workerId}`); mkdirSync(directory, { recursive: true });
  const m = await machine({ maxTokens, retryTimes: 0, continueTimes: 0, reasoningEffort: 'none', temperature: 0, seed: 42 }, { directory, keep: true });
  engines.push(m);
  await m.api('POST', '/exec', { sql: "insert or ignore into api (key_env,model,handle,modes,base_url,retry_on) select key_env,'deepseek-flash',handle,modes,base_url,'[]' from api where key_env='DEEPSEEK_API_KEY' limit 1" });
  await m.api('POST', '/declare', { handles: ['ready', 'correct'].map(node => ({ name: `${graderURL}/${node}`, expectMs: 120000 })), places: [{ place: 'local' }],
    modes: [{ mode: 'repair', cycles: [{ cycle: 'ask', apiMode: 'chat', maxUnits: 12, from: [], next: ['act'], infer: 'fn:infer.dfs' }, { cycle: 'act', maxUnits: 12, from: ['ask'], next: ['ask'], infer: 'fn:infer.dfs' }] }],
    agents: [{ name: 'bot', apis: [['DEEPSEEK_API_KEY', 'deepseek-flash']], unit: 'fn:unit.tools' }] });
  await m.api('POST', '/exec', { sql: "update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')" });
  let count = 0;
  while (next < plan.length && !fatal && count++ < limit) {
    while (next < plan.length && completedIndices.has(plan[next]!.index)) next++;
    if (next >= plan.length) break;
    const task = plan[next++], route = `${runId}/F-binary/${task.officialId}`, id = route;
    await m.api('POST', '/exec', { sql: "update api set base_url=:endpoint,retry_on='[]' where key_env='DEEPSEEK_API_KEY' and model='deepseek-flash'", params: { endpoint: `http://127.0.0.1:${proxy.port}/${route}/v1` } });
    const started = Date.now();
    await m.api('POST', '/tasks', { id, run: runId, mode: 'repair', agent: 'bot', place: 'local', source: 'user', description: task.prompt,
      objective, readable: false, solveSeconds: seconds, maxBranches: 4, maxDeadSiblings: 100000, noSearch: ['all'] });
    let terminal: any, terminalAt = 0;
    while (Date.now() - started < (seconds + 150) * 1000) {
      const state = await m.api('GET', `/tasks/${encodeURIComponent(id)}`);
      const outcome = state.result ? JSON.parse(state.result).outcome : undefined;
      if (['done', 'failed'].includes(state.state) && state.result && !['finalization_pending', 'finalization_error'].includes(outcome)) {
        terminal = state; terminalAt ||= Date.now();
        if (!(pending.get(route) ?? 0) && Date.now() - terminalAt > 2000) break;
      } else terminalAt = 0;
      if (fatal && !(pending.get(route) ?? 0)) break;
      await Bun.sleep(500);
    }
    if (!terminal) { fatal ??= 'no_terminal_result_before_deadline'; status('interrupted'); break; }
    const trace = await m.api('POST', '/query', { sql: 'select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like :prefix order by unit,seq', params: { prefix: `${id}#%` } });
    const db = new Database(join(directory, 'data/h2h.sqlite'), { readonly: true });
    let candidate: any;
    try { candidate = finalCandidate({ all: (sql: string, params: any[] = []) => db.query(sql).all(...params), run() { throw new Error('read-only'); }, exec() { throw new Error('read-only'); }, close() {} }, id); } finally { db.close(); }
    const taskCalls = calls.filter(c => c.route === route), verdict = JSON.parse(terminal.result);
    const generation = classifyGeneration({ runtimeVerdict: verdict, state: terminal.state, calls: taskCalls, trace: trace.rows, candidate: candidate?.body });
    const acceptance = await gradeFixedCandidate({ objective, task: { id }, candidate: candidate?.body, generation, expectedCandidateSha256: sha(candidate?.body ?? '') });
    const record = { index: task.index, officialId: task.officialId, taskId: id, arm: 'F-binary', state: terminal.state, runtimeVerdict: verdict,
      generationValid: generation.valid, generationClassification: generation, acceptance, seconds: (Date.now() - started) / 1000,
      answer: candidate?.body ?? '', candidateHow: candidate?.how ?? 'none', candidateSha256: sha(candidate?.body ?? ''), promptSha256: sha(task.prompt),
      traceSha256: sha(JSON.stringify(trace.rows)), apiCallSequences: taskCalls.map(c => c.sequence), costUpperBoundUsd: taskCalls.reduce((s, c) => s + (c.accountedUpperBoundUsd ?? 0), 0), worker: workerId, workerDirectory: directory };
    save(join(store, `task-${task.index}.json`), { ...record, trace: trace.rows });
    // Public summaries retain hashes and outcomes; raw answers/traces stay in the private run directory.
    const { answer, ...publicRecord } = record;
    records.push(publicRecord); summary(false); status('running');
    console.log(JSON.stringify({ completed: records.length, officialId: task.officialId, passed: acceptance.passed, valid: acceptance.valid, costUpperBoundUsd: spent }));
    if (!generation.valid || !acceptance.valid) fatal ??= `invalid_task:${task.officialId}`;
  }
  await m.stop();
}

let completed = false;
try {
  status('running');
  // First predefined task is part of the final cohort, never discarded or selected by its score.
  await worker(0, 1);
  if (!fatal) await Promise.all(Array.from({ length: concurrency }, (_, i) => worker(i + 1)));
  completed = !fatal && campaignComplete(plan.length, records);
  if (!completed) fatal ??= 'incomplete_campaign';
} catch (error) { fatal ??= error instanceof Error ? error.message : 'runner_error'; }
finally {
  for (const m of engines) await m.stop().catch(() => {});
  await proxy.stop(true); grader.kill();
  writeFileSync(join(store, 'grader.log'), graderLog);
  ledger(); summary(completed); status(completed ? 'completed' : 'interrupted');
}
console.log(JSON.stringify({ output, runId, completed, taskRuns: records.length, passed: records.filter(r => r.acceptance.passed).length, costUpperBoundUsd: spent, fatal }));
process.exitCode = completed ? 0 : 1;
