/** SkillsBench-owned USD cash fork: retain unknown evidence and continue.
 * Based on frozen repair-2026-10-08/benchmark-usd-cash.ts; event/close replay
 * remains compatible with its independent verifier. Shared source unchanged.
 */
import { closeSync, fsyncSync, openSync, readFileSync, readSync, statSync, writeSync } from "node:fs";
import { join, resolve } from "node:path";
import { inspectCampaignJournal } from "../shared/digitalocean-journal.ts";
import { createCnyCashShadow, type CashOptions, type CashFinish, type CashTicket, type JournalStart } from "../../../benchmark-repair/cny-cash-shadow-v2.ts";
import { actualPin, demand, gzipProof, hash, jsonPin, ordinaryDirectory, same, verifyPin, type Pin } from "../../../benchmark-repair/paid-resource-proof-v2.ts";
import { BENCHMARK_PROVIDER, type BenchmarkProvider } from "../shared/digitalocean-provider.ts";

export type UsdAdmission = { currency: "USD"; capUsd: number; runId: string; proofPin: Pin;
  owned: { ownerNonce: string; family?: string; pid: number }; scope: "production";
  assertOwned(): void; validateForwardSource(): void; registerCash(pin: Pin): void };
type Ticket = Readonly<{ requestSeq: number; route: string; reservationUsd: number; currency: "USD"; dispatchAllowed: boolean }>;
export type BenchmarkCashTicket = CashTicket | Ticket;
export type BenchmarkCash = { snapshot(): any; poison(reason: string): void;
  beforeForward(input: { id: string; route: string; rawRequest: Uint8Array; capturedRequest: Pin; journal: JournalStart }): { admitted: boolean; ticket: BenchmarkCashTicket; reason?: string };
  finish(ticket: BenchmarkCashTicket, finish: CashFinish): any; close(): Pin };
export type BenchmarkCashOptions = Omit<CashOptions, "admission"> & { admission?: CashOptions["admission"] | UsdAdmission };

function durable(path: string, value: any) {
  const raw = Buffer.from(JSON.stringify(value, null, 2) + "\n"), fd = openSync(path, "wx", 0o600);
  try { let at = 0; while (at < raw.length) { const count = writeSync(fd, raw, at, raw.length - at); demand(count > 0, "usd_cash_short_write"); at += count; } fsyncSync(fd); }
  finally { closeSync(fd); }
  demand(readFileSync(path).equals(raw), "usd_cash_readback"); return actualPin(path);
}
function validateUsdPrices(pin: Pin, providerSlug = BENCHMARK_PROVIDER.providerSlug) {
  const data = jsonPin(pin);
  demand(data.protocol === "openrouter-usd-pricing-source-snapshot-v1" && data.model === BENCHMARK_PROVIDER.model && data.currency === "USD" && data.providerSlug === providerSlug && data.actualOfficialGET === true && data.modelCalls === 0, "openrouter_price_profile");
  demand(same(data.reservationRates, BENCHMARK_PROVIDER.peakRates), "openrouter_reservation_rates");
  const raw = jsonPin(data.originalResponsePin);
  demand(raw.data?.endpoints?.some((row: any) => row.provider_name === ({relace:'Relace',deepseek:'DeepSeek',digitalocean:'DigitalOcean'}[providerSlug]) && row.tag === providerSlug && row.model_id === BENCHMARK_PROVIDER.model), "openrouter_price_raw_binding");
  return data;
}
function boundStart(directory: string, data: any) {
  const raw = readFileSync(join(directory, "api-events.jsonl")), end = data.startPrefix.bytes;
  demand(Number.isSafeInteger(end) && end > 0 && end <= raw.length && raw[end - 1] === 10, "usd_start_prefix_bounds");
  const begin = raw.lastIndexOf(10, end - 2) + 1, line = raw.subarray(begin, end), event = JSON.parse(line.toString("utf8"));
  demand(hash(line) === data.startPrefix.lastSha256 && event.kind === "start" && event.eventSeq + 1 === data.startPrefix.eventCount
    && event.requestSeq === data.ticket.requestSeq && event.record.route === data.ticket.route
    && same(data.requestPin, actualPin(event.record.requestFile)) && data.requestSha256 === event.record.requestSha256, "usd_start_journal_binding");
  gzipProof(data.requestPin, data.requestSha256, undefined, 4 * 1024 ** 2);
  return event.record;
}

export function createRecordingCash(options: BenchmarkCashOptions, provider?: BenchmarkProvider): BenchmarkCash {
  if (!provider) return createCnyCashShadow(options as CashOptions) as BenchmarkCash;
  return new UsdCash(options);
}
class UsdCash implements BenchmarkCash {
  private states = new Map<number, { ticket: Ticket; phase: "pending" | "denied" | "known" | "unknown"; amount: number; signature?: string }>();
  private tickets = new WeakSet<object>(); private events: any[] = []; private poisonReason?: string; private closed?: Pin;
  private fd: number; private previousHash: string; private capUsd: number; private bytes = 0;
  readonly directory: string; readonly configPin: Pin; readonly prices: any; readonly config: any;
  constructor(private options: BenchmarkCashOptions) {
    const admission = options.admission as UsdAdmission | undefined;
    demand(options.providerKind === "local-mock" || admission?.currency === "USD", "openrouter_usd_admission_required");
    this.directory = ordinaryDirectory(options.directory); this.prices = validateUsdPrices(options.prices);
    const config = jsonPin(options.journal.configPin);
    demand(config.provider === "openrouter-deepseek" && config.currency === "USD" && config.campaign === options.runId && config.priorCampaignCostUpperBoundUsd === 0, "openrouter_cash_journal_binding");
    this.capUsd = admission?.capUsd ?? config.capUsd;
    demand(Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd, "openrouter_cash_cap_binding");
    this.config = { protocol: "openrouter-usd-cash-config-v1", runId: options.runId,
      currency: "USD", providerKind: options.providerKind, capUsd: this.capUsd, costPolicy:"record_and_continue", ownerNonce: admission?.owned.ownerNonce ?? null,
      scope: admission?.scope ?? 'local-mock',
      admissionPin: admission?.proofPin ?? null, pricesPin: options.prices, journal: options.journal,
      sourcePin: actualPin(import.meta.path), createdAt: new Date().toISOString(), invoice: false, foreignExchangeConversion: false };
    this.configPin = durable(join(this.directory, "cash-config.json"), this.config);
    this.previousHash = this.configPin.sha256; this.fd = openSync(join(this.directory, "cash-events.jsonl"), "wx+", 0o600); fsyncSync(this.fd);
    try { admission?.registerCash(this.configPin); } catch (error) { closeSync(this.fd); throw error; }
  }
  private append(kind: string, data: any) {
    const event = { protocol: "openrouter-usd-cash-event-v1", index: this.events.length, previousSha256: this.previousHash, kind, data };
    const raw = Buffer.from(JSON.stringify(event) + "\n"); demand(raw.length <= 65536 && this.bytes + raw.length <= 256 * 1024 ** 2, "usd_cash_event_limit");
    let at = 0; while (at < raw.length) { const count = writeSync(this.fd, raw, at, raw.length - at, this.bytes + at); demand(count > 0, "usd_cash_short_write"); at += count; } fsyncSync(this.fd);
    const readback = Buffer.alloc(raw.length);
    demand(readSync(this.fd, readback, 0, raw.length, this.bytes) === raw.length && readback.equals(raw)
      && statSync(join(this.directory, "cash-events.jsonl")).size === this.bytes + raw.length, "usd_cash_event_readback");
    this.bytes += raw.length;
    this.previousHash = hash(raw); this.events.push(event);
  }
  snapshot() {
    let known = 0, pending = 0, unknown = 0, pendingCount = 0, unknownCount = 0;
    for (const state of this.states.values()) {
      if (state.phase === "known") known += state.amount;
      if (state.phase === "pending") { pending += state.ticket.reservationUsd; pendingCount++; }
      if (state.phase === "unknown") { unknown += state.amount; unknownCount++; }
    }
    return { protocol: "openrouter-usd-cash-state-v1", currency: "USD", runId: this.options.runId,
      capUsd: this.capUsd, billedUsd: known, pendingReservationUsd: pending, unknownReservationUsd: unknown,
      exposureUpperBoundUsd: known + pending + unknown, remainingUsd: this.capUsd - known - pending - unknown,
      pendingCount, newUnknownCount: unknownCount, poisoned: !!this.poisonReason, poisonReason: this.poisonReason ?? null,
      invoice: false, foreignExchangeConversion: false };
  }
  poison(reason: string) { this.poisonReason ??= reason; }
  beforeForward(input: Parameters<BenchmarkCash["beforeForward"]>[0]) {
    demand(!this.closed && permitsRecordedUnknown(this.snapshot()), "usd_cash_closed_or_nonfinancial_poisoned");
    const admission = this.options.admission as UsdAdmission | undefined; admission?.validateForwardSource();
    verifyPin(this.options.prices); verifyPin(this.config.sourcePin); verifyPin(this.options.journal.sourcePin);
    const observed = Date.parse(this.prices.observedAtUtc);
    if (this.options.providerKind === "real-provider") demand(Number.isFinite(observed) && Date.now() >= observed && Date.now() - observed <= 86400000, "openrouter_price_expired");
    const j = input.journal.admitted, raw = gzipProof(input.capturedRequest, j.requestSha256, undefined, 4 * 1024 ** 2);
    const inspected = inspectCampaignJournal(this.options.journal.directory);
    demand(inspected.valid && Buffer.from(input.rawRequest).equals(raw) && resolve(input.capturedRequest.path) === resolve(j.requestFile) && j.requestSeq === this.states.size, "usd_actual_request_binding");
    const reservationUsd = this.options.providerKind === "local-mock" ? 0 : j.reservationUsd;
    const permitted = this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 1e-9;
    const ticket: Ticket = Object.freeze({ requestSeq: j.requestSeq, route: input.route, reservationUsd,
      currency: "USD", dispatchAllowed: permitted });
    const start = { ticket, requestPin: input.capturedRequest, requestSha256: j.requestSha256, startPrefix: input.journal.startPrefix };
    demand(boundStart(this.options.journal.directory, start).reservationUsd === j.reservationUsd, "usd_actual_reservation_binding");
    this.append("start", start);
    this.states.set(j.requestSeq, { ticket, phase: permitted ? "pending" : "denied", amount: 0 }); this.tickets.add(ticket);
    if (!permitted) this.poison("usd_envelope_exhausted");
    return { admitted: permitted, ticket, ...(!permitted ? { reason: "usd_envelope_exhausted" } : {}) };
  }
  finish(given: BenchmarkCashTicket, finish: CashFinish) {
    demand(!this.closed && this.tickets.has(given), "usd_ticket_not_owned");
    const ticket = given as Ticket, state = this.states.get(ticket.requestSeq)!;
    const signature = hash(JSON.stringify(finish));
    if (state.signature) { demand(state.signature === signature, "usd_duplicate_finish_changed"); return this.snapshot(); }
    let phase: "known" | "unknown", amount: number, receipt: any;
    if (finish.kind === "journal-finish") {
      const ref = finish.journalRef;
      const bytes = readFileSync(join(this.options.journal.directory, "api-events.jsonl"));
      const line = bytes.subarray(ref.finishOffset, ref.finishEnd);
      demand(hash(line) === ref.finishLineSha256, "usd_finish_line_changed");
      const event = JSON.parse(line.toString("utf8")); receipt = event.record;
      demand(event.kind === "finish" && event.requestSeq === ticket.requestSeq && receipt.route === ticket.route && inspectCampaignJournal(this.options.journal.directory).valid, "usd_finish_journal_binding");
      phase = receipt.costBasis === "reservation" ? "unknown" : "known";
      amount = this.options.providerKind === "local-mock" ? 0 : receipt.usdUpperBound;
    } else {
      // Incomplete or failed journal capture never silently becomes zero USD.
      phase = "unknown"; amount = ticket.reservationUsd; this.poison("usd_failed_capture_unsettled");
    }
    demand(Number.isFinite(amount) && amount >= 0, "usd_finish_amount_invalid");
    this.append("finish", { ticket, signature, phase, amountUsd: amount, finish,
      costBasis: receipt?.costBasis ?? "reservation", generationId: receipt?.requestId ?? null,
      providerName: receipt?.providerName ?? null, servedModel: receipt?.servedModel ?? null });
    state.phase = phase; state.amount = amount; state.signature = signature;
    if (phase === "unknown") this.poison("usd_unknown_charge");
    if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 1e-9) this.poison("usd_cost_exceeded_cap");
    return this.snapshot();
  }
  close() {
    if (this.closed) return this.closed;
    fsyncSync(this.fd); closeSync(this.fd);
    const inspection = inspectCampaignJournal(this.options.journal.directory), state = this.snapshot();
    this.closed = durable(join(this.directory, "cash-close.json"), { protocol: "openrouter-usd-cash-close-v1",
      currency: "USD", configPin: this.configPin, cashEventsPin: actualPin(join(this.directory, "cash-events.jsonl")),
      snapshot: state, journalDirectory: this.options.journal.directory, journalPrefix: inspection.prefix,
      releasePermitted: inspection.valid && inspection.accountingClosed && state.pendingCount === 0 && state.newUnknownCount === 0,
      scoreCertificate: false, invoice: false, foreignExchangeConversion: false });
    return this.closed;
  }
}

export function permitsRecordedUnknown(snapshot:{poisoned:boolean;poisonReason:string|null}){
  return !snapshot.poisoned||['usd_unknown_charge','usd_failed_capture_unsettled'].includes(snapshot.poisonReason??'');
}

export function verifyBenchmarkCashClosure(closePin: Pin) {
  const proof = jsonPin(closePin);
  if (proof.protocol !== "openrouter-usd-cash-close-v1") throw Error("Expected OpenRouter USD cash closure");
  const config = jsonPin(proof.configPin), eventsRaw = readFileSync(verifyPin(proof.cashEventsPin));
  const journalConfig = jsonPin(config.journal.configPin);
  validateUsdPrices(config.pricesPin, journalConfig.providerSlug ?? 'deepseek'); verifyPin(config.sourcePin); verifyPin(config.journal.sourcePin);
  demand(config.currency === "USD" && config.protocol === "openrouter-usd-cash-config-v1" && Number.isFinite(config.capUsd) && config.capUsd > 0
    && resolve(config.journal.directory) === resolve(proof.journalDirectory) && journalConfig.currency === "USD"
    && journalConfig.provider === BENCHMARK_PROVIDER.kind && journalConfig.campaign === config.runId
    && journalConfig.priorCampaignCostUpperBoundUsd === 0 && journalConfig.capUsd <= config.capUsd, "usd_close_config");
  const journal = inspectCampaignJournal(proof.journalDirectory);
  demand(journal.valid && journal.accountingClosed && same(journal.prefix, proof.journalPrefix), "usd_close_journal");
  demand(eventsRaw.length <= 256 * 1024 ** 2 && (eventsRaw.length === 0 || eventsRaw.at(-1) === 10), "usd_cash_complete_events");
  let previous = proof.configPin.sha256, seq = 0, starts = 0, known = 0, unknown = 0, unknownCount = 0;
  const active = new Map<number, any>();
  for (const text of eventsRaw.toString("utf8").trimEnd().split("\n").filter(Boolean)) {
    const event = JSON.parse(text);
    demand(JSON.stringify(event) === text && Buffer.byteLength(text) <= 65536 && event.index === seq++ && event.previousSha256 === previous && event.protocol === "openrouter-usd-cash-event-v1", "usd_cash_chain"); previous = hash(text + "\n");
    const { data } = event;
    if (event.kind === "start") {
      const ticket = data.ticket, start = boundStart(proof.journalDirectory, data);
      demand(ticket.requestSeq === starts++ && ticket.currency === "USD" && ticket.reservationUsd === (config.providerKind === "local-mock" ? 0 : start.reservationUsd), "usd_start_reservation");
      const pending = [...active.values()].reduce((sum, row) => sum + (row.dispatchAllowed ? row.reservationUsd : 0), 0);
      demand(ticket.dispatchAllowed === (known + unknown + pending + ticket.reservationUsd <= config.capUsd + 1e-9), "usd_start_budget_replay");
      active.set(ticket.requestSeq, ticket);
    }
    else {
      demand(event.kind === "finish" && same(active.get(data.ticket.requestSeq), data.ticket) && data.signature === hash(JSON.stringify(data.finish))
        && Number.isFinite(data.amountUsd) && data.amountUsd >= 0, "usd_cash_finish_without_start");
      if (data.finish.kind === "journal-finish") {
        const ref = data.finish.journalRef, raw = readFileSync(join(proof.journalDirectory, "api-events.jsonl")).subarray(ref.finishOffset, ref.finishEnd);
        const offset = journal.offsets.get(data.ticket.requestSeq);
        demand(offset && offset.offset === ref.finishOffset && offset.offset + offset.bytes === ref.finishEnd && offset.sha256 === ref.finishLineSha256 && hash(raw) === ref.finishLineSha256, "usd_cash_raw_finish");
        const source = JSON.parse(raw.toString("utf8"));
        demand(source.kind === "finish" && source.requestSeq === data.ticket.requestSeq && source.record.route === data.ticket.route
          && data.phase === (source.record.costBasis === "reservation" ? "unknown" : "known") && data.costBasis === source.record.costBasis
          && data.generationId === (source.record.requestId ?? null) && data.providerName === (source.record.providerName ?? null)
          && data.servedModel === (source.record.servedModel ?? null)
          && (config.providerKind === "local-mock" ? data.amountUsd === 0 : source.record.usdUpperBound === data.amountUsd), "usd_cash_amount_binding");
      } else demand(data.finish.kind === "failed-capture" && data.finish.requestSeq === data.ticket.requestSeq && data.phase === "unknown" && data.amountUsd === data.ticket.reservationUsd, "usd_unknown_reservation_binding");
      active.delete(data.ticket.requestSeq); if (data.phase === "known") known += data.amountUsd; else { unknown += data.amountUsd; unknownCount++; }
    }
  }
  demand(active.size === 0 && starts === journal.snapshot!.acceptedRequestCount && proof.snapshot.pendingCount === 0 && proof.snapshot.pendingReservationUsd === 0
    && proof.snapshot.currency === "USD" && proof.snapshot.runId === config.runId && proof.snapshot.capUsd === config.capUsd
    && proof.snapshot.newUnknownCount === unknownCount && Math.abs(proof.snapshot.billedUsd - known) < 1e-9
    && Math.abs(proof.snapshot.unknownReservationUsd - unknown) < 1e-9 && Math.abs(proof.snapshot.exposureUpperBoundUsd - known - unknown) < 1e-9
    && Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 1e-9
    && (config.providerKind === "local-mock" || Math.abs(journal.snapshot!.recordedUsageUpperBoundUsd - known - unknown) < 1e-9), "usd_cash_replay_totals");
  demand(proof.releasePermitted === (unknownCount === 0) && (!(unknownCount || known + unknown > config.capUsd + 1e-9) || proof.snapshot.poisoned === true), "usd_release_consistency");
  return { proof, config };
}
