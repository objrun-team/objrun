import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { checkedOutputTokens } from "../scripts/benchmark-repair/campaign-contract.ts";
import { createCampaignJournal } from "../scripts/benchmark-repair/campaign-journal.ts";
import { ScientificJournalProxy } from "../scripts/benchmark-repair/scientific-journal-proxy.ts";
import { ScientificJournalProxy as ChemiqProxy } from "../scripts/benchmark-repair/chemiq-f-provider-proxy-v3.ts";
import { providerGateway } from "../scripts/terminal-bench-repair/tb12-v2/provider_gateway.ts";
import { actualPin, requestValues } from "../scripts/benchmark-repair/paid-resource-proof-v2.ts";

const inference = { maxTokens: 16384, reasoningEffort: "medium", temperature: 0, seed: 42, retryTimes: 3, continueTimes: 3 };
const root = resolve(import.meta.dir, "..");
const completion = JSON.stringify({ id: "zero-paid-inference-fixture", model: "local-fixture", choices: [{ message: { role: "assistant", content: "candidate", reasoning_content: "fixture reasoning" } }], usage: { prompt_tokens: 10, completion_tokens: 2 } });
const request = (extra: Record<string, unknown> = {}) => JSON.stringify({ model: "deepseek-flash", temperature: 0, seed: 42, reasoning_effort: "medium", max_tokens: 16384, messages: [{ role: "user", content: "public fixture" }], ...extra });

function fixture(Proxy: typeof ScientificJournalProxy | typeof ChemiqProxy) {
  const directory = join(root, ".scratch", "benchmark-inference-" + randomUUID());
  mkdirSync(directory, { recursive: true });
  const journal = createCampaignJournal({ directory, campaign: "repair-2026-10-10T00-00-00-000Z", capUsd: 1, priorCampaignCostUpperBoundUsd: 0 });
  const wires: Record<string, any>[] = [];
  const proxy = new Proxy(journal, { inference, routes: new Set(["task"]), failureDirectory: join(directory, "failures"), transport: async (raw: string) => {
    wires.push(JSON.parse(raw)); return { httpStatus: 200, rawResponse: completion.replace("zero-paid-inference-fixture", "zero-paid-inference-fixture-" + wires.length) };
  } } as any);
  return { journal, proxy, wires };
}

test("original 16384-token output budget is admitted without accepting malformed limits", () => {
  expect(checkedOutputTokens({ max_tokens: 16384 })).toBe(16384);
  expect(() => checkedOutputTokens({ max_tokens: 16385 })).toThrow();
  expect(() => checkedOutputTokens({ max_tokens: 16384, max_completion_tokens: 8192 })).toThrow();
  const reservation = requestValues(Buffer.from(request()));
  expect(reservation.output).toBe(16384);
  expect(reservation.peakNano).toBeGreaterThanOrEqual(16384n * 8000n);
});

test("Terminal-Bench's actual HTTP gateway preserves solve thinking and permits forced submit", async () => {
  const output = join(root, ".scratch", "benchmark-tb-gateway-" + randomUUID());
  mkdirSync(output, { recursive: true });
  const prices = JSON.parse(readFileSync(join(root, "docs/repair-2026-10-08/deepseek-cny-price-readonly.json"), "utf8"));
  prices.observedAtUtc = new Date().toISOString();
  prices.retrieval = "Synthetic timestamp for a zero-provider gateway test; not a new price observation";
  const pricePath = join(output, "fixture-prices.json");
  writeFileSync(pricePath, JSON.stringify(prices));
  const gateway = providerGateway({ runId: "repair-2026-10-10T00-00-00-000Z", output, prices: actualPin(pricePath), kind: "local-mock", inference, sourceGuard() {} });
  const tools = ["bash", "read", "write", "edit", "glob", "grep", "submit"].map(name => ({ type: "function", function: { name, parameters: { type: "object", properties: {} } } }));
  gateway.register("task", "nginx-request-logging", "F");
  const send = (body: string) => fetch(gateway.origin + "/task/v1/chat/completions", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + gateway.token }, body });
  try {
    expect((await send(request({ tools }))).status).toBe(200);
    expect((await send(request({ tools, reasoning_effort: "none", tool_choice: { type: "function", function: { name: "submit" } } }))).status).toBe(200);
    expect(gateway.calls.map(row => [row.wireParameters.reasoning_effort, row.wireParameters.thinking.type, row.wireParameters.max_tokens])).toEqual([["medium", "enabled", 16384], ["none", "disabled", 16384]]);
    expect(gateway.calls.every(row => row.providerAttempted === false)).toBe(true);
    expect(gateway.fault()).toBeUndefined();
  } finally { await gateway.stop(); gateway.close(); }
});

for (const [name, Proxy] of [["scientific/SKB", ScientificJournalProxy], ["ChemIQ", ChemiqProxy]] as const) {
  test(`${name} forwards the thinking profile and reserves the full output allowance`, async () => {
    const f = fixture(Proxy);
    try {
      const result = await f.proxy.handle("task", request());
      expect(result.httpStatus).toBe(200);
      expect(f.wires).toHaveLength(1);
      expect(f.wires[0]).toMatchObject({ reasoning_effort: "medium", thinking: { type: "enabled" }, max_tokens: 16384 });
      f.journal.exportLegacyLedger();
      const receipt = [...f.journal.closedCalls("task")][0];
      expect(receipt.reservationUsd).toBeGreaterThanOrEqual(16384 * 1.2 / 1e6);
      expect(receipt.wireParameters).toMatchObject({ reasoning_effort: "medium", thinking: { type: "enabled" }, max_tokens: 16384 });
      expect(f.journal.snapshot().reservedUpperBoundUsd).toBe(0);
    } finally { f.journal.close(); }
  });

  test(`${name} only disables thinking for forced tools and restores it on the following solve request`, async () => {
    const f = fixture(Proxy);
    try {
      expect((await f.proxy.handle("task", request({ reasoning_effort: "none", tool_choice: { type: "function", function: { name: "submit" } } }))).httpStatus).toBe(200);
      expect((await f.proxy.handle("task", request({ tool_choice: "auto" }))).httpStatus).toBe(200);
      expect(f.wires.map(body => [body.reasoning_effort, body.thinking.type])).toEqual([["none", "disabled"], ["medium", "enabled"]]);
    } finally { f.journal.close(); }
  });

  test(`${name} rejects accidentally disabled solve requests before forwarding`, async () => {
    const f = fixture(Proxy);
    try {
      expect((await f.proxy.handle("task", request({ reasoning_effort: "none", thinking: { type: "disabled" } }))).httpStatus).toBe(503);
      expect(f.wires).toHaveLength(0);
    } finally { f.journal.close(); }
  });

  test(`${name} preserves previous reasoning and tool-call history in the actual forwarded request`, async () => {
    const f = fixture(Proxy);
    const messages = [{ role: "user", content: "solve" }, { role: "assistant", content: null, reasoning_content: "prior reasoning", tool_calls: [{ id: "call-1", type: "function", function: { name: "read", arguments: "{}" } }] }, { role: "tool", tool_call_id: "call-1", content: "result" }, { role: "user", content: "continue" }];
    try {
      expect((await f.proxy.handle("task", request({ messages }))).httpStatus).toBe(200);
      expect(f.wires[0].messages).toEqual(messages);
    } finally { f.journal.close(); }
  });
}
