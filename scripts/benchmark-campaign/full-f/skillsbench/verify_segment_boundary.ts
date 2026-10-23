/** Offline actual SDK persistence/replay; no shared admission or provider calls. */
import {strict as assert} from 'node:assert';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,verifyPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import {createCampaignJournal,inspectCampaignJournal} from '../../../benchmark-repair/campaign-journal.ts';
import {ScientificJournalProxy} from '../../../benchmark-repair/scientific-journal-proxy.ts';
import {BENCHMARK_PROVIDER} from '../../../benchmark-repair/benchmark-provider.ts';
import {BENCHMARK_INFERENCE} from '../../../benchmark-repair/benchmark-inference.ts';
import {verifyBenchmarkCashClosure} from '../../../benchmark-repair/benchmark-usd-cash.ts';
import {createRecordingCash,permitsRecordedUnknown} from './recording_usd_cash.ts';
import {taskSegmentBoundary} from './segment_boundary.ts';
const root=resolve(import.meta.dir,'../../../..'),base=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench'),home=join(base,'segment-boundary-controls',crypto.randomUUID());mkdirSync(home,{recursive:true});
assert(process.argv[2],'existing authentic public price config required');const prices=JSON.parse(readFileSync(resolve(process.argv[2]),'utf8')).pricesPin;verifyPin(prices);
const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-')+'-13',directory=join(home,'journal'),tickets=new Map<number,any>();
const journal=createCampaignJournal({directory,campaign:runId,capUsd:1,priorCampaignCostUpperBoundUsd:0,outputDirectory:home,provider:BENCHMARK_PROVIDER});
const cash=createRecordingCash({directory:join(home,'cash'),runId,providerKind:'local-mock',prices,journal:{directory,configPin:actualPin(join(directory,'journal-config.json')),sourcePin:actualPin(join(import.meta.dir,'../../../benchmark-repair/campaign-journal.ts'))}},BENCHMARK_PROVIDER);
let localMockCalls=0;const cases:string[]=[];
const proxy=new ScientificJournalProxy(journal,{inference:BENCHMARK_INFERENCE,provider:BENCHMARK_PROVIDER,routes:new Set(['offline-first','offline-next']),failureDirectory:join(home,'capture-errors'),
 beforeAdmission:()=>assert(permitsRecordedUnknown(cash.snapshot())),
 beforeForward:(start,prefix,raw,route)=>{const ticket=cash.beforeForward({id:runId+'/'+start.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(start.requestFile),journal:{admitted:start,startPrefix:prefix}});assert(ticket.admitted);tickets.set(start.requestSeq,ticket.ticket);},
 afterDurableFinish:receipt=>{cash.finish(tickets.get(receipt.requestSeq),{kind:'journal-finish',journalRef:receipt.journalRef});},
 transport:async()=>{localMockCalls++;return {httpStatus:200,rawResponse:JSON.stringify({id:'offline-synthetic-cost-missing',model:BENCHMARK_PROVIDER.model,provider:BENCHMARK_PROVIDER.providerName,choices:[{index:0,message:{role:'assistant',content:'offline'},finish_reason:'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}})};},
});
const proof:any={protocol:'skillsbench-segment-boundary-offline-controls-v1',verified:false,scope:'Real SDK with synthetic local transport and independent original journal/cash replay; not real paid lifecycle validation',modelRequests:0,realProviderCalls:0,scoreCertificate:false,cases,
 sourcePins:['segment_boundary.ts','verify_segment_boundary.ts','recording_usd_cash.ts'].map(n=>actualPin(join(import.meta.dir,n)))};
try{
 assert.equal(taskSegmentBoundary({provider:{},cash:{newUnknownCount:1,pendingCount:0}}).closeSegment,false);cases.push('unknown_alone_does_not_close_segment');
 const raw=JSON.stringify({model:BENCHMARK_PROVIDER.model,messages:[{role:'user',content:'offline synthetic boundary control'}],max_tokens:16384,temperature:0,reasoning_effort:'high',seed:42});
 await proxy.handle('offline-first',raw);await proxy.drain();assert.equal(proxy.takeTaskReceipts('offline-first').length,1);
 const boundary=taskSegmentBoundary({provider:proxy.state(),cash:cash.snapshot()});assert(boundary.closeSegment);assert.equal(boundary.action,'close_and_continue_unfinished');assert.equal(boundary.reason,'provider_fault');cases.push('original_proxy_stop_is_real_new_segment_boundary');
 // Simulate the runtime decision: the following task is left pending, without
 // executing its proxy handle or writing a zero-call terminal result.
 const pendingTaskIds=['offline-next'];assert.equal(journal.snapshot().acceptedRequestCount,1);assert.equal(localMockCalls,1);cases.push('next_task_not_admitted_or_marked_failed');
 proxy.stop('segment_closed');await proxy.drain();const cashPin=cash.close();journal.close();const closed=verifyBenchmarkCashClosure(cashPin),inspection=inspectCampaignJournal(directory);
 assert(inspection.valid&&inspection.accountingClosed);assert.equal(closed.proof.snapshot.newUnknownCount,1);assert.equal(closed.proof.releasePermitted,false);cases.push('closed_unknown_preserved_by_original_independent_replay');
 for(const p of proof.sourcePins)verifyPin(p);proof.verified=true;proof.cashPin=cashPin;proof.journalPin=actualPin(join(directory,'api-events.jsonl'));proof.pendingTaskIds=pendingTaskIds;proof.localMockCalls=localMockCalls;
}catch(error){proof.failure={detail:String(error)};process.exitCode=1;}
finally{writeFileSync(join(home,'result.json'),JSON.stringify(proof,null,2)+'\n');const pin=actualPin(join(home,'result.json'));writeFileSync(join(base,'segment-boundary-controls/latest.json'),JSON.stringify({resultPin:pin})+'\n');console.log(JSON.stringify({resultPin:pin,verified:proof.verified,cases,modelRequests:0,failure:proof.failure}));}
