/** Bounded SDK -> current Bench proxy -> USD journal/cash submission smoke check. */
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { registerVendors, type Unit } from '../../app/src/llm/index.ts';
import { BENCHMARK_INFERENCE } from '../benchmark-repair/benchmark-inference.ts';
import { BENCHMARK_PROVIDER, benchmarkFetch, benchmarkProviderKey } from '../benchmark-repair/benchmark-provider.ts';
import { acquireOpenRouterAdmission } from '../benchmark-repair/openrouter-paid-admission.ts';
import { createBenchmarkCash, verifyBenchmarkCashClosure, type BenchmarkCashTicket } from '../benchmark-repair/benchmark-usd-cash.ts';
import { createCampaignJournal, inspectCampaignJournal } from '../benchmark-repair/campaign-journal.ts';
import { ScientificJournalProxy, captureProviderResponse } from '../benchmark-repair/scientific-journal-proxy.ts';
import { actualPin, demand, jsonPin } from '../benchmark-repair/paid-resource-proof-v2.ts';

const ROOT=resolve(import.meta.dir,'../..'),live=process.argv[2]==='--live';
demand(live||process.argv[2]==='--local','use_explicit_local_or_live');
const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-');
const output=join(ROOT,'docs/repair-2026-10-10/openrouter-system-submit',runId);mkdirSync(output,{recursive:true});
const sources=[import.meta.path,'app/src/llm/index.ts','app/package.json','app/bun.lock',...['benchmark-provider.ts','benchmark-inference.ts','benchmark-usd-cash.ts','openrouter-paid-admission.ts','campaign-journal.ts','campaign-contract.ts','scientific-journal-proxy.ts','paid-resource-proof-v2.ts'].map(name=>'scripts/benchmark-repair/'+name)].map(path=>actualPin(resolve(ROOT,path)));
const lease=live?await acquireOpenRouterAdmission({root:ROOT,output,runId,family:'openrouter-submit-smoke-v1',entry:import.meta.path,sourcePins:sources,capUsd:0.05}):undefined;
let prices=lease?.prices;
if(!prices){
  const profile=join(output,'synthetic-local-prices.json');
  writeFileSync(profile,JSON.stringify({protocol:'openrouter-usd-pricing-source-snapshot-v1',model:BENCHMARK_PROVIDER.model,currency:'USD',providerSlug:BENCHMARK_PROVIDER.providerSlug,
    reservationRates:BENCHMARK_PROVIDER.peakRates,actualOfficialGET:true,modelCalls:0,observedAtUtc:new Date().toISOString(),
    originalResponsePin:actualPin(join(ROOT,'test/fixtures/provider-check/openrouter-deepseek-check/3d75fcaf756e44918dab4e7f5ea061ba/v41-endpoints.json')),
    note:'Synthetic local control profile using a stored actual public endpoint response; no fresh tariff GET was made.'}));prices=actualPin(profile);
}
const key=live?benchmarkProviderKey(ROOT):undefined,directory=join(output,'journal');
const journal=createCampaignJournal({directory,campaign:runId,capUsd:lease?.capUsd??0.05,priorCampaignCostUpperBoundUsd:0,outputDirectory:output,provider:BENCHMARK_PROVIDER});
const cash=createBenchmarkCash({directory:join(output,'cash'),runId,providerKind:live?'real-provider':'local-mock',prices,admission:lease,
  journal:{directory,configPin:actualPin(join(directory,'journal-config.json')),sourcePin:actualPin(join(ROOT,'scripts/benchmark-repair/campaign-journal.ts'))}},BENCHMARK_PROVIDER);
const tickets=new Map<number,BenchmarkCashTicket>();let attempts=0,successfulGenerations=0;const requests:any[]=[];
const proxy=new ScientificJournalProxy(journal,{provider:BENCHMARK_PROVIDER,inference:BENCHMARK_INFERENCE,routes:new Set(['submit-smoke']),failureDirectory:join(output,'failures'),
  beforeForward(admitted,startPrefix,raw,route){const funding=cash.beforeForward({id:runId+'/'+admitted.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(admitted.requestFile),journal:{admitted,startPrefix}});tickets.set(admitted.requestSeq,funding.ticket);demand(funding.admitted,'smoke_usd_exhausted');},
  afterDurableFinish(receipt){cash.finish(tickets.get(receipt.requestSeq)!,{kind:'journal-finish',journalRef:receipt.journalRef});},
  async transport(raw){attempts++;requests.push(JSON.parse(raw));
    const response=live?await captureProviderResponse(await benchmarkFetch(raw,key!)):{httpStatus:200,rawResponse:JSON.stringify({id:'synthetic-'+attempts,provider:BENCHMARK_PROVIDER.providerName,model:BENCHMARK_PROVIDER.model,
      choices:[{index:0,finish_reason:attempts===1?'stop':'tool_calls',message:{role:'assistant',content:attempts===1?'42':null,reasoning:'Synthetic local reasoning',...(attempts===2?{tool_calls:[{id:'synthetic-submit',type:'function',function:{name:'submit',arguments:'{"answer":"42"}'}}]}:{})}}],usage:{prompt_tokens:10,completion_tokens:4,total_tokens:14,cost:0,completion_tokens_details:{reasoning_tokens:2}}})};
    if(response.httpStatus===200)successfulGenerations++;return response;
  }});
const token=randomUUID(),server=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(request){
  if(request.headers.get('authorization')!=='Bearer '+token)return Response.json({error:'unauthorized'},{status:401});
  const response=await proxy.handle('submit-smoke',await request.text());return new Response(response.rawResponse,{status:response.httpStatus,headers:{'content-type':'application/json'}});
}});
const env='TGENGIN_OPENROUTER_SMOKE_PROXY_KEY',previous=process.env[env];process.env[env]=token;
let errorName:string|undefined,submitPassed=false,reasoningHistoryReplayed=false,thoughtObserved=false;
try{
  const handles=new Map<string,any>();
  // Registry registration is a local shell; both model calls use the production SDK/adapter and proxy.
  registerVendors({run(){}} as any,{register(_db:any,name:string,_timeout:any,handler:any){handles.set(name,handler);}} as any,{warn(){}} as any,[],{...BENCHMARK_INFERENCE,retryTimes:0,continueTimes:0});
  const unit:Unit={agent:{},task:{},cycle:{},chain:'smoke',place:'local',instance:'smoke',unit:0,
    api:{key_env:env,model:BENCHMARK_PROVIDER.model,base_url:`http://127.0.0.1:${server.port}/v1`,retry_on:'[]'},
    context:[{seq:0,role:'user',kind:'prompt',body:'Compute 6 * 7. Give the numeric answer.'}],sentAs:{user:'messages',assistant:'messages'},mustCall:null,tools:[],rules:[]};
  const first=await handles.get('fn:api.openrouter')(unit);thoughtObserved=typeof first.thought==='string'&&first.thought.length>0;
  const second=await handles.get('fn:api.openrouter')({...unit,unit:1,mustCall:'submit',tools:[{name:'submit',does:'Submit the numeric answer',params:'{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}'}],
    context:[...unit.context,{seq:1,role:first.role,kind:first.kind,body:first.body,thought:first.thought},{seq:2,role:'user',kind:'prompt',body:'Submit the answer 42 now using submit exactly once.'}]});
  const calls=JSON.parse(second.body).calls;submitPassed=calls.length===1&&calls[0].name==='submit';
  reasoningHistoryReplayed=!!first.thought&&requests[1]?.messages?.some((message:any)=>message.role==='assistant'&&message.reasoning_content===first.thought);
}catch(error){errorName=error instanceof Error?error.name:'UnknownError';}
finally{await proxy.drain();await server.stop(true);if(previous===undefined)delete process.env[env];else process.env[env]=previous;}
const inspection=inspectCampaignJournal(directory),ledger=journal.exportLegacyLedger(),cashPin=cash.close(),checked=verifyBenchmarkCashClosure(cashPin);
let ownerReleased=false;
if(lease&&checked.proof.releasePermitted){lease.finishLightweight({ownedGenerationClosed:true,pendingRequests:0,cashPin,ledgerPin:actualPin(ledger.path),verificationOnly:true});ownerReleased=true;}
const receipts=[...journal.closedCalls('submit-smoke')];journal.close();
const result={protocol:'openrouter-current-system-submit-check-v1',runId,checkedAtUtc:new Date().toISOString(),live,benchmarkStarted:false,model:BENCHMARK_PROVIDER.model,provider:BENCHMARK_PROVIDER.providerName,currency:'USD',capUsd:0.05,
  providerAttempts:live?attempts:0,successfulGenerations:live?successfulGenerations:0,syntheticResponses:live?0:successfulGenerations,
  submitPassed,thoughtObserved,reasoningHistoryReplayed,thinkingEnabledOnAllRequests:requests.every(row=>row.reasoning?.enabled===true&&row.reasoning.effort==='high'),
  submitToolChoice:requests[1]?.tool_choice??null,errorName:errorName??null,accountingClosed:inspection.valid&&inspection.accountingClosed,billedUsd:cash.snapshot().billedUsd,
  unknownReservationUsd:cash.snapshot().unknownReservationUsd,ownerReleased,registryRegistrationShell:'local',sourcePins:sources,
  receiptSummary:receipts.map(row=>({httpStatus:row.httpStatus,providerName:row.providerName??null,servedModel:row.servedModel??null,costBasis:row.costBasis,usdUpperBound:row.usdUpperBound,nonGenerationRejection:row.nonGenerationRejection??null,fault:row.fault??null})),cashPin,ledgerPin:actualPin(ledger.path)};
const path=join(output,'result.json');writeFileSync(path,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({resultPath:path,live,submitPassed,providerAttempts:result.providerAttempts,successfulGenerations:result.successfulGenerations,accountingClosed:result.accountingClosed,billedUsd:result.billedUsd,ownerReleased}));
if(!submitPassed||!thoughtObserved||!reasoningHistoryReplayed)process.exitCode=2;
