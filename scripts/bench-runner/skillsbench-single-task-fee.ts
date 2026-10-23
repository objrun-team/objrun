/** One SkillsBench task on its caller-owned original shared resource/admission; no independent queue or owner. */
import {gatewayBudgetDecision} from '../repair-2026-10-10/full-f/novaeve_formal_v1/headless_budget_v7/gateway_budget_gate_v7.ts';
/** Full F journal/USD cash lifecycle. Provider communication uses shared broker. */
import { AsyncLocalStorage } from 'node:async_hooks';
import { mkdirSync,readFileSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin, demand, verifyPin, type Pin } from '../repair-2026-10-08/paid-resource-proof-v2.ts';
import { createCampaignJournal, inspectCampaignJournal } from '../repair-2026-10-10/full-f/shared/digitalocean-journal.ts';
import { ScientificJournalProxy, type TaskReceipt } from '../repair-2026-10-10/full-f/shared/digitalocean-proxy.ts';
import { createRecordingCash,permitsRecordedUnknown,type BenchmarkCashTicket } from '../repair-2026-10-10/full-f/skillsbench/recording_digitalocean_cash.ts';
import { BENCHMARK_PROVIDER } from '../repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
import { benchmarkProviderRequest, BENCHMARK_INFERENCE } from '../repair-2026-10-10/full-f/shared/digitalocean-inference.ts';
import type { SharedFullFAdmission } from '../repair-2026-10-10/full-f/shared/shared-admission.ts';
import { mandatorySubmission } from '../repair-2026-10-10/full-f/skillsbench/submission_retry.ts';
import { atomicStateJson } from '../repair-2026-10-10/full-f/shared/atomic-state.ts';

export function createSingleTaskFeeQueue(input:{runId:string;output:string;sourcePins:Pin[];taskId:string;schedule:{taskId:string;arm:string;route:string}[];admission:SharedFullFAdmission;freshMaximumNewSpendUsd:()=>Promise<number>;requireOwnedResource:()=>void}) {
  const policy=JSON.parse(readFileSync(join(input.admission.root,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8')).costPolicy;
  demand(policy?.mode==='record_and_continue'&&policy.feeReviewBlocksExecution===false,'record_and_continue_authorization_required');
  demand(input.schedule.length===1 && input.schedule[0].taskId===input.taskId && input.schedule.every(r=>r.arm==='F'),'single_task_f_route_required');
  const routes=new Set(input.schedule.map(r=>r.route));demand(routes.size===1,'duplicate_full_f_route');
  const context=new AsyncLocalStorage<string>(),sealed=new Set<string>(),tickets=new Map<number,BenchmarkCashTicket>(),receipts=new Map<string,TaskReceipt[]>();
  for(const route of routes)receipts.set(route,[]);
  const directory=join(input.output,'journal'),cashDirectory=join(input.output,'cash');
  mkdirSync(directory,{recursive:true});mkdirSync(cashDirectory,{recursive:true});mkdirSync(join(input.output,'failure-receipts'),{recursive:true});
  const sourceCheck=()=>{input.requireOwnedResource();input.admission.validateForwardSource();for(const pin of input.sourcePins)verifyPin(pin);};
  sourceCheck();
  const journal=createCampaignJournal({directory,campaign:input.runId,capUsd:input.admission.capUsd,priorCampaignCostUpperBoundUsd:0,outputDirectory:input.output,provider:BENCHMARK_PROVIDER});
  let cash:ReturnType<typeof createRecordingCash>;
  try {cash=createRecordingCash({directory:cashDirectory,runId:input.runId,providerKind:'real-provider',admission:input.admission,prices:input.admission.prices,
      journal:{directory,configPin:actualPin(join(directory,'journal-config.json')),sourcePin:actualPin(join(import.meta.dir,'../repair-2026-10-10/full-f/shared/digitalocean-journal.ts'))}},BENCHMARK_PROVIDER);}
  catch(error){journal.close();throw error;}
  const proxy=new ScientificJournalProxy(journal,{inference:BENCHMARK_INFERENCE,provider:BENCHMARK_PROVIDER,routes,failureDirectory:join(input.output,'failure-receipts'),
    beforeAdmission:()=>{sourceCheck();demand(permitsRecordedUnknown(cash.snapshot()),'skillsbench_usd_cash_nonfinancial_failure');},
    beforeForward:(start,prefix,raw,route)=>{
      const funding=cash.beforeForward({id:input.runId+'/'+start.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(start.requestFile),journal:{admitted:start,startPrefix:prefix}});
      tickets.set(start.requestSeq,funding.ticket);demand(funding.admitted,'skillsbench_shared_cash_envelope_exhausted');
    },
    afterDurableFinish:receipt=>{const ticket=tickets.get(receipt.requestSeq);demand(ticket,'skillsbench_cash_ticket_missing');cash.finish(ticket!,{kind:'journal-finish',journalRef:{...receipt.journalRef,callId:String(receipt.requestSeq)}});},
    afterFailedJournalCapture:(start,_finish,error:any)=>{
      if(!start)return;const ticket=tickets.get(start.requestSeq);if(!ticket)return;
      if(error.journalRef)cash.finish(ticket,{kind:'journal-finish',journalRef:{...error.journalRef,callId:String(start.requestSeq)}});
      else cash.finish(ticket,{kind:'failed-capture',requestSeq:start.requestSeq,evidence:{files:error.files,responsePin:error.files.find((p:Pin)=>p.path.endsWith('response.json.gz')),rawResponseSha256:error.rawResponseSha256,usage:error.usage,httpStatus:error.httpStatus,providerAttempted:error.providerAttempted,originalPrefix:error.journalSnapshot.durablePrefix,reason:error.error}});
    },
    transport:async raw=>{const route=context.getStore();demand(route&&routes.has(route),'skillsbench_broker_route_context_missing');return input.admission.transport(raw);},
  });
  let closed=false;const submissionRetries:any[]=[];
  function collect(route:string){demand(receipts.has(route),'unknown_full_f_receipt_route');for(const r of proxy.takeTaskReceipts(route)){demand(!receipts.get(route)!.some(old=>old.requestSeq===r.requestSeq),'duplicate_receipt');receipts.get(route)!.push(r);}return receipts.get(route)!.slice().sort((a,b)=>a.requestSeq-b.requestSeq);}
  return {proxy,cash,journal,
    async handle(route:string,raw:string){demand(routes.has(route)&&!sealed.has(route)&&!closed,'skillsbench_full_f_route_closed');return context.run(route,()=>mandatorySubmission(raw,async next=>{const maximum=await input.freshMaximumNewSpendUsd();demand(Number.isFinite(maximum)&&maximum>0,'single_task_fresh_budget_exhausted');const wire=JSON.stringify(benchmarkProviderRequest(JSON.parse(next),BENCHMARK_INFERENCE,BENCHMARK_PROVIDER));demand(gatewayBudgetDecision(journal,wire,maximum).result.admitted,'single_task_original_budget_envelope_exhausted');return proxy.handle(route,next)},BENCHMARK_INFERENCE.retryTimes,e=>{submissionRetries.push({route,...e});atomicStateJson(join(input.output,'submission-retries.json'),submissionRetries);}));},
    sealRoute(route:string){demand(routes.has(route),'unknown_full_f_route');sealed.add(route);},taskReceipts:collect,
    state(){return {closed,provider:proxy.state(),cash:cash.snapshot()};},
    async close(){
      demand(!closed,'skillsbench_fee_close_once');proxy.stop('all_generation_closed');await proxy.drain();sourceCheck();
      const inspection=inspectCampaignJournal(directory);
      demand(inspection.valid&&inspection.accountingClosed&&proxy.anomalies.length===0,'skillsbench_journal_or_cash_not_closed');
      for(const route of routes)collect(route);
      const seq=[...receipts.values()].flat().map(r=>r.requestSeq).sort((a,b)=>a-b);
      demand(seq.length===inspection.snapshot!.acceptedRequestCount&&seq.every((n,i)=>n===i),'skillsbench_full_f_request_partition');
      journal.exportLegacyLedger();const cashPin=cash.close();journal.close();closed=true;
      // The caller closes this exact lane once, after proving native custody.
      const ack={closed:false,callerMustCloseLane:true};
      return {cashPin,brokerClose:ack,journalConfigPin:actualPin(join(directory,'journal-config.json')),journalFilePin:actualPin(join(directory,'api-events.jsonl')),ledgerPin:actualPin(join(input.output,'api-ledger.json')),scoreCertificate:false};
    },
    async retainFailure(reason:string){
      demand(!closed,'skillsbench_fee_close_once');proxy.stop(reason);cash.poison(reason);await proxy.drain();const cashPin=cash.close();journal.close();closed=true;
      // Broker independently verifies this cash close. Unknown reservations are
      // preserved and may prevent parent owner release; they are never zeroed.
      const brokerClose={closed:false,callerMustCloseLane:true};
      return {cashPin,brokerClose,journal:journal.snapshot(),cash:cash.snapshot(),anomalies:proxy.anomalies,scoreCertificate:false};
    },
  };
}
