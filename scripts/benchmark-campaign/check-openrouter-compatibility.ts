/** Read-only route audit: all completions come from a local synthetic server. */
import { strict as assert } from "node:assert";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { registerVendors, VENDORS, type Unit } from "../../app/src/llm/index.ts";
import { BENCHMARK_INFERENCE } from "../benchmark-repair/benchmark-inference.ts";
import { createCampaignJournal } from "../benchmark-repair/campaign-journal.ts";
import { ScientificJournalProxy } from "../benchmark-repair/scientific-journal-proxy.ts";
import { ScientificJournalProxy as ChemiqProxy } from "../benchmark-repair/chemiq-f-provider-proxy-v3.ts";
import { requestValues } from "../benchmark-repair/paid-resource-proof-v2.ts";
import { BENCHMARK_PROVIDER } from "../benchmark-repair/benchmark-provider.ts";

const output = resolve(process.argv[2] ?? "");
assert(process.argv[2], "Provide the audit output directory");
mkdirSync(output, { recursive: true });
const requests: Record<string, any>[] = [];
const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
  assert.equal(new URL(request.url).pathname, "/v1/chat/completions");
  const body = await request.json() as Record<string, any>;
  requests.push(body);
  const forced = body.messages.at(-1)?.content === "Submit the candidate";
  return Response.json({ id: "local-openrouter-fixture-" + requests.length,
    object: "chat.completion", created: 0, model: body.model, provider: BENCHMARK_PROVIDER.providerName,
    choices: [{ index: 0, finish_reason: forced ? "tool_calls" : "stop", message: {
      role: "assistant", content: forced ? null : "Synthetic candidate",
      reasoning: "Synthetic reasoning for compatibility testing",
      ...(forced ? { tool_calls: [{ id: "fixture-submit", type: "function", function: {
        name: "submit", arguments: JSON.stringify({ answer: "42" }),
      } }] } : {}),
    } }], usage: { prompt_tokens: 12, completion_tokens: 8, total_tokens: 20,
      prompt_tokens_details: { cached_tokens: 2 }, completion_tokens_details: { reasoning_tokens: 5 }, cost: 0 },
  });
} });
const keyEnv = "TGENGIN_OPENROUTER_READONLY_FIXTURE_KEY";
const oldKey = process.env[keyEnv];
process.env[keyEnv] = "local-fixture-only";
try {
  const handles = new Map<string, (unit: Unit) => Promise<any>>();
  // Only the registry/database registration shell is doubled; request and response adapters are production code.
  const db = { run() {} } as any;
  const registry = { register(_db: unknown, name: string, _timeout: number, handler: any) {
    handles.set(name, handler);
  } } as any;
  registerVendors(db, registry, { warn() {} } as any, [], {
    ...BENCHMARK_INFERENCE, retryTimes: 0, continueTimes: 0,
  });
  const unit: Unit = { agent: {}, task: {}, cycle: {}, chain: "fixture", place: "local",
    instance: "fixture", unit: 0,
    api: { key_env: keyEnv, model: "deepseek/deepseek-v4.1-flash",
      base_url: `http://127.0.0.1:${server.port}/v1`, retry_on: "[]" },
    context: [{ seq: 0, role: "user", kind: "prompt", body: "Produce a synthetic candidate" }],
    sentAs: { user: "messages", assistant: "messages", system: "instructions" },
    mustCall: null, tools: [{ name: "submit", does: "Submit the candidate", params: JSON.stringify({
      type: "object", properties: { answer: { type: "string" } }, required: ["answer"],
    }) }], rules: [],
  };
  const adapter = handles.get("fn:api.openrouter")!;
  const first = await adapter(unit);
  assert.equal(first.thought, "Synthetic reasoning for compatibility testing");
  assert.equal(first.reasoning_tokens, 5);
  assert.equal(first.cached_tokens, 2);
  assert.equal(requests[0].reasoning_effort, "high");
  assert.equal(requests[0].max_tokens ?? requests[0].max_completion_tokens, 16384);
  assert.deepEqual(requests[0].provider, BENCHMARK_PROVIDER.routing);
  const second = await adapter({ ...unit, mustCall: "submit", unit: 1, context: [
    ...unit.context, { seq: 1, role: first.role, kind: first.kind, body: first.body, thought: first.thought },
    { seq: 2, role: "user", kind: "prompt", body: "Submit the candidate" },
  ] });
  assert.equal(requests[1].reasoning_effort, "high");
  assert.deepEqual(requests[1].reasoning, { enabled: true, effort: "high", exclude: false });
  assert.equal(requests[1].tool_choice, "auto");
  assert.deepEqual(requests[1].tools.map((tool: any) => tool.function.name), ["submit"]);
  assert.equal(requests[1].messages.find((message: any) => message.role === "assistant")?.reasoning_content, first.thought);
  assert.equal(JSON.parse(second.body).calls[0].name, "submit");

  const wire = JSON.stringify({ model: "deepseek/deepseek-v4.1-flash", messages: unit.context.map(row => ({ role: row.role, content: row.body })),
    temperature: 0, seed: 42, reasoning_effort: "high", max_tokens: 16384 });
  const guards = [];
  for (const [name, Proxy] of [["scientific/SkillsBench", ScientificJournalProxy], ["ChemIQ", ChemiqProxy]] as const) {
    const directory = join(output, "local-guard-" + guards.length);
    mkdirSync(directory, { recursive: true });
    const journal = createCampaignJournal({ directory, campaign: "repair-2026-10-10T00-00-00-000Z",
      capUsd: 1, priorCampaignCostUpperBoundUsd: 0, outputDirectory: directory, provider: BENCHMARK_PROVIDER });
    let forwarded = 0;
    const proxy = new Proxy(journal, { routes: new Set(["fixture"]), failureDirectory: directory,
      provider: BENCHMARK_PROVIDER, inference: BENCHMARK_INFERENCE, transport: async () => { forwarded++; return { httpStatus: 200, rawResponse: JSON.stringify({
        id: "synthetic-proxy-" + forwarded, provider: BENCHMARK_PROVIDER.providerName, model: BENCHMARK_PROVIDER.model, choices: [{ finish_reason: "stop", message: { role: "assistant", content: "42", reasoning: "synthetic reasoning" } }],
        usage: { prompt_tokens: 2, completion_tokens: 2, cost: 0 } }) }; } });
    try {
      const result = await proxy.handle("fixture", wire);
      assert.equal(result.httpStatus, 200);
      assert.equal(forwarded, 1);
      journal.exportLegacyLedger();
      guards.push({ name, openRouterModelAccepted: true, transportCalls: forwarded, currency: "USD" });
    } finally { journal.close(); }
  }
  assert.throws(() => requestValues(Buffer.from(wire)), /request_profile/);
  const result = { checkedAt: new Date().toISOString(), modelCalls: 0,
    localSyntheticCompletions: requests.length, realApiUsed: false,
    coreAdapter: { openRouterModelSerialized: true, reasoningStringParsed: true,
      reasoningHistoryReplayed: true, usageParsed: true, forcedToolSerialized: true,
      currentProviderRouting: requests[0].provider,
      note: "Current constrained-auto submit and strict local validation; this local fixture does not establish live provider availability." },
    benchmarkGuards: guards, cnyAdmissionRejectsOpenRouterModel: true,
    requests, localOutputs: [first, second] };
  writeFileSync(join(output, "local-compatibility-result.json"), JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify({ resultPath: join(output, "local-compatibility-result.json"),
    modelCalls: 0, localSyntheticCompletions: requests.length, coreAdapterPassed: true, benchmarkGuards: guards }));
} finally {
  if (oldKey === undefined) delete process.env[keyEnv]; else process.env[keyEnv] = oldKey;
  await server.stop(true);
}
