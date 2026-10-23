import { closeSync, fsyncSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { CampaignJournal, type Admission, type FinishInput } from "./campaign-journal.ts";
import { checkedOutputTokens, reconcileReceiptCost, type ApiReceipt } from "./campaign-contract.ts";
import { digest } from "./scientific-journal-plan.ts";
import { benchmarkProviderRequest, type BenchmarkInference } from "./benchmark-inference.ts";
import { type BenchmarkProvider } from "./benchmark-provider.ts";

export type Transport = (raw: string) => Promise<{ httpStatus: number; rawResponse: string }>;
export class CapturedTransportFailure extends Error {
  constructor(readonly capture: { httpStatus: number; rawBytes: Uint8Array; bodyComplete: false; fault: string }) { super(capture.fault); this.name = capture.fault; }
}
/** Trusted local transport rejected the request before any provider dispatch. */
export class ConfirmedNoForwardTransportFailure extends Error {
  constructor(message: string) { super(message); this.name = 'ConfirmedNoForwardTransportFailure'; }
}
/** A200 header never implies a complete body. Preserve the exact bounded bytes received on failure. */
export async function captureProviderResponse(response: Response, maxBytes = 64 * 1024 ** 2) {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 64 * 1024 ** 2) throw new Error("Invalid raw response capture limit");
  const chunks: Uint8Array[] = [], reader = response.body?.getReader(); let bytes = 0;
  const collected = () => Buffer.concat(chunks, bytes);
  try {
    if (reader) while (true) {
      const value = await reader.read(); if (value.done) break;
      const remaining = maxBytes - bytes;
      chunks.push(value.value.subarray(0, remaining)); bytes += Math.min(remaining, value.value.length);
      if (value.value.length > remaining) { try { await reader.cancel(); } catch {} throw new Error("ProviderResponseTooLarge"); }
    }
    const raw = collected();
    try { return { httpStatus: response.status, rawResponse: new TextDecoder("utf-8", { fatal: true }).decode(raw) }; }
    catch { throw new Error("ProviderResponseEncodingError"); }
  } catch (error) {
    const fault = error instanceof Error && ["ProviderResponseTooLarge", "ProviderResponseEncodingError"].includes(error.message) ? error.message : "ProviderResponseBodyError";
    throw new CapturedTransportFailure({ httpStatus: response.status, rawBytes: collected(), bodyComplete: false, fault });
  } finally { reader?.releaseLock(); }
}
type Admitted = Extract<Admission, { admitted: true }>;
export type TaskReceipt = ReturnType<CampaignJournal["finish"]>["receipt"] & {
  requestSeq: number; journalRef: { callId: number; finishOffset: number; finishEnd: number; finishLineSha256: string };
};
/** One proxy owns the only request admission queue. It never acquires/releases the external paid lock. */
export class ScientificJournalProxy {
  private stopReason?: string;
  private flights = new Map<Promise<unknown>, string>();
  private taskReceipts = new Map<string, TaskReceipt[]>();
  private anomalyOrdinal = 0;
  readonly anomalies: Record<string, unknown>[] = [];
  constructor(readonly journal: CampaignJournal, private options: {
    provider?: BenchmarkProvider;
    inference?: BenchmarkInference;
    routes: ReadonlySet<string>; failureDirectory: string; transport: Transport; beforeAdmission?: () => void; waitMs?: number;
    beforeForward?: (request: Admitted, startPrefix: ReturnType<CampaignJournal["snapshot"]>["durablePrefix"], raw: string, route: string) => void | Promise<void>;
    afterDurableFinish?: (receipt: TaskReceipt) => void | Promise<void>;
    afterFailedJournalCapture?: (request: Admitted | undefined, finish: FinishInput | undefined, evidence: Record<string, unknown>) => void | Promise<void>;
  }) {}
  stop(reason: string) { this.stopReason ??= reason; }
  state() { return { stopReason: this.stopReason, activeHandlers: this.flights.size, anomalies: this.anomalies.length, journal: this.journal.snapshot() }; }
  pending(route: string) { return [...this.flights.values()].filter(value => value === route).length; }
  async drain(route?: string) {
    while (true) {
      const current = [...this.flights].filter(([, value]) => route === undefined || route === value).map(([promise]) => promise);
      if (!current.length) return;
      await Promise.allSettled(current);
    }
  }
  takeTaskReceipts(route: string) {
    if (this.pending(route)) throw new Error("Task transport has not drained");
    const receipts = this.taskReceipts.get(route) ?? [];
    this.taskReceipts.delete(route);
    return receipts.sort((a, b) => a.requestSeq - b.requestSeq);
  }
  handle(route: string, raw: string) {
    const job = this.perform(route, raw);
    this.flights.set(job, route);
    void job.then(() => this.flights.delete(job), () => this.flights.delete(job));
    return job;
  }
  private async fallback(input: { stage: string; route: string; admitted?: Admitted; rawRequest?: string; finish?: FinishInput; rawResponseBytes?: Uint8Array; journalRef?: TaskReceipt["journalRef"]; error: unknown }) {
    const snapshot = this.journal.snapshot();
    const receipt: ApiReceipt = { providerAttempted: input.finish?.providerAttempted ?? false,
      ...(input.finish?.httpStatus !== undefined ? { httpStatus: input.finish.httpStatus } : {}),
      fault: "journal_failure", finishedAt: input.finish?.finishedAt ?? new Date().toISOString() } as ApiReceipt;
    let usage: unknown;
    if (input.finish?.rawResponse !== undefined) {
      try { usage = JSON.parse(input.finish.rawResponse).usage; if (usage && typeof usage === "object") receipt.usage = usage as Record<string, unknown>; } catch {}
    }
    const facts = { schemaVersion: 1, stage: input.stage, route: input.route, requestSeq: input.admitted?.requestSeq,
      providerAttempted: input.finish?.providerAttempted ?? false, confirmedNoForward: !input.finish?.providerAttempted,
      httpStatus: input.finish?.httpStatus, observedAt: new Date().toISOString(),
      requestSha256: input.admitted?.requestSha256 ?? (input.rawRequest === undefined ? undefined : digest(input.rawRequest)),
      rawResponseSha256: input.rawResponseBytes ? digest(input.rawResponseBytes) : input.finish?.rawResponse === undefined ? undefined : digest(input.finish.rawResponse),
      bodyComplete: input.rawResponseBytes ? false : undefined,
      journalRef: input.journalRef,
      usage, independentCost: reconcileReceiptCost(receipt, input.admitted?.reservationUsd ?? 0, { knownUncharged: !input.finish?.providerAttempted }),
      accounting: "Independent transport facts only. Original poisoned journal/pending/reserve are not repaired. Cost may overlap a durable finish; auditor must reconcile call ID before adding liability.",
      journalSnapshot: snapshot, error: input.error instanceof Error ? input.error.name : "JournalFailure",
      files: [] as Record<string, unknown>[], evidenceWriteError: undefined as string | undefined };
    const sequence = this.anomalyOrdinal++;
    const persist = (name: string, data: Uint8Array) => {
      const path = join(this.options.failureDirectory, `failure-${sequence}-${name}`), fd = openSync(path, "wx", 0o600);
      try { writeFileSync(fd, data); fsyncSync(fd); } finally { closeSync(fd); }
      return { path, bytes: data.byteLength, sha256: digest(data) };
    };
    try {
      mkdirSync(this.options.failureDirectory, { recursive: true });
      if (input.rawRequest !== undefined) facts.files.push(persist("request.json.gz", gzipSync(input.rawRequest)));
      if (input.rawResponseBytes || input.finish?.rawResponse !== undefined) facts.files.push(persist("response.json.gz", gzipSync(input.rawResponseBytes ?? input.finish!.rawResponse!)));
      facts.files.push(persist("receipt.json", Buffer.from(JSON.stringify(facts, null, 2) + "\n")));
    } catch (error) { facts.evidenceWriteError = error instanceof Error ? error.name : "FailureEvidenceIo"; }
    this.anomalies.push(facts);
    this.stop("journal_poison_or_evidence_failure");
    try { await this.options.afterFailedJournalCapture?.(input.admitted, input.finish, facts); }
    catch { facts.evidenceWriteError ??= "CashShadowLateCaptureFailure"; }
  }
  private async perform(route: string, raw: string): Promise<{ httpStatus: number; rawResponse: string }> {
    const rejected = (status: number, why: string) => ({ httpStatus: status, rawResponse: JSON.stringify({ error: { message: why } }) });
    let admitted: Admitted | undefined;
    try {
      if (!this.options.routes.has(route)) return rejected(404, "Unplanned model route");
      let body = JSON.parse(raw);
      if (this.options.inference) {
        body = benchmarkProviderRequest(body, this.options.inference, this.options.provider);
        raw = JSON.stringify(body);
      }
      if (body.model !== (this.options.provider?.model ?? "deepseek-flash") || body.stream === true || body.temperature !== 0 || (!this.options.provider && body.seed !== 42) ||
          !this.options.inference && (body.reasoning_effort !== "none" || checkedOutputTokens(body) !== 8192)) throw new Error("Wire parameters differ from the fixed scientific protocol");
      checkedOutputTokens(body);
      const started = Date.now();
      while (!admitted) {
        if (this.stopReason) return rejected(503, "Admission stopped: " + this.stopReason);
        this.options.beforeAdmission?.();
        const value = this.journal.admit({ route, rawRequest: raw });
        if (value.admitted) admitted = value;
        else if (value.reason !== "pending_limit") { this.stop(value.reason); return rejected(503, "Admission stopped: " + value.reason); }
        else {
          if (Date.now() - started > (this.options.waitMs ?? 300000)) { this.stop("admission_queue_timeout"); return rejected(503, "Admission queue timed out"); }
          await Bun.sleep(10);
        }
      }
    } catch (error) {
      await this.fallback({ stage: "admission", route, rawRequest: raw, error });
      return rejected(503, "Request was not forwarded; journal or protocol admission failed");
    }
    let response: { httpStatus: number; rawResponse: string } | undefined, fault: string | undefined, forwarded = false;
    let bodyFailure: CapturedTransportFailure | undefined;
    try {
      await this.options.beforeForward?.(admitted, this.journal.snapshot().durablePrefix, raw, route);
      if (this.stopReason) throw new Error("Admission stopped before provider dispatch");
      forwarded = true;
      response = await this.options.transport(raw);
    } catch (error) {
      fault = error instanceof Error ? error.name : "ProviderTransportError";
      if (error instanceof ConfirmedNoForwardTransportFailure) forwarded = false;
      if (error instanceof CapturedTransportFailure) {
        bodyFailure = error;
        // A valid UTF8 prefix can be stored by the frozen journal; exact raw bytes are also captured independently.
        try { response = { httpStatus: error.capture.httpStatus, rawResponse: new TextDecoder("utf-8", { fatal: true }).decode(error.capture.rawBytes) }; } catch {}
      }
      this.stop(forwarded ? "provider_transport_error" : "funding_before_forward_error");
    }
    const finish: FinishInput = { requestSeq: admitted.requestSeq, providerAttempted: forwarded,
      ...(!forwarded ? { confirmedNoForward: true } : {}), ...(response ?? {}), ...(bodyFailure ? { httpStatus: bodyFailure.capture.httpStatus } : {}), ...(fault ? { fault } : {}), finishedAt: new Date().toISOString() };
    let durableReceipt: TaskReceipt | undefined;
    try {
      const before = this.journal.snapshot().durablePrefix.bytes;
      const result = this.journal.finish(finish);
      const prefix = this.journal.snapshot().durablePrefix;
      const receipt = { ...result.receipt, requestSeq: result.requestSeq, journalRef: { callId: result.requestSeq, finishOffset: before, finishEnd: prefix.bytes, finishLineSha256: prefix.lastSha256 } };
      durableReceipt = receipt;
      await this.options.afterDurableFinish?.(receipt);
      if (bodyFailure) await this.fallback({ stage: "provider_body_incomplete", route, admitted, finish, journalRef: receipt.journalRef, rawResponseBytes: bodyFailure.capture.rawBytes, error: bodyFailure });
      const records = this.taskReceipts.get(route) ?? [];
      records.push(receipt); this.taskReceipts.set(route, records);
      if (this.journal.snapshot().stopReason) this.stop(this.journal.snapshot().stopReason!);
      return !fault && response ? response : rejected(503, "Provider transport did not complete; conservative request charge retained");
    } catch (error) {
      await this.fallback({ stage: "finish_or_post_finish_checkpoint", route, admitted, finish, journalRef: durableReceipt?.journalRef, rawResponseBytes: bodyFailure?.capture.rawBytes, error });
      return rejected(503, "Transport finished but journal remains invalid; actual response captured independently");
    }
  }
}
