import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { campaignComplete, checkedOutputTokens, classifyGeneration, completionFault, gradeFixedCandidate, reconcileReceiptCost, tokenCostUpperBound, type ApiReceipt } from "../scripts/repair-2026-10-08/campaign-contract.ts";

const receipt = (): ApiReceipt => ({ httpStatus: 200, usage: { prompt_tokens: 100, completion_tokens: 10 }, finishedAt: "2026-10-08T00:00:00Z", completionValid: true });
const sha = (text: string) => createHash("sha256").update(text).digest("hex");

test("malformed output limits cannot poison the campaign reservation", () => {
  for (const value of [NaN, Infinity, -1, 0, 1.5, 16385, "8192", "not-a-number", null]) expect(() => checkedOutputTokens({ max_tokens: value })).toThrow();
  expect(() => checkedOutputTokens({})).toThrow();
  expect(() => checkedOutputTokens({ max_tokens: 32, max_completion_tokens: 64 })).toThrow();
  expect(checkedOutputTokens({ max_tokens: 8192 })).toBe(8192);
  expect(checkedOutputTokens({ max_completion_tokens: 32 })).toBe(32);
});

test("a HTTP 200 body must supply completion choices and a usable assistant message", () => {
  expect(completionFault({ usage: { prompt_tokens: 1, completion_tokens: 1 } })).toBe("MissingCompletionChoices");
  expect(completionFault({ choices: [{ message: {} }] })).toBe("InvalidCompletionMessage");
  expect(completionFault({ choices: [{ message: { role: "assistant", content: null } }] })).toBe("MissingCompletionMessagePayload");
  expect(completionFault({ choices: [{ message: { role: "assistant", content: "" } }] })).toBeUndefined();
  expect(completionFault({ choices: [{ message: { role: "assistant", content: null, tool_calls: [{ id: "call-1", type: "function", function: { name: "submit", arguments: '{"answer":"42"}' } }] } }] })).toBeUndefined();
  expect(completionFault({ choices: [{ message: { role: "assistant", content: null, reasoning_content: "thinking" } }] })).toBeUndefined();
});

test("an unknown transport charge is attributable to its request and is not counted twice", () => {
  const call: ApiReceipt = { fault: "transport failure" };
  const first = reconcileReceiptCost(call, 0.013);
  expect(first).toMatchObject({ usdUpperBound: 0.013, deltaUsd: 0.013, costBasis: "reservation" });
  expect(call.usdUpperBound).toBe(0.013);
  expect(reconcileReceiptCost(call, 0.013).deltaUsd).toBe(0);
  expect(() => reconcileReceiptCost(call, NaN)).toThrow();
});

test("reported usage can reconcile a conservative charge while preserving the aggregate sum", () => {
  const call: ApiReceipt = {};
  let total = reconcileReceiptCost(call, 0.013).deltaUsd;
  call.usage = { prompt_tokens: 1000, completion_tokens: 100, prompt_cache_hit_tokens: 400 };
  total += reconcileReceiptCost(call, 0.013).deltaUsd;
  expect(total).toBeCloseTo(0.0003024, 12);
  expect(total).toBeCloseTo(Number(call.usdUpperBound), 12);
  expect(() => tokenCostUpperBound({ prompt_tokens: 100, completion_tokens: 1, prompt_cache_hit_tokens: 101 })).toThrow();
  const invalid: ApiReceipt = { usage: { prompt_tokens: "unknown" } };
  expect(reconcileReceiptCost(invalid, 0.02).usdUpperBound).toBe(0.02);
  expect(invalid.fault).toBe("InvalidProviderTokenUsage");
});

test("U and F budget exhaustion are equally valid experimental failures", async () => {
  const uRaw = { pass: 0, valid: false, outcome: "task_timeout", why: "over solve_seconds=1s" };
  const fRaw = { pass: 0, valid: false, outcome: "no_candidate", why: "over solve_seconds=1s; nothing submitted" };
  for (const raw of [uRaw, fRaw]) {
    const classified = classifyGeneration({ runtimeVerdict: raw, state: "failed", calls: [receipt()], trace: [] });
    expect(classified).toMatchObject({ valid: true, kind: "experimental_failure", outcome: "budget_exhausted", runtimeOutcome: raw.outcome, runtimeVerdict: raw });
    const accepted = await gradeFixedCandidate({ objective: undefined, task: { id: "fixture" }, generation: classified });
    expect(accepted).toMatchObject({ valid: true, passed: false, outcome: "budget_exhausted" });
  }
  expect(uRaw.outcome).toBe("task_timeout");
  expect(fRaw.outcome).toBe("no_candidate");
});

test("a semantic provider failure and kernel stuck message cannot masquerade as budget exhaustion", () => {
  const raw = { valid: false, outcome: "no_candidate", why: "over solve_seconds=1s" };
  expect(classifyGeneration({ runtimeVerdict: raw, calls: [receipt()], trace: [{ role: "system", kind: "inject", body: JSON.stringify({ stuck: "failed to process successful response" }) }] })).toMatchObject({ valid: false, kind: "infrastructure_error", outcome: "kernel_stuck" });
  expect(classifyGeneration({ runtimeVerdict: raw, calls: [{ ...receipt(), completionValid: false }], trace: [] })).toMatchObject({ valid: false, outcome: "malformed_completion" });
  expect(classifyGeneration({ runtimeVerdict: raw, calls: [], trace: [] })).toMatchObject({ valid: false, outcome: "missing_api_receipt" });
  expect(classifyGeneration({ runtimeVerdict: raw, calls: [{ ...receipt(), finishedAt: undefined }], trace: [] })).toMatchObject({ valid: false, outcome: "invalid_api_receipt" });
  expect(classifyGeneration({ runtimeVerdict: { valid: false, outcome: "provider_error" }, calls: [receipt()], trace: [] })).toMatchObject({ valid: false, outcome: "provider_error" });
});

test("a pending finalization remains pending and cannot be post-hoc scored", async () => {
  const generation = classifyGeneration({ runtimeVerdict: { valid: false, outcome: "finalization_error" }, state: "failed", calls: [receipt()], trace: [], candidate: "answer" });
  expect(generation).toMatchObject({ valid: false, kind: "pending" });
  expect(await gradeFixedCandidate({ objective: undefined, task: { id: "fixture" }, candidate: "answer", generation })).toMatchObject({ valid: false, passed: false, outcome: "pending_finalization" });
});

test("post-hoc scoring uses the shared graph, normalized candidate and origin-scoped authentication", async () => {
  const oldToken = process.env.TGENGIN_GRADER_TOKEN, oldOrigins = process.env.TGENGIN_GRADER_ORIGINS;
  const requests: { path: string; token: string | null; body: Record<string, unknown> }[] = [];
  let invalid = false;
  const grader = Bun.serve({ port: 0, async fetch(request) {
    const path = new URL(request.url).pathname;
    const body = await request.json() as Record<string, unknown>;
    requests.push({ path, token: request.headers.get("X-ObjRun-Grader-Token"), body });
    if (path === "/parsed" && invalid) return Response.json({ value: true, valid: false, outcome: "grader_error" });
    return Response.json(true);
  } });
  const base = `http://127.0.0.1:${grader.port}`;
  process.env.TGENGIN_GRADER_TOKEN = "local-contract-token";
  process.env.TGENGIN_GRADER_ORIGINS = base;
  const objective = { nodes: [{ name: "parsed", moment: "done", domain: "bool", handle: `${base}/parsed` }, { name: "correct", moment: "done", domain: "bool", handle: `${base}/correct` }], edges: [{ src: "parsed", out: 0, dst: "correct" }], sink: "correct", checks: 5 };
  const generation = classifyGeneration({ runtimeVerdict: { outcome: "unaided_generated", valid: true }, calls: [receipt()], trace: [], candidate: "fixed answer" });
  try {
    const first = await gradeFixedCandidate({ objective, task: { id: "fixture" }, candidate: "fixed answer", expectedCandidateSha256: sha("fixed answer"), generation });
    expect(first).toMatchObject({ valid: true, passed: true, outcome: "passed", candidateSha256: sha("fixed answer") });
    expect(requests[0]?.token).toBe("local-contract-token");
    expect(requests[0]?.body.input).toMatchObject({ task: { id: "fixture", result: "fixed answer" }, result: { kind: "prompt", body: "fixed answer" } });
    expect(requests[1]?.body.feed).toEqual([{ from: "parsed", out: 0, value: true }]);
    invalid = true;
    expect(await gradeFixedCandidate({ objective, task: { id: "fixture" }, candidate: "fixed answer", generation })).toMatchObject({ valid: false, passed: false, outcome: "grader_error" });
    const before = requests.length;
    expect(await gradeFixedCandidate({ objective, task: { id: "fixture" }, candidate: "changed", expectedCandidateSha256: sha("fixed answer"), generation })).toMatchObject({ valid: false, outcome: "candidate_changed" });
    expect(requests.length).toBe(before);
  } finally {
    if (oldToken === undefined) delete process.env.TGENGIN_GRADER_TOKEN; else process.env.TGENGIN_GRADER_TOKEN = oldToken;
    if (oldOrigins === undefined) delete process.env.TGENGIN_GRADER_ORIGINS; else process.env.TGENGIN_GRADER_ORIGINS = oldOrigins;
    await grader.stop(true);
  }
});

test("completion requires every planned identity and a valid final acceptance", () => {
  const success = { index: 0, acceptance: { valid: true, passed: true, outcome: "passed" } };
  const fail = { index: 1, acceptance: { valid: true, passed: false, outcome: "budget_exhausted" } };
  expect(campaignComplete(2, [success, fail])).toBe(true);
  expect(campaignComplete(2, [success])).toBe(false);
  expect(campaignComplete(2, [success, { ...fail, index: 0 }])).toBe(false);
  expect(campaignComplete(2, [success, { ...fail, acceptance: { valid: false, passed: false, outcome: "grader_error" } }])).toBe(false);
  expect(campaignComplete(2, [success, { ...fail, acceptance: { valid: false, passed: false, outcome: "pending_after_all_generation" } }])).toBe(false);
});
