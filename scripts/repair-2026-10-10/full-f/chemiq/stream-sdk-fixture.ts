import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';
import {captureChemiqSSE,makeChemiqStreamingWireRequest} from './upstream-stream-length-staged.ts';
import {createCampaignJournal,inspectCampaignJournal} from '../shared/digitalocean-journal.ts';
import {createBenchmarkCash,verifyBenchmarkCashClosure} from '../shared/digitalocean-usd-cash.ts';
import {ScientificJournalProxy} from '../shared/digitalocean-proxy.ts';
import {BENCHMARK_PROVIDER} from '../shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE} from '../../../repair-2026-10-08/benchmark-inference.ts';
import {actualPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
export function openFixture(directory:string){
 const root=path.resolve(import.meta.dir,'../../../..'),dir=path.join(directory,'native-stream'),id='repair-'+Date.now()+'-12-1';fs.mkdirSync(dir,{recursive:true});
 const journal=createCampaignJournal({directory:path.join(dir,'journal'),campaign:id,capUsd:20,priorCampaignCostUpperBoundUsd:0,outputDirectory:dir,provider:BENCHMARK_PROVIDER});
 const f=path.join(dir,'fixture-admission.json');fs.writeFileSync(f,JSON.stringify({localMock:true,noCanonicalOwner:true,runId:id}));
 const admission:any={currency:'USD',capUsd:20,runId:id,proofPin:actualPin(f),owned:{ownerNonce:'local-fixture',pid:process.pid},scope:'production',assertOwned(){},validateForwardSource(){},registerCash(){}};
 const cash=createBenchmarkCash({directory:path.join(dir,'cash'),runId:id,providerKind:'real-provider',admission,prices:actualPin(path.join(root,'docs/repair-2026-10-10/full-f-rerun/digitalocean-switch/funding-1791639763986/openrouter-prices.json')),journal:{directory:journal.directory,configPin:actualPin(path.join(journal.directory,'journal-config.json')),sourcePin:actualPin(path.join(root,'scripts/repair-2026-10-10/full-f/shared/digitalocean-journal.ts'))}},BENCHMARK_PROVIDER);
 let seq=0,wantsLength=false;const tickets=new Map(),captures=[];
 const proxy=new ScientificJournalProxy(journal,{provider:BENCHMARK_PROVIDER,inference:BENCHMARK_INFERENCE,routes:new Set(['fixture']),failureDirectory:path.join(dir,'failures'),beforeForward(j,p,body,route){const out=cash.beforeForward({id:id+'/'+j.requestSeq,route,rawRequest:Buffer.from(body),capturedRequest:actualPin(j.requestFile),journal:{admitted:j,startPrefix:p}});tickets.set(j.requestSeq,out.ticket);assert(out.admitted);},afterDurableFinish(r){cash.finish(tickets.get(r.requestSeq),{kind:'journal-finish',journalRef:r.journalRef});},async transport(original){
  const n=seq++,wire=makeChemiqStreamingWireRequest(original),meta={id:'gen-local-sdk-'+n,model:BENCHMARK_PROVIDER.model,provider:'DigitalOcean',created:1};
  const delta=wantsLength?{role:'assistant',content:'length-marker',reasoning:'fixture reasoning'}:{role:'assistant',tool_calls:[{index:0,id:'fixture-call-'+n,type:'function',function:{name:'submit',arguments:'{"answer":"local-control"}'}}]};
  const body=[{...meta,choices:[{index:0,delta,finish_reason:wantsLength?'length':'tool_calls'}]},{...meta,choices:[],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0.01}}].map(v=>'data: '+JSON.stringify(v)+'\n\n').join('')+'data: [DONE]\n\n';
  const response=await captureChemiqSSE(new Response(body),{originalRequest:original,wireRequest:wire,evidencePrefix:path.join(dir,'capture-'+n)});captures.push(response.evidence);return response;
 }});
 return {handle(body:any,length:boolean){wantsLength=length;return proxy.handle('fixture',JSON.stringify(body));},async close(){await proxy.drain();journal.exportLegacyLedger();const pin=cash.close();journal.close();const proof=verifyBenchmarkCashClosure(pin).proof;assert(inspectCampaignJournal(journal.directory).valid);assert.equal(proof.snapshot.pendingCount,0);assert.equal(proof.snapshot.newUnknownCount,0);assert(Math.abs(proof.snapshot.billedUsd-seq*0.01)<1e-9);return{cashClosePin:pin,generations:seq,captures,canonicalOwnerAcquired:false,externalCalls:0};}};
}
