import { expect, test } from "bun:test";
import { randomUUID } from "node:crypto";
import { closeSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createCampaignJournal, inspectCampaignJournal } from "../scripts/repair-2026-10-08/campaign-journal.ts";
import { ScientificJournalProxy } from "../scripts/repair-2026-10-08/scientific-journal-proxy.ts";
import { fixedScientificPlan } from "../scripts/repair-2026-10-08/scientific-journal-plan.ts";
const root = resolve(import.meta.dir, "..");
const out = join(root, ".scratch/scientific-journal-fixture-" + randomUUID());
mkdirSync(out, { recursive: true });
const campaign = "repair-2026-10-08T00-00-00-000Z";
const raw = JSON.stringify({ model: "deepseek-flash", temperature: 0, seed: 42, reasoning_effort: "none", max_tokens: 8192, messages: [{ role: "user", content: "Public synthetic zero-paid fixture" }] });
const response = (id: number) => ({ httpStatus: 200, rawResponse: JSON.stringify({ id: `local-fixture-${id}`, model: "local-fixture", choices: [{ message: { role: "assistant", content: "synthetic candidate" } }], usage: { prompt_tokens: 10, completion_tokens: 2 } }) });

test("prospective full1220 and ChemIQ32/1632 keep fixed complete denominators and metadata-only coverage", () => {
  const full = fixedScientificPlan(root, campaign, "full", ["chembench", "aime", "cmt"]);
  expect(full.tasks).toHaveLength(1220);
  expect(full.taskScheduleSha256).toBe("1ae6590140a51e9c48c656e92e482dd684843f8ae0e1dfc4e8f8ebad0e738bf8");
  expect(full.tasks.filter(t => t.arm === "U")).toHaveLength(610);
  expect(full.tasks.filter(t => t.benchmark === "cmt").every(t => t.seconds === 1800)).toBe(true);
  expect(full.tasks.filter(t => t.benchmark !== "cmt").every(t => t.seconds === 600)).toBe(true);
  const calibration = fixedScientificPlan(root, campaign, "chemiq-calibration", ["chemiq"]);
  expect(calibration.tasks).toHaveLength(32);
  expect(calibration.calibration?.categories).toHaveLength(8);
  expect(calibration.calibration?.methods).toHaveLength(5);
  expect(calibration.calibration?.positiveReferenceControlsMissing).toBe(34);
  expect(calibration.tasks.every(t => !["answer", "meta_data", "smiles", "verification_method"].some(k => k in t.row))).toBe(true);
  expect(fixedScientificPlan(root, campaign, "full", ["chemiq"]).tasks).toHaveLength(1632);
  writeFileSync(join(out, "prospective-plans.json"), JSON.stringify({ externalModelCalls: 0, full: full.taskSchedule, calibration: calibration.calibration, calibrationSchedule: calibration.taskSchedule }, null, 2));
});

test("four real-file workers drain out-of-order responses and preserve one legacy export and call offsets", async () => {
  const directory = join(out, "four-workers"), journal = createCampaignJournal({ directory, campaign, capUsd: 1, priorCampaignCostUpperBoundUsd: .1 });
  const releases: (() => void)[] = [];
  let forwarded = 0;
  const proxy = new ScientificJournalProxy(journal, { routes: new Set(["w0", "w1", "w2", "w3", "queued"]), failureDirectory: join(out, "failure-four"), transport: async () => {
    const id = forwarded++; await new Promise<void>(resolve => releases[id] = resolve); return response(id);
  } });
  try {
    const work = [0, 1, 2, 3].map(i => proxy.handle(`w${i}`, raw));
    while (forwarded < 4) await Bun.sleep(1);
    expect(journal.snapshot().active).toHaveLength(4);
    const queued = proxy.handle("queued", raw);
    await Bun.sleep(20); expect(forwarded).toBe(4);
    proxy.stop("generation_finished");
    let closed = false; const drain = proxy.drain().then(() => closed = true);
    await Bun.sleep(5); expect(closed).toBe(false);
    for (const i of [3, 1, 2, 0]) { releases[i](); await Bun.sleep(2); }
    const outcomes = await Promise.allSettled([...work, queued]); await drain;
    expect(outcomes.every(value => value.status === "fulfilled")).toBe(true);
    expect(forwarded).toBe(4); expect(proxy.state().activeHandlers).toBe(0);
    expect(journal.snapshot().finishedRequestCount).toBe(4);
    expect(journal.snapshot().reservedUpperBoundUsd).toBe(0);
    const exported = journal.exportLegacyLedger();
    expect(exported.accountingClosed).toBe(true);
    expect(JSON.parse(readFileSync(exported.path, "utf8")).calls).toHaveLength(4);
    for (let i = 0; i < 4; i++) {
      const task = proxy.takeTaskReceipts(`w${i}`); expect(task).toHaveLength(1);
      expect(task[0].journalRef.finishEnd).toBeGreaterThan(task[0].journalRef.finishOffset);
      expect([...journal.closedCalls(`w${i}`)]).toHaveLength(1);
    }
    writeFileSync(join(directory, "fixture-result.json"), JSON.stringify({ externalModelCalls: 0, fakeResponses: 4, exported, state: proxy.state() }, null, 2));
  } finally { journal.close(); }
});

test("finish checkpoint poison keeps late real responses in independent raw failure receipts without pretending pending zero", async () => {
  let fired = false;
  const directory = join(out, "poison-late"), journal = createCampaignJournal({ directory, campaign, capUsd: 1, priorCampaignCostUpperBoundUsd: .1 }, { before: op => {
    if (!fired && op.kind === "fsync" && op.stage === "checkpoint:finish:0") { fired = true; closeSync(op.fd!); }
  } });
  const releases: (() => void)[] = []; let forwarded = 0;
  const proxy = new ScientificJournalProxy(journal, { routes: new Set(["a", "b", "c", "d", "later"]), failureDirectory: join(directory, "failure-receipts"), transport: async () => {
    const id = forwarded++; await new Promise<void>(resolve => releases[id] = resolve); return response(id);
  } });
  try {
    const work = ["a", "b", "c", "d"].map(route => proxy.handle(route, raw));
    while (forwarded < 4) await Bun.sleep(1);
    releases[0](); await work[0];
    expect(journal.snapshot().finishedRequestCount).toBe(1);
    expect(journal.snapshot().active).toHaveLength(3);
    const later = await proxy.handle("later", raw); expect(later.httpStatus).toBe(503); expect(forwarded).toBe(4);
    for (let i = 1; i < 4; i++) releases[i]();
    await Promise.allSettled(work); await proxy.drain();
    expect(proxy.anomalies).toHaveLength(4);
    expect(proxy.anomalies.every(item => (item.files as unknown[]).length === 2 && item.usage)).toBe(true);
    expect(journal.snapshot().active).toHaveLength(3);
    expect(inspectCampaignJournal(directory).accountingClosed).toBe(false);
    expect(() => journal.exportLegacyLedger()).toThrow();
    writeFileSync(join(directory, "fixture-result.json"), JSON.stringify({ externalModelCalls: 0, actualSyntheticReturns: 4, state: proxy.state(), anomalies: proxy.anomalies, eligible: false }, null, 2));
  } finally { journal.close(); }
});

test("funding rejection before provider forward is explicit zero fee and funding failure after finish cannot certify", async () => {
  for (const stage of ["before", "after"]) {
    const directory = join(out, "funding-" + stage), journal = createCampaignJournal({ directory, campaign, capUsd: 1, priorCampaignCostUpperBoundUsd: .1 });
    let forwarded = 0;
    const proxy = new ScientificJournalProxy(journal, { routes: new Set(["only"]), failureDirectory: join(directory, "failures"), transport: async () => response(forwarded++),
      beforeForward: () => { if (stage === "before") throw new Error("synthetic funding fsync failure"); },
      afterDurableFinish: () => { if (stage === "after") throw new Error("synthetic funding finish failure"); } });
    try {
      await proxy.handle("only", raw); proxy.stop("stop"); await proxy.drain();
      expect(forwarded).toBe(stage === "before" ? 0 : 1);
      if (stage === "before") expect(journal.snapshot().recordedUsageUpperBoundUsd).toBe(0);
      else { expect(journal.snapshot().recordedUsageUpperBoundUsd).toBeGreaterThan(0); expect(proxy.anomalies).toHaveLength(1); }
      expect(proxy.state().stopReason).toBeTruthy();
    } finally { journal.close(); }
  }
});
