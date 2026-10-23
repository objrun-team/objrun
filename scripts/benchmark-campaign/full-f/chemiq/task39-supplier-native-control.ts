/** Offline fixture: native journal/cash, no canonical owner, paid calls or shared source writes. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {captureChemiqSSE,makeChemiqStreamingWireRequest} from './task39-supplier-stream-staged.ts';
import {createCampaignJournal,inspectCampaignJournal} from '../shared/supplier-journal.ts';
import {createBenchmarkCash,verifyBenchmarkCashClosure} from '../shared/supplier-usd-cash.ts';
import {ScientificJournalProxy} from '../shared/supplier-proxy.ts';
import {BENCHMARK_PROVIDER,SUPPLIER} from './task39-supplier-profile.ts';
import {BENCHMARK_INFERENCE} from '../../../benchmark-repair/benchmark-inference.ts';
import {actualPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const root=path.resolve(import.meta.dir,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq/supplier-native-control-'+SUPPLIER+'',String(Date.now()));
fs.mkdirSync(base,{recursive:true});
const raw=JSON.stringify({model:BENCHMARK_PROVIDER.model,messages:[{role:'user',content:'local fixture only'}],max_tokens:16384,temperature:0,reasoning_effort:'high'}),results=[];
for(const kind of ['complete','missing-cost','length'] as const){
 const dir=path.join(base,kind),id='repair-'+Date.now()+'-12-'+(['complete','missing-cost','length'].indexOf(kind)+1);
 fs.mkdirSync(dir,{recursive:true});
 const journal=createCampaignJournal({directory:path.join(dir,'journal'),campaign:id,capUsd:20,priorCampaignCostUpperBoundUsd:0,outputDirectory:dir,provider:BENCHMARK_PROVIDER});
 const admissionFile=path.join(dir,'fixture-admission.json');fs.writeFileSync(admissionFile,JSON.stringify({localMock:true,noCanonicalOwner:true,runId:id,capUsd:20}));
 const admission:any={currency:'USD',capUsd:20,runId:id,proofPin:actualPin(admissionFile),owned:{ownerNonce:'local-fixture',pid:process.pid},scope:'production',assertOwned(){},validateForwardSource(){},registerCash(){}};
 const cash=createBenchmarkCash({directory:path.join(dir,'cash'),runId:id,providerKind:'real-provider',admission,prices:actualPin(path.join(root,'docs/repair-2026-10-10/full-f-rerun/chembench-supplier-prices/'+SUPPLIER+'/openrouter-prices.json')),journal:{directory:journal.directory,configPin:actualPin(path.join(journal.directory,'journal-config.json')),sourcePin:actualPin(path.join(root,'scripts/benchmark-campaign/full-f/shared/supplier-journal.ts'))}},BENCHMARK_PROVIDER);
 const tickets=new Map();
 const proxy=new ScientificJournalProxy(journal,{provider:BENCHMARK_PROVIDER,inference:BENCHMARK_INFERENCE,routes:new Set(['fixture']),failureDirectory:path.join(dir,'failures'),
  beforeForward(j,p,body,route){const f=cash.beforeForward({id:id+'/'+j.requestSeq,route,rawRequest:Buffer.from(body),capturedRequest:actualPin(j.requestFile),journal:{admitted:j,startPrefix:p}});tickets.set(j.requestSeq,f.ticket);assert(f.admitted);},
  afterDurableFinish(r){cash.finish(tickets.get(r.requestSeq),{kind:'journal-finish',journalRef:r.journalRef});},
  async transport(original){
   const wire=makeChemiqStreamingWireRequest(original),meta={id:'gen-local-native-'+kind,model:BENCHMARK_PROVIDER.model,provider:BENCHMARK_PROVIDER.providerName,created:1};
   const frames=[{...meta,choices:[{index:0,delta:{role:'assistant',tool_calls:[{index:0,id:'fixture-call',type:'function',function:{name:'submit',arguments:'{"answer":"fixture"}'}}]},finish_reason:kind==='length'?'length':'tool_calls'}]}, {...meta,choices:[],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,...(kind==='missing-cost'?{}:{cost:0.01})}}];
   const body=frames.map(x=>'data: '+JSON.stringify(x)+'\n\n').join('')+'data: [DONE]\n\n';
   return captureChemiqSSE(new Response(body,{headers:{'content-type':'text/event-stream'}}),{originalRequest:original,wireRequest:wire,evidencePrefix:path.join(dir,'capture')});
  }});
 const response=await proxy.handle('fixture',raw);await proxy.drain();journal.exportLegacyLedger();const pin=cash.close();journal.close();
 const proof=verifyBenchmarkCashClosure(pin).proof,inspection=inspectCampaignJournal(journal.directory);
 assert(inspection.valid);assert.equal(proof.snapshot.pendingCount,0);
 assert.equal(proof.snapshot.newUnknownCount,kind==='missing-cost'?1:0);
 if(kind!=='missing-cost'){assert.equal(response.httpStatus,200);assert.equal(proof.snapshot.billedUsd,0.01);assert.equal(JSON.parse(response.rawResponse).choices[0].message.tool_calls[0].function.arguments,'{"answer":"fixture"}');}
 else {assert.notEqual(response.httpStatus,200);assert(proof.snapshot.unknownReservationUsd>0);assert.equal(proof.releasePermitted,false);}
 results.push({kind,passed:true,httpStatus:response.httpStatus,cashClosePin:pin,journalValid:true,snapshot:proof.snapshot});
}
const report={atUtc:new Date().toISOString(),passed:true,externalCalls:0,canonicalOwnerAcquired:false,sourcePin:actualPin(import.meta.path),adapterPin:actualPin(path.join(import.meta.dir,'task39-supplier-stream-staged.ts')),results};
fs.writeFileSync(path.join(base,'report.json'),JSON.stringify(report,null,2));fs.writeFileSync(path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq/supplier-native-control-'+SUPPLIER+'.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:true,cases:results.length,externalCalls:0,report:path.join(base,'report.json')}));
