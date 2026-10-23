import { expect, test } from 'bun:test';
import { randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, jsonPin } from '../scripts/repair-2026-10-08/paid-resource-proof-v2.ts';
import { verifyCashClosure } from '../scripts/repair-2026-10-08/cny-cash-shadow-v2.ts';
import { fixedSkbArtifactSchedule, loadSkbArtifactSelection } from '../scripts/repair-2026-10-08/skb-artifact-journal-contract-v2.ts';
import { createSkbArtifactFeeQueue } from '../scripts/repair-2026-10-08/skb-artifact-journal-core-v2.ts';
import { SKB_ARTIFACT_RUNTIME_SOURCE_NAMES } from '../scripts/repair-2026-10-08/skb-artifact-journal-campaign-v2.ts';
import type { SkbStorageDescriptor } from '../scripts/repair-2026-10-08/skb-artifact-storage-v2.ts';

const root = resolve(import.meta.dir, '..');
const area = join(root, 'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/core-controls', randomBytes(12).toString('hex'));
mkdirSync(area, { recursive: true });
const runId = 'repair-2026-10-09T08-30-00-000Z';
const selected = loadSkbArtifactSelection();
const schedule = fixedSkbArtifactSchedule(runId, selected.tasks);
const raw = JSON.stringify({ model: 'deepseek-flash', temperature: 0, seed: 42, reasoning_effort: 'none', max_tokens: 8192,
  messages: [{ role: 'user', content: 'Synthetic identical-payload concurrency control; no network or model.' }] });

function makeQueue(name: string, transport: (raw: string, route: string) => Promise<{ httpStatus: number; rawResponse: string }>) {
  const directory = join(area, name);
  mkdirSync(directory);
  const directories = Object.fromEntries(['journal', 'taskmeta', 'cash', 'raw'].map(key => {
    const path = join(directory, key); mkdirSync(path); return [key, path];
  }));
  const pricePath = join(directory, 'prices.json');
  writeFileSync(pricePath, JSON.stringify({ protocol: 'deepseek-cny-pricing-source-snapshot-v1', observedAtUtc: new Date().toISOString(),
    currency: 'CNY', model: 'deepseek-flash', modelCalls: 0, officialSource: 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
    peak: { uncachedInput: 2, cachedInput: .04, output: 8 }, offPeak: { uncachedInput: 1, cachedInput: .02, output: 4 } }) + '\n', { flag: 'wx' });
  let reservations = 0;
  const queue = createSkbArtifactFeeQueue({ runId, providerKind: 'local-mock', capUsd: 100, priorCostUpperBoundUsd: 0,
    prices: actualPin(pricePath), storage: { directories } as SkbStorageDescriptor,
    sourcePins: [actualPin(join(root, 'scripts/repair-2026-10-08/skb-artifact-journal-core-v2.ts'))], schedule,
    beforeProducerAdmission(bytes) { expect(bytes).toBe(288 * 1024**2); reservations++; }, transport });
  return { queue, directory, reservations: () => reservations };
}

function reply(route: string) {
  return { httpStatus: 200, rawResponse: JSON.stringify({ id: route, model: 'deepseek-v4-flash',
    choices: [{ finish_reason: 'stop', message: { role: 'assistant', content: 'synthetic candidate' } }],
    usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } }) };
}

test('same raw request on concurrent task routes preserves transport context and the actual receipt partition', async () => {
  const forwarded: string[] = [];
  const { queue, reservations } = makeQueue('identical-raw', async (body, route) => {
    expect(body).toBe(raw); forwarded.push(route);
    await Bun.sleep(route === schedule[0]!.route ? 12 : 2);
    return reply(route);
  });
  try {
    const responses = await Promise.all([queue.handle(schedule[0]!.route, raw), queue.handle(schedule[1]!.route, raw)]);
    expect(responses.map(r => JSON.parse(r.rawResponse).id)).toEqual([schedule[0]!.route, schedule[1]!.route]);
    expect(forwarded).toEqual([schedule[0]!.route, schedule[1]!.route]);
    const first = queue.taskReceipts(schedule[0]!.route), second = queue.taskReceipts(schedule[1]!.route);
    expect(first.map(r => [r.route, r.requestSeq])).toEqual([[schedule[0]!.route, 0]]);
    expect(second.map(r => [r.route, r.requestSeq])).toEqual([[schedule[1]!.route, 1]]);
    expect(queue.taskReceipts(schedule[0]!.route)).toEqual(first);
    expect(queue.taskReceipts(schedule[2]!.route)).toEqual([]);
    expect('record' in queue).toBe(false);
    const close = await queue.exportClosedAccounting();
    expect(close.localMockRequests).toBe(2); expect(close.realProviderRequests).toBe(0);
    const ledger = jsonPin(close.ledgerPin);
    expect(ledger.calls.map((c: any) => [c.route, c.requestFile])).toEqual([[first[0]!.route, first[0]!.requestFile], [second[0]!.route, second[0]!.requestFile]]);
    const cash = verifyCashClosure(close.cashPin);
    expect(cash.proof.releasePermitted).toBe(true); expect(cash.states.size).toBe(2);
    expect(reservations()).toBeGreaterThan(2);
    await expect(queue.exportClosedAccounting()).rejects.toThrow('skb_export_once');
  } finally { if (!queue.state().closed) await queue.retainFailure('control_interrupted'); }
});

test('sealing refuses new calls and receipt access waits for the actual admitted transport to finish', async () => {
  let release!: () => void;
  const { queue } = makeQueue('seal-drain', async (_body, route) => {
    await new Promise<void>(done => { release = done; }); return reply(route);
  });
  try {
    const work = queue.handle(schedule[0]!.route, raw);
    while (!release) await Bun.sleep(1);
    expect(() => queue.taskReceipts(schedule[0]!.route)).toThrow('Task transport has not drained');
    queue.sealRoute(schedule[0]!.route);
    await expect(queue.handle(schedule[0]!.route, raw)).rejects.toThrow('skb_delivered_or_closed_model_route');
    let drained = false;
    const drain = queue.drain().then(() => { drained = true; });
    await Bun.sleep(4); expect(drained).toBe(false);
    release(); await work; await drain;
    expect(queue.taskReceipts(schedule[0]!.route)).toHaveLength(1);
    const close = await queue.exportClosedAccounting(); expect(close.localMockRequests).toBe(1);
    await expect(queue.handle(schedule[1]!.route, raw)).rejects.toThrow('skb_delivered_or_closed_model_route');
  } finally { release?.(); if (!queue.state().closed) await queue.retainFailure('control_interrupted'); }
});

test('new runtime inventory includes the storage seam and both actual backend producers', () => {
  expect(SKB_ARTIFACT_RUNTIME_SOURCE_NAMES).toContain('skb-artifact-storage-v2.ts');
  expect(SKB_ARTIFACT_RUNTIME_SOURCE_NAMES).toContain('skb_artifact_transport_v2.py');
  expect(SKB_ARTIFACT_RUNTIME_SOURCE_NAMES).toContain('skb_artifact_solver_plan_v2.py');
  expect(SKB_ARTIFACT_RUNTIME_SOURCE_NAMES).toContain('skb_artifact_ram_executor_v2.py');
  expect(new Set(SKB_ARTIFACT_RUNTIME_SOURCE_NAMES).size).toBe(SKB_ARTIFACT_RUNTIME_SOURCE_NAMES.length);
});
