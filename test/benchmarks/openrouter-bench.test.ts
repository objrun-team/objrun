import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { createCampaignJournal, inspectCampaignJournal } from "../../scripts/benchmark-repair/campaign-journal.ts";
import { ScientificJournalProxy } from "../../scripts/benchmark-repair/scientific-journal-proxy.ts";
import { BENCHMARK_PROVIDER } from "../../scripts/benchmark-repair/benchmark-provider.ts";
import { BENCHMARK_INFERENCE } from "../../scripts/benchmark-repair/benchmark-inference.ts";
import { registerVendors, type Unit } from "../../app/src/llm/index.ts";
import { actualPin } from "../../scripts/benchmark-repair/paid-resource-proof-v2.ts";
import { createBenchmarkCash, verifyBenchmarkCashClosure } from "../../scripts/benchmark-repair/benchmark-usd-cash.ts";
import { classifyGeneration } from '../../scripts/benchmark-repair/campaign-contract.ts';

function fixture() {
  const directory = resolve(import.meta.dir, "../../.scratch/openrouter-bench-" + randomUUID()); mkdirSync(directory, { recursive: true });
  const journal = createCampaignJournal({ directory, campaign: "repair-2026-10-10T00-00-00-000Z",
    capUsd: 1, priorCampaignCostUpperBoundUsd: 0, provider: BENCHMARK_PROVIDER } as any);
  return { directory, journal };
}
const rawRequest = () => JSON.stringify({ model: BENCHMARK_PROVIDER.model, temperature: 0, seed: 42,
  reasoning_effort: "high", max_tokens: 16384, messages: [{ role: "user", content: "fixture" }] });
const completion = (extra = {}) => JSON.stringify({ id: "gen-fixture", provider: BENCHMARK_PROVIDER.providerName, model: BENCHMARK_PROVIDER.model,
  choices: [{ message: { role: "assistant", content: "42", reasoning: "synthetic reasoning" }, finish_reason: "stop" }],
  usage: { prompt_tokens: 10, completion_tokens: 3, total_tokens: 13, cost: 0.0000042,
    prompt_tokens_details: { cached_tokens: 2 }, completion_tokens_details: { reasoning_tokens: 2 } }, ...extra });

test("the current Bench proxy routes only to the pinned Relace provider with thinking enabled", async () => {
  const f = fixture(); const wires: any[] = [];
  const proxy = new ScientificJournalProxy(f.journal, { provider: BENCHMARK_PROVIDER,
    inference: { ...BENCHMARK_INFERENCE, reasoningEffort: "high" }, routes: new Set(["task"]), failureDirectory: join(f.directory, "failures"),
    transport: async (raw: string) => { wires.push(JSON.parse(raw)); return { httpStatus: 200, rawResponse: completion() }; } } as any);
  try {
    expect((await proxy.handle("task", rawRequest())).httpStatus).toBe(200);
    expect(wires[0]).toMatchObject({ model: BENCHMARK_PROVIDER.model, provider: { only: BENCHMARK_PROVIDER.routing.only, allow_fallbacks: false },
      reasoning: { enabled: true, effort: "high", exclude: false }, max_tokens: 16384 });
    expect(wires[0].seed).toBeUndefined();
    expect(wires[0].thinking).toBeUndefined();
    f.journal.exportLegacyLedger();
    const receipt = [...f.journal.closedCalls("task")][0] as any;
    expect(receipt.costBasis).toBe("provider_reported_usd");
    expect(receipt.usdUpperBound).toBe(0.0000042);
    expect(receipt.providerName).toBe(BENCHMARK_PROVIDER.providerName);
    expect(inspectCampaignJournal(f.directory).valid).toBe(true);
  } finally { f.journal.close(); }
});

test("OpenRouter response provider and model are verified without clipping the billed cost", () => {
  const f = fixture();
  try {
    const body = JSON.parse(rawRequest()); body.provider = BENCHMARK_PROVIDER.routing; body.reasoning = { enabled: true, effort: "high" };
    const ticket = f.journal.admit({ route: "task", rawRequest: JSON.stringify(body) });
    expect(ticket.admitted).toBe(true);
    if (!ticket.admitted) throw Error("fixture admission");
    const receipt = f.journal.finish({ requestSeq: ticket.requestSeq, providerAttempted: true, httpStatus: 200,
      rawResponse: completion({ provider: "Other", usage: { prompt_tokens: 1, completion_tokens: 1, cost: 0.5 } }) }).receipt as any;
    expect(receipt.fault).toBe("UnexpectedOpenRouterProvider");
    expect(receipt.usdUpperBound).toBe(0.5);
    expect(f.journal.snapshot().stopReason).toBeDefined();
    const inspected = inspectCampaignJournal(f.directory);
    expect(inspected.valid).toBe(true);
    expect(inspected.eligibleForScoreCertification).toBe(false);
  } finally { f.journal.close(); }
});

for (const valid of [true, false]) test(`the actual adapter ${valid ? "accepts a submit call while keeping thinking on" : "rejects text-only forced submission"}`, async () => {
  const bodies: any[] = [];
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(req) {
    bodies.push(await req.json());
    return Response.json({ id: "synthetic-submit", model: BENCHMARK_PROVIDER.model, provider: BENCHMARK_PROVIDER.providerName,
      choices: [{ index: 0, message: { role: "assistant", content: valid ? null : "42", reasoning: "synthetic reasoning",
        ...(valid ? { tool_calls: [{ id: "submit-1", type: "function", function: { name: "submit", arguments: '{"answer":"42"}' } }] } : {}) },
        finish_reason: valid ? "tool_calls" : "stop" }], usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 } });
  } });
  const env = "TGENGIN_OPENROUTER_SUBMIT_FIXTURE_KEY", before = process.env[env]; process.env[env] = "local-only";
  try {
    const handles = new Map<string, any>();
    registerVendors({ run() {} } as any, { register(_db: any, name: string, _timeout: any, handler: any) { handles.set(name, handler); } } as any,
      { warn() {} } as any, [], { ...BENCHMARK_INFERENCE, retryTimes: 0, continueTimes: 0 });
    const unit: Unit = { agent: {}, task: {}, cycle: {}, chain: "fixture", place: "local", instance: "fixture", unit: 0,
      api: { key_env: env, model: BENCHMARK_PROVIDER.model, base_url: `http://127.0.0.1:${server.port}/v1`, retry_on: "[]" },
      context: [{ seq: 0, role: "user", kind: "prompt", body: "Submit answer 42" }], sentAs: { user: "messages", assistant: "messages" },
      mustCall: "submit", rules: [], tools: ["submit", "read"].map(name => ({ name, does: name, params: '{"type":"object","properties":{"answer":{"type":"string"}}}' })) };
    if (valid) { const result = await handles.get("fn:api.openrouter")(unit); expect(JSON.parse(result.body).calls[0].name).toBe("submit"); }
    else await expect(handles.get("fn:api.openrouter")(unit)).rejects.toMatchObject({ name: "RequiredToolCallMissing" });
    expect(bodies).toHaveLength(1);
    expect(bodies[0].reasoning).toEqual({ enabled: true, effort: "high", exclude: false });
    expect(bodies[0].tool_choice).toBe("auto");
    expect(bodies[0].tools.map((row: any) => row.function.name)).toEqual(["submit"]);
    expect(bodies[0].provider.only).toEqual(BENCHMARK_PROVIDER.routing.only);
    expect(bodies[0].seed).toBeUndefined();
  } finally { if (before === undefined) delete process.env[env]; else process.env[env] = before; await server.stop(true); }
});

function cashFixture(f: ReturnType<typeof fixture>, providerKind: 'real-provider' | 'local-mock' = 'real-provider') {
  const runId = "repair-2026-10-10T00-00-00-000Z";
  const stored = join(f.directory, "synthetic-endpoints.json");
  writeFileSync(stored, JSON.stringify({ fixtureOnly: true, data: { endpoints: [{ provider_name: BENCHMARK_PROVIDER.providerSlug === "relace" ? "Relace" : "DeepSeek", tag: BENCHMARK_PROVIDER.providerSlug, model_id: BENCHMARK_PROVIDER.model }] } }));
  const priceFile = join(f.directory, "fixture-price-profile.json");
  writeFileSync(priceFile, JSON.stringify({ protocol: "openrouter-usd-pricing-source-snapshot-v1", currency: "USD", model: BENCHMARK_PROVIDER.model,
    providerSlug: BENCHMARK_PROVIDER.providerSlug, reservationRates: BENCHMARK_PROVIDER.peakRates, originalResponsePin: actualPin(stored),
    actualOfficialGET: true, modelCalls: 0, observedAtUtc: new Date().toISOString(),
    note: "Synthetic profile and endpoint body for a local control; no official GET was made." }));
  const admissionFile = join(f.directory, "fixture-admission.json"); writeFileSync(admissionFile, '{"synthetic":true}');
  return createBenchmarkCash({ directory: join(f.directory, "cash"), runId, providerKind,
    prices: actualPin(priceFile), admission: { currency: "USD", capUsd: 1, runId, owned: { ownerNonce: "fixture", pid: process.pid }, scope: "production",
      proofPin: actualPin(admissionFile), assertOwned() {}, validateForwardSource() {}, registerCash() {} },
    journal: { directory: f.directory, configPin: actualPin(join(f.directory, "journal-config.json")),
      sourcePin: actualPin(resolve(import.meta.dir, "../../scripts/benchmark-repair/campaign-journal.ts")) } }, BENCHMARK_PROVIDER);
}
test("USD cash records and independently replays the actual journal cost without CNY fields", () => {
  const f = fixture(), cash = cashFixture(f), runId = "repair-2026-10-10T00-00-00-000Z";
  try {
    const request = JSON.stringify({ ...JSON.parse(rawRequest()), provider: BENCHMARK_PROVIDER.routing });
    const admitted = f.journal.admit({ route: "task", rawRequest: request }); if (!admitted.admitted) throw Error("fixture admission");
    const funded = cash.beforeForward({ id: runId + "/0", route: "task", rawRequest: Buffer.from(request), capturedRequest: actualPin(admitted.requestFile),
      journal: { admitted, startPrefix: f.journal.snapshot().durablePrefix } });
    const start = f.journal.snapshot().durablePrefix.bytes;
    f.journal.finish({ requestSeq: admitted.requestSeq, providerAttempted: true, httpStatus: 200, rawResponse: completion() });
    const prefix = f.journal.snapshot().durablePrefix;
    cash.finish(funded.ticket, { kind: "journal-finish", journalRef: { finishOffset: start, finishEnd: prefix.bytes, finishLineSha256: prefix.lastSha256 } });
    expect(cash.snapshot()).toMatchObject({ currency: "USD", billedUsd: 0.0000042, pendingCount: 0, newUnknownCount: 0 });
    expect(cash.snapshot().newKnownEstimatedNanoCny).toBeUndefined();
    const closed = cash.close(), result = verifyBenchmarkCashClosure(closed);
    expect(result.proof.releasePermitted).toBe(true);
    const oldBytes = readFileSync(closed.path); writeFileSync(closed.path, oldBytes.toString().replace('0.0000042', '0.0000001'));
    expect(() => verifyBenchmarkCashClosure(actualPin(closed.path))).toThrow();
  } finally { cash.close(); f.journal.close(); }
});

test("missing USD cost keeps the reservation while an evidenced routing rejection is zero", () => {
  for (const rejection of [false, true]) {
    const f = fixture();
    try {
      const request = JSON.stringify({ ...JSON.parse(rawRequest()), provider: BENCHMARK_PROVIDER.routing });
      const admitted = f.journal.admit({ route: 'task', rawRequest: request }); if (!admitted.admitted) throw Error('fixture admission');
      const receipt = f.journal.finish({ requestSeq: admitted.requestSeq, providerAttempted: true, httpStatus: rejection ? 404 : 200,
        rawResponse: rejection ? JSON.stringify({ error: { message: 'Synthetic privacy control', metadata: { failed_routing_step: 'Filter by Guardrails', routing_funnel: [] } } })
          : completion({ usage: { prompt_tokens: 10, completion_tokens: 3 } }) }).receipt;
      expect(receipt.costBasis).toBe(rejection ? 'known_uncharged' : 'reservation');
      expect(receipt.usdUpperBound).toBe(rejection ? 0 : admitted.reservationUsd);
      expect(inspectCampaignJournal(f.directory).valid).toBe(true);
      expect(inspectCampaignJournal(f.directory).eligibleForScoreCertification).toBe(false);
    } finally { f.journal.close(); }
  }
});

test("cash replay requires every zero-cost request and cannot release a zero-amount unknown", () => {
  for (const unknown of [false, true]) {
    const f = fixture(), cash = cashFixture(f, 'local-mock');
    try {
      const request = JSON.stringify({ ...JSON.parse(rawRequest()), provider: BENCHMARK_PROVIDER.routing });
      const admitted = f.journal.admit({ route: 'task', rawRequest: request }); if (!admitted.admitted) throw Error('fixture admission');
      const funded = cash.beforeForward({ id: 'fixture', route: 'task', rawRequest: Buffer.from(request), capturedRequest: actualPin(admitted.requestFile), journal: { admitted, startPrefix: f.journal.snapshot().durablePrefix } });
      const offset = f.journal.snapshot().durablePrefix.bytes;
      f.journal.finish({ requestSeq: admitted.requestSeq, providerAttempted: true, httpStatus: 200,
        rawResponse: completion({ usage: { prompt_tokens: 10, completion_tokens: 3, ...(unknown ? {} : { cost: 0 }) } }) });
      const prefix = f.journal.snapshot().durablePrefix;
      cash.finish(funded.ticket, { kind: 'journal-finish', journalRef: { finishOffset: offset, finishEnd: prefix.bytes, finishLineSha256: prefix.lastSha256 } });
      const closed = cash.close(), checked = verifyBenchmarkCashClosure(closed);
      expect(checked.proof.releasePermitted).toBe(!unknown);
      expect(checked.proof.snapshot.newUnknownCount).toBe(unknown ? 1 : 0);
      const fake = JSON.parse(readFileSync(closed.path, 'utf8'));
      if (unknown) fake.releasePermitted = true;
      else { writeFileSync(fake.cashEventsPin.path, ''); fake.cashEventsPin = actualPin(fake.cashEventsPin.path); }
      writeFileSync(closed.path, JSON.stringify(fake));
      expect(() => verifyBenchmarkCashClosure(actualPin(closed.path))).toThrow();
    } finally { cash.close(); f.journal.close(); }
  }
});

test('an evidenced Relace rate rejection can retry, while an ambiguous 429 retains its reservation', async () => {
  for(const explicit of [true,false]){
    const f=fixture();let calls=0;
    const proxy=new ScientificJournalProxy(f.journal,{provider:BENCHMARK_PROVIDER,inference:BENCHMARK_INFERENCE,routes:new Set(['task']),failureDirectory:join(f.directory,'failures'),
      transport:async()=>++calls===1?{httpStatus:429,rawResponse:JSON.stringify({error:{code:429,message:'Provider returned error',metadata:{provider_name:BENCHMARK_PROVIDER.providerName,
        limit_source:explicit?'upstream_provider_shared_pool':'unknown',raw:BENCHMARK_PROVIDER.model+' is temporarily rate-limited upstream. Please retry shortly.'}}})}:{httpStatus:200,rawResponse:completion()}});
    try{
      expect((await proxy.handle('task',rawRequest())).httpStatus).toBe(429);
      await proxy.drain();const first=proxy.takeTaskReceipts('task')[0];
      expect(first.costBasis).toBe(explicit?'known_uncharged':'reservation');
      if(explicit){
        expect(first.usdUpperBound).toBe(0);expect(f.journal.snapshot().stopReason).toBeUndefined();
        expect((await proxy.handle('task',rawRequest())).httpStatus).toBe(200);
        await proxy.drain();const receipts=[first,...proxy.takeTaskReceipts('task')];
        expect(classifyGeneration({runtimeVerdict:{valid:true,outcome:'candidate'},state:'done',calls:receipts,trace:[],candidate:'42',arm:'F'} as any).valid).toBe(true);
        expect(inspectCampaignJournal(f.directory).eligibleForScoreCertification).toBe(true);
      }else{
        expect(first.usdUpperBound).toBeGreaterThan(0);expect(f.journal.snapshot().stopReason).toBeDefined();
        expect((await proxy.handle('task',rawRequest())).httpStatus).toBe(503);expect(calls).toBe(1);
      }
      expect(inspectCampaignJournal(f.directory).valid).toBe(true);
    }finally{f.journal.close();}
  }
});
