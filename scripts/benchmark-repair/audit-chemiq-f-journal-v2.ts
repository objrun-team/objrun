/** Stored-only ChemIQ audit. Never generates, rescores, queries a model or touches old SQLite. */
import { closeSync, existsSync, openSync, readFileSync, readSync, readdirSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { finalCandidate } from '../../app/src/objective/candidate.ts';
import { createHash } from 'node:crypto';
import { classifyGeneration } from './campaign-contract.ts';
import { actualPin, demand, gzipProof, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_FAMILY, CHEMIQ_F_ROOT, assertChemiqRecordSet, chemiqOutput, chemiqOrdinary, loadChemiqFPlan, validateChemiqProviderObservations, validateChemiqRecipe, validateChemiqRuntimeGateContents } from './chemiq-f-journal-contract-v2.ts';
import { verifyChemiqOwnedObservation } from './chemiq-f-owned-v2.ts';

export function chemiqTrace(path: string) {
  const fd = openSync(path, 'r'); let pending = Buffer.alloc(0), rows = 0, explicitVerifyCalls = 0, stuck = false;
  try { while (true) {
    const block = Buffer.alloc(65536), n = readSync(fd, block); if (!n) break;
    pending = Buffer.concat([pending, block.subarray(0, n)]); let nl: number;
    while ((nl = pending.indexOf(10)) >= 0) {
      const line = pending.subarray(0, nl); pending = pending.subarray(nl + 1); if (!line.length) continue;
      demand(line.length <= 16 * 1024 ** 2, 'chemiq_trace_line_bound');
      const row = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(line)); rows++;
      if (row.kind === 'call') try { explicitVerifyCalls += JSON.parse(row.body).calls?.filter((c: any) => c.name === 'verify').length ?? 0; } catch {}
      if (row.role === 'system' && row.kind === 'inject') try { stuck ||= Object.hasOwn(JSON.parse(row.body), 'stuck'); } catch {}
    }
    demand(pending.length <= 16 * 1024 ** 2, 'chemiq_trace_line_bound');
  } demand(pending.length === 0, 'chemiq_trace_partial_line'); return { rows, explicitVerifyCalls, stuck }; } finally { closeSync(fd); }
}
/** The public legacy export must be the exact actual finish records, not a second mutable accounting authority. */
export function assertChemiqJournalExport(ledger: any, inspected: ReturnType<typeof inspectCampaignJournal>, runId: string, routes: Set<string>) {
  demand(inspected.valid && inspected.accountingClosed && inspected.snapshot && inspected.config?.campaign === runId && ledger.campaign === runId && ledger.calls.length === inspected.snapshot.acceptedRequestCount && ledger.reservedUpperBoundUsd === 0 && Object.keys(ledger.pending).length === 0 && Math.abs(ledger.recordedUsageUpperBoundUsd - inspected.snapshot.recordedUsageUpperBoundUsd) < 1e-9, 'chemiq_legacy_export_accounting');
  const fd = openSync(inspected.journalPath, 'r');
  try { for (const [seq, receipt] of ledger.calls.entries()) {
    const offset = inspected.offsets.get(seq); demand(offset && routes.has(receipt.route), 'chemiq_unplanned_ledger_route');
    const line = Buffer.alloc(offset.bytes); demand(readSync(fd, line, 0, line.length, offset.offset) === line.length && hash(line) === offset.sha256, 'chemiq_actual_finish_line');
    demand(same(JSON.parse(line.toString('utf8')).record, receipt), 'chemiq_export_not_actual_finish');
  } } finally { closeSync(fd); }
}
export function auditChemiqFArtifacts(output: string, kind: 'score' | 'financial-abort') {
  const manifestPin = actualPin(join(output, 'manifest.json')), manifest = jsonPin(manifestPin);
  demand(resolve(output) === chemiqOutput(manifest.runId) && manifest.family === CHEMIQ_F_FAMILY && manifest.providerKind === 'real-provider', 'chemiq_audit_scope');
  chemiqOrdinary(output, CHEMIQ_F_ROOT, true);
  const recipe = jsonPin(manifest.recipePin), plan = validateChemiqRecipe(recipe), inputArtifacts: Pin[] = [manifestPin, manifest.recipePin, actualPin(import.meta.path)];
  demand(recipe.runtimeGate, 'chemiq_audit_actual_cold_gate_missing');
  const coldGate = jsonPin(recipe.runtimeGate);
  const admission=jsonPin(actualPin(join(output,'chemiq-admission.json')));
  demand(admission.runId===plan.runId && admission.family===CHEMIQ_F_FAMILY && Number.isFinite(Date.parse(admission.coldRuntimeValidatedAtUtc)) && Date.parse(admission.coldRuntimeValidatedAtUtc)<=Date.parse(manifest.createdAt),'chemiq_audit_cold_validation_time');
  validateChemiqRuntimeGateContents(coldGate, plan, Date.parse(admission.coldRuntimeValidatedAtUtc));
  const providerObservations=validateChemiqProviderObservations(recipe,Date.parse(admission.coldRuntimeValidatedAtUtc));
  inputArtifacts.push(...Object.values(providerObservations));
  demand(recipe.sourcePins.some((p: Pin) => same(p, coldGate.sourcePin)), 'chemiq_audit_cold_source_binding');
  inputArtifacts.push(recipe.runtimeGate);
  const startup=jsonPin(manifest.startupResourcePin);inputArtifacts.push(manifest.startupResourcePin);
  demand(startup.protocol==='chemiq-f-startup-resource-observation-v2' && startup.runId===plan.runId && startup.family===CHEMIQ_F_FAMILY && startup.validated===true && startup.modelCalls===0 && startup.paidLockTaken===false && startup.diskVolumes.length===2 && startup.diskVolumes.every((r:any)=>r.freeBytes>=1024**3) && startup.memory.selected===recipe.workers,'chemiq_audit_actual_startup_resources');
  demand(manifest.taskScheduleSha256 === plan.taskScheduleSha256 && manifest.scope === plan.scope && manifest.plannedTaskRuns === plan.tasks.length && manifest.taskSeconds === 900 && manifest.arms.join(',') === 'F', 'chemiq_audit_schedule');
  for (const name of ['summary.json', 'source-close.json', 'owned-close.json', 'currency-close.json', 'grading-close.json', 'raw-close.json', 'journal-export.json', 'api-ledger.json', 'frozen-source.json', 'source.json']) inputArtifacts.push(actualPin(join(output, name)));
  const named = (name: string) => jsonPin(inputArtifacts.find(p => basename(p.path) === name)!);
  const summary = named('summary.json'), source = named('source-close.json'), owned = named('owned-close.json'), currency = named('currency-close.json'), grading = named('grading-close.json'), raw = named('raw-close.json');
  demand(source.protocol === 'chemiq-f-source-close-v2' && source.family === CHEMIQ_F_FAMILY && source.runId === plan.runId && same(source.pins, recipe.sourcePins) && source.recipeExecutionDigest === recipe.sourceExecutionDigest, 'chemiq_audit_source');
  for (const p of source.pins) verifyPin(p);
  for (const p of Object.values(recipe.hostExecutors) as Pin[]) verifyPin(p);
  const frozen = named('frozen-source.json'), actualSource = named('source.json');
  demand(actualSource.taskScheduleSha256 === plan.taskScheduleSha256 && frozen.sourceExecutionDigest === actualSource.executionDigest && manifest.sourceExecutionDigest === actualSource.executionDigest, 'chemiq_archive_source_digest');
  verifyPin({ path: frozen.archive, bytes: frozen.archiveBytes, sha256: frozen.archiveSha256 });
  for (const file of [...actualSource.files, ...actualSource.repairFiles, ...frozen.dependencyFiles]) verifyPin({ ...file, path: resolve(CHEMIQ_F_ROOT, file.path) });
  demand(owned.protocol === 'chemiq-f-owned-close-v2' && owned.family === CHEMIQ_F_FAMILY && owned.runId === plan.runId && owned.closed === true && Array.isArray(owned.registrationPins), 'chemiq_audit_owned');
  for (const p of owned.registrationPins) verifyPin(p);
  const actors = verifyChemiqOwnedObservation(owned.observationPin, owned.registrationPins, [owned.proxyPort, owned.gradePort]);
  demand(summary.protocol === 'chemiq-f-operational-summary-v2' && summary.runId === plan.runId && summary.family === CHEMIQ_F_FAMILY && summary.formalFull816Score === false && summary.providerForwardingClosed === true && summary.gradeServerClosed === true, 'chemiq_audit_summary');
  demand(summary.sealRecords.length <= plan.tasks.length && summary.sealRecords.every((r: any) => Number.isFinite(r.sealedAt) && r.reason && r.deadline === r.start + 900000), 'chemiq_audit_seal');
  demand(summary.proxyState.activeHandlers === 0 && summary.gradeState.activeHandlers === 0 && summary.activeEngines === 0, 'chemiq_audit_active_transport');
  demand(grading.protocol === 'chemiq-f-grading-close-v2' && grading.family === CHEMIQ_F_FAMILY && grading.runId === plan.runId && grading.fixtureOnly === false && grading.explicitVerifyBudget === 5 && grading.budgetIsAllPhysicalGCalls === false, 'chemiq_audit_grading_scope');
  const gradeReceipts = grading.physicalGradeReceiptPins.map((p: Pin) => { inputArtifacts.push(p); const r = jsonPin(p);
    demand(r.protocol === 'chemiq-f-physical-grade-receipt-v2' && r.family === CHEMIQ_F_FAMILY && r.runId === plan.runId && r.fixtureOnly === false && r.modelCalls === 0 && ['parsed', 'correct'].includes(r.node), 'chemiq_grade_record_type');
    const req = JSON.parse(gzipProof(r.requestPin, r.requestRawSha256, undefined, 4 * 1024 ** 2).toString('utf8'));
    const response = gzipProof(r.responsePin, r.responseRawSha256, undefined, 4 * 1024 ** 2);
    demand(req.node === r.node && req.input?.task?.id === r.taskId && plan.tasks.some(t => t.index === r.taskIndex && t.taskId === r.taskId && t.officialId === r.officialId), 'chemiq_grade_task_binding');
    if (r.valid) demand(r.httpStatus === 200 && r.bodyComplete && !r.fault && JSON.parse(response.toString('utf8')).value === r.value && typeof r.value === 'boolean', 'chemiq_grade_value_raw');
    return { ...r, body: req }; });
  demand(grading.physicalGCalls === gradeReceipts.length && new Set(gradeReceipts.map((r: any) => r.index)).size === gradeReceipts.length, 'chemiq_grade_count');
  const cash = verifyCashClosure(currency.cashClosePin), journal = inspectCampaignJournal(recipe.store);
  demand(currency.protocol === 'chemiq-f-currency-close-v2' && currency.family === CHEMIQ_F_FAMILY && currency.runId === plan.runId && cash.config.providerKind === 'real-provider' && cash.config.scope === 'production' && cash.config.carryNanoCny === '8392180000' && jsonPin(cash.config.admissionPin).family === CHEMIQ_F_FAMILY && journal.valid && journal.accountingClosed && same(cash.proof.journalPrefix, journal.prefix), 'chemiq_cash_journal_closed');
  inputArtifacts.push(currency.cashClosePin, cash.proof.journalConfigPin);
  const ledger = named('api-ledger.json'), exported = named('journal-export.json');
  assertChemiqJournalExport(ledger, journal, plan.runId, new Set(plan.tasks.map(t => t.route)));
  demand(raw.protocol === 'chemiq-f-raw-close-v2' && raw.family === CHEMIQ_F_FAMILY && raw.runId === plan.runId && same(raw.journalPrefix, journal.prefix) && raw.recordedUsageUpperBoundUsd === ledger.recordedUsageUpperBoundUsd && exported.accountingClosed === true && ledger.calls.length === journal.snapshot?.acceptedRequestCount, 'chemiq_raw_export');
  demand(ledger.calls.every((r: any) => r.providerAttempted === true || r.providerAttempted === false && r.confirmedNoForward === true), 'chemiq_forward_fact_missing');
  demand(ledger.calls.every((r: any) => r.providerAttempted === false || ['deepseek-flash', 'deepseek-v4-flash'].includes(r.servedModel)), 'chemiq_served_model');
  const inventory = readdirSync(output).filter(name => /^task-\d+\.json$/.test(name)).sort(), records = inventory.map(name => { const p = actualPin(join(output, name)); inputArtifacts.push(p); return jsonPin(p); });
  demand(records.length === summary.recordedTaskRuns && records.every((r: any) => r.runId === plan.runId && r.family === CHEMIQ_F_FAMILY && r.benchmark === 'chemiq' && r.arm === 'F') && new Set(records.map((r: any) => r.index)).size === records.length, 'chemiq_record_actual_inventory');
  for (const row of records) {
    const task = plan.tasks[row.index]; demand(task && row.officialId === task.officialId && row.taskId === task.taskId && row.promptSha256 === task.promptSha256 && row.candidateSha256 === hash(row.answer), 'chemiq_record_fixed_candidate');
    const actualIds = [...(journal.routes.get(task.route) ?? [])].sort((a, b) => a - b);
    if(kind==='score') demand(ledger.calls.some((r:any)=>r.route===task.route && r.providerAttempted===true),'chemiq_task_never_forwarded_to_real_provider');
    const actualRefs = actualIds.map(seq => { const line = journal.offsets.get(seq)!; return { callId: seq, finishOffset: line.offset, finishEnd: line.offset + line.bytes, finishLineSha256: line.sha256 }; });
    demand(same(row.callIds, actualIds) && same(row.journalRefs, actualRefs), 'chemiq_task_api_keyset');
    verifyPin(row.tracePin); inputArtifacts.push(row.tracePin); const trace = chemiqTrace(row.tracePin.path);
    demand(row.traceSha256 === row.tracePin.sha256 && row.traceRows === trace.rows && row.explicitVerifyCalls === trace.explicitVerifyCalls, 'chemiq_trace_full_inventory');
    // Only the newly owned stopped task database is read, never a historical SQLite file.
    const dbPath = join(recipe.store, `task-${row.index}`, 'data/h2h.sqlite'); chemiqOrdinary(dbPath, recipe.store); verifyPin(row.taskDatabasePin);
    demand(resolve(row.taskDatabasePin.path) === resolve(dbPath), 'chemiq_task_db_scope');
    const checkWal = () => { if (row.taskWalPin) { demand(resolve(row.taskWalPin.path) === resolve(dbPath + '-wal'), 'chemiq_task_wal_scope'); chemiqOrdinary(dbPath + '-wal', recipe.store); verifyPin(row.taskWalPin); } else demand(!existsSync(dbPath + '-wal'), 'chemiq_unrecorded_task_wal'); };
    checkWal();
    const { Database } = require('bun:sqlite'), db = new Database(dbPath, { readonly: true });
    try {
      const sql = (text: string, params: any[] = []) => db.query(text).all(...params);
      const taskRow = sql('select state,result,created_at,solve_seconds from task where id=?', [row.taskId]);
      demand(taskRow.length === 1 && taskRow[0].solve_seconds === 900 && taskRow[0].created_at === row.actualCreatedAt && row.declaredDeadlineAt === row.actualCreatedAt + 900000, 'chemiq_task_time_budget');
      const candidate = finalCandidate({ all: sql, run() { throw Error('readonly'); }, exec() { throw Error('readonly'); }, close() {} } as never, row.taskId);
      demand((candidate?.body ?? '') === row.answer && (candidate?.how ?? 'none') === row.candidateHow, 'chemiq_stored_final_candidate_changed');
      const traceDigest = createHash('sha256'); let databaseTraceRows = 0;
      for (const message of db.query('select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like ? order by unit,seq').iterate(row.taskId + '#%')) { traceDigest.update(JSON.stringify(message) + '\n'); databaseTraceRows++; }
      demand(traceDigest.digest('hex') === row.tracePin.sha256 && databaseTraceRows === trace.rows, 'chemiq_trace_database_binding');
      const runtime = JSON.parse(taskRow[0].result ?? '{"outcome":"finalization_pending","valid":false}');
      const generation = classifyGeneration({ runtimeVerdict: runtime, state: taskRow[0].state, calls: ledger.calls.filter((r: any) => r.route === task.route), trace: trace.stuck ? [{ role: 'system', kind: 'inject', body: '{"stuck":true}' }] : [], candidate: candidate?.body });
      demand(same(runtime, row.runtimeVerdict) && row.state === taskRow[0].state && same(generation, row.generationClassification) && generation.valid === row.generationValid, 'chemiq_generation_replay');
      if (kind === 'score' && !candidate) demand(row.acceptance.passed === false && row.acceptance.outcome === generation.outcome && row.acceptance.valid === generation.valid, 'chemiq_absent_candidate_false_score');
    } finally { db.close(); }
    verifyPin(row.taskDatabasePin);
    checkWal();
    if (row.acceptance?.valid && row.candidateHow !== 'none' && row.generationValid) {
      const final = gradeReceipts.filter((r: any) => r.phase === 'independent-final' && r.taskIndex === row.index);
      demand(final.length === 2 && final.every((r: any) => r.valid && r.body.input.result.body === row.answer && Date.parse(r.startedAtUtc) >= Date.parse(summary.generationClosedAtUtc)), 'chemiq_final_grading_not_after_seal');
      demand(row.acceptance.nodes.parsed?.value === final.find((r: any) => r.node === 'parsed').value && row.acceptance.nodes.correct?.value === final.find((r: any) => r.node === 'correct').value, 'chemiq_acceptance_official_receipts');
      demand(row.acceptance.passed === final.find((r: any) => r.node === 'correct').value && row.acceptance.outcome === (row.acceptance.passed ? 'passed' : 'rejected'), 'chemiq_acceptance_pass_value');
    }
  }
  const secrets = jsonPin(summary.secretAuditPin); inputArtifacts.push(summary.secretAuditPin);
  demand(secrets.protocol === 'chemiq-f-evidence-secret-audit-v2' && secrets.family === CHEMIQ_F_FAMILY && secrets.runId === plan.runId && secrets.passed === true && secrets.valuesChecked >= 2 && secrets.findings.length === 0 && secrets.headersArchived === false && secrets.rawGzipExpanded === true && secrets.privateConfigArchived === false, 'chemiq_secret_boundary');
  let scoreCertificateValid = false;
  if (kind === 'score') {
    assertChemiqRecordSet(plan, records); demand(!summary.fatal && summary.operationalComplete && grading.generationClosedBeforeAllFinalGrading && exported.eligibleForScoreCertification && !cash.proof.snapshot.poisoned, 'chemiq_score_not_closed'); scoreCertificateValid = true;
  } else {
    demand(summary.financialOnly === true && summary.operationalComplete === false && summary.scoreCertificateValid === false && ['cash_envelope_exhausted', 'fee_cap'].includes(summary.financialStopReason) && cash.proof.snapshot.newUnknownCount === 0 && cash.proof.snapshot.pendingCount === 0, 'chemiq_financial_abort_not_allowed');
  }
  for (const p of inputArtifacts) verifyPin(p, undefined, 512 * 1024 ** 2);
  return { protocol: 'chemiq-f-independent-audit-v2', family: CHEMIQ_F_FAMILY, runId: plan.runId, scope: plan.scope, sourceScheduleSha256: plan.taskScheduleSha256,
    plannedTaskRuns: plan.tasks.length, recordedTaskRuns: records.length, actualDifferentTasksForwarded: new Set(ledger.calls.filter((r:any)=>r.providerAttempted===true).map((r:any)=>r.route)).size, integrityValid: true, financialClosed: true, financialOnly: kind === 'financial-abort', scoreCertificateValid,
    full816ScoreCertified: scoreCertificateValid && plan.scope === 'full816', oldUnknownSettled: false, oldUnknownCarryNanoCny: '8392180000', inputArtifacts,
    recordedUsageUpperBoundUsd: ledger.recordedUsageUpperBoundUsd, estimatedCny: cash.proof.snapshot.newKnownEstimatedNanoCny, physicalGCalls: gradeReceipts.length,
    explicitVerifyCalls: records.reduce((n: number, r: any) => n + r.explicitVerifyCalls, 0), modelCalls: 0, actualModelForwarded: ledger.calls.filter((r: any) => r.providerAttempted === true).length,
    limitations: ['Stored-only audit; official decision wire is verified without rescore.', 'Model determinism or legacy0731 equivalence is not certified.', 'Control34 readiness is a separate runtime gate; trial16 is not816 score.'] };
}
if (import.meta.main) {
  const [output, kind = 'score'] = process.argv.slice(2); demand(output && ['score', 'financial-abort'].includes(kind), 'chemiq_audit_cli');
  console.log(JSON.stringify(auditChemiqFArtifacts(resolve(output), kind as 'score' | 'financial-abort')));
}
