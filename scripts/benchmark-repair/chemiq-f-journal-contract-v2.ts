/** ChemIQ's separate F900 contract. No provider, grader, process or paid lock operations. */
import { existsSync, lstatSync, readFileSync, realpathSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { actualPin, demand, gzipProof, hash, inside, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { scientificPrompt } from './scientific-journal-plan.ts';
import { assertChemiqPrivateBridgeObservation, assertChemiqSolverColdObservation, CHEMIQ_PRIVATE_CID } from './chemiq-private-boundary-v2.ts';
import { parseChemiqOfficialFlashPricing } from './chemiq-official-price-v2.ts';

export const CHEMIQ_F_FAMILY = 'chemiq-f-journal-v2';
export const CHEMIQ_F_ROOT = resolve(import.meta.dir, '../..');
export const CHEMIQ_F_DOC = join(CHEMIQ_F_ROOT, 'docs/repair-2026-10-08');
export const CHEMIQ_F_SETTINGS = Object.freeze({ model: 'deepseek-flash', temperature: 0, seed: 42, reasoningEffort: 'none', maxTokens: 8192,
  solveSeconds: 900, checks: 5, maxBranches: 4, maxDeadSiblings: 100000, search: false, readable: false, reuse: 'text' });
export const CHEMIQ_F_SCOPE_PIN: Pin = Object.freeze({ path: join(CHEMIQ_F_DOC, 'chemiq-f-formal-readiness-v1/task-scope.json'), bytes: 209338, sha256: '8a1d219398fa36877a00a14c253601df9fd38dddc986726233b48c16319e6b12' });
export const CHEMIQ_F_READINESS_PIN: Pin = Object.freeze({ path: join(CHEMIQ_F_DOC, 'chemiq-f-formal-readiness-v2-900s/readiness.json'), bytes: 47205, sha256: 'bf04a9352e415c1484ee60c4761bca5b8ab180c6261ccce7644fedb8d68d50d9' });
export const CHEMIQ_F_BOOK_SHA = '4b11ba7dbcef8f075941c2e5337d687fa94d28837fc93e87a4eed1673a99646f';
export const CHEMIQ_F_STAND_SHA = '0d45cab758e9d0137dad3271618d7b37d291541144369ecc4bf892b01c916cda';
export const CHEMIQ_F_PROVENANCE_SHA = 'ffda1b12d5d0190767a9564229362371277ffd01978ff936cc25efdbd762ca39';
export type ChemiqFScope = 'pilot16' | 'full816';
export type ChemiqFTask = { index: number; officialIndex: number; benchmark: 'chemiq'; arm: 'F'; replica: 0; officialId: string; promptSha256: string;
  prompt: string; row: Record<string, unknown>; category: string; subCategory: string; method: string; seconds: 900; route: string; taskId: string };
export type ChemiqFPlan = { family: typeof CHEMIQ_F_FAMILY; runId: string; scope: ChemiqFScope; tasks: ChemiqFTask[]; taskSchedule: unknown[];
  taskScheduleSha256: string; fullDenominator: 816; datasetPin: Pin; scopePin: Pin; readinessPin: Pin; fullIdKeysetSha256: string };

export function chemiqOrdinary(path: string, boundary = CHEMIQ_F_ROOT, directory = false) {
  const p = resolve(path), root = resolve(boundary); demand(inside(root, p), 'chemiq_path_outside_owner');
  let at = p;
  while (true) {
    demand(!lstatSync(at).isSymbolicLink() && realpathSync(at).toLowerCase() === at.toLowerCase(), 'chemiq_reparse_path');
    if (at === root) break;
    at = dirname(at);
  }
  demand(directory ? lstatSync(p).isDirectory() : lstatSync(p).isFile(), 'chemiq_wrong_path_kind'); return p;
}
export function chemiqRunId(run: string) { demand(/^repair-[0-9TZ-]+$/.test(run), 'chemiq_run_identity'); return run; }
export function chemiqOutput(run: string) { return join(CHEMIQ_F_DOC, 'chemiq-f-journal-campaigns-v2', chemiqRunId(run)); }
export function chemiqStore(run: string) { return join(CHEMIQ_F_ROOT, '.phase1-data/chemiq-f-journal-v2', chemiqRunId(run)); }
export function chemiqObjective(origin: string) {
  const url = new URL(origin); demand(url.origin === origin && url.hostname === '127.0.0.1' && url.protocol === 'http:' && url.port !== '', 'chemiq_private_local_origin');
  return { nodes: [{ name: 'parsed', domain: 'bool', moment: 'done', handle: origin + '/parsed' }, { name: 'correct', domain: 'bool', moment: 'done', handle: origin + '/correct' }],
    edges: [{ src: 'parsed', out: 0, dst: 'correct' }], sink: 'correct', checks: 5, reuse: 'text' };
}
export function loadChemiqFPlan(runId: string, scope: ChemiqFScope): ChemiqFPlan {
  chemiqRunId(runId); demand(scope === 'pilot16' || scope === 'full816', 'chemiq_scope');
  const original = jsonPin(CHEMIQ_F_SCOPE_PIN), readiness = jsonPin(CHEMIQ_F_READINESS_PIN);
  demand(original.protocol === 'chemiq-f-prospective-fixed-scope-v1' && original.executed === false && original.taskSchedule.length === 816 && readiness.timeSelection.solveSeconds === 900, 'chemiq_scope_provenance');
  const book = join(CHEMIQ_F_ROOT, '.phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl'); verifyPin({ path: book, sha256: CHEMIQ_F_BOOK_SHA });
  const rows = readFileSync(book, 'utf8').trim().split(/\r?\n/).map(line => {
    const privateRow = JSON.parse(line);
    const row = Object.fromEntries(['uuid', 'question_category', 'sub_category', 'answer_format', 'prompt'].filter(k => k in privateRow).map(k => [k, privateRow[k]]));
    return { row: { ...row, id: 'chemiq-' + privateRow.uuid }, method: String(privateRow.verification_method) };
  });
  demand(rows.length === 816 && new Set(rows.map(r => r.row.id)).size === 816, 'chemiq_original_denominator');
  const selectedIds = readiness.minimumRepresentativeFPilot.taskRecords.map((r: any) => r.officialId);
  demand(selectedIds.length === 16 && new Set(selectedIds).size === 16, 'chemiq_pilot_keyset');
  const selected = new Set(scope === 'pilot16' ? selectedIds : rows.map(r => r.row.id));
  const tasks: ChemiqFTask[] = [];
  for (const [officialIndex, { row, method }] of rows.entries()) {
    const originalTask = original.taskSchedule[officialIndex], prompt = scientificPrompt('chemiq', row), officialId = row.id;
    demand(originalTask.index === officialIndex && originalTask.benchmark === 'chemiq' && originalTask.arm === 'F' && originalTask.replica === 0 && originalTask.officialId === officialId && originalTask.promptSha256 === hash(prompt), 'chemiq_scope_prompt_or_order_changed');
    if (!selected.has(officialId)) continue;
    tasks.push({ index: tasks.length, officialIndex, benchmark: 'chemiq', arm: 'F', replica: 0, officialId, promptSha256: hash(prompt), prompt, row,
      category: String(row.question_category), subCategory: String(row.sub_category), method, seconds: 900,
      route: `${runId}/chemiq/F/0/${encodeURIComponent(officialId)}`, taskId: `${runId}/chemiq/F0/${officialId}` });
  }
  demand(tasks.length === (scope === 'pilot16' ? 16 : 816), 'chemiq_selected_denominator');
  const taskSchedule = tasks.map(({ index, officialIndex, benchmark, arm, replica, officialId, promptSha256 }) => ({ index, officialIndex, benchmark, arm, replica, officialId, promptSha256 }));
  return { family: CHEMIQ_F_FAMILY, runId, scope, tasks, taskSchedule, taskScheduleSha256: hash(JSON.stringify(taskSchedule)), fullDenominator: 816,
    datasetPin: actualPin(book), scopePin: CHEMIQ_F_SCOPE_PIN, readinessPin: CHEMIQ_F_READINESS_PIN, fullIdKeysetSha256: readiness.formalTarget.fullTaskIdKeysetSha256 };
}

/** Route admission is sealed before drain/candidate extraction. All queued jobs check it again before forwarding. */
export class ChemiqRouteSeal {
  private states = new Map<string, { start: number; deadline: number; sealedAt?: number; reason?: string }>();
  constructor(private wall: () => number = Date.now) {}
  open(route: string, createdAt: number) { demand(!this.states.has(route) && Number.isFinite(createdAt), 'chemiq_route_reopen'); this.states.set(route, { start: createdAt, deadline: createdAt + 900000 }); }
  bindCreation(route: string, createdAt: number) { const s = this.states.get(route); demand(s && s.sealedAt === undefined && Number.isFinite(createdAt) && createdAt >= s.start && createdAt <= this.wall() + 5000, 'chemiq_creation_clock'); s.start = createdAt; s.deadline = createdAt + 900000; }
  check(route: string) { const s = this.states.get(route); demand(s && s.sealedAt === undefined && this.wall() >= s.start && this.wall() <= s.deadline, 'chemiq_route_closed_or_deadline'); }
  seal(route: string, reason: string) { const s = this.states.get(route); demand(s, 'chemiq_unopened_route'); if (s.sealedAt === undefined) { s.sealedAt = this.wall(); s.reason = reason; } return { route, ...s }; }
  records() { return [...this.states].map(([route, data]) => ({ route, ...data })); }
}
export function assertChemiqRuntimeGate(gate: any, plan: ChemiqFPlan, now = Date.now()) {
  demand(gate?.protocol === 'chemiq-f-runtime-control-gate-v2' && gate.family === CHEMIQ_F_FAMILY && gate.validated === true && gate.modelCalls === 0 && gate.officialQuestionCount === 816, 'chemiq_runtime_gate_type');
  const at = Date.parse(gate.observedAtUtc); demand(Number.isFinite(at) && now >= at && now - at <= 10 * 60000, 'chemiq_runtime_gate_stale');
  demand(gate.standSourcePin?.sha256 === CHEMIQ_F_STAND_SHA && gate.provenancePin?.sha256 === CHEMIQ_F_PROVENANCE_SHA && gate.datasetPin?.sha256 === CHEMIQ_F_BOOK_SHA, 'chemiq_runtime_source_profile');
  const profile = gate.profile;
  demand(profile?.items === 816 && profile.level === 0 && profile.length_policy === 'raw-input-length' && profile.opsin?.profile === 'local-2.8' && profile.opsin.version === '2.8.0' && profile.opsin.rest_fallback === false && profile.opsin.jar_sha256 === 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab', 'chemiq_runtime_profile');
  demand(gate.privateGrader?.networkMode === 'bridge' && gate.privateGrader.boundaryProfile === 'exact-original-loopback-bridge-v2' && gate.privateGrader.cleanInterpreter === true && gate.privateGrader.solverToolsDisabled === true && gate.privateGrader.containerId === CHEMIQ_PRIVATE_CID, 'chemiq_private_runtime_boundary');
  demand(gate.requestedControls === 96 && gate.actualHttpRequests === 96 && gate.scope === 'pilot16' && gate.solverColdObservationPin, 'chemiq_cold96_actual_scope');
  demand(Array.isArray(gate.controls) && new Set(gate.controls.map((r: any) => r.officialId)).size === gate.controls.length, 'chemiq_control_duplicates');
  for (const task of plan.tasks) {
    const c = gate.controls.find((r: any) => r.officialId === task.officialId);
    demand(c && c.positive?.valid === true && c.positive.value === true && c.wrongValue?.valid === true && c.wrongValue.value === false && c.wrongFormat?.valid === true && c.wrongFormat.value === false, 'chemiq_selected_controls_missing');
  }
  if (plan.scope === 'full816') demand(gate.controls.length === 816 && gate.missingPositiveReferenceCount === 0, 'chemiq_full_positive_reference_gap');
}
export function validateChemiqRuntimeGate(pin: Pin, plan: ChemiqFPlan) {
  return validateChemiqRuntimeGateContents(jsonPin(pin), plan);
}
export function validateChemiqRuntimeGateContents(gate: any, plan: ChemiqFPlan, asOf = Date.now()) {
  assertChemiqRuntimeGate(gate, plan, asOf);
  for (const item of [gate.standSourcePin, gate.provenancePin, gate.datasetPin, gate.privateGrader.inspectPin, gate.privateGrader.runtimeAuditPin, gate.privateGrader.bridgeObservationPin, gate.solverColdObservationPin, gate.materialPin, gate.resourcePin,
    ...gate.controls.flatMap((r: any) => [r.positive, r.wrongValue, r.wrongFormat].flatMap(c => [c.receiptPin, c.parsedReceiptPin]))]) verifyPin(item, undefined, 512 * 1024 ** 2);
  const observed = assertChemiqPrivateBridgeObservation(jsonPin(gate.privateGrader.inspectPin), CHEMIQ_F_ROOT), runtime = jsonPin(gate.privateGrader.runtimeAuditPin);
  demand(runtime.valid === true && runtime.modelCalls === 0 && runtime.containerId === observed.containerId && runtime.imageId === observed.inspect.Image && runtime.provenanceSha256 === CHEMIQ_F_PROVENANCE_SHA, 'chemiq_private_runtime_audit');
  const bridge = jsonPin(gate.privateGrader.bridgeObservationPin);
  demand(bridge.protocol === 'chemiq-private-host-bridge-observation-v2' && bridge.modelCalls === 0 && bridge.validated === true && bridge.actualPid === bridge.status.pid && bridge.status.stopped !== true && bridge.observedUnixSeconds - bridge.status.heartbeat < 30 && bridge.processSourcePin.sha256 === jsonPin(gate.provenancePin).host_bridge.script.sha256, 'chemiq_private_bridge_runtime');
  for (const p of [bridge.processSourcePin, bridge.javaPin, bridge.jarPin, bridge.pythonPin]) verifyPin(p);
  assertChemiqSolverColdObservation(jsonPin(gate.solverColdObservationPin));
  const resources=jsonPin(gate.resourcePin);
  demand(resources.protocol==='chemiq-host-resource-observation-v2' && resources.modelCalls===0 && resources.disks.C.free>=1024**3 && resources.disks.F.free>=1024**3 && resources.memory.valid===true && resources.memory.availablePhysical>=1024**3,'chemiq_cold_actual_resources');
  const materials = jsonPin(gate.materialPin);
  demand(materials.protocol === 'chemiq-f-private-cold-materials-v2' && materials.taskScheduleSha256 === plan.taskScheduleSha256 && materials.requests === 96 && materials.executed === false && materials.modelCalls === 0, 'chemiq_cold_material_scope');
  for (const c of gate.controls) for (const kind of ['positive', 'wrongValue', 'wrongFormat']) {
    const expected = kind === 'positive', receipt = jsonPin(c[kind].receiptPin);
    const material = materials.tasks.find((r: any) => r.officialId === c.officialId)?.cases[kind];
    demand(material && receipt.valid === true && receipt.value === expected, 'chemiq_control_material_missing');
    for (const [node, p] of [['correct', c[kind].receiptPin], ['parsed', c[kind].parsedReceiptPin]] as const) {
      const wire = jsonPin(p);
      demand(wire.protocol === 'chemiq-f-runtime-control-receipt-v2' && wire.officialId === c.officialId && wire.kind === kind && wire.node === node && wire.valid === true && wire.value === material.expected[node] && wire.modelCalls === 0 && wire.fixtureOnly === false && wire.httpStatus === 200 && wire.bodyComplete === true && !wire.fault && wire.containerId === observed.containerId && wire.standSourceSha256 === CHEMIQ_F_STAND_SHA && wire.datasetSha256 === CHEMIQ_F_BOOK_SHA, 'chemiq_control_receipt_binding');
      const request = JSON.parse(gzipProof(wire.requestPin, wire.requestRawSha256, undefined, 4 * 1024 ** 2).toString('utf8'));
      const response = JSON.parse(gzipProof(wire.responsePin, wire.responseRawSha256, undefined, 4 * 1024 ** 2).toString('utf8'));
      demand(request.node === node && typeof request.input?.task?.id === 'string' && request.input.task.id.endsWith('/' + c.officialId) && hash(request.input.result.body) === material.inputSha256 && response.value === material.expected[node], 'chemiq_control_raw_value');
    }
  }
  return gate;
}

export type ChemiqFRecipe = { protocol: 'chemiq-f-journal-recipe-v2'; family: typeof CHEMIQ_F_FAMILY; runId: string; scope: ChemiqFScope;
  mode: 'prepare' | 'real-provider'; createdAtUtc: string; settings: typeof CHEMIQ_F_SETTINGS; taskScheduleSha256: string;
  output: string; store: string; sourcePins: Pin[]; sourceExecutionDigest: string; hostExecutors: { bun: Pin; python: Pin };
  balance?: Pin; prices: Pin; modelAvailability?: Pin; runtimeGate?: Pin; fullAuthorization?: Pin; financialBoundary?: { acknowledgementPin: Pin; originalLockArchivePin: Pin };
  deferredFault: Pin; originalPidClosure: Pin; requestedNewEnvelopeCny?: string; headroomCny: string; capUsd?: number;
  priorCampaignCostUpperBoundUsd?: number; workers: number; modelCallsByPreparation: 0; providerForwardingEnabled: false;
  jpgDScanner?: { module: Pin; executionPins: Pin[]; exportName: 'scanJpgDRegistries' }; userResourceDirective?: Pin; preparationInventory: Pin[] };
export function validateChemiqProviderObservations(recipe: ChemiqFRecipe, asOf: number) {
  demand(recipe.modelAvailability && recipe.balance, 'chemiq_model_availability_required');
  const model=jsonPin(recipe.modelAvailability!), price=jsonPin(recipe.prices), balance=jsonPin(recipe.balance!);
  const modelAt=Date.parse(model.observedAtUtc),priceAt=Date.parse(price.observedAtUtc),balanceAt=Date.parse(balance.observedAtUtc);
  demand(model.protocol==='chemiq-provider-models-readonly-v2' && model.provider==='https://api.deepseek.com' && model.endpoint==='/models' && model.method==='GET' && model.httpStatus===200 && model.modelCalls===0 && model.credentialPrinted===false && model.data.some((row:any)=>row.id==='deepseek-flash') && Number.isFinite(modelAt) && asOf>=modelAt && asOf-modelAt<=1800000,'chemiq_model_availability_observation');
  demand(price.protocol==='deepseek-cny-pricing-source-snapshot-v1' && price.method==='GET' && price.officialHttpStatus===200 && price.modelCalls===0 && price.officialResponsePin && price.priceParserSourcePin && Number.isFinite(priceAt) && asOf>=priceAt && asOf-priceAt<=86400000,'chemiq_actual_price_response_required');
  verifyPin(price.officialResponsePin);verifyPin(price.priceParserSourcePin);
  demand(price.officialResponseSha256===price.officialResponsePin.sha256 && recipe.sourcePins.some(p=>same(p,price.priceParserSourcePin)),'chemiq_price_parser_source_binding');
  const provider=recipe.sourcePins.find(p=>basename(p.path)==='chemiq-provider-readonly-v2.ts');
  demand(provider && [price,model,balance].every(observation=>observation.sourceScriptSha256===provider.sha256),'chemiq_provider_probe_source_binding');
  demand(Number.isFinite(balanceAt) && asOf>=balanceAt && asOf-balanceAt<=1800000,'chemiq_observed_balance_time');
  const parsed=parseChemiqOfficialFlashPricing(readFileSync(price.officialResponsePin.path,'utf8'));
  for(const [field,value] of Object.entries(parsed)) demand(same(price[field],value),'chemiq_price_response_value_binding');
  return {modelPin:recipe.modelAvailability!,pricePin:recipe.prices,balancePin:recipe.balance!,officialPriceResponsePin:price.officialResponsePin};
}
export function validateChemiqRecipe(recipe: ChemiqFRecipe, production = false) {
  demand(recipe?.protocol === 'chemiq-f-journal-recipe-v2' && recipe.family === CHEMIQ_F_FAMILY && same(recipe.settings, CHEMIQ_F_SETTINGS) && recipe.modelCallsByPreparation === 0 && recipe.providerForwardingEnabled === false, 'chemiq_recipe_protocol');
  const plan = loadChemiqFPlan(recipe.runId, recipe.scope);
  demand(recipe.taskScheduleSha256 === plan.taskScheduleSha256 && resolve(recipe.output) === chemiqOutput(recipe.runId) && resolve(recipe.store) === chemiqStore(recipe.runId), 'chemiq_recipe_scope');
  demand(Number.isSafeInteger(recipe.workers) && recipe.workers >= 1 && recipe.workers <= 4 && recipe.sourcePins.length > 0 && recipe.sourceExecutionDigest === hash(JSON.stringify(recipe.sourcePins)), 'chemiq_execution_source_set');
  for (const p of [...recipe.sourcePins, recipe.prices, ...(recipe.modelAvailability?[recipe.modelAvailability]:[]), ...recipe.preparationInventory, ...Object.values(recipe.hostExecutors)]) verifyPin(p);
  if (recipe.jpgDScanner) {
    demand(recipe.jpgDScanner.exportName === 'scanJpgDRegistries' && Array.isArray(recipe.jpgDScanner.executionPins) && recipe.jpgDScanner.executionPins.length > 0 && recipe.jpgDScanner.executionPins.some(p => same(p, recipe.jpgDScanner!.module)) && recipe.jpgDScanner.executionPins.every(p => recipe.sourcePins.some(s => same(p, s))), 'chemiq_jpg_d_execution_graph');
  }
  demand(recipe.sourcePins.some(p => basename(p.path) === 'chemiq-f-journal-campaign-v2.ts') && recipe.sourcePins.some(p => basename(p.path) === 'audit-chemiq-f-journal-v2.ts'), 'chemiq_executed_entry_and_auditor');
  if (production) {
    validateChemiqProviderObservations(recipe,Date.now());
    if (Number(recipe.headroomCny) < 30) {
      demand(recipe.scope === 'pilot16' && recipe.userResourceDirective, 'chemiq_headroom_user_directive_required');
      const directive = jsonPin(recipe.userResourceDirective!);
      demand(directive.protocol === 'chemiq-pilot-user-resource-directive-v2' && directive.source === 'direct-user-message-in-current-chat' && directive.waiveRechargePrerequisite === true && directive.waiveOperator30CnyHeadroom === true, 'chemiq_headroom_user_directive_scope');
    }
    demand(recipe.mode === 'real-provider' && recipe.balance && recipe.runtimeGate && recipe.financialBoundary && recipe.requestedNewEnvelopeCny && Number.isFinite(recipe.capUsd) && Number.isFinite(recipe.priorCampaignCostUpperBoundUsd) && recipe.capUsd! > recipe.priorCampaignCostUpperBoundUsd!, 'chemiq_production_recipe_not_ready');
    const actualRuntime = validateChemiqRuntimeGate(recipe.runtimeGate!, plan);
    demand(recipe.sourcePins.some(p => same(p, actualRuntime.sourcePin)), 'chemiq_cold_source_not_frozen_in_paid_graph');
    // Explicit D-scanner is mandatory: silently overlooking a new JPG D family is not allowed.
    demand(recipe.jpgDScanner?.exportName === 'scanJpgDRegistries' && recipe.jpgDScanner.module && recipe.sourcePins.some(p => same(p, recipe.jpgDScanner!.module)), 'chemiq_jpg_d_scanner_not_frozen'); verifyPin(recipe.jpgDScanner!.module);
    if (plan.scope === 'full816') {
      demand(recipe.fullAuthorization, 'chemiq_full_not_confirmed'); const permission = jsonPin(recipe.fullAuthorization!);
      demand(permission.protocol === 'chemiq-f-full-confirmation-v2' && permission.family === CHEMIQ_F_FAMILY && permission.userConfirmed === true && permission.runId === recipe.runId && permission.solveSeconds === 900 && permission.taskScheduleSha256 === plan.taskScheduleSha256 && permission.sourceExecutionDigest === recipe.sourceExecutionDigest && permission.denominator === 816, 'chemiq_full_confirmation_scope');
    }
  }
  return plan;
}
/** Exact complete keysets are mandatory; an invalid task remains invalid rather than a model0. */
export function assertChemiqRecordSet(plan: Pick<ChemiqFPlan, 'tasks'>, records: any[]) {
  demand(records.length === plan.tasks.length && new Set(records.map(r => r.index)).size === records.length, 'chemiq_record_denominator');
  for (const task of plan.tasks) {
    const row = records.find(r => r.index === task.index);
    demand(row?.family === CHEMIQ_F_FAMILY && row.officialId === task.officialId && row.arm === 'F' && row.replica === 0 && row.promptSha256 === task.promptSha256 && row.generationValid === true && row.acceptance?.valid === true && typeof row.acceptance.passed === 'boolean' && row.acceptance.candidateSha256 === row.candidateSha256 && row.acceptance.passed === (row.acceptance.outcome === 'passed'), 'chemiq_record_not_valid');
    demand(['passed', 'rejected', 'budget_exhausted', 'no_candidate'].includes(row.acceptance.outcome), 'chemiq_acceptance_outcome');
    demand(row.candidateDeadlinePolicy === 'frozen-finalCandidate-at<=created+solve_seconds' && Number.isFinite(row.declaredDeadlineAt), 'chemiq_candidate_deadline_policy');
  }
}
