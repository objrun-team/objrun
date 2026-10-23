/** Finance-only lease for a separately reviewed ChemIQ family; old ledgers/guards are immutable. */
import { randomBytes } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { assertPidsAbsent, observeOriginalPaidPids, scanOtherPaidRuns, type AdmissionLease } from './paid-resource-admission-v2.ts';
import { actualJpgPriorUsd, jpgCarry, scanJpgPaidRuns } from './jpg-paid-resource-admission-v1.ts';
import { FINANCIAL_RUN } from './financial-interruption-release.ts';
import { FINANCIAL_KNOWN_USD, verifyFinancialInterruptedBoundary } from './financial-interruption-closure-v1.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { actualPin, demand, jsonPin, nanoCny, REAL_CLOCK, same, validatePrices, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_FAMILY, CHEMIQ_F_ROOT, chemiqOutput, chemiqOrdinary, validateChemiqRecipe, type ChemiqFRecipe } from './chemiq-f-journal-contract.ts';

export const CHEMIQ_F_REGISTRY = 'chemiq-f-paid-resource-run-v1';
export function durableChemiqJson(path: string, value: unknown, replace = false): Pin {
  mkdirSync(dirname(path), { recursive: true }); chemiqOrdinary(dirname(path), CHEMIQ_F_ROOT, true);
  const raw = Buffer.from(JSON.stringify(value, null, 2) + '\n'), temporary = replace ? path + '.tmp-' + randomBytes(8).toString('hex') : path;
  const fd = openSync(temporary, 'wx', 0o600); try { writeFileSync(fd, raw); fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(temporary).equals(raw), 'chemiq_json_readback');
  if (replace) { chemiqOrdinary(path); renameSync(temporary, path); }
  demand(readFileSync(path).equals(raw), 'chemiq_json_commit_readback'); return actualPin(path);
}
export function chemiqCashEnvelope(balance: any, requested: string, headroom: string, now = Date.now()) {
  demand(balance?.protocol === 'deepseek-resource-readonly-v1' && balance.provider === 'https://api.deepseek.com' && balance.endpoint === '/user/balance' && balance.method === 'GET' && balance.httpStatus === 200 && balance.isAvailable === true && balance.modelCalls === 0 && balance.credentialPrinted === false, 'chemiq_balance_source');
  const at = Date.parse(balance.observedAtUtc); demand(Number.isFinite(at) && now >= at && now - at <= 1800000, 'chemiq_balance_expired');
  const rows = balance.balances.filter((r: any) => r.currency === 'CNY'); demand(rows.length === 1, 'chemiq_balance_currency');
  const available = nanoCny(rows[0].total_balance), margin = nanoCny(headroom), envelope = nanoCny(requested), carry = 8392180000n;
  demand(nanoCny(rows[0].granted_balance) + nanoCny(rows[0].topped_up_balance) === available, 'chemiq_balance_components');
  demand(margin >= 30000000000n && envelope > 0n && envelope + margin + carry <= available, 'chemiq_cash_envelope');
  return { available, margin, envelope, carry };
}

export async function verifyChemiqCertificate(pin: Pin, runId: string) {
  const certificate = jsonPin(pin);
  demand(certificate.protocol === 'chemiq-f-close-certificate-v1' && certificate.family === CHEMIQ_F_FAMILY && certificate.runId === runId && ['score', 'financial-abort'].includes(certificate.kind), 'chemiq_close_certificate_type');
  const { auditChemiqFArtifacts } = await import('./audit-chemiq-f-journal.ts');
  const audited = auditChemiqFArtifacts(chemiqOutput(runId), certificate.kind);
  demand(audited.financialClosed === true && audited.integrityValid === true && certificate.financialClosed === true && certificate.scoreCertificateValid === (certificate.kind === 'score'), 'chemiq_close_certificate_invalid');
  const saved = jsonPin(certificate.auditor);
  demand(saved.protocol === 'chemiq-f-independent-audit-v1' && saved.runId === runId && saved.family === CHEMIQ_F_FAMILY && saved.modelCalls === 0 && saved.integrityValid === true && same(saved.inputArtifacts, audited.inputArtifacts) && saved.scoreCertificateValid === audited.scoreCertificateValid, 'chemiq_actual_auditor_binding');
  demand(certificate.auditorSourcePin && audited.inputArtifacts.some(p => same(p, certificate.auditorSourcePin)), 'chemiq_auditor_source_binding');
  for (const name of ['summary', 'source', 'owned', 'cash', 'grading', 'journal', 'raw']) demand(audited.inputArtifacts.some(p => same(p, certificate[name])), 'chemiq_cert_pin_graph');
  return { certificate, audited };
}

/** Closed-only; no Boolean marker can hide unaccounted provider calls. */
export async function scanChemiqFPaidRuns(root: string, currentRun: string) {
  demand(resolve(root) === CHEMIQ_F_ROOT, 'chemiq_scanner_root');
  const home = join(root, 'docs/repair-2026-10-08/chemiq-f-journal-campaigns'), inputPins: Pin[] = [], closedRunIds: string[] = [];
  let closedRecordedCostUpperBoundUsd = 0;
  if (!existsSync(home)) return { family: CHEMIQ_F_FAMILY, closedRecordedCostUpperBoundUsd, inputPins, closedRunIds };
  chemiqOrdinary(home, root, true);
  for (const runId of readdirSync(home)) {
    if (runId === currentRun) continue;
    const registryPin = actualPin(join(home, runId, 'chemiq-paid-resource-run.json')), row = jsonPin(registryPin);
    demand(row.protocol === CHEMIQ_F_REGISTRY && row.family === CHEMIQ_F_FAMILY && row.runId === runId && row.providerKind === 'real-provider' && row.released === true && row.certificationPin && row.releaseCommittedPin && row.releasePin && row.admissionPin, 'chemiq_other_unclosed_run');
    const graph = await verifyChemiqCertificate(row.certificationPin, runId), ack = jsonPin(row.releaseCommittedPin), release = jsonPin(row.releasePin), admitted = jsonPin(row.admissionPin);
    demand(ack.protocol === 'chemiq-f-lock-release-committed-v1' && ack.family === CHEMIQ_F_FAMILY && ack.runId === runId && ack.released === true && ack.ownerNonce === admitted.owned.ownerNonce && same(ack.authorizationPin, row.releasePin) && same(release.certificationPin, row.certificationPin) && release.originalUnknownSettled === false, 'chemiq_committed_release_missing');
    const ledger = jsonPin(graph.certificate.raw);
    demand(Number.isFinite(ledger.recordedUsageUpperBoundUsd) && ledger.recordedUsageUpperBoundUsd >= 0, 'chemiq_prior_unknown');
    closedRecordedCostUpperBoundUsd += ledger.recordedUsageUpperBoundUsd;
    inputPins.push(registryPin, row.certificationPin, row.releaseCommittedPin, row.releasePin); closedRunIds.push(runId);
  }
  return { family: CHEMIQ_F_FAMILY, closedRecordedCostUpperBoundUsd, inputPins, closedRunIds };
}
export function addChemiqPrior(base: number, own: number, jpgD: number, interruptedLedgerExists: boolean) {
  demand([base, own, jpgD].every(v => Number.isFinite(v) && v >= 0) && !interruptedLedgerExists, 'chemiq_prior_duplicate_or_unknown');
  return base + FINANCIAL_KNOWN_USD + own + jpgD;
}
export async function chemiqFinancialPreflight(recipe: ChemiqFRecipe) {
  demand(recipe.financialBoundary && recipe.jpgDScanner, 'chemiq_cross_family_boundary_missing');
  const fixed = await verifyFinancialInterruptedBoundary(recipe.financialBoundary!);
  scanOtherPaidRuns(CHEMIQ_F_ROOT, FINANCIAL_RUN); scanJpgPaidRuns(CHEMIQ_F_ROOT, recipe.runId);
  const own = await scanChemiqFPaidRuns(CHEMIQ_F_ROOT, recipe.runId);
  verifyPin(recipe.jpgDScanner!.module);
  const module = await import(pathToFileURL(recipe.jpgDScanner!.module.path).href);
  demand(typeof module.scanJpgDRegistries === 'function', 'chemiq_jpg_d_scanner_export');
  const jpgD = await module.scanJpgDRegistries(CHEMIQ_F_ROOT, recipe.runId);
  demand(jpgD && jpgD.family === 'jpg-journal-v1' && Number.isFinite(jpgD.closedRecordedCostUpperBoundUsd) && jpgD.closedRecordedCostUpperBoundUsd >= 0 && Array.isArray(jpgD.inputPins), 'chemiq_jpg_d_closed_cost');
  for (const p of jpgD.inputPins) verifyPin(p, undefined, 512 * 1024 ** 2);
  const base = actualJpgPriorUsd(CHEMIQ_F_ROOT), prior = addChemiqPrior(base, own.closedRecordedCostUpperBoundUsd, jpgD.closedRecordedCostUpperBoundUsd,
    existsSync(join(CHEMIQ_F_ROOT, 'docs/repair-2026-10-08/campaigns', FINANCIAL_RUN, 'api-ledger.json')));
  return { fixed, prior, baseLegacyAndJpgFUsd: base, fixedFinancialInterruptedUsdAddedOnce: FINANCIAL_KNOWN_USD, own, jpgD };
}

/** Never reads/removes an old canonical owner. Only fresh wx, then this exact nonce can be released. */
export async function acquireChemiqPaidResource(recipe: ChemiqFRecipe): Promise<AdmissionLease> {
  const plan = validateChemiqRecipe(recipe, true);
  demand(!existsSync(recipe.output) && !existsSync(recipe.store), 'chemiq_no_store_or_run_reuse');
  const carryProof = jpgCarry(recipe as never), budget = chemiqCashEnvelope(jsonPin(recipe.balance!), recipe.requestedNewEnvelopeCny!, recipe.headroomCny);
  const prices = validatePrices(recipe.prices), priceTime = Date.parse(prices.observedAtUtc);
  demand(Number.isFinite(priceTime) && Date.now() >= priceTime && Date.now() - priceTime <= 86400000, 'chemiq_price_expired');
  assertPidsAbsent([50652, 38176, 87440, 96080, 96848], await observeOriginalPaidPids());
  const preflight = await chemiqFinancialPreflight(recipe);
  demand(Math.abs(preflight.prior - recipe.priorCampaignCostUpperBoundUsd!) < 1e-9, 'chemiq_actual_prior_changed');
  const path = join(CHEMIQ_F_ROOT, '.phase1-data/owned-paid-campaign.lock.json');
  const owned = Object.freeze({ pid: process.pid, startedAt: new Date().toISOString(), runId: recipe.runId,
    entry: recipe.sourcePins.find(p => basename(p.path) === 'chemiq-f-journal-campaign.ts')!.path, ownerNonce: randomBytes(24).toString('hex'), family: CHEMIQ_F_FAMILY, purpose: recipe.scope + '-F900' });
  durableChemiqJson(path, owned);
  let released = false, cashPin: Pin | undefined; const registered: Pin[] = [];
  const assertOwned = () => demand(!released && same(JSON.parse(readFileSync(path, 'utf8')), owned), 'chemiq_current_owner_changed');
  const proofPin = durableChemiqJson(join(recipe.output, 'chemiq-admission.json'), { protocol: 'paid-resource-admission-v2', family: CHEMIQ_F_FAMILY, purpose: 'chemiq-F-finance-only', runId: recipe.runId,
    scope: 'production', owned, recipe, sourcePins: recipe.sourcePins, originalCriticalPins: carryProof.critical, carry: carryProof.carry, carryNanoCny: budget.carry.toString(),
    balanceNanoCny: budget.available.toString(), headroomNanoCny: budget.margin.toString(), selectedNewEnvelopeNanoCny: budget.envelope.toString(), balancePin: recipe.balance, pricePin: recipe.prices,
    historicalFinancialBoundary: preflight.fixed, priorDecomposition: { legacyAndJpgF: preflight.baseLegacyAndJpgFUsd, interruptedAddedOnce: FINANCIAL_KNOWN_USD, chemiq: preflight.own.closedRecordedCostUpperBoundUsd, jpgD: preflight.jpgD.closedRecordedCostUpperBoundUsd } });
  const registry = join(recipe.output, 'chemiq-paid-resource-run.json');
  durableChemiqJson(registry, { protocol: CHEMIQ_F_REGISTRY, family: CHEMIQ_F_FAMILY, runId: recipe.runId, providerKind: 'real-provider', admissionPin: proofPin, released: false, certificationPin: null });
  const validateForwardSource = () => { assertOwned(); for (const p of [...recipe.sourcePins, recipe.balance!, recipe.prices, recipe.runtimeGate!, ...(recipe.fullAuthorization ? [recipe.fullAuthorization] : [])]) verifyPin(p); const t = Date.parse(prices.observedAtUtc); demand(Date.now() >= t && Date.now() - t <= 86400000, 'chemiq_price_expired'); };
  return Object.freeze({ protocol: 'paid-resource-admission-v2' as const, root: CHEMIQ_F_ROOT, runId: recipe.runId, path, proofPin, owned, clock: REAL_CLOCK, scope: 'production' as const,
    envelopeNanoCny: budget.envelope, balanceNanoCny: budget.available, headroomNanoCny: budget.margin, carryNanoCny: budget.carry, carry: carryProof.carry, sourcePins: recipe.sourcePins,
    assertOwned, validateForwardSource,
    registerCash(pin: Pin) { assertOwned(); const c = jsonPin(pin); demand(!cashPin && c.protocol === 'cny-shadow-config-v2' && c.runId === recipe.runId && c.providerKind === 'real-provider' && c.ownerNonce === owned.ownerNonce && same(c.admissionPin, proofPin) && c.carryNanoCny === budget.carry.toString() && c.envelopeNanoCny === budget.envelope.toString(), 'chemiq_cash_registration'); cashPin = pin; },
    registerOwnedProcess(pin: Pin) { assertOwned(); const p = jsonPin(pin); demand(p.protocol === 'paid-owned-process-v2' && p.family === CHEMIQ_F_FAMILY && p.runId === recipe.runId && p.ownerNonce === owned.ownerNonce && p.pid > 0 && p.pid !== process.pid && Number.isSafeInteger(p.taskIndex) && !registered.some(r => jsonPin(r).taskIndex === p.taskIndex), 'chemiq_worker_registration'); registered.push(pin); },
    async release(proof: any) {
      assertOwned(); validateForwardSource(); demand(cashPin, 'chemiq_no_cash_to_release'); for (const p of carryProof.critical) verifyPin(p);
      const graph = await verifyChemiqCertificate(proof.certification, recipe.runId), certificate = graph.certificate;
      demand(same(certificate.source, proof.sourceClosed) && same(certificate.owned, proof.ownedClosed) && same(certificate.cash, proof.cashClosed), 'chemiq_release_bound_graph');
      const cash = verifyCashClosure(certificate.cash), close = jsonPin(certificate.owned);
      demand(same(cash.config.admissionPin, proofPin) && same(cash.proof.configPin, cashPin) && cash.config.carryNanoCny === '8392180000' && same(jsonPin(certificate.source).pins, recipe.sourcePins), 'chemiq_release_cash_source');
      demand(same(close.registrationPins, registered) && (certificate.kind !== 'score' || registered.length === plan.tasks.length), 'chemiq_release_worker_inventory');
      const { observeChemiqOwned } = await import('./chemiq-f-owned.ts');
      await observeChemiqOwned(recipe.output, registered, [close.proxyPort, close.gradePort], 'release');
      demand(Date.now() - Date.parse(certificate.createdAtUtc) <= 60000, 'chemiq_release_certificate_stale');
      validateForwardSource();
      const releasePin = durableChemiqJson(join(recipe.output, 'chemiq-financial-release.json'), { protocol: 'chemiq-f-financial-release-v1', family: CHEMIQ_F_FAMILY, runId: recipe.runId,
        ownerNonce: owned.ownerNonce, certificationPin: proof.certification, financialOnly: certificate.kind === 'financial-abort', scoreCertificateValid: certificate.kind === 'score', originalUnknownSettled: false, carriedOriginalUnknownNanoCny: '8392180000', released: false, observedAtUtc: new Date().toISOString() });
      assertOwned(); unlinkSync(path); released = true;
      const ack = durableChemiqJson(join(recipe.output, 'chemiq-lock-release-committed.json'), { protocol: 'chemiq-f-lock-release-committed-v1', family: CHEMIQ_F_FAMILY, runId: recipe.runId,
        ownerNonce: owned.ownerNonce, released: true, authorizationPin: releasePin, observedAtUtc: new Date().toISOString() });
      durableChemiqJson(registry, { protocol: CHEMIQ_F_REGISTRY, family: CHEMIQ_F_FAMILY, runId: recipe.runId, providerKind: 'real-provider', admissionPin: proofPin,
        released: true, certificationPin: proof.certification, releasePin, releaseCommittedPin: ack }, true);
    },
  });
}
