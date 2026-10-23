import { createHash } from "node:crypto";
import { graderFetch, Registry } from "../../app/src/engine/registry.ts";
import { candidateInput, evaluate, type Verdict } from "../../app/src/objective/run.ts";
import { parseObjective } from "../../app/src/objective/spec.ts";

export const MAX_OUTPUT_TOKENS = 16384;
export const PEAK_RATES = Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 });
type ObjectRow = Record<string, unknown>;
const object = (value: unknown): ObjectRow | undefined => value !== null && typeof value === "object" && !Array.isArray(value) ? value as ObjectRow : undefined;
const count = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;

/** Require an explicit limit so the reservation covers the provider's output allowance. */
export function checkedOutputTokens(body: ObjectRow): number {
  const values = [body.max_tokens, body.max_completion_tokens].filter(value => value !== undefined && value !== null);
  if (!values.length || values.some(value => !count(value) || value < 1 || value > MAX_OUTPUT_TOKENS)) throw new Error(`Output token limit must be a finite positive integer at most ${MAX_OUTPUT_TOKENS}`);
  if (values.length > 1 && values[0] !== values[1]) throw new Error("Conflicting output token limits");
  return values[0] as number;
}

/** A HTTP 200 is not enough: the SDK still needs a chat completion message. */
export function completionFault(value: unknown): string | undefined {
  const data = object(value);
  if (!data || data.error) return "InvalidCompletionEnvelope";
  if (!Array.isArray(data.choices) || data.choices.length === 0) return "MissingCompletionChoices";
  for (const entry of data.choices) {
    const choice = object(entry), message = object(choice?.message);
    if (!message || message.role !== "assistant") return "InvalidCompletionMessage";
    const tools = message.tool_calls;
    if (tools !== undefined && tools !== null) {
      if (!Array.isArray(tools)) return "InvalidCompletionToolCalls";
      for (const item of tools) {
        const call = object(item), fn = object(call?.function);
        if (call?.type !== "function" || typeof call.id !== "string" || !call.id || typeof fn?.name !== "string" || !fn.name || typeof fn.arguments !== "string") return "InvalidCompletionToolCall";
      }
    }
    const hasText = typeof message.content === "string";
    const hasTools = Array.isArray(tools) && tools.length > 0;
    const hasReasoning = [message.reasoning_content, message.reasoning].some(value => typeof value === "string" && value.length > 0);
    if (!hasText && !hasTools && !hasReasoning) return "MissingCompletionMessagePayload";
    if (message.content !== undefined && message.content !== null && !hasText) return "InvalidCompletionContent";
  }
  return undefined;
}

function usageCounts(value: unknown): { input: number; output: number; cached: number } {
  const usage = object(value);
  const input = usage?.prompt_tokens, output = usage?.completion_tokens;
  const cached = usage?.prompt_cache_hit_tokens ?? object(usage?.prompt_tokens_details)?.cached_tokens ?? 0;
  if (!count(input) || !count(output) || !count(cached) || cached > input) throw new Error("InvalidProviderTokenUsage");
  return { input, output, cached };
}
export function validTokenUsage(value: unknown): boolean {
  try { usageCounts(value); return true; } catch { return false; }
}
export function tokenCostUpperBound(usage: unknown, rates = PEAK_RATES): number {
  if (Object.values(rates).some(rate => !Number.isFinite(rate) || rate < 0)) throw new Error("Invalid frozen price rates");
  const { input, output, cached } = usageCounts(usage);
  return ((input - cached) * rates.input + cached * rates.cachedInput + output * rates.output) / 1e6;
}

export interface ApiReceipt {
  httpStatus?: number;
  usage?: unknown;
  finishedAt?: string;
  fault?: string;
  completionValid?: boolean;
  completionFault?: string;
  reservationUsd?: number;
  usdUpperBound?: number;
  accountedUpperBoundUsd?: number;
  costBasis?: "reported_usage" | "provider_reported_usd" | "reservation" | "known_uncharged";
  billedCostUsd?: number;
  nonGenerationRejection?: 'upstream_rate_limit';
  providerAttempted?: boolean;
  requestId?: string;
}
export function isNonGenerationRateRejection(call: ApiReceipt) {
  return call.nonGenerationRejection === 'upstream_rate_limit' && call.httpStatus === 429 && call.providerAttempted === true
    && call.costBasis === 'known_uncharged' && call.usdUpperBound === 0 && !call.usage && !call.requestId && !call.fault && !!call.finishedAt;
}
/** Return the ledger delta so catch/finally cannot charge the same receipt twice. */
export function reconcileReceiptCost(receipt: ApiReceipt, reservationUsd: number, options: { knownUncharged?: boolean; rates?: typeof PEAK_RATES; provider?: "openrouter-deepseek" } = {}): { usdUpperBound: number; deltaUsd: number; costBasis: ApiReceipt["costBasis"] } {
  if (!Number.isFinite(reservationUsd) || reservationUsd < 0) throw new Error("Invalid request cost reservation");
  const before = receipt.accountedUpperBoundUsd ?? 0;
  if (!Number.isFinite(before) || before < 0) throw new Error("Invalid accounted request cost");
  let upper = reservationUsd;
  let basis: ApiReceipt["costBasis"] = options.knownUncharged ? "known_uncharged" : "reservation";
  if (options.knownUncharged) upper = 0;
  if (options.provider && !options.knownUncharged) {
    const usage = object(receipt.usage), cost = usage?.cost;
    if (typeof cost === "number" && Number.isFinite(cost) && cost >= 0) {
      upper = cost; basis = "provider_reported_usd"; receipt.billedCostUsd = cost;
      if (!validTokenUsage(usage)) receipt.fault ??= "InvalidProviderTokenUsage";
    } else { receipt.fault ??= "MissingOrInvalidOpenRouterUsdCost"; }
  } else if (receipt.usage !== undefined) {
    if (validTokenUsage(receipt.usage)) { upper = tokenCostUpperBound(receipt.usage, options.rates); basis = "reported_usage"; }
    else { upper = reservationUsd; basis = "reservation"; receipt.fault ??= "InvalidProviderTokenUsage"; }
  }
  receipt.reservationUsd = reservationUsd;
  receipt.usdUpperBound = upper;
  receipt.accountedUpperBoundUsd = upper;
  receipt.costBasis = basis;
  return { usdUpperBound: upper, deltaUsd: upper - before, costBasis: basis };
}

export interface GenerationClassification {
  valid: boolean;
  kind: "candidate" | "experimental_failure" | "infrastructure_error" | "pending";
  outcome: string;
  why: string;
  runtimeOutcome: string;
  runtimeVerdict: unknown;
}
export function classifyGeneration(input: { runtimeVerdict: unknown; state?: string; calls: ApiReceipt[]; trace: { role?: unknown; kind?: unknown; body?: unknown }[]; candidate?: string }): GenerationClassification {
  const runtime = object(input.runtimeVerdict);
  const runtimeOutcome = String(runtime?.outcome ?? "unaided_generated");
  const result = (valid: boolean, kind: GenerationClassification["kind"], outcome: string, why: string): GenerationClassification => ({ valid, kind, outcome, why, runtimeOutcome, runtimeVerdict: structuredClone(input.runtimeVerdict) });
  if (["finalization_pending", "finalization_error"].includes(runtimeOutcome) || (input.state !== undefined && !["done", "failed"].includes(input.state))) return result(false, "pending", "pending_finalization", "generation or finalization has not finished");
  if (["provider_error", "grader_error"].includes(runtimeOutcome)) return result(false, "infrastructure_error", runtimeOutcome, String(runtime?.why ?? runtimeOutcome));
  const stuck = input.trace.some(row => {
    if (row.role !== "system" || row.kind !== "inject") return false;
    try { return Object.hasOwn(object(JSON.parse(String(row.body))) ?? {}, "stuck"); } catch { return false; }
  });
  if (stuck) return result(false, "infrastructure_error", "kernel_stuck", "the runtime recorded a failed execution unit");
  if (!input.calls.length) return result(false, "infrastructure_error", "missing_api_receipt", "no model request receipt was recorded");
  if (input.calls.some(call => call.completionValid === false || call.completionFault)) return result(false, "infrastructure_error", "malformed_completion", "a HTTP success did not contain a valid completion");
  if (input.calls.some(call => !isNonGenerationRateRejection(call) && (call.fault || call.httpStatus !== 200 || !call.finishedAt || !validTokenUsage(call.usage)))) return result(false, "infrastructure_error", "invalid_api_receipt", "a model call failed, remained pending, or lacks valid token usage");
  if (runtime?.valid === false && !["task_timeout", "no_candidate"].includes(runtimeOutcome)) return result(false, "infrastructure_error", "invalid_runtime", "the runtime explicitly rejected the validity of its receipt");
  if (input.candidate === undefined) {
    const exhausted = runtimeOutcome === "task_timeout" || /over solve_seconds=/.test(String(runtime?.why ?? ""));
    return result(true, "experimental_failure", exhausted ? "budget_exhausted" : "no_candidate", exhausted ? "the declared solving budget was exhausted without a hand-in" : "the model did not hand in a candidate");
  }
  return result(true, "candidate", "candidate", "");
}

export interface FixedAcceptance {
  valid: boolean;
  passed: boolean;
  outcome: string;
  why: string;
  candidateSha256: string;
  nodes: Record<string, { value: unknown; valid: boolean; error?: string; note?: string }>;
  verdict?: Verdict;
}
/** Grade exactly the already-frozen candidate. This function never generates or selects an answer. */
export async function gradeFixedCandidate(input: { objective: unknown; task: ObjectRow; candidate?: string; expectedCandidateSha256?: string; generation: GenerationClassification; timeoutMs?: number }): Promise<FixedAcceptance> {
  const candidateSha256 = createHash("sha256").update(input.candidate ?? "").digest("hex");
  const no = (valid: boolean, outcome: string, why: string): FixedAcceptance => ({ valid, passed: false, outcome, why, candidateSha256, nodes: {} });
  if (input.expectedCandidateSha256 !== undefined && input.expectedCandidateSha256 !== candidateSha256) return no(false, "candidate_changed", "the frozen candidate digest does not match");
  if (!input.generation.valid) return no(false, input.generation.outcome, input.generation.why);
  if (input.candidate === undefined) return no(true, input.generation.outcome, input.generation.why);
  try {
    const objective = parseObjective(input.objective);
    const registry = new Registry();
    for (const node of objective.nodes) registry.adopt(node.handle, input.timeoutMs ?? 120000, async arg => {
      const url = new URL(node.handle);
      if (!["http:", "https:"].includes(url.protocol)) throw new Error("Campaign graders must be HTTP handles");
      const response = await graderFetch(node.handle, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(arg), signal: AbortSignal.timeout(input.timeoutMs ?? 120000), ...{ timeout: false } });
      if (!response.ok) throw new Error(`${node.name}: grader HTTP ${response.status}`);
      return await response.json();
    });
    const verdict = await evaluate(objective, registry, candidateInput(input.task, input.candidate));
    const nodes = Object.fromEntries(verdict.trace.map(node => [node.node, { value: node.value, valid: !node.error, ...(node.error ? { error: node.error } : {}), ...(node.note ? { note: node.note } : {}) }]));
    return { valid: verdict.valid, passed: verdict.valid && verdict.pass === 1, outcome: verdict.outcome, why: verdict.why, candidateSha256, nodes, verdict };
  } catch (error) { return no(false, "grader_error", error instanceof Error ? error.message : "grading failed"); }
}

export function campaignComplete(planned: number, records: { index: unknown; acceptance?: { valid?: unknown; passed?: unknown; outcome?: unknown } }[]): boolean {
  if (!Number.isSafeInteger(planned) || planned < 1 || records.length !== planned) return false;
  const seen = new Set<number>();
  for (const record of records) {
    if (!count(record.index) || record.index >= planned || seen.has(record.index)) return false;
    seen.add(record.index);
    const accepted = record.acceptance;
    if (accepted?.valid !== true || typeof accepted.passed !== "boolean") return false;
    if (!["passed", "rejected", "budget_exhausted", "no_candidate"].includes(String(accepted.outcome)) || accepted.passed !== (accepted.outcome === "passed")) return false;
  }
  return true;
}
