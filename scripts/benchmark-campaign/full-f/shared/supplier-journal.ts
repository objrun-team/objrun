import { createHash, randomBytes } from "node:crypto";
import { closeSync, existsSync, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readSync, readdirSync, realpathSync, renameSync, statSync, writeSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { gunzipSync, gzipSync } from "node:zlib";
import { checkedOutputTokens, completionFault, isNonGenerationRateRejection, reconcileReceiptCost, validTokenUsage, type ApiReceipt } from "../../../benchmark-repair/campaign-contract.ts";
import { BENCHMARK_PROVIDER, officialOpenRouterFault, openRouterRateLimitRejection, type BenchmarkProvider } from "./digitalocean-provider.ts";

export const CAMPAIGN_JOURNAL_PROTOCOL = "campaign-api-journal-v1";
export const OPENROUTER_JOURNAL_PROTOCOL = "campaign-api-journal-openrouter-v1";
const MAX_LINE = 64 * 1024;
const MAX_REQUEST = 4 * 1024 * 1024;
const MAX_RESPONSE = 64 * 1024 * 1024;
const MAX_JOURNAL = 2 * 1024 * 1024 * 1024;
const EPS = 1e-9;
const WIRE = ["model", "temperature", "seed", "reasoning_effort", "thinking", "reasoning", "provider", "max_tokens", "max_completion_tokens", "tool_choice", "response_format", "stream"];
const hash = (data: string | Buffer) => createHash("sha256").update(data).digest("hex");
const json = (value: unknown) => JSON.stringify(value);
const same = (a: unknown, b: unknown) => json(a) === json(b);
const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n >= 0;

export class CampaignJournalError extends Error {
  readonly code: string;
  readonly stage?: string;
  constructor(code: string, stage?: string) { super(code + (stage ? ":" + stage : "")); this.name = "CampaignJournalError"; this.code = code; this.stage = stage; }
}
function demand(ok: unknown, code: string): asserts ok { if (!ok) throw new CampaignJournalError(code); }

export interface JournalIoOperation {
  kind: "write" | "fsync" | "rename";
  stage: string;
  path: string;
  fd?: number;
  bytes?: number;
}
export interface JournalHooks { before?: (op: JournalIoOperation) => void; after?: (op: JournalIoOperation) => void }
export interface JournalOptions { directory: string; campaign: string; capUsd: number; priorCampaignCostUpperBoundUsd: number; outputDirectory?: string; provider?: BenchmarkProvider }
type Prefix = { bytes: number; eventCount: number; lastSha256: string };
type Receipt = ApiReceipt & { route: string; startedAt: string; requestSha256: string; requestedModel: string; requestFile: string; providerAttempted: boolean; wireParameters: Record<string, unknown>; requestCompressedSha256: string; requestBytes: number; responseFile?: string; responseSha256?: string; responseCompressedSha256?: string; servedModel?: string; requestId?: string; confirmedNoForward?: boolean; providerName?: string };
type Config = { protocol: string; campaign: string; capUsd: number; priorCampaignCostUpperBoundUsd: number; pendingLimit: number; model: string; provider?: "openrouter-deepseek"; currency?: "USD";
  providerName?: string; providerSlug?: string; providerRouting?: typeof BENCHMARK_PROVIDER.routing; zeroChargePolicy?: 'explicit-rate-rejection-v2'; maxLineBytes: number; maxJournalBytes: number; createdAt: string };
type Event = { protocol: string; eventSeq: number; previousEventSha256: string; kind: "start" | "finish"; requestSeq: number; record: Receipt };
type Offset = { offset: number; bytes: number; sha256: string };
type Metrics = { journalBytesWritten: number; checkpointBytesWritten: number; rawGzipBytesWritten: number; exportBytesWritten: number; fsyncCallsReturned: number; maxHotMetadataBytes: number };
type Active = { requestSeq: number; receipt: Receipt };
export interface FinishInput { requestSeq: number; providerAttempted: boolean; httpStatus?: number; rawResponse?: string; fault?: string; confirmedNoForward?: boolean; finishedAt?: string }
export type Admission = { admitted: false; reason: string } | { admitted: true; requestSeq: number; reservationUsd: number; requestFile: string; requestSha256: string };

function ordinaryDirectory(path: string) {
  demand(isAbsolute(path), "absolute_directory_required");
  mkdirSync(path, { recursive: true });
  demand(lstatSync(path).isDirectory() && !lstatSync(path).isSymbolicLink(), "ordinary_directory_required");
  return realpathSync(path);
}
function regularInStore(path: string, store: string) {
  const full = resolve(path), rel = relative(store, full);
  demand(rel && !rel.startsWith("..") && !isAbsolute(rel), "raw_outside_store");
  let current = store;
  for (const component of rel.split(/[\\/]/)) {
    current = join(current, component);
    const s = lstatSync(current);
    demand(!s.isSymbolicLink(), "raw_reparse");
  }
  demand(lstatSync(full).isFile() && realpathSync(full) === full, "raw_not_regular");
  return full;
}
function fileHash(path: string) {
  const before = statSync(path), fd = openSync(path, "r"), digest = createHash("sha256"), buffer = Buffer.alloc(64 * 1024); let at = 0;
  try { while (at < before.size) { const n = readSync(fd, buffer, 0, Math.min(buffer.length, before.size - at), at); demand(n > 0, "hash_short_read"); digest.update(buffer.subarray(0, n)); at += n; } }
  finally { closeSync(fd); }
  const after = statSync(path); demand(before.size === after.size && before.mtimeMs === after.mtimeMs, "hash_file_changed"); return digest.digest("hex");
}
function rawEvidence(path: string, expected: string, compressedExpected: string, store: string, parse = true) {
  regularInStore(path, store);
  const before = statSync(path);
  const zipped = readFileSync(path);
  demand(zipped.length <= MAX_RESPONSE + 1024 * 1024, "raw_resource_limit");
  const raw = gunzipSync(zipped, { maxOutputLength: MAX_RESPONSE });
  const after = statSync(path);
  demand(before.size === after.size && before.mtimeMs === after.mtimeMs && hash(zipped) === compressedExpected && hash(raw) === expected, "raw_digest_changed");
  const data = parse ? JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) : undefined;
  return { raw, data };
}
function frozenRouting(config: Config) {
  const slug = config.providerSlug ?? "deepseek";
  demand(config.zeroChargePolicy === undefined || config.zeroChargePolicy === 'explicit-rate-rejection-v2', 'journal_zero_charge_policy');
  demand(["deepseek", "relace", "digitalocean", "dekallm", "wafer"].includes(slug) && (config.providerName === undefined || config.providerName === ({relace:"Relace",deepseek:"DeepSeek",digitalocean:"DigitalOcean",dekallm:"DekaLLM",wafer:"Wafer"}[slug])), "journal_provider_identity");
  const route = { only: [slug], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };
  demand(config.providerRouting === undefined || same(config.providerRouting, route), "journal_provider_route");
  return route;
}
function requestValues(raw: Buffer, data: Record<string, unknown>, config?: Config) {
  demand(data && typeof data === "object" && !Array.isArray(data) && data.model === (config?.model ?? "deepseek-flash") && data.stream !== true, "invalid_frozen_request");
  if (config?.provider) demand(same(data.provider, frozenRouting(config)) && data.models === undefined && data.route === undefined && data.plugins === undefined, "pinned_provider_routing_required");
  const limit = checkedOutputTokens(data);
  demand(Array.isArray(data.messages), "invalid_request_messages");
  const reservationUsd = ((raw.length + 2048 + data.messages.length * 256) * 0.3 + limit * 1.2) / 1e6;
  return { reservationUsd, wireParameters: Object.fromEntries(WIRE.filter(k => k in data).map(k => [k, data[k]])) };
}
function checkedStart(c: Receipt, seq: number, store: string, config: Config) {
  demand(typeof c.route === "string" && c.route.length > 0 && Buffer.byteLength(c.route) <= 1024 && !/[\r\n\0]/.test(c.route), "invalid_route");
  demand(Number.isFinite(Date.parse(c.startedAt)) && c.providerAttempted === false, "invalid_start_receipt");
  demand(c.requestFile === join(store, `provider-${seq}-request.json.gz`), "request_sequence_path");
  const { raw, data } = rawEvidence(c.requestFile, c.requestSha256, c.requestCompressedSha256, store);
  const expected = requestValues(raw, data, config);
  demand(raw.length === c.requestBytes && c.requestedModel === data.model && same(c.wireParameters, expected.wireParameters) && finite(c.reservationUsd) && Math.abs(c.reservationUsd - expected.reservationUsd) <= EPS, "request_receipt_mismatch");
}
function routingRejection(config: Config, data: any, status?: number) {
  return !!config.provider && status === 404 && Array.isArray(data?.error?.metadata?.routing_funnel) && typeof data?.error?.metadata?.failed_routing_step === "string" && data.error.metadata.failed_routing_step.startsWith("Filter by ") && !data.usage;
}
function rateRejection(config: Config, data: any, status?: number) {
  return !!config.provider && config.zeroChargePolicy === 'explicit-rate-rejection-v2' && openRouterRateLimitRejection(data, status, config.providerName ?? 'DeepSeek');
}
function checkedFinish(c: Receipt, start: Receipt, seq: number, store: string, config: Config) {
  for (const key of ["route", "startedAt", "requestSha256", "requestedModel", "requestFile", "wireParameters", "requestCompressedSha256", "requestBytes"] as const) demand(same(c[key], start[key]), "finish_start_mismatch");
  demand(typeof c.providerAttempted === "boolean" && typeof c.finishedAt === "string" && Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
  if (!c.providerAttempted) demand(c.confirmedNoForward === true && !c.responseFile && !c.usage, "unproven_zero_charge");
  let rejectedBeforeGeneration = false, rateLimited = false;
  if (c.responseFile) {
    demand(c.providerAttempted && c.responseFile === join(store, `provider-${seq}-response.json.gz`) && c.responseSha256 && c.responseCompressedSha256, "response_sequence_path");
    const { raw } = rawEvidence(c.responseFile, c.responseSha256, c.responseCompressedSha256, store, false);
    let data: Record<string, unknown> | undefined;
    try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); } catch {}
    if (data && typeof data === "object") {
      rejectedBeforeGeneration = routingRejection(config, data, c.httpStatus);
      rateLimited = rateRejection(config, data, c.httpStatus);
      demand(same(data.usage, c.usage) && (typeof data.model === "string" ? data.model : undefined) === c.servedModel && (typeof data.id === "string" ? data.id : undefined) === c.requestId, "response_receipt_mismatch");
      if (config.provider) {
        demand((typeof data.provider === "string" ? data.provider : undefined) === c.providerName, "provider_receipt_mismatch");
        const routeFault = c.httpStatus === 200 ? officialOpenRouterFault(data, config.providerName ?? "DeepSeek") : undefined;
        if (routeFault) demand(c.fault === routeFault, "official_provider_fault_missing");
      }
      if (c.httpStatus === 200) demand(c.completionValid === !completionFault(data) && c.completionFault === completionFault(data), "completion_receipt_mismatch");
    } else demand(c.fault && c.usage === undefined && c.servedModel === undefined && c.requestId === undefined && c.completionValid === undefined, "invalid_json_receipt_mismatch");
  } else demand(c.fault && !c.usage && c.servedModel === undefined && c.requestId === undefined, "missing_response_evidence");
  demand(c.nonGenerationRejection === (rateLimited ? 'upstream_rate_limit' : undefined), 'rate_rejection_raw_binding');
  const expected: ApiReceipt = { usage: c.usage };
  reconcileReceiptCost(expected, start.reservationUsd!, { provider: config.provider, knownUncharged: rateLimited || rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
  demand(c.billedCostUsd === expected.billedCostUsd, "reported_usd_cost_mismatch");
  demand(c.reservationUsd === start.reservationUsd && c.costBasis === expected.costBasis && finite(c.usdUpperBound) && finite(c.accountedUpperBoundUsd) && Math.abs(c.usdUpperBound - expected.usdUpperBound!) <= EPS && c.usdUpperBound === c.accountedUpperBoundUsd, "cost_receipt_mismatch");
}
function pendingOf(active: Map<number, Receipt>) { const result = new Map<string, number>(); for (const c of active.values()) result.set(c.route, (result.get(c.route) ?? 0) + 1); return Object.fromEntries(result); }
function reserveOf(active: Map<number, Receipt>) { let n = 0; for (const c of active.values()) n += c.reservationUsd!; return n; }
function financialState(config: Config, configSha256: string, active: Map<number, Receipt>, accepted: number, finished: number, spent: number, prefix: Prefix, stopReason?: string) {
  return { protocol: config.protocol, ...(config.provider ? { currency: "USD", provider: config.provider } : {}), campaign: config.campaign, configSha256, capUsd: config.capUsd, priorCampaignCostUpperBoundUsd: config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: spent, reservedUpperBoundUsd: reserveOf(active), pending: pendingOf(active), active: [...active].map(([requestSeq, c]) => ({ requestSeq, route: c.route, requestSha256: c.requestSha256, reservationUsd: c.reservationUsd })), acceptedRequestCount: accepted, finishedRequestCount: finished, durablePrefix: { ...prefix }, ...(stopReason ? { stopReason } : {}) };
}

function* lines(fd: number, length: number) {
  let offset = 0, at = 0, carry = Buffer.alloc(0);
  const buffer = Buffer.alloc(16 * 1024);
  while (at < length) {
    const n = readSync(fd, buffer, 0, Math.min(buffer.length, length - at), at); demand(n > 0, "journal_short_read"); at += n;
    carry = Buffer.concat([carry, buffer.subarray(0, n)]);
    for (;;) {
      const newline = carry.indexOf(10); if (newline < 0) break;
      const line = carry.subarray(0, newline + 1); demand(line.length <= MAX_LINE, "journal_line_limit");
      yield { offset, line }; offset += line.length; carry = carry.subarray(newline + 1);
    }
    demand(carry.length <= MAX_LINE, "journal_line_limit");
  }
  demand(carry.length === 0, "truncated_journal");
}
type Inspection = { valid: boolean; accountingClosed: boolean; eligibleForScoreCertification: boolean; errors: string[]; snapshot?: ReturnType<typeof financialState>; prefix?: Prefix; offsets: Map<number, Offset>; routes: Map<string, number[]>; config?: Config; journalPath: string; directory: string };
/** Read-only validation; deliberately offers no resume or provider forwarding API. */
export function inspectCampaignJournal(directory: string): Inspection { return inspect(directory); }
function inspect(directory: string, ownedExport?: { path: string; bytes: number; sha256: string }): Inspection {
  const result: Inspection = { valid: false, accountingClosed: false, eligibleForScoreCertification: false, errors: [], offsets: new Map(), routes: new Map(), journalPath: join(resolve(directory), "api-events.jsonl"), directory: resolve(directory) };
  let fd: number | undefined;
  try {
    const store = realpathSync(directory); demand(store === resolve(directory), "journal_directory_identity");
    const configBytes = readFileSync(join(store, "journal-config.json")), config = JSON.parse(configBytes.toString("utf8")) as Config;
    const providerValid = config.provider === "openrouter-deepseek" ? config.protocol === OPENROUTER_JOURNAL_PROTOCOL && config.model === BENCHMARK_PROVIDER.model && config.currency === "USD" : config.provider === undefined && config.protocol === CAMPAIGN_JOURNAL_PROTOCOL && config.model === "deepseek-flash";
    if (config.provider) frozenRouting(config);
    demand(providerValid && Number.isSafeInteger(config.pendingLimit) && config.pendingLimit >= 4 && config.pendingLimit <= 50 && config.maxLineBytes === MAX_LINE && config.maxJournalBytes === MAX_JOURNAL && finite(config.capUsd) && config.capUsd > 0 && finite(config.priorCampaignCostUpperBoundUsd), "journal_config_invalid");
    const configSha = hash(configBytes), before = statSync(result.journalPath);
    demand(before.size <= MAX_JOURNAL && lstatSync(result.journalPath).isFile() && !lstatSync(result.journalPath).isSymbolicLink(), "journal_resource_or_identity");
    fd = openSync(result.journalPath, "r");
    const active = new Map<number, Receipt>(), ids = new Set<string>(); let accepted = 0, finished = 0, spent = 0, allProviderValid = true;
    let prefix: Prefix = { bytes: 0, eventCount: 0, lastSha256: configSha };
    for (const { offset, line } of lines(fd, before.size)) {
      const e = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line.subarray(0, -1))) as Event;
      demand(same(Object.keys(e), ["protocol", "eventSeq", "previousEventSha256", "kind", "requestSeq", "record"]) && Buffer.from(json(e) + "\n").equals(line), "unknown_or_noncanonical_event");
      demand(e.protocol === config.protocol && e.eventSeq === prefix.eventCount && e.previousEventSha256 === prefix.lastSha256 && Number.isSafeInteger(e.requestSeq) && e.requestSeq >= 0, "journal_chain_or_sequence");
      if (e.kind === "start") {
        demand(e.requestSeq === accepted && active.size < config.pendingLimit && !active.has(e.requestSeq), "duplicate_or_unbounded_start");
        checkedStart(e.record, e.requestSeq, store, config);
        demand(config.priorCampaignCostUpperBoundUsd + spent + reserveOf(active) + e.record.reservationUsd! <= config.capUsd + EPS, "admission_exceeded_cap");
        active.set(e.requestSeq, e.record); accepted++;
      } else if (e.kind === "finish") {
        const start = active.get(e.requestSeq); demand(start && !result.offsets.has(e.requestSeq), "duplicate_or_unknown_finish");
        checkedFinish(e.record, start, e.requestSeq, store, config);
        if (e.record.requestId) { demand(!ids.has(e.record.requestId), "duplicate_provider_id"); ids.add(e.record.requestId); }
        spent += e.record.usdUpperBound!; active.delete(e.requestSeq); finished++;
        allProviderValid &&= isNonGenerationRateRejection(e.record) || e.record.providerAttempted && e.record.httpStatus === 200 && e.record.completionValid === true && validTokenUsage(e.record.usage) && !e.record.fault;
        result.offsets.set(e.requestSeq, { offset, bytes: line.length, sha256: hash(line) });
        const route = result.routes.get(e.record.route) ?? []; route.push(e.requestSeq); result.routes.set(e.record.route, route);
      } else throw new CampaignJournalError("unknown_event");
      prefix = { bytes: offset + line.length, eventCount: prefix.eventCount + 1, lastSha256: hash(line) };
      result.snapshot = financialState(config, configSha, active, accepted, finished, spent, prefix);
    }
    result.snapshot ??= financialState(config, configSha, active, accepted, finished, spent, prefix);
    result.prefix = prefix; result.config = config;
    const checkpoint = JSON.parse(readFileSync(join(store, "api-state.json"), "utf8"));
    const expected = { ...result.snapshot, ...(checkpoint.stopReason ? { stopReason: checkpoint.stopReason } : {}) };
    demand(same(checkpoint, expected), "checkpoint_prefix_or_accounting");
    const requests = readdirSync(store).filter(n => /^provider-\d+-request\.json\.gz$/.test(n));
    const responses = readdirSync(store).filter(n => /^provider-\d+-response\.json\.gz$/.test(n));
    demand(requests.length === accepted && requests.every(n => Number(n.match(/\d+/)![0]) < accepted), "unindexed_raw_request");
    demand(responses.every(n => result.offsets.has(Number(n.match(/\d+/)![0]))), "unindexed_raw_response");
    if (ownedExport) demand(ownedExport.path === join(store, "api-ledger.json.partial") && statSync(ownedExport.path).size === ownedExport.bytes && fileHash(ownedExport.path) === ownedExport.sha256, "owned_export_partial_changed");
    demand(!existsSync(join(store, "journal-error.json")) && !readdirSync(store).some(n => (n.includes(".partial") && join(store, n) !== ownedExport?.path) || n.startsWith("api-state.json.new-")), "unclosed_error_or_partial");
    const after = statSync(result.journalPath);
    demand(before.size === after.size && before.mtimeMs === after.mtimeMs && hash(readFileSync(join(store, "journal-config.json"))) === configSha, "journal_changed_during_inspection");
    result.valid = true; result.accountingClosed = active.size === 0 && accepted === finished;
    result.eligibleForScoreCertification = result.accountingClosed && allProviderValid && !checkpoint.stopReason && config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS;
  } catch (e) { result.errors.push(e instanceof CampaignJournalError ? e.code : (e as NodeJS.ErrnoException).code ?? (e as Error).name); }
  finally { if (fd !== undefined) closeSync(fd); }
  return result;
}

export function createCampaignJournal(options: JournalOptions, hooks: JournalHooks = {}) { return new CampaignJournal(options, hooks); }
export class CampaignJournal {
  private readonly directory: string;
  private readonly outputDirectory: string;
  private readonly config: Config;
  private readonly configSha256: string;
  private readonly journalPath: string;
  private fd = -1;
  private prefix: Prefix;
  private journalMtime = 0;
  private lastLine?: Offset;
  private readonly active = new Map<number, Receipt>();
  private accepted = 0;
  private finished = 0;
  private spent = 0;
  private stopReason?: string;
  private poisoned?: CampaignJournalError;
  private exported = false;
  private closedProof?: Inspection;
  private closed = false;
  private readonly providerIds = new Set<string>();
  private readonly metrics: Metrics = { journalBytesWritten: 0, checkpointBytesWritten: 0, rawGzipBytesWritten: 0, exportBytesWritten: 0, fsyncCallsReturned: 0, maxHotMetadataBytes: 0 };
  constructor(options: JournalOptions, private readonly hooks: JournalHooks) {
    demand(finite(options.capUsd) && options.capUsd > 0 && finite(options.priorCampaignCostUpperBoundUsd) && /^repair-[0-9TZ-]+$/.test(options.campaign), "invalid_journal_options");
    this.directory = ordinaryDirectory(resolve(options.directory));
    this.outputDirectory = ordinaryDirectory(resolve(options.outputDirectory ?? options.directory));
    demand(!readdirSync(this.directory).some(n => ["api-events.jsonl", "journal-config.json", "api-state.json", "journal-error.json"].includes(n) || /^provider-\d+-/.test(n)), "existing_journal");
    if (options.provider) demand(options.provider.kind === BENCHMARK_PROVIDER.kind && options.provider.model === BENCHMARK_PROVIDER.model, "unsupported_journal_provider");
    this.config = { protocol: options.provider ? OPENROUTER_JOURNAL_PROTOCOL : CAMPAIGN_JOURNAL_PROTOCOL, campaign: options.campaign, capUsd: options.capUsd, priorCampaignCostUpperBoundUsd: options.priorCampaignCostUpperBoundUsd, pendingLimit: 50, model: options.provider?.model ?? "deepseek-flash", ...(options.provider ? { provider: options.provider.kind, currency: "USD" as const,
      providerName: options.provider.providerName, providerSlug: options.provider.providerSlug, providerRouting: options.provider.routing, zeroChargePolicy: 'explicit-rate-rejection-v2' as const } : {}), maxLineBytes: MAX_LINE, maxJournalBytes: MAX_JOURNAL, createdAt: new Date().toISOString() };
    const configRaw = Buffer.from(JSON.stringify(this.config, null, 2) + "\n");
    this.configSha256 = hash(configRaw); this.prefix = { bytes: 0, eventCount: 0, lastSha256: this.configSha256 };
    this.journalPath = join(this.directory, "api-events.jsonl");
    try {
      this.persistExclusive(join(this.directory, "journal-config.json"), configRaw, "config", "checkpointBytesWritten");
      this.fd = openSync(this.journalPath, "wx+"); this.sync(this.fd, this.journalPath, "journal:create"); this.journalMtime = fstatSync(this.fd).mtimeMs; this.checkpoint("create");
    } catch (e) { this.close(); if (e instanceof CampaignJournalError) throw e; throw new CampaignJournalError("journal_create_io", (e as NodeJS.ErrnoException).code); }
  }
  private write(fd: number, path: string, raw: Buffer, stage: string, metric: keyof Pick<Metrics, "journalBytesWritten" | "checkpointBytesWritten" | "rawGzipBytesWritten" | "exportBytesWritten">) {
    let at = 0;
    while (at < raw.length) {
      const op: JournalIoOperation = { kind: "write", stage, path, fd, bytes: raw.length - at }; this.hooks.before?.(op);
      const n = writeSync(fd, raw, at, raw.length - at); demand(n > 0, "short_write");
      this.metrics[metric] += n; at += n; this.hooks.after?.({ ...op, bytes: n });
    }
  }
  private sync(fd: number, path: string, stage: string) {
    const op: JournalIoOperation = { kind: "fsync", stage, path, fd }; this.hooks.before?.(op); fsyncSync(fd); this.metrics.fsyncCallsReturned++; this.hooks.after?.(op);
  }
  private persistExclusive(path: string, raw: Buffer, stage: string, metric: keyof Pick<Metrics, "journalBytesWritten" | "checkpointBytesWritten" | "rawGzipBytesWritten" | "exportBytesWritten">) {
    const fd = openSync(path, "wx", 0o600);
    try { this.write(fd, path, raw, stage, metric); this.sync(fd, path, stage); } finally { try { closeSync(fd); } catch {} }
  }
  private state() { return financialState(this.config, this.configSha256, this.active, this.accepted, this.finished, this.spent, this.prefix, this.stopReason); }
  snapshot() { return { ...this.state(), ...(this.poisoned ? { error: this.poisoned.code } : {}), metrics: { ...this.metrics } }; }
  private poison(code: string, stage: string, uncommittedReceipt?: Receipt): never {
    const error = this.poisoned ?? new CampaignJournalError(code, stage); this.poisoned = error;
    try { this.persistExclusive(join(this.directory, "journal-error.json"), Buffer.from(json({ protocol: CAMPAIGN_JOURNAL_PROTOCOL, error: error.code, stage, state: this.state(), ...(uncommittedReceipt ? { uncommittedReceipt } : {}) }) + "\n"), "error_diagnostic", "checkpointBytesWritten"); } catch {}
    throw error;
  }
  private writable() {
    if (this.poisoned) throw new CampaignJournalError("journal_poisoned", this.poisoned.code);
    demand(!this.closed, "writer_closed"); demand(!this.exported, "already_exported");
    try {
      const checkpointPath = join(this.directory, "api-state.json"); regularInStore(checkpointPath, this.directory);
      const checkpoint = readFileSync(checkpointPath);
      if (checkpoint.length > MAX_LINE || !checkpoint.equals(Buffer.from(json(this.state()) + "\n"))) this.poison("checkpoint_changed", "before_append");
    } catch { this.poison("checkpoint_changed", "before_append"); }
    if (existsSync(join(this.directory, "journal-error.json"))) this.poison("journal_changed", "unexpected_error_marker");
    try { regularInStore(join(this.directory, "journal-config.json"), this.directory); if (fileHash(join(this.directory, "journal-config.json")) !== this.configSha256) this.poison("journal_changed", "config_changed"); }
    catch { this.poison("journal_changed", "config_changed"); }
    try {
      const s = fstatSync(this.fd), disk = lstatSync(this.journalPath);
      if (!disk.isFile() || disk.isSymbolicLink() || disk.ino !== s.ino || disk.dev !== s.dev || s.size !== this.prefix.bytes || s.mtimeMs !== this.journalMtime) this.poison("journal_changed", "before_append");
      if (this.lastLine) { const raw = Buffer.alloc(this.lastLine.bytes); const n = readSync(this.fd, raw, 0, raw.length, this.lastLine.offset); if (n !== raw.length || hash(raw) !== this.lastLine.sha256) this.poison("journal_changed", "last_durable_line"); }
    } catch (e) { if (this.poisoned) throw e; this.poison("journal_identity_io", "before_append"); }
  }
  private checkpoint(stage: string) {
    const target = join(this.directory, "api-state.json"), temp = target + ".new-" + randomBytes(8).toString("hex");
    const raw = Buffer.from(json(this.state()) + "\n"); demand(raw.length <= MAX_LINE, "checkpoint_resource_limit"); this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    try {
      this.persistExclusive(temp, raw, "checkpoint:" + stage, "checkpointBytesWritten");
      const op: JournalIoOperation = { kind: "rename", stage: "checkpoint:" + stage, path: target }; this.hooks.before?.(op); renameSync(temp, target); this.hooks.after?.(op);
    } catch { this.poison("checkpoint_io", stage); }
  }
  private append(kind: "start" | "finish", seq: number, receipt: Receipt, apply: () => void) {
    const e: Event = { protocol: this.config.protocol, eventSeq: this.prefix.eventCount, previousEventSha256: this.prefix.lastSha256, kind, requestSeq: seq, record: receipt };
    const raw = Buffer.from(json(e) + "\n"); if (raw.length > MAX_LINE || this.prefix.bytes + raw.length > MAX_JOURNAL) this.poison("journal_resource_limit", `${kind}:${seq}`, receipt); this.metrics.maxHotMetadataBytes = Math.max(this.metrics.maxHotMetadataBytes, raw.length);
    const offset = this.prefix.bytes, fsyncBefore = this.metrics.fsyncCallsReturned;
    const commit = () => { this.prefix = { bytes: offset + raw.length, eventCount: this.prefix.eventCount + 1, lastSha256: hash(raw) }; this.lastLine = { offset, bytes: raw.length, sha256: this.prefix.lastSha256 }; apply(); };
    try { this.write(this.fd, this.journalPath, raw, `journal:${kind}:${seq}`, "journalBytesWritten"); this.sync(this.fd, this.journalPath, `journal:${kind}:${seq}`); }
    catch { if (this.metrics.fsyncCallsReturned > fsyncBefore) commit(); this.poison("journal_io", `${kind}:${seq}`, receipt); }
    // Nothing after an actual fsync return may undo or conceal this accounting transition.
    commit();
    try { this.journalMtime = fstatSync(this.fd).mtimeMs; } catch { this.poison("journal_identity_io", `${kind}:${seq}`, receipt); }
    this.checkpoint(`${kind}:${seq}`);
  }
  /** All budget/reservation and journal transitions below are synchronous, with no yield. */
  admit(input: { route: string; rawRequest: string; startedAt?: string }): Admission {
    this.writable(); if (this.stopReason) return { admitted: false, reason: this.stopReason };
    if (this.active.size >= this.config.pendingLimit) return { admitted: false, reason: "pending_limit" };
    demand(typeof input.rawRequest === "string" && Buffer.byteLength(input.rawRequest) <= MAX_REQUEST, "request_resource_limit");
    demand(typeof input.route === "string" && input.route.length > 0 && Buffer.byteLength(input.route) <= 1024 && !/[\r\n\0]/.test(input.route), "invalid_route");
    const raw = Buffer.from(input.rawRequest), data = JSON.parse(input.rawRequest), values = requestValues(raw, data, this.config);
    if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) + values.reservationUsd > this.config.capUsd) { this.stopReason = "local_budget_exhausted"; this.checkpoint("budget_stop"); return { admitted: false, reason: this.stopReason }; }
    const seq = this.accepted, requestFile = join(this.directory, `provider-${seq}-request.json.gz`), zipped = gzipSync(raw);
    const c: Receipt = { route: input.route, startedAt: input.startedAt ?? new Date().toISOString(), requestSha256: hash(raw), requestedModel: String(data.model), requestFile, providerAttempted: false, wireParameters: values.wireParameters, requestCompressedSha256: hash(zipped), requestBytes: raw.length, reservationUsd: values.reservationUsd };
    demand(Number.isFinite(Date.parse(c.startedAt)), "invalid_start_time");
    // Retain the proposed reservation in memory even if raw/journal capture fails.
    this.active.set(seq, c);
    try { this.persistExclusive(requestFile, zipped, `raw_request:${seq}`, "rawGzipBytesWritten"); }
    catch { this.poison("raw_capture_io", `start:${seq}`, c); }
    this.append("start", seq, c, () => { this.accepted++; });
    return { admitted: true, requestSeq: seq, reservationUsd: values.reservationUsd, requestFile, requestSha256: c.requestSha256 };
  }
  /** Caller supplies actual host transport facts; this method never forwards a request. */
  finish(input: FinishInput) {
    this.writable();
    try { return this.finishReceipt(input); }
    catch (e) { if (this.poisoned) throw e; this.poison(e instanceof CampaignJournalError ? e.code : "finish_input_error", "finish_input"); }
  }
  private finishReceipt(input: FinishInput) {
    const start = this.active.get(input.requestSeq);
    if (!start) this.poison(input.requestSeq < this.accepted ? "duplicate_finish" : "unknown_finish", "finish");
    const c: Receipt = { ...start, providerAttempted: input.providerAttempted };
    demand(typeof input.providerAttempted === "boolean", "invalid_provider_attempt");
    if (!input.providerAttempted) { demand(input.confirmedNoForward === true && input.rawResponse === undefined, "unproven_zero_charge"); c.confirmedNoForward = true; }
    if (input.httpStatus !== undefined) { demand(Number.isInteger(input.httpStatus) && input.httpStatus >= 100 && input.httpStatus <= 599, "invalid_http_status"); c.httpStatus = input.httpStatus; }
    let rejectedBeforeGeneration = false;
    if (input.rawResponse !== undefined) {
      demand(input.providerAttempted && typeof input.rawResponse === "string" && Buffer.byteLength(input.rawResponse) <= MAX_RESPONSE, "response_resource_limit");
      const raw = Buffer.from(input.rawResponse), zipped = gzipSync(raw), responseFile = join(this.directory, `provider-${input.requestSeq}-response.json.gz`);
      c.responseFile = responseFile; c.responseSha256 = hash(raw); c.responseCompressedSha256 = hash(zipped);
      try { this.persistExclusive(responseFile, zipped, `raw_response:${input.requestSeq}`, "rawGzipBytesWritten"); }
      catch { this.poison("raw_capture_io", `finish:${input.requestSeq}`, c); }
      try {
        const data = JSON.parse(input.rawResponse);
        rejectedBeforeGeneration = routingRejection(this.config, data, input.httpStatus);
        if (rateRejection(this.config, data, input.httpStatus)) { c.nonGenerationRejection = 'upstream_rate_limit'; rejectedBeforeGeneration = true; }
        if (this.config.provider) {
          c.providerName = typeof data.provider === "string" ? data.provider : undefined;
          if (input.httpStatus === 200) c.fault = officialOpenRouterFault(data, this.config.providerName ?? "DeepSeek");
        }
        c.servedModel = typeof data.model === "string" ? data.model : undefined; c.requestId = typeof data.id === "string" ? data.id : undefined;
        if (data.usage && typeof data.usage === "object") c.usage = data.usage;
        if (input.httpStatus === 200) { c.completionFault = completionFault(data); c.completionValid = !c.completionFault; }
      } catch { c.fault = "InvalidProviderJSON"; }
    }
    if (input.fault) { demand(typeof input.fault === "string" && Buffer.byteLength(input.fault) <= 2048, "fault_resource_limit"); c.fault = input.fault; }
    if (!c.responseFile && !c.fault) c.fault = input.providerAttempted ? "UncapturedProviderTransport" : "LocalBeforeForwardError";
    reconcileReceiptCost(c, start.reservationUsd!, { provider: this.config.provider, knownUncharged: rejectedBeforeGeneration || !c.providerAttempted || !c.usage && [401, 402, 403].includes(c.httpStatus ?? 0) });
    c.finishedAt = input.finishedAt ?? new Date().toISOString();
    demand(Number.isFinite(Date.parse(c.finishedAt)) && Date.parse(c.finishedAt) >= Date.parse(c.startedAt), "invalid_finish_time");
    if (c.requestId && this.providerIds.has(c.requestId)) this.poison("duplicate_provider_id", "finish", c);
    this.append("finish", input.requestSeq, c, () => {
      this.spent += c.usdUpperBound!; this.active.delete(input.requestSeq); this.finished++;
      if (c.requestId) this.providerIds.add(c.requestId);
      if (c.usdUpperBound! > start.reservationUsd! + EPS) this.stopReason ??= "usage_exceeded_reservation";
      if (this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) > this.config.capUsd + EPS) this.stopReason ??= "actual_cost_exceeded_cap";
      if (!isNonGenerationRateRejection(c) && (c.fault || c.httpStatus !== 200 || c.completionValid !== true || !validTokenUsage(c.usage))) this.stopReason ??= "provider_fault";
    });
    return { requestSeq: input.requestSeq, receipt: { ...c }, accountingCommitted: true };
  }
  private readReceipt(fd: number, offset: Offset) {
    const line = Buffer.alloc(offset.bytes); demand(readSync(fd, line, 0, line.length, offset.offset) === line.length && hash(line) === offset.sha256, "export_receipt_changed");
    return (JSON.parse(line.toString("utf8")) as Event).record;
  }
  *closedCalls(route?: string) {
    demand(this.exported && this.closedProof, "not_exported"); const proof = this.closedProof;
    demand(statSync(this.journalPath).size === proof.prefix!.bytes, "exported_journal_changed");
    const fd = openSync(this.journalPath, "r");
    const indices = route === undefined ? Array.from({ length: this.accepted }, (_, i) => i) : [...(proof.routes.get(route) ?? [])].sort((a, b) => a - b);
    try { for (const seq of indices) { const offset = proof.offsets.get(seq); demand(offset, "missing_finish_offset"); const c = this.readReceipt(fd, offset); const start: Receipt = { ...c, providerAttempted: false }; checkedStart(start, seq, this.directory, this.config); checkedFinish(c, start, seq, this.directory, this.config); yield c; } }
    finally { closeSync(fd); }
  }
  /** Only exports accounting. Caller must separately validate all grades/source before completed=true. */
  exportLegacyLedger() {
    this.writable(); demand(this.active.size === 0 && this.accepted === this.finished, "journal_not_closed");
    const proof = inspectCampaignJournal(this.directory);
    if (!proof.valid || !proof.accountingClosed || !same(proof.prefix, this.prefix) || Math.abs(proof.snapshot!.recordedUsageUpperBoundUsd - this.spent) > EPS) this.poison("export_integrity", "before_export");
    const target = join(this.outputDirectory, "api-ledger.json"), temp = target + ".partial";
    demand(!existsSync(target) && !existsSync(temp), "existing_export");
    const fd = openSync(temp, "wx", 0o600), journalFd = openSync(this.journalPath, "r");
    try {
      const header = { ...(this.config.provider ? { protocol: this.config.protocol, currency: "USD", provider: this.config.provider, model: this.config.model } : {}), campaign: this.config.campaign, capUsd: this.config.capUsd, priorCampaignCostUpperBoundUsd: this.config.priorCampaignCostUpperBoundUsd, recordedUsageUpperBoundUsd: this.spent, reservedUpperBoundUsd: 0, ...(this.stopReason ? { fatal: this.stopReason } : {}), pending: {}, captureErrors: [], calls: [] };
      const opening = JSON.stringify(header, null, 2).replace(/\[\]\n}$/, "[\n");
      this.write(fd, temp, Buffer.from(opening), "legacy_export", "exportBytesWritten");
      for (let seq = 0; seq < this.accepted; seq++) {
        const offset = proof.offsets.get(seq); demand(offset, "missing_finish_offset");
        const text = JSON.stringify(this.readReceipt(journalFd, offset), null, 2).split("\n").map(line => "    " + line).join("\n");
        this.write(fd, temp, Buffer.from(text + (seq + 1 < this.accepted ? ",\n" : "\n")), "legacy_export", "exportBytesWritten");
      }
      this.write(fd, temp, Buffer.from("  ]\n}\n"), "legacy_export", "exportBytesWritten"); this.sync(fd, temp, "legacy_export");
    } catch { this.poison("export_io", "legacy_export"); }
    finally { try { closeSync(fd); } catch {} closeSync(journalFd); }
    const ownPartial = this.outputDirectory === this.directory ? { path: temp, bytes: statSync(temp).size, sha256: fileHash(temp) } : undefined;
    const after = inspect(this.directory, ownPartial);
    if (!after.valid || !after.accountingClosed || !same(after.prefix, proof.prefix)) this.poison("export_integrity", "after_export");
    try { const op: JournalIoOperation = { kind: "rename", stage: "legacy_export", path: target }; this.hooks.before?.(op); renameSync(temp, target); this.hooks.after?.(op); }
    catch { this.poison("export_io", "legacy_rename"); }
    this.exported = true; this.closedProof = after;
    return { path: target, bytes: statSync(target).size, sha256: fileHash(target), accountingClosed: true, eligibleForScoreCertification: proof.eligibleForScoreCertification, durablePrefix: { ...this.prefix }, legacyCompletedNotSet: true };
  }
  /** Descriptor lifecycle only; never touches an external shared paid lock. */
  close() { if (!this.closed) { try { closeSync(this.fd); } catch {} this.closed = true; } }
}
