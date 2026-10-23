/** Offline journal/cash replay regression. No broker, owner, provider or model calls. */
import {strict as assert} from 'node:assert';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {createCampaignJournal,inspectCampaignJournal} from '../shared/digitalocean-journal.ts';
import {actualPin,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from '../shared/digitalocean-usd-cash.ts';
import {BENCHMARK_PROVIDER} from '../shared/digitalocean-provider.ts';
import {createRecordingCash,permitsRecordedUnknown} from './recording_digitalocean_cash.ts';

const root=resolve(import.meta.dir,'../../../..'),base=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
const configPath=process.argv[2];assert(configPath,'Pass a read-only existing cash-config path to reuse authentic public price evidence');
const sourceConfig=JSON.parse(readFileSync(resolve(configPath),'utf8')),prices=sourceConfig.pricesPin;verifyPin(prices);
const home=join(base,'digitalocean-recording-cash-controls',crypto.randomUUID());mkdirSync(home,{recursive:true});
const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-')+'-13',directory=join(home,'journal');
const journal=createCampaignJournal({directory,campaign:runId,capUsd:1,priorCampaignCostUpperBoundUsd:0,outputDirectory:home,provider:BENCHMARK_PROVIDER});
const cash=createRecordingCash({directory:join(home,'cash'),runId,providerKind:'local-mock',prices,
  journal:{directory,configPin:actualPin(join(directory,'journal-config.json')),sourcePin:actualPin(join(import.meta.dir,'../shared/digitalocean-journal.ts'))}},BENCHMARK_PROVIDER);
const sourcePins=['recording_usd_cash.ts','verify_recording_cash.ts'].map(n=>actualPin(join(import.meta.dir,n)));
const result:any={protocol:'skillsbench-recording-cash-offline-controls-v1',verified:false,scope:'Offline synthetic transport receipts using real journal/cash persistence and independent original replay; not a paid campaign or broker lifecycle validation',modelRequests:0,realProviderCalls:0,scoreCertificate:false,sourcePins,pricesPin:prices,cases:[]};
const rawRequest=JSON.stringify({model:BENCHMARK_PROVIDER.model,provider:BENCHMARK_PROVIDER.routing,messages:[{role:'user',content:'offline synthetic cash test'}],max_tokens:16384,temperature:0,reasoning:{effort:'high'}});
function admit(route:string){const start=journal.admit({route,rawRequest});assert(start.admitted);return {start,prefix:journal.snapshot().durablePrefix};}
function forward(a:ReturnType<typeof admit>){return cash.beforeForward({id:runId+'/'+a.start.requestSeq,route:a.start.requestSeq===0?'offline-first':'offline-second',rawRequest:Buffer.from(rawRequest),capturedRequest:actualPin(a.start.requestFile),journal:{admitted:a.start,startPrefix:a.prefix}});}
function finishCash(ticket:any){const inspection=inspectCampaignJournal(directory),offset=inspection.offsets.get(ticket.requestSeq);assert(offset);cash.finish(ticket,{kind:'journal-finish',journalRef:{finishOffset:offset.offset,finishEnd:offset.offset+offset.bytes,finishLineSha256:offset.sha256}});}
try{
  // Both starts are durable before the first response, as in a concurrent queue.
  const first=admit('offline-first'),second=admit('offline-second');const one=forward(first);assert(one.admitted);
  journal.finish({requestSeq:first.start.requestSeq,providerAttempted:true,httpStatus:200,rawResponse:JSON.stringify({id:'offline-synthetic-missing-cost',model:BENCHMARK_PROVIDER.model,provider:BENCHMARK_PROVIDER.providerName,choices:[{index:0,message:{role:'assistant',content:'offline'},finish_reason:'stop'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}})});
  finishCash(one.ticket);assert.equal(cash.snapshot().newUnknownCount,1);assert(cash.snapshot().poisoned);assert(permitsRecordedUnknown(cash.snapshot()));result.cases.push('unknown_receipt_and_poison_retained');
  const two=forward(second);assert(two.admitted);result.cases.push('durable_second_request_cash_ticket_allowed_after_unknown');
  journal.finish({requestSeq:second.start.requestSeq,providerAttempted:false,confirmedNoForward:true});finishCash(two.ticket);
  const cashPin=cash.close();journal.close();const original=verifyBenchmarkCashClosure(cashPin);
  assert.equal(original.proof.snapshot.newUnknownCount,1);assert.equal(original.proof.releasePermitted,false);assert.equal(original.proof.snapshot.pendingCount,0);
  result.cases.push('independent_original_close_replay_preserves_unknown_and_release_false');
  for(const reason of ['usd_owner_lost','usd_envelope_exhausted','cash_finish_validation_failed'])assert.equal(permitsRecordedUnknown({poisoned:true,poisonReason:reason}),false);
  result.cases.push('nonfinancial_failures_block_continuation');for(const p of sourcePins)verifyPin(p);
  result.verified=true;result.cashPin=cashPin;result.journalPin=actualPin(join(directory,'api-events.jsonl'));result.localSnapshot=original.proof.snapshot;
}catch(error){result.failure={type:error instanceof Error?error.name:'Error',detail:String(error)};process.exitCode=1;}
finally{writeFileSync(join(home,'result.json'),JSON.stringify(result,null,2)+'\n');const pin=actualPin(join(home,'result.json'));writeFileSync(join(base,'digitalocean-recording-cash-controls/latest.json'),JSON.stringify({resultPin:pin})+'\n');console.log(JSON.stringify({resultPin:pin,verified:result.verified,cases:result.cases,modelRequests:0,failure:result.failure}));}
