import { test, expect, spyOn } from 'bun:test';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { startFullFBroker, BENCH_WEIGHTS } from './digitalocean-broker-cb-continuation.ts';
import { acquireFullFAdmission, acquireFullFResource, BENCH_CODES } from './supplier-shared-admission.ts';
import { actualPin, jsonPin, same } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { BENCHMARK_PROVIDER } from './digitalocean-provider.ts';
import { BENCHMARK_PROVIDER as RELACE_PROVIDER } from '../../../benchmark-repair/benchmark-provider.ts';
import {CHEMBENCH_SUPPLIERS} from './chembench-supplier-profiles.ts';
import { BENCHMARK_INFERENCE } from '../../../benchmark-repair/benchmark-inference.ts';
import { createCampaignJournal } from './supplier-journal.ts';
import { createBenchmarkCash, verifyBenchmarkCashClosure } from './supplier-usd-cash.ts';
import { ScientificJournalProxy } from './supplier-proxy.ts';
import { cashClosureAllowsContinuation, acquireOpenRouterAdmission } from './digitalocean-admission.ts';

const ROOT=resolve(import.meta.dir,'../../../..');
function save(path:string,value:any){mkdirSync(dirname(path),{recursive:true});writeFileSync(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(path);}
async function fixture(transport?:(raw:string)=>Promise<any>,recordAndContinue=false) {
  const runId='repair-'+Date.now()+'-'+Math.floor(Math.random()*100000000),directory=join(ROOT,'.scratch/full-f-broker-tests',runId),canonical=join(directory,'mock-canonical.lock.json');
  const prices=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/digitalocean-switch/funding-1791639763986/openrouter-prices.json'));
  const balance=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/funding-observation/openrouter-balance.json'));
  let owners=0,registered=0,allocated=0;
  const broker=await startFullFBroker({root:ROOT,output:directory,runId,port:0,localMock:true,transport,recordAndContinue,maxInFlight:16,perBenchMax:8,heavyCapacity:1,async leaseFactory(input){
    owners++;allocated=0;const owned={pid:process.pid,runId,ownerNonce:randomBytes(12).toString('hex'),family:'local-mock-only'};
    save(canonical,owned);const proofPin=save(join(input.output,'mock-parent.json'),{protocol:'openrouter-usd-admission-v1',owned,capUsd:100,currency:'USD',localMock:true});
    const cash=new Map<string,any>();return {owned,proofPin,path:canonical,prices,balance,capUsd:100,
      forkLane(id:string,output:string,capUsd:number){allocated+=capUsd;if(allocated>100)throw new Error('overallocated');
        const pin=save(join(output,'openrouter-lane-admission.json'),{protocol:'openrouter-usd-lane-admission-v1',runId:id,capUsd,currency:'USD',parentAdmissionPin:proofPin,ownerNonce:owned.ownerNonce});
        return {runId:id,capUsd,owned:{...owned,runId:id},proofPin:pin,validateForwardSource(){if(!same(jsonPin(actualPin(canonical)),owned))throw new Error('owner_changed');},
          registerCash(p:any){registered++;cash.set(id,p);},registerOwnedProcess(){}};
      },finishLightweight(){const closures=[...cash.values()].map(p=>verifyBenchmarkCashClosure(actualPin(join(dirname(p.path),'cash-close.json'))));
        expect(closures.every(v=>cashClosureAllowsContinuation(v.proof,recordAndContinue))).toBe(true);expect(closures.length).toBeGreaterThan(0);expect(same(JSON.parse(readFileSync(canonical,'utf8')),owned)).toBe(true);
        unlinkSync(canonical);return save(join(input.output,'mock-release.json'),{localMock:true,currency:'USD',cashCount:cash.size,billedUsd:0});}
    };
  }});
  async function lane(slug:string,suffix='relace') {
    const id=runId+'-'+BENCH_CODES[slug]+'-'+({relace:'1',dekallm:'2',wafer:'3'} as any)[suffix],output=join(ROOT,'docs/repair-2026-10-10/full-f-rerun',slug,'local-broker-tests',id);
    const admission=await acquireFullFAdmission({root:ROOT,output,runId:id,slug,providerSlug:slug==='chembench'?suffix:undefined,sourcePins:[actualPin(import.meta.path)],connection:broker.connection});
    const provider=slug==='chembench'?(CHEMBENCH_SUPPLIERS as any)[suffix]:BENCHMARK_PROVIDER;
    const journal=createCampaignJournal({directory:join(output,'journal'),campaign:id,capUsd:admission.capUsd,priorCampaignCostUpperBoundUsd:0,outputDirectory:output,provider});
    const cash=createBenchmarkCash({directory:join(output,'cash'),runId:id,providerKind:'local-mock',prices:admission.prices,admission,
      journal:{directory:journal.directory,configPin:actualPin(join(output,'journal/journal-config.json')),sourcePin:actualPin(join(ROOT,'scripts/benchmark-campaign/full-f/shared/supplier-journal.ts'))}},provider);
    const tickets=new Map<number,any>();const proxy=new ScientificJournalProxy(journal,{provider,inference:BENCHMARK_INFERENCE,routes:new Set(['t']),failureDirectory:join(output,'failures'),transport:admission.transport,
      beforeForward(j,p,raw,route){const f=cash.beforeForward({id:id+'/'+j.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(j.requestFile),journal:{admitted:j,startPrefix:p}});tickets.set(j.requestSeq,f.ticket);if(!f.admitted)throw new Error('cash_denied');},
      afterDurableFinish(r){cash.finish(tickets.get(r.requestSeq),{kind:'journal-finish',journalRef:r.journalRef});}});
    async function close(){await proxy.drain();journal.exportLegacyLedger();const cashPin=cash.close();const result=await admission.finishLightweight({cashPin});journal.close();return result;}
    return {admission,proxy,cash,journal,close};
  }
  return {broker,lane,canonical,get owners(){return owners;},get registered(){return registered;},get allocated(){return allocated;}};
}
const raw=(n:number)=>JSON.stringify({model:BENCHMARK_PROVIDER.model,messages:[{role:'user',content:'Synthetic local test '+n}],max_tokens:16384,temperature:0,reasoning_effort:'high'});

test('only ChemBench uses upstream SSE and cash settles original complete stream usage',async()=>{
  const nativeFetch=globalThis.fetch,wire:any[]=[];
  const mocked=spyOn(globalThis,'fetch').mockImplementation((async(url:any,options:any)=>{
    if(String(url).startsWith('http://127.0.0.1:'))return nativeFetch(url,options);
    if(String(url)!==BENCHMARK_PROVIDER.endpoint)throw new Error('external network forbidden in local test');
    const body=JSON.parse(options.body);wire.push(body);
    const id='gen-synthetic-local-stream-'+wire.length;
    const base={id,object:'chat.completion.chunk',provider:({relace:'Relace',dekallm:'DekaLLM',wafer:'Wafer',digitalocean:'DigitalOcean'} as any)[body.provider.only[0]],model:BENCHMARK_PROVIDER.model,created:1};
    if(body.stream===true){
      const frames=[{...base,choices:[{index:0,delta:{role:'assistant',content:'42'},finish_reason:null}]},{...base,choices:[{index:0,delta:{content:''},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0.00002}}];
      return new Response(': OPENROUTER PROCESSING\n\n'+frames.map(x=>'data: '+JSON.stringify(x)+'\n\n').join('')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
    }
    return Response.json({...base,object:'chat.completion',choices:[{index:0,message:{role:'assistant',content:'42'},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0.00002}});
  }) as any);
  const f=await fixture(undefined,true);
  try{
    const cb=await f.lane('chembench'),cq=await f.lane('chemiq');
    await cb.proxy.handle('t',raw(411));await cq.proxy.handle('t',raw(412));
    expect(wire.length).toBe(2);expect(wire[0].provider.only).toEqual(['relace']);expect(wire[1].provider.only).toEqual(['digitalocean']);expect(wire[0].stream).toBe(true);expect(wire[1].stream).not.toBe(true);
    expect(cb.cash.snapshot().billedUsd).toBe(0);expect(cb.cash.snapshot().newUnknownCount).toBe(0);
    const finished=readFileSync(join(cb.journal.directory,'api-events.jsonl'),'utf8').trim().split('\n').map(JSON.parse).find(e=>e.kind==='finish').record;
    expect(finished.costBasis).toBe('provider_reported_usd');expect(finished.billedCostUsd).toBe(0.00002);expect(finished.completionValid).toBe(true);
    expect(cq.cash.snapshot().billedUsd).toBe(0);expect(cq.cash.snapshot().newUnknownCount).toBe(0);
    expect(f.broker.snapshot().transportPolicy.chembench).toBe('upstream-sse-approved-supplier-complete-aggregation-length-v2');
    await cb.close();
    for(const name of ['dekallm','wafer']){const last=await f.lane('chembench',name);await last.proxy.handle('t',raw(450));expect(wire.at(-1).provider.only).toEqual([name]);expect(last.cash.snapshot().newUnknownCount).toBe(0);await last.close();}
    await cq.close();await f.broker.stop();
  }finally{mocked.mockRestore();await f.broker.server.stop(true);}
});


test('a paused broker reclaims only the identical existing lane to close its native cash',async()=>{
 const f=await fixture(undefined,true);const cb=await f.lane('chembench');
 try{await fetch(f.broker.connection.endpoint+'/admin/pause',{method:'POST',headers:{authorization:'Bearer '+f.broker.connection.accessToken},body:'{}'});
 const reclaimed=await acquireFullFAdmission({root:ROOT,output:dirname(cb.journal.directory),runId:cb.admission.runId,slug:'chembench',providerSlug:'relace',sourcePins:cb.admission.sourcePins,connection:f.broker.connection});
 await cb.proxy.drain();cb.journal.exportLegacyLedger();const cashPin=cb.cash.close();expect((await reclaimed.finishLightweight({cashPin})).ownerReleased).toBe(true);cb.journal.close();await f.broker.stop();
 }finally{await f.broker.server.stop(true);}
});
test('a lane cannot silently change its supplier or allocate an unauthorized one',async()=>{
 const f=await fixture(undefined,true);const cb=await f.lane('chembench');
 try{const claim=(providerSlug:string,runId=cb.admission.runId)=>acquireFullFAdmission({root:ROOT,output:dirname(cb.journal.directory),runId,slug:'chembench',providerSlug,sourcePins:cb.admission.sourcePins,connection:f.broker.connection});
 await expect(claim('wafer')).rejects.toThrow('lane_reclaim_changed');await expect(claim('foreign',cb.admission.runId.replace(/-1$/,'-9'))).rejects.toThrow('unapproved_chembench_lane_provider');
 await cb.close();await f.broker.stop();
 }finally{await f.broker.server.stop(true);}
});
