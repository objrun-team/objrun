/** Supplemental verification for the drained, stopped four-Bench owner. Never edits old cash/journal. */
import { createHash } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { actualPin, jsonPin, same, verifyPin, type Pin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { verifyBenchmarkCashClosure } from '../../../benchmark-repair/benchmark-usd-cash.ts';
import { inspectCampaignJournal } from '../../../benchmark-repair/campaign-journal.ts';
import { BENCHMARK_PROVIDER, officialOpenRouterFault } from '../../../benchmark-repair/benchmark-provider.ts';

const check = (ok: unknown, why: string): asserts ok => { if (!ok) throw Error(why); };
const hash = (data: string | Buffer) => createHash('sha256').update(data).digest('hex');
const within = (root: string, path: string) => { const rel = relative(resolve(root), resolve(path)); return !!rel && !rel.startsWith('..') && !isAbsolute(rel); };
const read = (path: string) => JSON.parse(readFileSync(path, 'utf8'));
function save(path: string, data: any) {
  mkdirSync(dirname(path), { recursive: true }); const fd = openSync(path, 'wx', 0o600);
  try { writeFileSync(fd, JSON.stringify(data, null, 2) + '\n'); fsyncSync(fd); } finally { closeSync(fd); }
  return actualPin(path);
}
function alive(pid: number) {
  check(Number.isSafeInteger(pid) && pid > 0, 'invalid_pid');
  const result = Bun.spawnSync(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
    `if(Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}'){ 'alive' }else{ 'dead' }`]);
  check(result.exitCode === 0, 'process_probe_failed'); return result.stdout.toString().trim() === 'alive';
}
export function resolveUnknownReceipt(record: any, seq: number, dispatch: any | undefined, response: any | undefined, fenced: boolean) {
  check(fenced, 'broker_generation_not_fenced');
  if (dispatch) {
    check(dispatch.requestSeq === seq && dispatch.requestSha256 === record.requestSha256, 'dispatch_request_mismatch');
    check(response?.requestSeq === seq && response.httpStatus === 200 && response.responsePin, 'late_complete_response_required');
    const body = jsonPin(response.responsePin);
    check(typeof body.id === 'string' && body.id === response.generationId && Number.isFinite(body.usage?.cost) && body.usage.cost >= 0
      && body.usage.cost === response.billedUsd, 'late_response_cost_or_id_mismatch');
    return { requestSeq: seq, requestSha256: record.requestSha256, classification: 'late_complete_provider_receipt',
      actualCostUsd: body.usage.cost, generationId: body.id, providerName: body.provider, servedModel: body.model,
      responsePin: response.responsePin, protocolFault: officialOpenRouterFault(body), scoreCertificate: false };
  }
  check(!response && record.httpStatus === 503 && record.responseFile, 'unforwarded_rejection_evidence_required');
  const zipped = readFileSync(record.responseFile), raw = gunzipSync(zipped);
  check(hash(zipped) === record.responseCompressedSha256 && hash(raw) === record.responseSha256, 'local_rejection_bytes_changed');
  const body = JSON.parse(raw.toString('utf8'));
  check(!body.id && !body.usage && !body.choices && (body.error?.code === 'bench_broker_stopped'
    || body.error?.message === 'Broker stopped'), 'not_a_verified_local_broker_rejection');
  return { requestSeq: seq, requestSha256: record.requestSha256, classification: 'fenced_broker_never_dispatched',
    actualCostUsd: 0, generationId: null, localResponsePin: actualPin(record.responseFile), scoreCertificate: false };
}
function evaluate(scope: any) {
  const h = jsonPin(scope.healthPin), parent = jsonPin(scope.parentAdmissionPin), archive = jsonPin(scope.sourceArchivePin);
  check(h.protocol === 'full-f-broker-status-v1' && h.localMock === false && h.healthy === false && h.stopReason && h.lanes.length > 0
    && h.activeRequests === 0 && h.queuedRequests === 0 && Object.keys(h.resources).length === 0, 'broker_not_drained');
  check(parent.protocol === 'openrouter-usd-admission-v1' && parent.currency === 'USD'
    && parent.family === 'four-bench-full-f-v1' && same(parent.owned, h.canonicalOwner)
    && parent.owned.runId === h.runId && parent.owned.pid === h.pid && parent.sourcePins.length >= 10
    && parent.owned.entry === join(resolve(scope.root), 'scripts/benchmark-campaign/full-f/shared/full-f-broker.ts'), 'parent_identity_mismatch');
  for (const pin of parent.sourcePins) {
    const row = archive.pins.find((item: any) => same(item.original, pin));
    check(row && row.archived.sha256 === pin.sha256 && row.archived.bytes === pin.bytes, 'missing_original_source_archive'); verifyPin(row.archived);
  }
  const eventRows = scope.eventPins.map((pin: Pin) => ({ pin, value: jsonPin(pin) }));
  check(eventRows.every((row: any, index: number) => row.value.index === index && row.value.localMock === false), 'incomplete_broker_event_prefix');
  const events = eventRows.map((row: any) => row.value);
  check(events.some((event: any) => event.kind === 'stop'), 'missing_broker_stop');
  const acquired = eventRows.find((row: any) => row.value.kind === 'canonical-owner-acquired');
  check(acquired && same(acquired.value.admissionPin, scope.parentAdmissionPin), 'wrong_parent_event');
  const dispatches = new Map<string, any>(), responses = new Map<string, any>(), generations = new Set<string>();
  let rawCostUsd = 0;
  for (const event of events) {
    if (!['dispatch', 'response'].includes(event.kind)) continue;
    check(h.lanes.some((lane: any) => lane.runId === event.runId), 'dispatch_outside_registered_lanes');
    const key = `${event.runId}/${event.requestSeq}`;
    if (event.kind === 'dispatch') { check(!dispatches.has(key), 'duplicate_dispatch'); dispatches.set(key, event); }
    else {
      check(dispatches.has(key) && !responses.has(key), 'response_without_unique_dispatch'); responses.set(key, event);
      const body = jsonPin(event.responsePin);
      if (event.httpStatus === 200) {
        check(body.id === event.generationId && typeof body.id === 'string' && !generations.has(body.id)
          && Number.isFinite(body.usage?.cost) && body.usage.cost >= 0 && body.usage.cost === event.billedUsd, 'invalid_or_duplicate_billed_generation');
        generations.add(body.id); rawCostUsd += body.usage.cost;
      } else check(event.explicitRateRejection === true && event.generationId === null && !body.usage && !body.choices, 'unsettled_real_provider_response');
    }
  }
  check(dispatches.size === responses.size, 'provider_request_still_unsettled');
  const lanes: any[] = [];
  let unknownCount = 0;
  for (const lane of h.lanes) {
    check(['chembench', 'chemiq', 'skillsbench', 'terminal-bench'].includes(lane.slug)
      && within(join(scope.root, 'docs/repair-2026-10-10/full-f-rerun', lane.slug), lane.output), 'unexpected_lane_scope');
    const cashRow = scope.cashClosures.find((row: any) => row.runId === lane.runId);
    check(cashRow && within(lane.output, cashRow.closePin.path), 'missing_lane_cash_closure');
    const closed = verifyBenchmarkCashClosure(cashRow.closePin), proof = closed.proof, config = closed.config;
    const registered = events.find((event: any) => event.kind === 'cash-registered' && event.runId === lane.runId);
    const created = events.find((event: any) => event.kind === 'lane-created' && event.runId === lane.runId);
    check(registered && created && same(registered.cashPin, proof.configPin) && same(created.admissionPin, config.admissionPin)
      && config.ownerNonce === parent.owned.ownerNonce && config.capUsd === lane.capUsd && config.providerKind === 'real-provider', 'cash_parent_registration_mismatch');
    const journal = inspectCampaignJournal(config.journal.directory);
    check(journal.valid && journal.accountingClosed && journal.snapshot?.active.length === 0, 'journal_not_closed');
    const finished = readFileSync(join(config.journal.directory, 'api-events.jsonl'), 'utf8').trimEnd().split('\n').filter(Boolean)
      .map(line => JSON.parse(line)).filter(event => event.kind === 'finish');
    const resolutions = [];
    for (const event of finished) {
      const key = `${lane.runId}/${event.requestSeq}`, record = event.record, dispatch = dispatches.get(key), response = responses.get(key);
      if (record.costBasis === 'reservation') {
        if (!dispatch) check(Date.parse(record.finishedAt) >= Date.parse(events.find((entry: any) => entry.kind === 'stop').atUtc), 'local_rejection_before_broker_stop');
        resolutions.push(resolveUnknownReceipt(record, event.requestSeq, dispatch, response, true));
      } else if (record.costBasis === 'provider_reported_usd') {
        check(dispatch?.requestSha256 === record.requestSha256 && response?.generationId === record.requestId
          && response.billedUsd === record.usdUpperBound, 'known_receipt_broker_mismatch');
      } else check(record.usdUpperBound === 0 && (!dispatch || response?.explicitRateRejection === true), 'unproven_original_zero');
    }
    check(resolutions.length === proof.snapshot.newUnknownCount
      && [...dispatches.keys()].filter(key => key.startsWith(lane.runId + '/')).length === lane.dispatched, 'lane_dispatch_or_unknown_count_mismatch');
    unknownCount += resolutions.length;
    const recoveredCostUsd = resolutions.reduce((sum, row) => sum + row.actualCostUsd, 0);
    lanes.push({ slug: lane.slug, runId: lane.runId, originalCashClosePin: cashRow.closePin,
      originalReleasePermitted: proof.releasePermitted, originalUnknownCount: proof.snapshot.newUnknownCount,
      originalUnknownReservationUsd: proof.snapshot.unknownReservationUsd, originalKnownBilledUsd: proof.snapshot.billedUsd,
      resolutions, recoveredCostUsd, effectiveBilledUsd: proof.snapshot.billedUsd + recoveredCostUsd,
      remainingUnknownCostCount: 0, originalJournalAndCashUnmodified: true, scoreCertificate: false });
  }
  check(lanes.length === scope.cashClosures.length, 'extra_cash_closures');
  const effectiveBilledUsd = lanes.reduce((sum, lane) => sum + lane.effectiveBilledUsd, 0);
  check(Math.abs(effectiveBilledUsd - rawCostUsd) < 1e-9 && effectiveBilledUsd <= parent.capUsd + 1e-9, 'reconciled_cost_does_not_match_all_real_dispatches');
  return { owner: parent.owned, brokerRunId: h.runId, lanes, originalUnknownCostCount: unknownCount,
    remainingUnknownCostCount: 0, effectiveBilledUsd, rawProviderBilledUsd: rawCostUsd, modelCalls: 0, scoreCertificate: false };
}
export function verifyReconciliation(pin: Pin) {
  const report = jsonPin(pin);
  check(report.protocol === 'full-f-supplemental-cash-reconciliation-v1', 'wrong_reconciliation_protocol');
  check(same(report.verifierSourcePin, actualPin(import.meta.path)), 'reconciliation_verifier_source_changed');
  const checked = evaluate(report.scope); check(same(checked, report.result), 'reconciliation_report_changed'); return checked;
}
export function auditLegacyParent(root: string) {
  const output = join(root, 'docs/repair-2026-10-10/full-f-rerun'), control = read(join(output, 'control.json'));
  check(control.paidReady === false && control.financialHold, 'financial_hold_required');
  const h = read(control.broker.healthPath), brokerDir = dirname(control.broker.healthPath);
  const directory = join(output, 'financial-recovery-2026-10-10', 'audit-' + new Date().toISOString().replace(/[:.]/g, '-'));
  const eventPins = readdirSync(join(brokerDir, 'events')).filter(name => /^\d+\.json$/.test(name)).sort().map(name => actualPin(join(brokerDir, 'events', name)));
  const acquired = eventPins.map(jsonPin).find(event => event.kind === 'canonical-owner-acquired'); check(acquired, 'parent_event_missing');
  const cashClosures = h.lanes.map((lane: any) => {
    const path = [join(lane.output, 'currency/cash-close.json'), join(lane.output, 'journal/currency/cash-close.json')].find(existsSync);
    check(path, 'lane_cash_not_safely_closed'); return { runId: lane.runId, closePin: actualPin(path!) };
  });
  const scope = { root: resolve(root), healthPin: save(join(directory, 'stopped-health.json'), h), eventPins,
    parentAdmissionPin: acquired.admissionPin, cashClosures,
    sourceArchivePin: actualPin(join(output, 'financial-recovery-2026-10-10/source-archives/index.json')) };
  const result = evaluate(scope);
  const reportPin = save(join(directory, 'reconciliation.json'), { protocol: 'full-f-supplemental-cash-reconciliation-v1', atUtc: new Date().toISOString(), verifierSourcePin: actualPin(import.meta.path), scope, result });
  verifyReconciliation(reportPin); return { reportPin, result, brokerAlive: alive(h.pid) };
}
export function releaseReconciledOwnParent(root: string, reportPin: Pin) {
  const result = verifyReconciliation(reportPin), owner = result.owner;
  const report = jsonPin(reportPin);
  check(report.scope.root === resolve(root), 'reconciliation_for_another_root');
  const control = read(join(root, 'docs/repair-2026-10-10/full-f-rerun/control.json'));
  check(control.paidReady === false && control.broker.runId === owner.runId && control.broker.pid === owner.pid, 'recovery_owner_not_this_control');
  check(!alive(owner.pid), 'cannot_release_live_broker');
  const eventDirectory = dirname(report.scope.eventPins[0].path);
  check(readdirSync(eventDirectory).filter(name => /^\d+\.json$/.test(name)).length === report.scope.eventPins.length, 'broker_events_after_reconciliation_fence');
  for (const slug of ['chembench', 'chemiq']) {
    const status = read(join(root, 'docs/repair-2026-10-10/full-f-rerun', slug, 'status.json'));
    check(!alive(status.runnerPid ?? status.pid), 'cannot_release_live_bench_runner');
  }
  const lock = join(resolve(root), '.phase1-data/owned-paid-campaign.lock.json');
  check(same(read(lock), owner) && owner.family === 'four-bench-full-f-v1', 'canonical_owner_changed');
  const receipt = save(join(dirname(reportPin.path), 'parent-reconciled-release.json'), {
    protocol: 'full-f-reconciled-owned-release-v1', atUtc: new Date().toISOString(), owner,
    reconciliationPin: reportPin, effectiveBilledUsd: result.effectiveBilledUsd,
    originalUnknownCostCount: result.originalUnknownCostCount, remainingUnknownCostCount: 0,
    rawLegacyCashReleasePermittedChanged: false, modelCalls: 0, scoreCertificate: false });
  check(same(read(lock), owner) && !alive(owner.pid), 'owner_changed_before_release'); unlinkSync(lock); return receipt;
}
if (import.meta.main) {
  const root = resolve(import.meta.dir, '../../../..');
  if (process.argv[2] === '--audit') {
    const value = auditLegacyParent(root); console.log(JSON.stringify({ reportPin: value.reportPin, brokerAlive: value.brokerAlive,
      effectiveBilledUsd: value.result.effectiveBilledUsd, originalUnknownCostCount: value.result.originalUnknownCostCount,
      remainingUnknownCostCount: value.result.remainingUnknownCostCount, resolutions: value.result.lanes.flatMap(lane => lane.resolutions), modelCalls: 0 }, null, 2));
  } else if (process.argv[2] === '--release') console.log(JSON.stringify(releaseReconciledOwnParent(root, actualPin(process.argv[3])), null, 2));
  else throw Error('Use --audit or --release <verified report path>');
}
