/** The same durable model hooks are used by the paid entry and F-only in-memory transport controls. */
import { join } from 'node:path';
import { actualPin, type Pin } from './paid-resource-proof-v2.ts';
import { createCampaignJournal } from './campaign-journal.ts';
import { type BenchmarkCash, type BenchmarkCashTicket as CashTicket } from './benchmark-usd-cash.ts';
import type { BenchmarkProvider } from './benchmark-provider.ts';
import { ScientificJournalProxy } from './chemiq-f-provider-proxy-v3.ts';
import { ChemiqRouteSeal } from './chemiq-f-journal-contract-v3.ts';
import type { BenchmarkInference } from './benchmark-inference.ts';

export function createChemiqModelWitness(options: {
  inference?: BenchmarkInference; provider?: BenchmarkProvider;
  runId: string; routes: Set<string>; failureDirectory: string; journal: ReturnType<typeof createCampaignJournal>;
  cash: BenchmarkCash; seal: ChemiqRouteSeal; beforeAdmission(): void;
  onFinancialStop(reason: string): void; transport(raw: string): Promise<{ httpStatus: number; rawResponse: string }>;
}) {
  const tickets = new Map<number, CashTicket>(); let proxy: ScientificJournalProxy;
  proxy = new ScientificJournalProxy(options.journal, { inference: options.inference, provider: options.provider, routes: options.routes, failureDirectory: options.failureDirectory,
    beforeAdmission: options.beforeAdmission,
    beforeForward(admitted, startPrefix, raw, route) {
      const admission = options.cash.beforeForward({ id: options.runId + '/' + admitted.requestSeq, route, rawRequest: Buffer.from(raw), capturedRequest: actualPin(admitted.requestFile), journal: { admitted, startPrefix } });
      tickets.set(admitted.requestSeq, admission.ticket);
      if (!admission.admitted) { options.onFinancialStop(admission.reason!); throw Error('Cash admission denied:' + admission.reason); }
      // The route is checked after the durable ticket too, so queued work cannot pass a late seal.
      options.seal.check(route);
    },
    afterDurableFinish(receipt) {
      const status = options.cash.finish(tickets.get(receipt.requestSeq)!, { kind: 'journal-finish', journalRef: receipt.journalRef });
      if (status.poisoned) proxy.stop('cash:' + status.poisonReason);
    },
    afterFailedJournalCapture(request, _finish, evidence) {
      const seq = request?.requestSeq, ticket = seq === undefined ? undefined : tickets.get(seq);
      if (!ticket) {
        // This branch has not entered journal.admit. Other flights retain their real tickets.
        if (!request && evidence.requestSeq === undefined && evidence.stage === 'before_admission_guard' &&
            evidence.providerAttempted === false && evidence.confirmedNoForward === true &&
            !(evidence.journalSnapshot as any).error && !evidence.evidenceWriteError) return;
        options.cash.poison('unacknowledged_admission'); return;
      }
      if (evidence.journalRef) options.cash.finish(ticket, { kind: 'journal-finish', journalRef: evidence.journalRef as never });
      else {
        const files = evidence.files as Pin[];
        options.cash.finish(ticket, { kind: 'failed-capture', requestSeq: seq!, evidence: { files, responsePin: files.find(p => p.path.endsWith('response.json.gz')),
          rawResponseSha256: evidence.rawResponseSha256 as string, usage: evidence.usage, httpStatus: evidence.httpStatus as number, providerAttempted: evidence.providerAttempted as boolean,
          originalPrefix: (evidence.journalSnapshot as any).durablePrefix, reason: 'source_or_cash_capture_failure' } });
      }
    }, transport: options.transport,
  });
  return proxy;
}
