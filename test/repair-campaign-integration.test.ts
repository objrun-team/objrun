import { expect, test } from "bun:test";
import { createHash, timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { gzipSync, gunzipSync } from "node:zlib";
import { campaignComplete, checkedOutputTokens, completionFault, reconcileReceiptCost, validTokenUsage, type ApiReceipt } from "../scripts/repair-2026-10-08/campaign-contract.ts";

// Exercise the real next-entry proxy body, injecting all I/O. Do not import it:
// its top level launches a campaign with the project API credential.
const source = readFileSync(join(import.meta.dir, "../scripts/repair-2026-10-08/campaign-next.ts"), "utf8");
const body = source.slice(source.indexOf("const proxy = Bun.serve("), source.indexOf("\nconst sourcePath ="));
const transpiler = new Bun.Transpiler({ loader: "ts" });
const sha = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const build = new Function("Bun", "timingSafeEqual", "authorization", "maxTokens", "priorCampaignCost", "spent", "reserved", "fatal", "pending", "calls", "ledger", "sha", "fetch", "cap", "checkedOutputTokens", "statfsSync", "store", "join", "writeFileSync", "gzipSync", "reconcileReceiptCost", "validTokenUsage", "completionFault", "captureErrors", transpiler.transformSync(body) + "\nreturn { handle: proxy.fetch, state: () => ({ spent, reserved, fatal, pending: Object.fromEntries(pending), calls, captureErrors }) };" );

type Receipt = ApiReceipt & { requestFile?: string; responseFile?: string; requestSha256?: string; responseSha256?: string; captureErrors?: { stage: string }[] };
type ProxyFixture = { handle(request: Request): Promise<Response>; state(): { spent: number; reserved: number; fatal?: string; pending: Record<string, number>; calls: Receipt[]; captureErrors: { stage: string }[] }; files: Map<string, Buffer>; forwarded(): number };
function fixture(response: () => Promise<Response>, options: { diskBytes?: number; writeFault?: boolean | "response"; ledgerFault?: boolean; ledgerFailAt?: number; diskFault?: boolean; cap?: number } = {}): ProxyFixture {
  const files = new Map<string, Buffer>();
  let forwarded = 0, ledgers = 0;
  const proxy = build({ serve: (options: { fetch: unknown }) => ({ fetch: options.fetch }) }, timingSafeEqual, "Bearer local-integration-probe", 8192, 0, 0, 0, undefined, new Map(), [], () => { ledgers++; if (options.ledgerFault || options.ledgerFailAt === ledgers) throw new Error("FixtureLedgerWriteFailure"); }, sha,
    async () => { forwarded++; return await response(); }, options.cap ?? 15, checkedOutputTokens,
    () => { if (options.diskFault) throw new Error("FixtureDiskUnavailable"); return { bavail: options.diskBytes ?? 1024 ** 3, bsize: 1 }; }, "/private-local-fixture", join,
    (path: string, bytes: Buffer) => { if (options.writeFault === true || (options.writeFault === "response" && path.includes("-response."))) throw new Error("FixtureEvidenceWriteFailure"); files.set(path, bytes); }, gzipSync, reconcileReceiptCost, validTokenUsage, completionFault, []);
  return { ...proxy, files, forwarded: () => forwarded };
}
function request(maxTokens: unknown = 8192) {
  return new Request("http://127.0.0.1/fixture/v1/chat/completions", { method: "POST", headers: { authorization: "Bearer local-integration-probe", "content-type": "application/json" }, body: JSON.stringify({ model: "deepseek-flash", max_tokens: maxTokens, messages: [{ role: "user", content: "private fixture" }] }) });
}
const completion = () => ({ id: "local-completion", model: "deepseek-flash", usage: { prompt_tokens: 100, completion_tokens: 10, prompt_cache_hit_tokens: 40 }, choices: [{ message: { role: "assistant", content: "fixture answer" } }] });

test("integrated proxy preserves request/response evidence and reconciles the receipt delta", async () => {
  const proxy = fixture(async () => Response.json(completion()));
  expect((await proxy.handle(request())).status).toBe(200);
  const state = proxy.state(), call = state.calls[0]!;
  expect(state.reserved).toBe(0);
  expect(state.pending.fixture).toBe(0);
  expect(state.fatal).toBeUndefined();
  expect(call).toMatchObject({ completionValid: true, costBasis: "reported_usage" });
  expect(state.spent).toBeCloseTo(0.00003024, 12);
  expect(state.spent).toBe(call.usdUpperBound!);
  expect(call.finishedAt).toBeString();
  const rawRequest = gunzipSync(proxy.files.get(call.requestFile!)!).toString();
  const rawResponse = gunzipSync(proxy.files.get(call.responseFile!)!).toString();
  expect(call.requestSha256).toBe(sha(rawRequest));
  expect(call.responseSha256).toBe(sha(rawResponse));
  expect(JSON.parse(rawResponse)).toEqual(completion());
  expect(rawRequest + rawResponse).not.toContain("Bearer local-integration-probe");
});

test("integrated transport failure charges its conservative receipt once and releases the reserve", async () => {
  const proxy = fixture(async () => { throw new Error("FixtureTransportFailure"); });
  expect((await proxy.handle(request())).status).toBe(503);
  const state = proxy.state(), call = state.calls[0]!;
  expect(state.reserved).toBe(0);
  expect(state.pending.fixture).toBe(0);
  expect(state.spent).toBe(call.reservationUsd!);
  expect(state.spent).toBe(call.usdUpperBound!);
  expect(call.costBasis).toBe("reservation");
  expect(call.finishedAt).toBeString();
});

test("integrated malformed HTTP 200 preserves usage charge and cannot double charge in catch", async () => {
  const data = completion();
  const proxy = fixture(async () => Response.json({ ...data, choices: undefined }));
  expect((await proxy.handle(request())).status).toBe(503);
  const state = proxy.state(), call = state.calls[0]!;
  expect(call).toMatchObject({ completionValid: false, completionFault: "MissingCompletionChoices", costBasis: "reported_usage" });
  expect(state.spent).toBeCloseTo(0.00003024, 12);
  expect(state.spent).toBe(call.usdUpperBound!);
  expect(state.reserved).toBe(0);
  expect(state.pending.fixture).toBe(0);
});

test("integrated account rejection remains known uncharged without fabricated token usage", async () => {
  const proxy = fixture(async () => Response.json({ error: "fixture rejected" }, { status: 402 }));
  expect((await proxy.handle(request())).status).toBe(402);
  expect(proxy.state()).toMatchObject({ spent: 0, reserved: 0, fatal: "provider_http_402" });
  expect(proxy.state().calls[0]).toMatchObject({ usdUpperBound: 0, costBasis: "known_uncharged" });
});

test("integrated invalid limit stops before forwarding or evidence/cost allocation", async () => {
  const proxy = fixture(async () => Response.json(completion()));
  expect((await proxy.handle(request("not-a-number"))).status).toBe(400);
  expect((await proxy.handle(request())).status).toBe(402);
  expect(proxy.forwarded()).toBe(0);
  expect(proxy.files.size).toBe(0);
  expect(proxy.state()).toMatchObject({ spent: 0, reserved: 0, calls: [], fatal: "invalid_request_output_limit" });
});

test("integrated disk guard stops before allocating a provider call", async () => {
  const proxy = fixture(async () => Response.json(completion()), { diskBytes: 511 * 1024 * 1024 });
  expect((await proxy.handle(request())).status).toBe(507);
  expect(proxy.forwarded()).toBe(0);
  expect(proxy.files.size).toBe(0);
  expect(proxy.state()).toMatchObject({ spent: 0, reserved: 0, calls: [], fatal: "local_disk_low" });
});

test("request evidence write failure is captured without a charge or lingering allocation", async () => {
  const proxy = fixture(async () => Response.json(completion()), { writeFault: true });
  expect((await proxy.handle(request())).status).toBe(503);
  expect(proxy.forwarded()).toBe(0);
  expect(proxy.state()).toMatchObject({ spent: 0, reserved: 0, fatal: "local_evidence_error" });
  expect(proxy.state().pending.fixture).toBe(0);
  expect(proxy.state().calls[0]).toMatchObject({ fault: "capture_error", usdUpperBound: 0, costBasis: "known_uncharged", providerAttempted: false });
  expect(proxy.state().calls[0]?.finishedAt).toBeString();
  expect(proxy.state().captureErrors).toContainEqual(expect.objectContaining({ stage: "request_capture" }));
});

test("initial ledger write failure is captured and finalized without forwarding", async () => {
  const proxy = fixture(async () => Response.json(completion()), { ledgerFault: true });
  expect((await proxy.handle(request())).status).toBe(503);
  expect(proxy.forwarded()).toBe(0);
  expect(proxy.state()).toMatchObject({ spent: 0, reserved: 0, fatal: "local_evidence_error" });
  expect(proxy.state().pending.fixture).toBe(0);
  expect(proxy.state().calls[0]).toMatchObject({ fault: "capture_error", usdUpperBound: 0, costBasis: "known_uncharged", providerAttempted: false });
  expect(proxy.state().calls[0]?.finishedAt).toBeString();
  expect(proxy.state().captureErrors.map(error => error.stage)).toEqual(["initial_ledger", "final_ledger"]);
});

test("final ledger failure preserves the charge and memory error while blocking further forwarding", async () => {
  const proxy = fixture(async () => Response.json(completion()), { ledgerFailAt: 2 });
  expect((await proxy.handle(request())).status).toBe(503);
  const state = proxy.state(), call = state.calls[0]!;
  expect(state).toMatchObject({ reserved: 0, fatal: "local_evidence_error" });
  expect(state.pending.fixture).toBe(0);
  expect(state.spent).toBeCloseTo(0.00003024, 12);
  expect(call).toMatchObject({ fault: "capture_error", costBasis: "reported_usage" });
  expect(call.finishedAt).toBeString();
  expect(state.captureErrors).toContainEqual(expect.objectContaining({ stage: "final_ledger" }));
  expect((await proxy.handle(request())).status).toBe(402);
  expect(proxy.forwarded()).toBe(1);
  expect(proxy.state().calls.length).toBe(1);
});

test("response capture failure after forwarding retains a conservative request charge", async () => {
  const proxy = fixture(async () => Response.json(completion()), { writeFault: "response" });
  expect((await proxy.handle(request())).status).toBe(503);
  const state = proxy.state(), call = state.calls[0]!;
  expect(proxy.forwarded()).toBe(1);
  expect(state.reserved).toBe(0);
  expect(state.pending.fixture).toBe(0);
  expect(state.spent).toBe(call.reservationUsd!);
  expect(state.spent).toBe(call.usdUpperBound!);
  expect(call).toMatchObject({ fault: "capture_error", costBasis: "reservation", providerAttempted: true });
  expect(call.captureErrors).toContainEqual(expect.objectContaining({ stage: "response_capture" }));
});

test("unavailable disk statistics stop safely even if the diagnostic ledger cannot be saved", async () => {
  const proxy = fixture(async () => Response.json(completion()), { diskFault: true, ledgerFault: true });
  expect((await proxy.handle(request())).status).toBe(503);
  expect(proxy.forwarded()).toBe(0);
  expect(proxy.state()).toMatchObject({ spent: 0, reserved: 0, calls: [], fatal: "local_evidence_error" });
  expect(proxy.state().captureErrors.map(error => error.stage)).toEqual(["disk_status", "disk_status_ledger"]);
});

test("next-entry provenance captures the executing basename and validates selected graders", () => {
  const repairAssignment = source.slice(source.indexOf("source.repairFiles ="), source.indexOf("\nsource.executionDigest =")).replaceAll("import.meta.path", "executingPath").replaceAll("import.meta.dir", "executingDirectory");
  const snapshot: { repairFiles?: { path: string; sha256: string }[]; files: { path: string; sha256: string }[] } = { files: [] };
  new Function("source", "basename", "executingPath", "executingDirectory", "sha", "readFileSync", "join", transpiler.transformSync(repairAssignment))(snapshot, basename, "/fixture/campaign-next.ts", "/fixture", sha, () => "frozen source", join);
  expect(snapshot.repairFiles?.map(file => file.path)).toEqual(["scripts/repair-2026-10-08/campaign-next.ts", "scripts/repair-2026-10-08/campaign-contract.ts", "scripts/repair-2026-10-08/paid-campaign-lock.ts", "scripts/repair-2026-10-08/chemiq-nextwave-contract.ts", "scripts/repair-2026-10-08/campaign-workers.ts", "scripts/repair-2026-10-08/freeze_source.py"]);
  const values = new Map<string, string>();
  for (const path of ["app/src/main.ts", "test/_lib.ts", "examples/benchmark/gpqa/stand.py", "examples/benchmark/_lib/gradelib.py"]) { snapshot.files.push({ path, sha256: sha("frozen source") }); values.set(join("/fixture-root", path), "frozen source"); }
  for (const file of snapshot.repairFiles!) values.set(join("/fixture-root", file.path), "frozen source");
  const validatorBody = source.slice(source.indexOf("const graderFiles ="), source.indexOf("\nconst plan:"));
  const validator = new Function("selected", "source", "sha", "readFileSync", "join", "root", transpiler.transformSync(validatorBody) + "\nreturn validateSource;")(["gpqa"], snapshot, sha, (path: string) => values.get(path), join, "/fixture-root");
  expect(() => validator()).not.toThrow();
  values.set(join("/fixture-root", "examples/benchmark/gpqa/stand.py"), "changed grader");
  expect(() => validator()).toThrow("Frozen execution source changed: examples/benchmark/gpqa/stand.py");
});

test("the actual next-entry finishing flow validates source before and after post-hoc scoring", async () => {
  const finishBody = source.slice(source.indexOf("let completed = false;"), source.indexOf("\nprocess.exitCode ="));
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const finish = new AsyncFunction("concurrency", "worker", "validateSource", "records", "gradeFixedCandidate", "objectiveFor", "output", "join", "readFileSync", "save", "fatal", "campaignComplete", "plan", "ledger", "summary", "console", "engines", "proxy", "spent", "cap", "paidLock", "chemiqProvenance", transpiler.transformSync(finishBody) + "\nreturn { completed, fatal };");
  for (const failAfterScore of [false, true]) {
    const sequence: string[] = [], statuses: boolean[] = [];
    let validations = 0;
    const record = { index: 0, benchmark: "gpqa", taskId: "fixture", answer: "fixed answer", candidateHow: "submitted", candidateSha256: sha("fixed answer"), generationClassification: { valid: true } };
    const work = finish(2, async () => { sequence.push("generation"); }, () => { sequence.push("validate"); if (++validations === 2 && failAfterScore) throw new Error("FixtureSourceChangedAfterScoring"); }, [record], async () => { sequence.push("grade"); return { valid: true, passed: true, outcome: "passed" }; }, () => ({}), "/private-fixture", join, () => "{}", () => {}, undefined, campaignComplete, [{}], () => {}, (completed: boolean) => { statuses.push(completed); }, { log() {} }, [{ async stop() { sequence.push("stop"); } }], { stop() { sequence.push("proxy-stop"); } }, 0, 15, { release() { sequence.push("lock-release"); } });
    if (failAfterScore) { await expect(work).rejects.toThrow("FixtureSourceChangedAfterScoring"); expect(statuses).toEqual([false]); }
    else { expect(await work).toMatchObject({ completed: true }); expect(statuses).toEqual([true]); }
    expect(sequence).toEqual(["generation", "generation", "validate", "grade", "validate", "stop", "proxy-stop", "lock-release"]);
  }
});
