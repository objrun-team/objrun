import { expect, spyOn, test } from 'bun:test';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { startFullFBroker } from './full-f-broker.ts';
import { acquireFullFAdmission } from './shared-admission.ts';
import { actualPin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { BENCHMARK_PROVIDER } from '../../../repair-2026-10-08/benchmark-provider.ts';
import { BENCHMARK_INFERENCE } from '../../../repair-2026-10-08/benchmark-inference.ts';
import { createCampaignJournal } from '../../../repair-2026-10-08/campaign-journal.ts';
import { createBenchmarkCash } from '../../../repair-2026-10-08/benchmark-usd-cash.ts';
import { ScientificJournalProxy } from '../../../repair-2026-10-08/scientific-journal-proxy.ts';

const root = resolve(import.meta.dir, '../../../..');
const save = (path: string, data: any) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(data) + '\n', { flag: 'wx' }); return actualPin(path); };
const raw = (id: number) => JSON.stringify({ model: BENCHMARK_PROVIDER.model, messages: [{ role: 'user', content: 'Local transport test ' + id }], max_tokens: 16384, temperature: 0, reasoning_effort: 'high' });
async function fixture(transport: (raw: string) => Promise<any>, maxInFlight = 4) {
  const runId = 'repair-' + Date.now() + '-' + Math.floor(Math.random() * 1e9);
  const output = join(root, '.scratch/full-f-transport-tests', runId);
  const lock = join(output, 'mock-only.lock.json');
  const prices = actualPin(join(root, 'docs/repair-2026-10-10/full-f-rerun/funding-observation/openrouter-prices.json'));
  const balance = actualPin(join(root, 'docs/repair-2026-10-10/full-f-rerun/funding-observation/openrouter-balance.json'));
  const broker = await startFullFBroker({ root, output, runId, port: 0, localMock: true, transport, maxInFlight,
    async leaseFactory(input) {
      const owned = { pid: process.pid, runId, ownerNonce: randomBytes(12).toString('hex'), family: 'synthetic-transport-only' };
      save(lock, owned); const proofPin = save(join(input.output, 'mock-parent.json'), { protocol: 'openrouter-usd-admission-v1', owned, capUsd: 100, currency: 'USD', localMock: true });
      return { owned, proofPin, path: lock, prices, balance, capUsd: 100,
        forkLane(id: string, laneOutput: string, capUsd: number) {
          return { runId: id, capUsd, owned: { ...owned, runId: id }, proofPin: save(join(laneOutput, 'openrouter-lane-admission.json'), { protocol: 'openrouter-usd-lane-admission-v1', runId: id, capUsd, currency: 'USD', parentAdmissionPin: proofPin, ownerNonce: owned.ownerNonce }),
            validateForwardSource() {}, registerCash() {}, registerOwnedProcess() {} };
        }, finishLightweight() { unlinkSync(lock); return save(join(input.output, 'mock-release.json'), { localMock: true }); } };
    } });
  const id = runId + '-11-1', laneOutput = join(root, 'docs/repair-2026-10-10/full-f-rerun/chembench/local-broker-tests', id);
  const admission = await acquireFullFAdmission({ root, output: laneOutput, runId: id, slug: 'chembench', sourcePins: [actualPin(import.meta.path)], connection: broker.connection });
  const journal = createCampaignJournal({ directory: join(laneOutput, 'journal'), campaign: id, capUsd: admission.capUsd, priorCampaignCostUpperBoundUsd: 0, outputDirectory: laneOutput, provider: BENCHMARK_PROVIDER });
  const cash = createBenchmarkCash({ directory: join(laneOutput, 'cash'), runId: id, providerKind: 'local-mock', prices: admission.prices, admission,
    journal: { directory: journal.directory, configPin: actualPin(join(journal.directory, 'journal-config.json')), sourcePin: actualPin(join(root, 'scripts/repair-2026-10-08/campaign-journal.ts')) } }, BENCHMARK_PROVIDER);
  const tickets = new Map<number, any>();
  const proxy = new ScientificJournalProxy(journal, { provider: BENCHMARK_PROVIDER, inference: BENCHMARK_INFERENCE, routes: new Set(['t']), failureDirectory: join(laneOutput, 'failures'), transport: admission.transport,
    beforeForward(start, prefix, request, route) { const result = cash.beforeForward({ id: id + '/' + start.requestSeq, route, rawRequest: Buffer.from(request), capturedRequest: actualPin(start.requestFile), journal: { admitted: start, startPrefix: prefix } }); tickets.set(start.requestSeq, result.ticket); if (!result.admitted) throw Error('cash_denied'); },
    afterDurableFinish(receipt) { cash.finish(tickets.get(receipt.requestSeq), { kind: 'journal-finish', journalRef: receipt.journalRef }); } });
  return { broker, admission, journal, cash, proxy, async close() { await proxy.drain(); journal.exportLegacyLedger(); await admission.finishLightweight({ cashPin: cash.close() }); journal.close(); await broker.stop(); } };
}
const successful = () => ({ httpStatus: 200, rawResponse: JSON.stringify({ id: 'synthetic-local-' + randomBytes(8).toString('hex'), provider: 'Relace', model: BENCHMARK_PROVIDER.model,
  choices: [{ index: 0, finish_reason: 'stop', message: { role: 'assistant', content: '42' } }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12, cost: 0 } }) });

test('queued non-streaming requests survive the HTTP client idle window and keep their actual cost', async () => {
  const fetch = globalThis.fetch;
  const shorterIdle = spyOn(globalThis, 'fetch').mockImplementation(((url: any, options: any) =>
    fetch(url, String(url).includes('/forward') ? { ...options, signal: AbortSignal.timeout(500) } : options)) as any);
  const f = await fixture(async () => { await Bun.sleep(1200); return successful(); });
  try { const response = await f.proxy.handle('t', raw(0)); expect(response.httpStatus).toBe(200); expect(f.cash.snapshot().newUnknownCount).toBe(0); await f.close(); }
  finally { shorterIdle.mockRestore(); await f.broker.server.stop(true); }
}, 10000);

test('a request rejected from the stopped broker queue is proven unforwarded, without a second unknown charge', async () => {
  const f = await fixture(async () => { await Bun.sleep(40); return { httpStatus: 500, rawResponse: JSON.stringify({ error: { message: 'Synthetic upstream ambiguity' } }) }; }, 1);
  try {
    await Promise.all([f.proxy.handle('t', raw(0)), f.proxy.handle('t', raw(1))]);
    const events = readFileSync(join(f.journal.directory, 'api-events.jsonl'), 'utf8').trimEnd().split('\n').map(line => JSON.parse(line));
    const queued = events.find(event => event.kind === 'finish' && event.requestSeq === 1).record;
    expect(queued.providerAttempted).toBe(false); expect(queued.confirmedNoForward).toBe(true); expect(queued.usdUpperBound).toBe(0);
    expect(f.cash.snapshot().newUnknownCount).toBe(1);
  } finally { await f.broker.server.stop(true); }
});
