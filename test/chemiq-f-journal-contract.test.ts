import { afterAll, expect, test } from 'bun:test';
import { randomUUID } from 'node:crypto';
import { closeSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { Database } from 'bun:sqlite';
import { spawn } from 'node:child_process';
import { actualPin, hash, jsonPin, same, verifyPin, type Pin } from '../scripts/benchmark-repair/paid-resource-proof-v2.ts';
import { CHEMIQ_F_FAMILY, CHEMIQ_F_ROOT, CHEMIQ_F_SETTINGS, CHEMIQ_F_SCOPE_PIN, CHEMIQ_F_READINESS_PIN, CHEMIQ_F_BOOK_SHA,
  CHEMIQ_F_STAND_SHA, CHEMIQ_F_PROVENANCE_SHA, ChemiqRouteSeal, assertChemiqRuntimeGate, assertChemiqRecordSet, chemiqObjective, loadChemiqFPlan, validateChemiqRecipe } from '../scripts/benchmark-repair/chemiq-f-journal-contract.ts';
import { addChemiqPrior, chemiqCashEnvelope, durableChemiqJson } from '../scripts/benchmark-repair/chemiq-f-paid-admission-v1.ts';
import { ChemiqGradingRecorder } from '../scripts/benchmark-repair/chemiq-f-grading-recorder.ts';
import { assertChemiqOwnedFrame, chemiqActorCommand } from '../scripts/benchmark-repair/chemiq-f-owned.ts';
import { assertChemiqJournalExport, chemiqTrace } from '../scripts/benchmark-repair/audit-chemiq-f-journal.ts';
import { chemiqAdditionalExecutionFiles, prepareChemiqF, CHEMIQ_F_EXECUTION_FILES } from '../scripts/benchmark-repair/chemiq-f-journal-campaign.ts';
import { finalCandidate } from '../app/src/objective/candidate.ts';
import { createCampaignJournal, inspectCampaignJournal } from '../scripts/benchmark-repair/campaign-journal.ts';
import { createCnyCashShadow, verifyCashClosure } from '../scripts/benchmark-repair/cny-cash-shadow-v2.ts';
import { createChemiqModelWitness } from '../scripts/benchmark-repair/chemiq-f-model-witness.ts';

const root = CHEMIQ_F_ROOT, area = join(root, '.scratch/chemiq-f-journal-tests', randomUUID()); mkdirSync(area, { recursive: true });
const runId = 'repair-2026-10-09T00-00-00-000Z', plan = loadChemiqFPlan(runId, 'pilot16'), full = loadChemiqFPlan(runId, 'full816');
const before = [...CHEMIQ_F_EXECUTION_FILES.map(p => actualPin(join(root, p))), actualPin(import.meta.path), CHEMIQ_F_SCOPE_PIN, CHEMIQ_F_READINESS_PIN];
const old = jsonPin(actualPin(join(root, 'test/fixtures/repair/campaigns/repair-2026-10-08T18-32-57-118Z/source.json')));
const protected81 = [...old.files, ...old.repairFiles].map((p: any) => actualPin(resolve(root, p.path)));
function fresh(name: string) { const directory = join(area, name); mkdirSync(directory); return directory; }
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
function gate() { return { protocol: 'chemiq-f-runtime-control-gate-v1', family: CHEMIQ_F_FAMILY, validated: true, modelCalls: 0, officialQuestionCount: 816, observedAtUtc: new Date().toISOString(),
  standSourcePin: { sha256: CHEMIQ_F_STAND_SHA }, provenancePin: { sha256: CHEMIQ_F_PROVENANCE_SHA }, datasetPin: { sha256: CHEMIQ_F_BOOK_SHA },
  profile: { items: 816, level: 0, length_policy: 'raw-input-length', opsin: { profile: 'local-2.8', version: '2.8.0', rest_fallback: false, jar_sha256: 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab' } },
  privateGrader: { networkMode: 'none', cleanInterpreter: true, solverToolsDisabled: true, containerId: 'a'.repeat(64) }, missingPositiveReferenceCount: 34,
  controls: plan.tasks.map(t => ({ officialId: t.officialId, positive: { valid: true, value: true }, wrongValue: { valid: true, value: false }, wrongFormat: { valid: true, value: false } })) }; }
function record(task: any) { return { family: CHEMIQ_F_FAMILY, index: task.index, officialId: task.officialId, arm: 'F', replica: 0, promptSha256: task.promptSha256,
  generationValid: true, candidateSha256: hash('synthetic wrong answer'), candidateDeadlinePolicy: 'frozen-finalCandidate-at<=created+solve_seconds', declaredDeadlineAt: 900000,
  acceptance: { valid: true, passed: false, outcome: 'rejected', candidateSha256: hash('synthetic wrong answer') } }; }
function balance(at = Date.now()) { return { protocol: 'deepseek-resource-readonly-v1', provider: 'https://api.deepseek.com', endpoint: '/user/balance', method: 'GET', httpStatus: 200,
  isAvailable: true, observedAtUtc: new Date(at).toISOString(), modelCalls: 0, credentialPrinted: false, balances: [{ currency: 'CNY', total_balance: '100.00', granted_balance: '0', topped_up_balance: '100.00' }] }; }

test('real816 public projection and fixed16 F900 preserve original order/14 strata/five methods without answers', () => {
  expect(plan.tasks.length).toBe(16); expect(full.tasks.length).toBe(816); expect(new Set(plan.tasks.map(t => t.officialId)).size).toBe(16);
  expect(new Set(plan.tasks.map(t => t.category + '/' + t.subCategory)).size).toBe(14); expect(new Set(plan.tasks.map(t => t.method)).size).toBe(5);
  expect(plan.tasks.every((t, i) => t.arm === 'F' && t.seconds === 900 && (i === 0 || plan.tasks[i - 1].officialIndex < t.officialIndex))).toBe(true);
  expect(plan.tasks.every(t => !['answer', 'meta_data', 'smiles', 'verification_method'].some(k => k in t.row))).toBe(true);
  expect(same(CHEMIQ_F_SETTINGS, { model: 'deepseek-flash', temperature: 0, seed: 42, reasoningEffort: 'none', maxTokens: 8192, solveSeconds: 900, checks: 5, maxBranches: 4, maxDeadSiblings: 100000, search: false, readable: false, reuse: 'text' })).toBe(true);
  expect(chemiqObjective('http://127.0.0.1:12345').checks).toBe(5); expect(() => chemiqObjective('http://example.org:12345')).toThrow();
});
test('runtime contract rejects gap/stale/foreign profile and duplicate controls; pure flags do not mint a cold certificate', () => {
  expect(() => assertChemiqRuntimeGate(gate(), plan)).not.toThrow(); expect(() => assertChemiqRuntimeGate(gate(), full)).toThrow();
  for (const edit of [ (g: any) => g.observedAtUtc = new Date(Date.now() - 600001).toISOString(), (g: any) => g.family = 'other',
    (g: any) => g.profile.length_policy = 'parsed-length', (g: any) => g.controls.push(g.controls[0]), (g: any) => g.controls[0].positive.value = false,
    (g: any) => g.privateGrader.cleanInterpreter = false ]) { const g = gate(); edit(g); expect(() => assertChemiqRuntimeGate(g, plan)).toThrow(); }
});
test('metadata prepare creates no lock/provider/engine and real-provider mode requires an actual resource/runtime recipe', () => {
  const identity = 'repair-' + new Date().toISOString().replace(/[:.]/g, '-'), result = prepareChemiqF('pilot16', identity), recipe = jsonPin(result.recipePin);
  expect(result.modelCalls).toBe(0); expect(result.formalPaidReady).toBe(false); expect(recipe.providerForwardingEnabled).toBe(false);
  expect(validateChemiqRecipe(recipe).tasks.length).toBe(16); expect(existsSync(recipe.store)).toBe(false); expect(existsSync(recipe.output)).toBe(false);
  expect(() => validateChemiqRecipe(recipe, true)).toThrow('chemiq_production_recipe_not_ready');
  durableChemiqJson(join(area, 'metadata-preparation-result.json'), { result, productionCalled: false, canonicalLockTaken: false });
});
test('the frozen JPG D scanner execution graph is unioned once and cannot omit its own module from source pins', () => {
  const peer = jsonPin(actualPin(join(root, 'test/fixtures/repair/jpg-D-journal-preparations/repair-2026-10-09T06-57-26-283Z/recipe.json')));
  expect(peer.sourcePins.length).toBe(95);
  const module = peer.sourcePins.find((p: Pin) => p.path.endsWith('jpg-D-paid-resource-admission-v1.ts'));
  expect(module.sha256).toBe('87d19f8afd528c3fc4f98a37f650a2d2bdb4fec5287c27b10d131c6446516beb');
  // This is a source-inventory control. The archived paid recipe remains pinned
  // to its original bytes; use newly observed current sources for the new preparation.
  const executionPins = peer.sourcePins.map((p: Pin) => actualPin(p.path));
  const identity = 'repair-' + new Date().toISOString().replace(/[:.]/g, '-'), prepared = prepareChemiqF('pilot16', identity, { jpgDScanner: { module, executionPins, exportName: 'scanJpgDRegistries' } });
  const recipe = jsonPin(prepared.recipePin); expect(validateChemiqRecipe(recipe).tasks.length).toBe(16); expect(recipe.sourcePins.every((p: Pin, i: number, all: Pin[]) => all.findIndex(a => a.path === p.path) === i)).toBe(true);
  const altered = clone(recipe); altered.jpgDScanner.executionPins = altered.jpgDScanner.executionPins.filter((p: Pin) => !same(p, module)); expect(() => validateChemiqRecipe(altered)).toThrow('chemiq_jpg_d_execution_graph');
  expect(existsSync(recipe.store)).toBe(false); expect(existsSync(recipe.output)).toBe(false);
});
test('actual frozen native source archiver makes a source-bound F ZIP without duplicate core or private task data', async () => {
  const dir = fresh('source-archive'), meta = join(dir, 'metadata'), store = join(dir, 'public-source'); mkdirSync(meta); mkdirSync(store);
  const peer = jsonPin(actualPin(join(root, 'test/fixtures/repair/jpg-D-journal-preparations/repair-2026-10-09T06-57-26-283Z/recipe.json')));
  const extras = chemiqAdditionalExecutionFiles(peer.sourcePins); expect(extras.every(p => p.startsWith('scripts/benchmark-repair/'))).toBe(true);
  const python = 'D:/ProgramData/anaconda3/python.exe', archiver = join(root, 'scripts/benchmark-repair/freeze-scientific-journal.py');
  durableChemiqJson(join(meta, 'manifest.json'), { campaign: runId, createdAt: new Date().toISOString(), benchmarks: ['chemiq'], taskScheduleSha256: plan.taskScheduleSha256,
    fixtureOnly: true, modelCalls: 0, hostExecutors: { bun: { path: process.execPath }, python: { path: python } }, additionalExecutionFiles: extras });
  const start = Date.now(); const result = await new Promise<{ code: number | null; timedOut: boolean; stdout: string; stderr: string }>((resolve, reject) => {
    const child = spawn(python, ['-B', '-X', 'utf8', archiver, meta, store], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', timedOut = false; const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL'); }, 60000);
    child.stdout.on('data', b => stdout += b.toString('utf8')); child.stderr.on('data', b => stderr += b.toString('utf8'));
    child.once('error', error => { clearTimeout(timer); reject(error); }); child.once('close', code => { clearTimeout(timer); resolve({ code, timedOut, stdout, stderr }); });
  });
  durableChemiqJson(join(dir, 'native-transcript.json'), { ...result, actualElapsedMs: Date.now() - start, fixtureOnly: true, modelCalls: 0, sourcePin: actualPin(archiver), pythonPin: actualPin(python) });
  expect(result.code).toBe(0); expect(result.timedOut).toBe(false); expect(result.stderr.trim()).toBe('');
  const source = jsonPin(actualPin(join(meta, 'source.json'))), frozen = jsonPin(actualPin(join(meta, 'frozen-source.json')));
  expect(frozen.archiveFsyncReturned).toBe(true); expect(frozen.archiveBytes).toBeGreaterThan(0); verifyPin({ path: frozen.archive, sha256: frozen.archiveSha256, bytes: frozen.archiveBytes });
  expect(new Set([...source.files, ...source.repairFiles].map((p: any) => p.path)).size).toBe(source.files.length + source.repairFiles.length);
  expect([...source.files, ...source.repairFiles].every((p: any) => !p.path.includes('.env') && !p.path.includes('chemiq.jsonl'))).toBe(true);
}, 65000);
test('CNY envelope checks fresh GET balance/currency/components and carries original four8.39218 independently', () => {
  const actual = chemiqCashEnvelope(balance(), '60', '30'); expect(actual.carry).toBe(8392180000n); expect(actual.envelope).toBe(60000000000n);
  for (const mutate of [(b: any) => b.method = 'POST', (b: any) => b.balances[0].currency = 'USD', (b: any) => b.isAvailable = false,
    (b: any) => b.balances[0].topped_up_balance = '99', (b: any) => b.observedAtUtc = new Date(Date.now() - 1800001).toISOString()]) { const b = balance(); mutate(b); expect(() => chemiqCashEnvelope(b, '60', '30')).toThrow(); }
  expect(() => chemiqCashEnvelope(balance(), '62', '30')).toThrow(); expect(() => chemiqCashEnvelope(balance(), '60', '29')).toThrow();
});
test('prior decomposition adds interrupted known cost once and refuses duplicate/unknown amounts', () => {
  expect(addChemiqPrior(1, 2, 3, false)).toBeCloseTo(80.31931532400054, 9);
  expect(() => addChemiqPrior(1, 2, 3, true)).toThrow(); expect(() => addChemiqPrior(NaN, 2, 3, false)).toThrow();
});
test('route seal rejects queued/late/reopened requests and clock rollback; actual creation binding is bounded', () => {
  let clock = 1000; const seal = new ChemiqRouteSeal(() => clock); seal.open('route', clock); expect(() => seal.check('route')).not.toThrow();
  clock += 5; seal.bindCreation('route', clock); clock = 1004; expect(() => seal.check('route')).toThrow(); clock = 901006; expect(() => seal.check('route')).toThrow();
  seal.seal('route', 'deadline'); clock = 1005; expect(() => seal.check('route')).toThrow(); expect(() => seal.open('route', clock)).toThrow(); expect(() => seal.bindCreation('route', clock)).toThrow();
});
test('exact16 record contract retains wrong answers and refuses missing/duplicate/invalid/candidate changes', () => {
  const records = plan.tasks.map(record); expect(() => assertChemiqRecordSet(plan, records)).not.toThrow();
  expect(() => assertChemiqRecordSet(plan, records.slice(1))).toThrow();
  for (const edit of [(r: any[]) => r[1] = r[0], (r: any[]) => r[0].acceptance.valid = false, (r: any[]) => r[0].candidateSha256 = '0'.repeat(64), (r: any[]) => r[0].acceptance.passed = true]) { const r = clone(records); edit(r); expect(() => assertChemiqRecordSet(plan, r)).toThrow(); }
});
test('frozen finalCandidate selects the on-time submit in a newly created SQLite fixture, ignoring late answer', () => {
  const dir = fresh('candidate'), db = new Database(join(dir, 'new-fixture.sqlite'));
  db.exec('create table task(id text,mode text,created_at integer,solve_seconds integer);create table task_repair(task text,agent text,instance text,unit integer);create table agent_bot_msg(instance text,unit integer,kind text,at integer,seq integer,body text);create table cycle(mode text,cycle text);');
  db.run('insert into task values(?,?,?,?)', ['fixture', 'repair', 1000, 900]); db.run('insert into task_repair values(?,?,?,?)', ['fixture', 'bot', 'fixture#0', 0]);
  const payload = (answer: string) => JSON.stringify({ calls: [{ name: 'submit', input: { answer } }] });
  db.run('insert into agent_bot_msg values(?,?,?,?,?,?)', ['fixture#0', 0, 'call', 900999, 1, payload('timely')]); db.run('insert into agent_bot_msg values(?,?,?,?,?,?)', ['fixture#0', 0, 'call', 901001, 2, payload('late')]);
  const conn = { all: (sql: string, args: any[]) => db.query(sql).all(...args), run() {}, exec() {}, close() {} };
  expect(finalCandidate(conn as never, 'fixture')).toEqual({ body: 'timely', how: 'submitted' }); db.close();
});
test('streamed trace inventory counts every verify and rejects a truncated final line', () => {
  const dir = fresh('trace'), path = join(dir, 'trace.jsonl'); writeFileSync(path, JSON.stringify({ kind: 'call', body: JSON.stringify({ calls: [{ name: 'verify' }, { name: 'submit' }] }) }) + '\n' + JSON.stringify({ kind: 'prompt', body: 'fixed' }) + '\n');
  expect(chemiqTrace(path)).toEqual({ rows: 2, explicitVerifyCalls: 1, stuck: false }); writeFileSync(join(dir, 'partial.jsonl'), '{"kind":"prompt"}'); expect(() => chemiqTrace(join(dir, 'partial.jsonl'))).toThrow('chemiq_trace_partial_line');
});
test('owned frame rejects alive/unknown/missing/duplicate actors or listening ports without spawning a probe', () => {
  const frame = { protocol: 'chemiq-f-native-owned-query-v1', queryHostPid: 101, processes: [{ pid: 222, state: 'absent' }], ports: [{ port: 12345, listening: false }] };
  expect(() => assertChemiqOwnedFrame(frame, [222], [12345])).not.toThrow();
  for (const edit of [(f: any) => f.processes[0].state = 'present', (f: any) => f.processes[0].state = 'unknown', (f: any) => f.processes = [], (f: any) => f.processes.push(f.processes[0]), (f: any) => f.ports[0].listening = true]) { const f = clone(frame); edit(f); expect(() => assertChemiqOwnedFrame(f, [222], [12345])).toThrow(); }
  expect(() => chemiqActorCommand([process.pid], [12345])).toThrow(); expect(() => chemiqActorCommand([222], [12345, 12345])).toThrow();
});
const token = 'local-fixture-header-only-not-a-real-secret', body = (taskId = plan.tasks[0].taskId) => JSON.stringify({ node: 'correct', input: { task: { id: taskId }, result: { body: 'synthetic' } } });
const req = (raw = body(), key = token) => new Request('http://127.0.0.1:12345/correct', { method: 'POST', headers: { 'X-ObjRun-Grader-Token': key }, body: raw });
test('host grade recorder missing/fake authorization and foreign task return401/404 without forwarding', async () => {
  let forwards = 0; const r = new ChemiqGradingRecorder(plan, fresh('grader-auth'), 'http://127.0.0.1:17918', token, { transport: async () => { forwards++; return { httpStatus: 200, rawResponse: '{"value":true}' }; } });
  expect((await r.handle(req(body(), ''))).status).toBe(401); expect((await r.handle(req(body(), 'fake'))).status).toBe(401); expect((await r.handle(req(body('foreign')))).status).toBe(404); expect(forwards).toBe(0); expect(r.state().receipts).toBe(0);
});
test('grade recorder durable rawfalse is a valid negative; official503 remains invalid and phase waits real flight', async () => {
  let release!: () => void; const dir = fresh('grader-wire'), r = new ChemiqGradingRecorder(plan, dir, 'http://127.0.0.1:17918', token, { transport: async () => { await new Promise<void>(done => release = done); return { httpStatus: 200, rawResponse: '{"value":false}' }; } });
  const work = r.handle(req()); while (!release) await Bun.sleep(1); expect(() => r.finalPhase()).toThrow(); let drained = false; const drain = r.drain().then(() => drained = true); await Bun.sleep(2); expect(drained).toBe(false); release(); expect((await work).status).toBe(200); await drain; r.finalPhase();
  const receipt = jsonPin(actualPin(join(dir, 'grade-0-receipt.json'))); expect(receipt.valid).toBe(true); expect(receipt.value).toBe(false); expect(receipt.fixtureOnly).toBe(true); expect(receipt.credentialHeadersArchived).toBe(false);
  const broken = new ChemiqGradingRecorder(plan, fresh('grader503'), 'http://127.0.0.1:17918', token, { transport: async () => ({ httpStatus: 503, rawResponse: '{"error":"infrastructure"}' }) }); expect((await broken.handle(req())).status).toBe(503); expect(broken.state().receipts).toBe(1);
});

const requestRaw = JSON.stringify({ model: 'deepseek-flash', temperature: 0, seed: 42, reasoning_effort: 'none', max_tokens: 8192, messages: [{ role: 'user', content: 'Public F-only synthetic zero-network fixture' }] });
function reply(id: number) { return { httpStatus: 200, rawResponse: JSON.stringify({ id: 'fixture-' + id, model: 'deepseek-v4-flash', choices: [{ finish_reason: 'stop', message: { role: 'assistant', content: 'synthetic candidate' } }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } }) }; }
function witness(name: string, options: { envelope?: bigint; io?: any; journalHook?: any; transport?: any } = {}) {
  const dir = fresh(name), journal = createCampaignJournal({ directory: join(dir, 'journal'), campaign: runId, capUsd: 100, priorCampaignCostUpperBoundUsd: 0 }, options.journalHook);
  const proofPin = durableChemiqJson(join(dir, 'synthetic-fixture-lease.json'), { protocol: 'paid-resource-admission-v2', scope: 'f-fixture', fixtureOnly: true, modelCalls: 0,
    runId, owned: { ownerNonce: 'synthetic-fixture-no-production-lock' }, selectedNewEnvelopeNanoCny: (options.envelope ?? 1000000000n).toString(), carryNanoCny: '8392180000', productionAdmission: false });
  const fixtureLease = { scope: 'f-fixture', clock: { wallUnixMs: Date.now, monotonicNs: () => process.hrtime.bigint() }, owned: { ownerNonce: 'synthetic-fixture-no-production-lock' }, proofPin,
    envelopeNanoCny: options.envelope ?? 1000000000n, carryNanoCny: 8392180000n, registerCash() {}, assertOwned() { verifyPin(proofPin); }, validateForwardSource() { verifyPin(proofPin); } };
  const prices = durableChemiqJson(join(dir, 'prices.json'), { protocol: 'deepseek-cny-pricing-source-snapshot-v1', observedAtUtc: new Date().toISOString(), currency: 'CNY', model: 'deepseek-flash', modelCalls: 0,
    officialSource: 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/', peak: { uncachedInput: 2, cachedInput: .04, output: 8 }, offPeak: { uncachedInput: 1, cachedInput: .02, output: 4 } });
  const cash = createCnyCashShadow({ directory: join(dir, 'cash'), runId, providerKind: 'real-provider', admission: fixtureLease as never, prices,
    journal: { directory: journal.directory, configPin: actualPin(join(journal.directory, 'journal-config.json')), sourcePin: actualPin(join(root, 'scripts/benchmark-repair/campaign-journal.ts')) }, fixtureIo: options.io });
  const seal = new ChemiqRouteSeal(); for (const route of ['a', 'b', 'c', 'd']) seal.open(route, Date.now()); let forwarded = 0, stopped: string | undefined;
  const proxy = createChemiqModelWitness({ runId, journal, cash, seal, routes: new Set(['a', 'b', 'c', 'd']), failureDirectory: join(dir, 'failures'), beforeAdmission() {}, onFinancialStop(reason) { stopped = reason; },
    transport: options.transport ?? (async () => reply(forwarded++)) });
  return { dir, journal, cash, seal, proxy, forwarded: () => forwarded, stopped: () => stopped };
}
test('the actual entry witness binds requestgzip/start/fsync/cash before in-memory transport then closed cash/raw', async () => {
  const f = witness('actual-witness'); try { expect((await f.proxy.handle('a', requestRaw)).httpStatus).toBe(200); await f.proxy.drain(); expect(f.forwarded()).toBe(1);
    const inspection = inspectCampaignJournal(f.journal.directory); expect(inspection.valid).toBe(true); expect(inspection.accountingClosed).toBe(true); const closed = f.cash.close(); expect(verifyCashClosure(closed).proof.releasePermitted).toBe(true); expect(jsonPin(closed).snapshot.carriedOriginalUnknownNanoCny).toBe('8392180000');
  } finally { f.journal.close(); }
});
test('legacy export is independently matched to every actual durable finish row and cannot alter cost/route/usage', async () => {
  const f = witness('export-binding'); try {
    await f.proxy.handle('a', requestRaw); await f.proxy.drain(); const exported = f.journal.exportLegacyLedger(), ledger = jsonPin(exported), inspection = inspectCampaignJournal(f.journal.directory);
    expect(() => assertChemiqJournalExport(ledger, inspection, runId, new Set(['a']))).not.toThrow();
    for (const edit of [(l: any) => l.recordedUsageUpperBoundUsd = 0, (l: any) => l.calls[0].route = 'foreign', (l: any) => l.calls[0].usage.completion_tokens = 99, (l: any) => l.calls = []]) { const altered = clone(ledger); edit(altered); expect(() => assertChemiqJournalExport(altered, inspection, runId, new Set(['a']))).toThrow(); }
  } finally { f.journal.close(); }
});
test('actual cash fsync failure and journal start fsync failure both stop before any provider transport', async () => {
  let armed = true; const a = witness('cash-fsync', { io: (stage: string) => { if (armed && stage === 'cash_fsync') { armed = false; throw Error('Injected actual cash fsync failure'); } } });
  try { expect((await a.proxy.handle('a', requestRaw)).httpStatus).toBe(503); expect(a.forwarded()).toBe(0); expect(() => verifyCashClosure(a.cash.close())).toThrow(); } finally { a.journal.close(); }
  let fired = false; const b = witness('journal-fsync', { journalHook: { before(op: any) { if (!fired && op.kind === 'fsync' && op.stage.startsWith('checkpoint:start:')) { fired = true; closeSync(op.fd); } } } });
  try { expect((await b.proxy.handle('a', requestRaw)).httpStatus).toBe(503); expect(b.forwarded()).toBe(0); expect(inspectCampaignJournal(b.journal.directory).accountingClosed).toBe(false); } finally { b.journal.close(); }
});
test('cash reservation denial is durably confirmed no-forward with zero new fee and original carry unaltered', async () => {
  const f = witness('deny', { envelope: 1n }); try { expect((await f.proxy.handle('a', requestRaw)).httpStatus).toBe(503); expect(f.forwarded()).toBe(0); expect(f.stopped()).toBe('cash_envelope_exhausted');
    const rows = f.proxy.takeTaskReceipts('a'); expect(rows[0].providerAttempted).toBe(false); expect(rows[0].confirmedNoForward).toBe(true); expect(f.cash.snapshot().newKnownEstimatedNanoCny).toBe('0'); expect(f.cash.snapshot().newUnknownCount).toBe(0); expect(verifyCashClosure(f.cash.close()).proof.releasePermitted).toBe(true);
  } finally { f.journal.close(); }
});
test('late-sealed queued request is not forwarded; four in-memory flights drain before closing and keep out-of-order evidence', async () => {
  const sealed = witness('sealed'); sealed.seal.seal('a', 'generation_closed'); try { expect((await sealed.proxy.handle('a', requestRaw)).httpStatus).toBe(503); expect(sealed.forwarded()).toBe(0); } finally { sealed.journal.close(); }
  const releases: (() => void)[] = []; let calls = 0; const f = witness('four', { transport: async () => { const id = calls++; await new Promise<void>(resolve => releases[id] = resolve); return reply(id); } });
  try { const work = ['a', 'b', 'c', 'd'].map(r => f.proxy.handle(r, requestRaw)); while (calls < 4) await Bun.sleep(1); let drained = false; const drain = f.proxy.drain().then(() => drained = true); await Bun.sleep(2); expect(drained).toBe(false);
    for (const i of [3, 1, 2, 0]) { releases[i](); await Bun.sleep(1); } await Promise.all(work); await drain; expect(f.cash.snapshot().pendingCount).toBe(0); expect(verifyCashClosure(f.cash.close()).proof.releasePermitted).toBe(true); expect(f.journal.snapshot().finishedRequestCount).toBe(4);
  } finally { f.journal.close(); }
});
test('finish checkpoint poison preserves every late raw capture and conservative unknown instead of minting release', async () => {
  let fired = false, calls = 0; const releases: (() => void)[] = [];
  const f = witness('poison-late', { journalHook: { before(op: any) { if (!fired && op.kind === 'fsync' && op.stage === 'checkpoint:finish:0') { fired = true; closeSync(op.fd); } } },
    transport: async () => { const id = calls++; await new Promise<void>(resolve => releases[id] = resolve); return reply(id); } });
  try { const work = ['a', 'b', 'c', 'd'].map(r => f.proxy.handle(r, requestRaw)); while (calls < 4) await Bun.sleep(1); releases[0](); await work[0]; for (const i of [1, 2, 3]) releases[i](); await Promise.all(work); await f.proxy.drain();
    expect(f.proxy.anomalies.length).toBe(4); expect(f.proxy.anomalies.every((r: any) => r.files.some((p: Pin) => p.path.endsWith('response.json.gz')))).toBe(true); expect(f.cash.snapshot().newUnknownCount).toBeGreaterThan(0); expect(() => verifyCashClosure(f.cash.close())).toThrow();
  } finally { f.journal.close(); }
});
afterAll(() => {
  const current = before.map(p => actualPin(p.path)), protectedAfter = protected81.map(p => actualPin(p.path)); expect(same(before, current)).toBe(true); expect(protected81.length).toBe(81); expect(same(protected81, protectedAfter)).toBe(true);
  durableChemiqJson(join(area, 'source-and-boundary.json'), { protocol: 'chemiq-f-zero-network-control-boundary-v1', fixtureOnly: true, productionAdmissionCalled: false,
    nativePidPortProbesCalled: false, nativeFSourceArchiverInvoked: true, httpServersStarted: 0, externalModelCalls: 0, realProviderRequests: 0, dockerCalls: 0, productionLockTaken: false,
    currentSourcePins: before, sourceUnchanged: true, protected81Before: protected81, protected81Unchanged: true, fixtureRoot: area,
    limitations: ['Synthetic providerAttempted marks only the in-memory transport.', 'These controls do not certify the actual cold grader, PID/port removal, real provider, or formal paid readiness.'] });
  console.log('CHEMIQ_ZERO_NETWORK_CONTROL_ROOT=' + area);
});
