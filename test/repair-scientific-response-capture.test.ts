import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join, resolve } from "node:path";
import { createCampaignJournal } from "../scripts/benchmark-repair/campaign-journal.ts";
import { captureProviderResponse, CapturedTransportFailure, ScientificJournalProxy } from "../scripts/benchmark-repair/scientific-journal-proxy.ts";
const root = resolve(import.meta.dir, ".."), out = join(root, ".scratch/scientific-response-capture-" + randomUUID());
mkdirSync(out, { recursive: true });
const raw = JSON.stringify({ model: "deepseek-flash", max_tokens: 8192, temperature: 0, seed: 42, reasoning_effort: "none", messages: [{ role: "user", content: "public fixture" }] });
test("200 body failure preserves actual header and exact partial raw gzip, and retains unknown fee", async () => {
  const prefix = Buffer.from('{"choices":[{"message":'); let n = 0;
  const body = new ReadableStream({ pull(controller) { if (n++ === 0) controller.enqueue(prefix); else controller.error(new Error("local stream failure")); } });
  const journal = createCampaignJournal({ directory: out, campaign: "repair-2026-10-08T00-00-00-000Z", capUsd: 1, priorCampaignCostUpperBoundUsd: .1 });
  const proxy = new ScientificJournalProxy(journal, { routes: new Set(["only"]), failureDirectory: join(out, "failures"), transport: async () => captureProviderResponse(new Response(body, { status: 200 })) });
  try {
    const result = await proxy.handle("only", raw); await proxy.drain();
    expect(result.httpStatus).toBe(503);
    expect(proxy.state().stopReason).toBeTruthy();
    const anomaly = proxy.anomalies[0]; expect(anomaly.httpStatus).toBe(200); expect(anomaly.bodyComplete).toBe(false);
    const file = (anomaly.files as { path: string }[]).find(x => x.path.endsWith("response.json.gz"))!;
    expect(gunzipSync(readFileSync(file.path))).toEqual(prefix);
    const call = proxy.takeTaskReceipts("only")[0]; expect(call.providerAttempted).toBe(true); expect(call.fault).toBe("ProviderResponseBodyError");
    expect(journal.snapshot().recordedUsageUpperBoundUsd).toBeGreaterThan(0);
  } finally { journal.close(); }
});
test("response over limit and invalid UTF8 are typed failures with exact bounded bytes", async () => {
  for (const [data, limit, why] of [[Buffer.from("123456789"), 8, "ProviderResponseTooLarge"], [Buffer.from([255, 0]), 8, "ProviderResponseEncodingError"]] as const) {
    try { await captureProviderResponse(new Response(data), limit); throw new Error("expected failure"); }
    catch (error) {
      expect(error).toBeInstanceOf(CapturedTransportFailure);
      const fault = error as CapturedTransportFailure;
      expect(fault.capture.fault).toBe(why); expect(fault.capture.rawBytes).toEqual(data.subarray(0, limit));
    }
  }
  const complete = await captureProviderResponse(new Response('{"public":"fixture"}'));
  expect(complete.rawResponse).toBe('{"public":"fixture"}');
});
