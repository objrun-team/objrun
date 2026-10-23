import { test, expect } from 'bun:test';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { startFullFBroker, BENCH_WEIGHTS } from './full-f-broker.ts';
import { acquireFullFAdmission, acquireFullFResource, BENCH_CODES } from './shared-admission.ts';
import { actualPin, jsonPin, same } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { BENCHMARK_PROVIDER } from '../../../repair-2026-10-08/benchmark-provider.ts';
import { BENCHMARK_INFERENCE } from '../../../repair-2026-10-08/benchmark-inference.ts';
import { createCampaignJournal } from '../../../repair-2026-10-08/campaign-journal.ts';
import { createBenchmarkCash, verifyBenchmarkCashClosure } from '../../../repair-2026-10-08/benchmark-usd-cash.ts';
import { ScientificJournalProxy } from '../../../repair-2026-10-08/scientific-journal-proxy.ts';
import { cashClosureAllowsContinuation } from '../../../repair-2026-10-08/openrouter-paid-admission.ts';

const ROOT=resolve(import.meta.dir,'../../../..');
function save(path:string,value:any){mkdirSync(dirname(path),{recursive:true});writeFileSync(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(path);}
async function fixture(transport?:(raw:string)=>Promise<any>,recordAndContinue=false) {
  const runId='repair-'+Date.now()+'-'+Math.floor(Math.random()*100000000),directory=join(ROOT,'.scratch/full-f-broker-tests',runId),canonical=join(directory,'mock-canonical.lock.json');
  const prices=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/funding-observation/openrouter-prices.json'));
  const balance=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/funding-observation/openrouter-balance.json'));
  let owners=0,registered=0,allocated=0;
  const broker=await startFullFBroker({root:ROOT,output:directory,runId,port:0,localMock:true,transport,recordAndContinue,async leaseFactory(input){
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
  async function lane(slug:string,suffix='1') {
    const id=runId+'-'+BENCH_CODES[slug]+'-'+suffix,output=join(ROOT,'docs/repair-2026-10-10/full-f-rerun',slug,'local-broker-tests',id);
    const admission=await acquireFullFAdmission({root:ROOT,output,runId:id,slug,sourcePins:[actualPin(import.meta.path)],connection:broker.connection});
    const journal=createCampaignJournal({directory:join(output,'journal'),campaign:id,capUsd:admission.capUsd,priorCampaignCostUpperBoundUsd:0,outputDirectory:output,provider:BENCHMARK_PROVIDER});
    const cash=createBenchmarkCash({directory:join(output,'cash'),runId:id,providerKind:'local-mock',prices:admission.prices,admission,
      journal:{directory:journal.directory,configPin:actualPin(join(output,'journal/journal-config.json')),sourcePin:actualPin(join(ROOT,'scripts/repair-2026-10-08/campaign-journal.ts'))}},BENCHMARK_PROVIDER);
    const tickets=new Map<number,any>();const proxy=new ScientificJournalProxy(journal,{provider:BENCHMARK_PROVIDER,inference:BENCHMARK_INFERENCE,routes:new Set(['t']),failureDirectory:join(output,'failures'),transport:admission.transport,
      beforeForward(j,p,raw,route){const f=cash.beforeForward({id:id+'/'+j.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(j.requestFile),journal:{admitted:j,startPrefix:p}});tickets.set(j.requestSeq,f.ticket);if(!f.admitted)throw new Error('cash_denied');},
      afterDurableFinish(r){cash.finish(tickets.get(r.requestSeq),{kind:'journal-finish',journalRef:r.journalRef});}});
    async function close(){await proxy.drain();journal.exportLegacyLedger();const cashPin=cash.close();const result=await admission.finishLightweight({cashPin});journal.close();return result;}
    return {admission,proxy,cash,journal,close};
  }
  return {broker,lane,canonical,get owners(){return owners;},get registered(){return registered;},get allocated(){return allocated;}};
}
const raw=(n:number)=>JSON.stringify({model:BENCHMARK_PROVIDER.model,messages:[{role:'user',content:'Synthetic local test '+n}],max_tokens:16384,temperature:0,reasoning_effort:'high'});

test('only the four requested Benches can obtain lanes; duplicate active runs are rejected',async()=>{
  const f=await fixture();expect(Object.keys(BENCH_WEIGHTS).sort()).toEqual(['chembench','chemiq','skillsbench','terminal-bench'].sort());
  for(const slug of ['aime','gpqa','cmt','minif2f','deepswe'])await expect(f.lane(slug)).rejects.toThrow('invalid_bench_run_id');
  expect(f.owners).toBe(0);const a=await f.lane('chembench');expect(a.admission.capUsd).toBe(10);
  await expect(f.lane('chembench','2')).rejects.toThrow('bench_already_active');
  const result=await a.close();expect(result.ownerReleased).toBe(true);expect(f.registered).toBe(1);expect(existsSync(f.canonical)).toBe(false);await f.broker.stop();
});

test('two cash-backed Bench lanes share at most four forwards and at most two per Bench',async()=>{
  let active=0,peak=0,seq=0;const f=await fixture(async()=>{const id=++seq;active++;peak=Math.max(peak,active);await new Promise(r=>setTimeout(r,40));active--;
    return {httpStatus:200,rawResponse:JSON.stringify({id:'synthetic-local-'+id,provider:'Relace',model:BENCHMARK_PROVIDER.model,choices:[{index:0,finish_reason:'stop',message:{role:'assistant',content:'42'}}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0}})};
  });
  const a=await f.lane('chembench'),b=await f.lane('chemiq');let perBenchPeak=0;
  const monitor=setInterval(()=>{for(const l of f.broker.snapshot().lanes)perBenchPeak=Math.max(perBenchPeak,l.active);},5);
  const responses=await Promise.all([0,1,2,3].flatMap(n=>[a.proxy.handle('t',raw(n)),b.proxy.handle('t',raw(n+10))]));clearInterval(monitor);
  expect(responses.every(r=>r.httpStatus===200)).toBe(true);expect(seq).toBe(8);expect(peak).toBeLessThanOrEqual(4);expect(peak).toBeGreaterThan(2);expect(perBenchPeak).toBeLessThanOrEqual(2);
  expect(f.owners).toBe(1);expect(f.registered).toBe(2);expect(f.allocated).toBe(30);expect(a.cash.snapshot().pendingCount).toBe(0);expect(b.cash.snapshot().pendingCount).toBe(0);
  expect((await a.close()).ownerReleased).toBe(false);expect((await b.close()).ownerReleased).toBe(true);await f.broker.stop();
});

test('the heavy-container resource is exclusive and owner checked',async()=>{
  const f=await fixture();const skb=await acquireFullFResource(ROOT,'skillsbench','heavy-container',f.broker.connection);
  await expect(acquireFullFResource(ROOT,'terminal-bench','heavy-container',f.broker.connection)).rejects.toThrow();
  await skb.release();const tb=await acquireFullFResource(ROOT,'terminal-bench','heavy-container',f.broker.connection);await tb.release();expect(f.owners).toBe(0);await f.broker.stop();
});

test('record-and-continue retains an uncertain fee without stopping another Bench or rewriting the closure',async()=>{
  let calls=0;const f=await fixture(async()=>++calls===1?{httpStatus:500,rawResponse:JSON.stringify({error:{message:'Synthetic upstream uncertainty'}})}:
    {httpStatus:200,rawResponse:JSON.stringify({id:'synthetic-continue-'+calls,provider:'Relace',model:BENCHMARK_PROVIDER.model,
      choices:[{index:0,finish_reason:'stop',message:{role:'assistant',content:'42'}}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0}})},true);
  try{
    const a=await f.lane('chembench'),b=await f.lane('chemiq');
    expect((await a.proxy.handle('t',raw(0))).httpStatus).toBe(500);expect(a.cash.snapshot().newUnknownCount).toBe(1);
    expect(f.broker.snapshot().healthy).toBe(true);expect((await b.proxy.handle('t',raw(1))).httpStatus).toBe(200);
    expect((await a.close()).ownerReleased).toBe(false);
    const original=verifyBenchmarkCashClosure(actualPin(join(a.journal.directory,'../cash/cash-close.json'))).proof;
    expect(original.releasePermitted).toBe(false);expect(original.snapshot.newUnknownCount).toBe(1);
    expect(cashClosureAllowsContinuation(original)).toBe(false);expect(cashClosureAllowsContinuation(original,true)).toBe(true);
    expect(cashClosureAllowsContinuation({...original,snapshot:{...original.snapshot,pendingCount:1}},true)).toBe(false);
    expect((await b.close()).ownerReleased).toBe(true);expect(calls).toBe(2);await f.broker.stop();
  }finally{await f.broker.server.stop(true);}
});
