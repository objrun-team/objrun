import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, renameSync, unlinkSync, openSync, closeSync, fsyncSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { BENCHMARK_PROVIDER, benchmarkProviderKey, officialOpenRouterFault } from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import { BENCHMARK_INFERENCE, benchmarkProviderRequest } from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts';
import { runBinaryTask } from './humaneval-binary-policy.ts';
import { recoverEmptyLengthCompletion } from './humaneval-binary-length.ts';

const ROOT = resolve(import.meta.dir, '../../..');
const HOME = join(ROOT, 'docs/evalplus-20261012/humaneval/binary-v1');
const read = (p: string) => JSON.parse(readFileSync(p, 'utf8').replace(/^\uFEFF/, ''));
const cfg = read(join(HOME, 'config.json'));
const OUT = join(HOME, 'full'), mode = process.argv[2] ?? 'full';
if (!['full', 'status', 'preflight'].includes(mode)) throw Error('Use full|status|preflight');
const hash = (s: string | Buffer) => createHash('sha256').update(s).digest('hex');
function save(p: string, v: any) { mkdirSync(dirname(p), { recursive: true }); const t = p + '.' + process.pid + '.tmp'; writeFileSync(t, JSON.stringify(v, null, 2) + '\n'); renameSync(t, p); }
function durable(p: string, v: any) { mkdirSync(dirname(p), { recursive: true }); const fd = openSync(p, 'wx'); try { writeFileSync(fd, JSON.stringify(v, null, 2) + '\n'); fsyncSync(fd); } finally { closeSync(fd); } }
function walk(p: string): string[] { return existsSync(p) ? readdirSync(p, { withFileTypes: true }).flatMap(x => x.isDirectory() ? walk(join(p, x.name)) : [join(p, x.name)]) : []; }
function pins() { for (const name of ['source-pins.json', 'length-recovery-v2-source-pins.json']) for (const f of read(join(HOME, name)).files) if (hash(readFileSync(f.path)) !== f.sha256) throw Error('FrozenSourceChanged:' + f.path); }
const records = () => walk(join(OUT, 'results')).filter(p => p.endsWith('.json')).map(read);
function totals() {
  const paths = walk(join(OUT, 'calls')), rr = paths.filter(p => p.endsWith('receipt.json')).map(read);
  const dispatches = paths.filter(p => p.endsWith('dispatch.json'));
  return { modelCalls: dispatches.length, completedCalls: rr.length, pendingCalls: dispatches.filter(p => !existsSync(join(dirname(p), 'receipt.json'))).length,
    actualCostUsd: rr.reduce((n, r) => n + (r.actualCostUsd ?? 0), 0), unknownCostCount: rr.filter(r => r.unknownCost).length,
    unknownCostUpperBoundUsd: rr.filter(r => r.unknownCost).reduce((n, r) => n + r.upperBoundUsd, 0) };
}
if (mode === 'status') { console.log(JSON.stringify({ ...(existsSync(join(OUT, 'status.json')) ? read(join(OUT, 'status.json')) : {}), verifiedRecords: records().length, ...totals() }, null, 2)); process.exit(0); }
pins();
const catalog = read(join(ROOT, 'docs/evalplus-20261012/humaneval/public-tasks.json'));
if (catalog.length !== 164 || cfg.maxChecks !== 5 || cfg.concurrency !== 2 || cfg.maxTokens !== 16384 || cfg.feedbackTests !== 'base') throw Error('UnexpectedBinaryProtocol');
const baseline = read(join(ROOT, 'docs/evalplus-20261012/humaneval/full/calls/baseline/HumanEval-0/sample-0/attempt-0/request.json'));
const sorted = (v: any): any => Array.isArray(v) ? v.map(sorted) : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k, sorted(v[k])])) : v;
function options(v: any) { const { messages, ...other } = v; return JSON.stringify(sorted(other)); }
function wire(messages: any[]) {
  const v = benchmarkProviderRequest({ model: cfg.model, messages, stream: false, temperature: 0, seed: 42, reasoning_effort: 'high', max_tokens: 16384 }, BENCHMARK_INFERENCE, BENCHMARK_PROVIDER);
  if (options(v) !== options(baseline)) throw Error('GenerationOptionsDifferFromHumanEvalBaseline');
  return v;
}
wire([{ role: 'user', content: catalog[0].prompt }]);
const key = benchmarkProviderKey(ROOT), grader = 'http://127.0.0.1:' + cfg.graderPort;
const health: any = await (await fetch(grader + '/health', { signal: AbortSignal.timeout(5000) })).json();
if (!health.ok || health.dataset !== 'humaneval' || !health.executor.includes('venv')) throw Error('UnexpectedGrader');
if (!read(join(HOME, 'controls.json')).allPassed) throw Error('ControlsNotPassed');
if (mode === 'preflight') { console.log(JSON.stringify({ ok: true, count: catalog.length, modelCalls: 0, generationOptionsMatchBaseline: true, grader: health })); process.exit(0); }

const lock = join(OUT, 'runner-lock.json');
durable(lock, { pid: process.pid, atUtc: new Date().toISOString(), command: process.argv });
const start = Date.now(); let stage = 'starting', stopReason: string | undefined; const active: any[] = [];
function status() {
  const r = records(), valid = r.filter(x => x.grade?.valid);
  save(join(OUT, 'status.json'), { dataset: 'humaneval', arm: 'binary', protocolVersion: cfg.protocolVersion, adapterVersion: 'length-recovery-v2', stage, pid: process.pid,
    atUtc: new Date().toISOString(), startedAtUtc: new Date(start).toISOString(), elapsedSeconds: (Date.now() - start) / 1000,
    completed: r.length, total: catalog.length, valid: valid.length, passed: valid.filter(x => x.grade.passed).length,
    exceptions: r.length - valid.length, sampleCount: r.reduce((n, x) => n + x.sampleCount, 0), active: [...active],
    concurrency: cfg.concurrency, maxChecks: cfg.maxChecks, feedbackTests: 'base', finalScoring: 'base+plus', stopReason, ...totals() });
}
let balanceAt = 0, remaining = 0, reserved = 0, balancePending: Promise<any> | undefined;
async function balance() {
  if (Date.now() - balanceAt < 30000) return;
  if (balancePending) return balancePending;
  balancePending = (async () => {
    const data: any = {};
    for (const name of ['credits', 'key']) {
      let last: any;
      for (let i = 0; i < 3; i++) {
        try { const r = await fetch('https://openrouter.ai/api/v1/' + name, { headers: { authorization: 'Bearer ' + key }, proxy: cfg.httpProxy, signal: AbortSignal.timeout(30000) } as any);
          const v: any = await r.json(); if (!r.ok) throw Error('BalanceHTTP' + r.status); last = v.data; break;
        } catch (e) { if (i === 2) throw e; await Bun.sleep(1000); }
      }
      data[name] = last;
    }
    const k = data.key, account = data.credits.total_credits - data.credits.total_usage;
    const limit = Math.min(k.limit_remaining ?? (k.limit == null ? Infinity : k.limit - k.usage), k.effective_budget?.remaining_usd ?? Infinity, ...(k.budgets ?? []).map((b: any) => b.remaining_usd ?? Infinity));
    if (!Number.isFinite(account) || Number.isNaN(limit)) throw Error('InvalidBalance');
    remaining = Math.min(account, limit); balanceAt = Date.now();
    save(join(OUT, 'balance-latest.json'), { atUtc: new Date().toISOString(), remainingUsd: remaining, accountRemainingUsd: account, keyRemainingUsd: Number.isFinite(limit) ? limit : null, readOnly: true });
  })(); try { await balancePending; } finally { balancePending = undefined; }
}
async function generate(short: string, index: number, messages: any[]) {
  const body = wire(messages), rawRequest = JSON.stringify(body), requestSha256 = hash(rawRequest);
  const upper = Buffer.byteLength(rawRequest) * 0.3 / 1e6 + cfg.maxTokens * 1.2 / 1e6;
  for (let attempt = 0; attempt < 3; attempt++) {
    const dir = join(OUT, 'calls', short, 'sample-' + index, 'attempt-' + attempt), receiptPath = join(dir, 'receipt.json');
    let receipt: any, response: any;
    if (existsSync(receiptPath)) {
      receipt = read(receiptPath); if (receipt.requestSha256 !== requestSha256) throw Error('CachedRequestMismatch');
      if (existsSync(join(dir, 'response.json'))) response = read(join(dir, 'response.json'));
    } else {
      if (existsSync(join(dir, 'request.json')) || existsSync(join(dir, 'dispatch.json'))) throw Error('UnresolvedDispatch:' + dir);
      pins(); await balance();
      if (remaining - reserved < upper) { stopReason = 'InsufficientAccountOrKeyBalance'; throw Error(stopReason); }
      reserved += upper;
      durable(join(dir, 'request.json'), body); durable(join(dir, 'dispatch.json'), { atUtc: new Date().toISOString(), pid: process.pid, requestSha256, upperBoundUsd: upper });
      const begin = Date.now(); let httpStatus = 0, transport: string | undefined, raw = '';
      try { const r = await fetch(BENCHMARK_PROVIDER.endpoint, { method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + key, 'X-OpenRouter-Title': 'ObjRun HumanEval binary feedback' }, body: rawRequest, proxy: cfg.httpProxy, signal: AbortSignal.timeout(600000) } as any);
        httpStatus = r.status; raw = await r.text(); writeFileSync(join(dir, 'response.raw.txt'), raw); response = JSON.parse(raw); durable(join(dir, 'response.json'), response);
      } catch (e) { transport = String(e); }
      const cost = typeof response?.usage?.cost === 'number' && Number.isFinite(response.usage.cost) && response.usage.cost >= 0 ? response.usage.cost : null;
      const rejected = [400, 401, 402, 403, 404, 429].includes(httpStatus) && !response?.id && !response?.usage;
      let fault = transport ?? response?.error?.message ?? (httpStatus === 200 ? officialOpenRouterFault(response) : 'ProviderHTTP' + httpStatus);
      if (!fault && (response?.choices?.[0]?.finish_reason === 'error' || typeof response?.choices?.[0]?.message?.content !== 'string')) fault = 'InvalidProviderCompletion';
      receipt = { atUtc: new Date().toISOString(), httpStatus, generationId: response?.id ?? null, provider: response?.provider ?? null, model: response?.model ?? null,
        usage: response?.usage ?? null, actualCostUsd: rejected ? 0 : cost, unknownCost: !rejected && cost === null, upperBoundUsd: rejected ? 0 : cost ?? upper,
        requestSha256, responseSha256: raw ? hash(raw) : null, fault, seconds: (Date.now() - begin) / 1000, finishReason: response?.choices?.[0]?.finish_reason };
      durable(receiptPath, receipt); reserved -= upper; remaining -= receipt.actualCostUsd ?? receipt.upperBoundUsd;
    }
    const truncated = recoverEmptyLengthCompletion(receipt, response, cfg.maxTokens);
    if (truncated) return truncated;
    if (receipt.httpStatus === 200 && (!receipt.fault || receipt.fault === 'MissingOrInvalidOpenRouterUsdCost') && typeof response?.choices?.[0]?.message?.content === 'string')
      return { answer: response.choices[0].message.content, receipt, finishReason: receipt.finishReason, requestSha256 };
    const fault = receipt.fault ?? '';
    if ([401, 402, 403].includes(receipt.httpStatus)) { stopReason = 'PersistentProviderFault:' + fault; throw Error(stopReason); }
    const transient = receipt.httpStatus === 0 || receipt.httpStatus === 429 || receipt.httpStatus >= 500 || /timeout|timed out|temporar|overload|fetch|socket|connection|network/i.test(fault);
    if (!transient || attempt === 2) throw Error('ProviderFault:' + fault);
    await Bun.sleep(1000 * (attempt + 1));
  }
  throw Error('FiniteProviderRetriesExhausted');
}
async function grade(tid: string, answer: string, feedback: boolean) {
  let last: any;
  for (let i = 0; i < 3; i++) {
    try { const r = await fetch(grader + '/grade', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ task_id: tid, code: answer, feedback_only: feedback }), signal: AbortSignal.timeout(180000) });
      last = await r.json(); if (r.ok && last.valid === true) return last;
    } catch (e) { last = { valid: false, passed: false, errorType: 'GraderTransport', diagnostic: String(e) }; }
    await Bun.sleep(1000 * (i + 1));
  }
  return last;
}
async function execute(task: any) {
  pins(); const short = task.officialId.replace('/', '-'), path = join(OUT, 'results', short + '.json');
  if (existsSync(path) && read(path).grade?.valid) return;
  if (!['HumanEval/32', 'HumanEval/99', 'HumanEval/145'].includes(task.officialId)) throw Error('OutsideLengthRecoveryScope');
  if (existsSync(path)) save(join(OUT, 'history', short, Date.now() + '.json'), read(path));
  const dir = join(OUT, 'tasks', short), samplePath = join(dir, 'samples.json'), began = Date.now();
  active.push({ taskId: task.officialId, startedAtUtc: new Date().toISOString() }); status();
  let result: any = { officialId: task.officialId, arm: 'binary', promptSha256: task.promptSha256, protocolVersion: cfg.protocolVersion };
  try {
    const x = await runBinaryTask({ prompt: task.prompt, prior: existsSync(samplePath) ? read(samplePath) : [],
      generate: (i, messages) => generate(short, i, messages), gradeBase: answer => grade(task.officialId, answer, true), gradeFinal: answer => grade(task.officialId, answer, false), persist: samples => save(samplePath, samples),
      freeze: (answer, stoppingReason) => save(join(dir, 'candidate.json'), { answer, sha256: hash(answer), selectedBeforePlusGrading: true, frozenAtUtc: new Date().toISOString(), stoppingReason }) });
    result = { ...result, answer: x.answer, candidateSha256: hash(x.answer), grade: x.grade, stoppingReason: x.stoppingReason, feedbackChecks: x.samples.length };
  } catch (e) { result = { ...result, error: String(e), grade: { valid: false, passed: false, errorType: 'GenerationOrEnvironmentException' } }; }
  const samples = existsSync(samplePath) ? read(samplePath) : [], rr = walk(join(OUT, 'calls', short)).filter(p => p.endsWith('receipt.json')).map(read);
  result = { ...result, sampleCount: samples.length, completedAtUtc: new Date().toISOString(), seconds: (Date.now() - began) / 1000,
    actualCostUsd: rr.reduce((n, r) => n + (r.actualCostUsd ?? 0), 0), modelCalls: rr.length, unknownCostCount: rr.filter(r => r.unknownCost).length,
    unknownCostUpperBoundUsd: rr.filter(r => r.unknownCost).reduce((n, r) => n + r.upperBoundUsd, 0) };
  save(path, result); active.splice(active.findIndex(x => x.taskId === task.officialId), 1); status();
  console.log(JSON.stringify({ taskId: task.officialId, valid: result.grade.valid, passed: result.grade.passed, samples: result.sampleCount, error: result.error, cost: result.actualCostUsd }));
}
const timer = setInterval(status, 15000);
try {
  await balance(); stage = 'running'; status(); let cursor = 0;
  await Promise.all(Array.from({ length: cfg.concurrency }, async () => { while (cursor < catalog.length && !stopReason) {
    try { await execute(catalog[cursor++]); } catch (e) { stopReason = String(e); console.error(stopReason); }
  } }));
  const r = records(); stage = stopReason ? 'needs_attention' : r.length !== catalog.length ? 'incomplete' : r.some(x => !x.grade?.valid) ? 'complete_with_exceptions' : 'complete';
  if (stage === 'complete') save(join(OUT, 'FINAL-RESULTS.json'), { dataset: 'HumanEval+', arm: 'binary', denominator: 164, passed: r.filter(x => x.grade.passed).length,
    protocol: cfg, results: r.map(x => ({ officialId: x.officialId, passed: x.grade.passed, sampleCount: x.sampleCount })), ...totals() });
} catch (e) { stopReason = String(e); stage = 'needs_attention'; process.exitCode = 1; console.error(stopReason); }
finally { clearInterval(timer); status(); unlinkSync(lock); }
