import { test, expect, spyOn } from 'bun:test';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { startFullFBroker, BENCH_WEIGHTS } from './digitalocean-broker-dynamic-sixteen-actual-disk.next.ts';
import { acquireFullFAdmission, acquireFullFResource, BENCH_CODES } from './supplier-shared-admission.ts';
import { actualPin, jsonPin, same } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { BENCHMARK_PROVIDER } from './digitalocean-provider.ts';
import { BENCHMARK_PROVIDER as RELACE_PROVIDER } from '../../../benchmark-repair/benchmark-provider.ts';
import {CHEMBENCH_SUPPLIERS,supplierProfile} from './chembench-supplier-profiles.ts';
import { BENCHMARK_INFERENCE } from '../../../benchmark-repair/benchmark-inference.ts';
import { createCampaignJournal } from './supplier-journal.ts';
import { createBenchmarkCash, verifyBenchmarkCashClosure } from './supplier-usd-cash.ts';
import { ScientificJournalProxy } from './supplier-proxy.ts';
import { cashClosureAllowsContinuation, acquireOpenRouterAdmission } from './digitalocean-admission.ts';

const ROOT=resolve(import.meta.dir,'../../../..');
function save(path:string,value:any){mkdirSync(dirname(path),{recursive:true});writeFileSync(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(path);}
async function fixture(transport?:(raw:string)=>Promise<any>,recordAndContinue=false,taskLimit=2) {
  const runId='repair-'+Date.now()+'-'+Math.floor(Math.random()*100000000),directory=join(ROOT,'.scratch/full-f-broker-tests',runId),canonical=join(directory,'mock-canonical.lock.json');
  const prices=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/digitalocean-switch/funding-1791639763986/openrouter-prices.json'));
  const balance=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/funding-observation/openrouter-balance.json'));
  let owners=0,registered=0,allocated=0;
  const broker=await startFullFBroker({root:ROOT,output:directory,runId,port:0,localMock:true,transport,recordAndContinue,maxInFlight:16,perBenchMax:8,heavyCapacity:Math.min(taskLimit*2,16),heavyMemoryMb:taskLimit*12288,perBenchHeavySlots:taskLimit,async leaseFactory(input){
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
  async function lane(slug:string,suffix=slug==='chembench'?'relace':'digitalocean',streamScope?:any,ordinal?:number) {
    const id=runId+'-'+BENCH_CODES[slug]+'-'+(ordinal??({relace:'1',dekallm:'2',wafer:'3',digitalocean:'4'} as any)[suffix])+(streamScope?.eligibleIndices?.length>1?'-9':''),output=join(ROOT,'docs/repair-2026-10-10/full-f-rerun',slug,'local-broker-tests',id);
    const sourcePins=[actualPin(import.meta.path)];
    if(streamScope)sourcePins.push(save(join(output,'stream-task-scope.json'),streamScope));
    const admission=await acquireFullFAdmission({root:ROOT,output,runId:id,slug,providerSlug:['chembench','chemiq'].includes(slug)?suffix:undefined,sourcePins,connection:broker.connection});
    const provider=['chembench','chemiq'].includes(slug)&&suffix!=='digitalocean'?(CHEMBENCH_SUPPLIERS as any)[suffix]:BENCHMARK_PROVIDER;
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

const cqScope={protocol:'chemiq-task39-stream-scope-v1',eligibleIndices:[39],officialId:'chemiq-1b8804c1-d279-422a-ad63-755bb021b922',retainedValid:815,solveSeconds:900,maxTokens:16384,provider:'digitalocean',reasoning:'high',allowFallbacks:false};
test('only the pinned ChemIQ39 scope streams; ordinary DigitalOcean remains nonstream',async()=>{
 const nativeFetch=globalThis.fetch,wire:any[]=[];
 const mocked=spyOn(globalThis,'fetch').mockImplementation((async(url:any,options:any)=>{
  if(String(url).startsWith('http://127.0.0.1:'))return nativeFetch(url,options);
  if(String(url)!==BENCHMARK_PROVIDER.endpoint)throw Error('external network forbidden');
  const body=JSON.parse(options.body);wire.push(body);
  const base={id:'gen-local-cq-scope-'+wire.length,model:BENCHMARK_PROVIDER.model,provider:'DigitalOcean',created:1};
  const usage={prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0.00002};
  if(body.stream){const frames=[{...base,choices:[{index:0,delta:{role:'assistant',content:'42'},finish_reason:null}]},{...base,choices:[{index:0,delta:{},finish_reason:'stop'}],usage}];return new Response(frames.map(v=>'data: '+JSON.stringify(v)+'\n\n').join('')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});}
  return Response.json({...base,choices:[{index:0,message:{role:'assistant',content:'42'},finish_reason:'stop'}],usage});
 }) as any);
 const f=await fixture(undefined,true);
 try{const cb=await f.lane('chembench','digitalocean'),cq=await f.lane('chemiq','digitalocean',cqScope);
  await cb.proxy.handle('t',raw(901));await cq.proxy.handle('t',raw(902));
  expect(wire.length).toBe(2);expect(wire[0].stream).not.toBe(true);expect(wire[1].stream).toBe(true);expect(wire[1].stream_options.include_usage).toBe(true);
  expect(wire[1].reasoning.enabled).toBe(true);expect(wire[1].reasoning.effort).toBe('high');expect(wire[1].provider.only).toEqual(['digitalocean']);expect(wire[1].provider.allow_fallbacks).toBe(false);expect(wire[1].max_tokens).toBe(16384);
  expect(cq.cash.snapshot().newUnknownCount).toBe(0);await cb.close();await cq.close();await f.broker.stop();
 }finally{mocked.mockRestore();await f.broker.server.stop(true);}
});
test('ChemIQ streaming rejects any scope beyond the sole unscored39',async()=>{
 const f=await fixture(undefined,true);
 try{await expect(f.lane('chemiq','digitalocean',{...cqScope,eligibleIndices:[38,39]})).rejects.toThrow('invalid_chemiq_task39_stream_scope');expect(f.owners).toBe(0);}
 finally{await f.broker.server.stop(true);}
});

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
    expect(f.broker.snapshot().transportPolicy.chembench).toBe('digitalocean-nonstream-600s-approved-supplier-sse-length-v2');
    await cb.close();
    for(const name of ['dekallm','wafer','digitalocean']){const last=await f.lane('chembench',name);await last.proxy.handle('t',raw(450));expect(wire.at(-1).provider.only).toEqual([name]);expect(wire.at(-1).stream===true).toBe(name!=='digitalocean');expect(wire.at(-1).reasoning.enabled).toBe(true);expect(wire.at(-1).reasoning.effort).toBe('high');expect(wire.at(-1).provider.allow_fallbacks).toBe(false);expect(last.cash.snapshot().newUnknownCount).toBe(0);await last.close();}
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

 test('only human-authorized CQ39 suppliers route SSE with native cash; changed scopes fail before owner',async()=>{
  const nativeFetch=globalThis.fetch,wire:any[]=[];
  const mocked=spyOn(globalThis,'fetch').mockImplementation((async(url:any,opts:any)=>{
    if(String(url).startsWith('http://127.0.0.1:'))return nativeFetch(url,opts);
    if(String(url)!==BENCHMARK_PROVIDER.endpoint)throw Error('external network forbidden');
    const b=JSON.parse(opts.body);wire.push(b);const base={id:'gen-local-supplier-'+wire.length,model:BENCHMARK_PROVIDER.model,provider:supplierProfile(b.provider.only[0]).providerName,created:1};
    return new Response('data: '+JSON.stringify({...base,choices:[{index:0,delta:{role:'assistant',content:'42'},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0.00002}})+'\n\ndata: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});
  }) as any);
  const f=await fixture(undefined,true);const authorizationPin=actualPin(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/chemiq/task39-supplier-human-authorization.json'));
  try{for(const provider of ['relace','dekallm','wafer']){const scope={...cqScope,protocol:'chemiq-task39-supplier-scope-v1',provider,authorizationPin};
    await expect(f.lane('chemiq',provider,{...scope,eligibleIndices:[38,39]})).rejects.toThrow('invalid_chemiq_task39_supplier_scope');
    const lane=await f.lane('chemiq',provider,scope);await lane.proxy.handle('t',raw(1001));expect(wire.at(-1).provider.only).toEqual([provider]);expect(wire.at(-1).stream).toBe(true);expect(wire.at(-1).max_tokens).toBe(16384);expect(lane.cash.snapshot().newUnknownCount).toBe(0);await lane.close();
  }await f.broker.stop();}finally{mocked.mockRestore();await f.broker.server.stop(true);}
 });


test('four independent leases allow two per Bench and retain slot/budget/ownership limits',async()=>{
 const id='repair-local-parallel-'+Date.now(),f=await startFullFBroker({root:ROOT,output:join(ROOT,'.scratch/full-f-broker-tests',id),runId:id,port:0,localMock:true,heavyCapacity:4,heavyMemoryMb:24576,perBenchHeavySlots:2});
 const leases:any[]=[];const call=(body:any,path='/resource/acquire')=>fetch(f.connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+f.connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
  for(const [slug,pid] of [['skillsbench',101],['skillsbench',102],['terminal-bench',103],['terminal-bench',104]] as const){const r=await call({slug,pid,kind:'heavy-container'});expect(r.status).toBe(200);leases.push(await r.json());}
  expect(f.snapshot().availableResourceSlots['heavy-container']).toBe(0);
  expect((await call({slug:'skillsbench',pid:105,kind:'heavy-container'})).status).toBe(409);
  expect((await call({slug:'terminal-bench',pid:104,kind:'heavy-container',memoryMb:1})).status).toBe(409);
  expect((await call({...leases[0],token:'foreign'},'/resource/release')).status).toBe(409);
  expect(f.snapshot().resourceSlots.length).toBe(4);
 }finally{for(const l of leases)expect((await call(l,'/resource/release')).status).toBe(200);await f.stop();}
});
test('actual disk floor ignores predicted and cumulative storage growth',async()=>{
 let freeBytes=28*1024**3;const id='repair-local-parallel-disk-'+Date.now(),f=await startFullFBroker({root:ROOT,output:join(ROOT,'.scratch/full-f-broker-tests',id),runId:id,port:0,localMock:true,diskObserver:()=>({drive:'E:',driveType:3,freeBytes,observedAtMs:Date.now()})});
 const leases:any[]=[];const call=(body:any,path='/resource/acquire')=>fetch(f.connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+f.connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
  for(const [slug,pid] of [['skillsbench',201],['terminal-bench',202]] as const){const r=await call({slug,pid,kind:'heavy-container'});expect(r.status).toBe(200);leases.push(await r.json());}
  const third=await call({slug:'terminal-bench',pid:203,kind:'heavy-container'});expect(third.status).toBe(200);leases.push(await third.json());
  const smaller=await call({slug:'terminal-bench',pid:205,kind:'heavy-container',plannedGrowthBytes:0});expect(smaller.status).toBe(200);leases.push(await smaller.json());
  freeBytes=0;expect((await call({slug:'skillsbench',pid:204,kind:'heavy-container',plannedGrowthBytes:0})).status).toBe(409);
 }finally{for(const l of leases)expect((await call(l,'/resource/release')).status).toBe(200);await f.stop();}
});

 test('two independent paid lanes per container Bench remain bounded and cash closes separately',async()=>{
 const f=await fixture(undefined,true),leases:any[]=[],opened:any[]=[];
 const call=(body:any,path='/resource/acquire')=>fetch(f.broker.connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+f.broker.connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
 for(const [slug,pid] of [['skillsbench',301],['skillsbench',302],['terminal-bench',303],['terminal-bench',304]] as const){const r=await call({slug,pid,kind:'heavy-container'});expect(r.status).toBe(200);leases.push(await r.json());}
 for(const slug of ['skillsbench','terminal-bench']){const pair=await Promise.all([f.lane(slug,'digitalocean',undefined,11),f.lane(slug,'digitalocean',undefined,12)]);opened.push(...pair);await expect(f.lane(slug,'digitalocean',undefined,13)).rejects.toThrow('bench_already_active');}
 expect(new Set(opened.map(l=>l.admission.runId)).size).toBe(4);expect(f.allocated).toBe(65);expect(f.owners).toBe(1);
 expect(opened[0].admission.capUsd).toBe(15);expect(opened[2].admission.capUsd).toBe(17.5);
 for(const l of opened)await l.close();expect(f.broker.snapshot().lanes.every((l:any)=>l.closed)).toBe(true);
 }finally{for(const l of leases)expect((await call(l,'/resource/release')).status).toBe(200);await f.broker.stop();}
 });

test('human-authorized eight independent paid lanes per Bench retain sixteen slots, native cash and ninth-lane rejection',async()=>{
 const f=await fixture(undefined,true,8),leases:any[]=[],opened:any[]=[];
 const call=(body:any,path='/resource/acquire')=>fetch(f.broker.connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+f.broker.connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
 for(const slug of ['skillsbench','terminal-bench'])for(let n=0;n<8;n++){const r=await call({slug,pid:(slug==='skillsbench'?1000:2000)+n,kind:'heavy-container'});expect(r.status).toBe(200);leases.push(await r.json());}
 expect(f.broker.snapshot().resourceSlots.length).toBe(16);expect(f.broker.snapshot().availableResourceSlots['heavy-container']).toBe(0);
 expect((await call({slug:'skillsbench',pid:3000,kind:'heavy-container'})).status).toBe(409);
 for(const slug of ['skillsbench','terminal-bench']){opened.push(...await Promise.all(Array.from({length:8},(_,n)=>f.lane(slug,'digitalocean',undefined,100+n))));await expect(f.lane(slug,'digitalocean',undefined,999)).rejects.toThrow('bench_already_active');}
 expect(new Set(opened.map(l=>l.admission.runId)).size).toBe(16);expect(new Set(opened.map(l=>l.journal.directory)).size).toBe(16);expect(new Set(opened.map(l=>l.admission.proofPin.path)).size).toBe(16);
 expect(f.allocated).toBe(65);expect(f.owners).toBe(1);
 for(const l of opened)await l.close();expect(f.broker.snapshot().lanes.every((l:any)=>l.closed)).toBe(true);expect(f.registered).toBe(16);
 }finally{for(const l of leases)expect((await call(l,'/resource/release')).status).toBe(200);await f.broker.stop();}
});

test('sixteen borrowed slots above E and F actual floors ignore predicted growth and aggregate declared memory',async()=>{
 let efree=6*1024**3,ffree=6*1024**3;
 const id='repair-dynamic-floor-'+Date.now(),b=await startFullFBroker({root:ROOT,output:join(ROOT,'.scratch/full-f-broker-tests',id),runId:id,port:0,localMock:true,heavyCapacity:16,heavyMemoryMb:1,perBenchHeavySlots:16,
 diskObserver:()=>({drive:'E:',driveType:3,freeBytes:efree,observedAtMs:Date.now()}),hostDiskObserver:()=>({drive:'F:',driveType:3,freeBytes:ffree,observedAtMs:Date.now()})});
 const leases:any[]=[];const call=(body:any,path='/resource/acquire')=>fetch(b.connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+b.connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
  ffree=4*1024**3;expect((await call({slug:'skillsbench',pid:5000,kind:'heavy-container',memoryMb:16384,plannedGrowthBytes:100*1024**3})).status).toBe(409);
  ffree=6*1024**3;efree=4*1024**3;expect((await call({slug:'skillsbench',pid:5000,kind:'heavy-container',memoryMb:16384,plannedGrowthBytes:100*1024**3})).status).toBe(409);
  efree=6*1024**3;for(let n=0;n<16;n++){const r=await call({slug:'skillsbench',pid:5000+n,kind:'heavy-container',memoryMb:16384,plannedGrowthBytes:100*1024**3});expect(r.status).toBe(200);leases.push(await r.json());}
  expect(b.snapshot().resourceSlots.length).toBe(16);expect(b.snapshot().availableResourceSlots['heavy-container']).toBe(0);
  expect((await call({slug:'terminal-bench',pid:6000,kind:'heavy-container'})).status).toBe(409);
  expect((await call(leases.pop(),'/resource/release')).status).toBe(200);
  const borrowed=await call({slug:'terminal-bench',pid:6000,kind:'heavy-container'});expect(borrowed.status).toBe(200);leases.push(await borrowed.json());
 }finally{for(const l of leases)expect((await call(l,'/resource/release')).status).toBe(200);await b.stop();}
});
test('sixteen borrowed paid lanes retain unique native journals and closes',async()=>{
 const f=await fixture(undefined,true,16),leases:any[]=[],opened:any[]=[];
 const call=(body:any,path='/resource/acquire')=>fetch(f.broker.connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+f.broker.connection.accessToken,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
 for(let n=0;n<16;n++){const r=await call({slug:'skillsbench',pid:7000+n,kind:'heavy-container'});expect(r.status).toBe(200);leases.push(await r.json());}
 opened.push(...await Promise.all(Array.from({length:16},(_,n)=>f.lane('skillsbench','digitalocean',undefined,700+n))));
 expect(new Set(opened.map(l=>l.admission.runId)).size).toBe(16);expect(new Set(opened.map(l=>l.journal.directory)).size).toBe(16);expect(f.owners).toBe(1);expect(f.allocated).toBe(60);
 await expect(f.lane('skillsbench','digitalocean',undefined,9999)).rejects.toThrow('bench_already_active');
 for(const l of opened)await l.close();expect(f.broker.snapshot().lanes.every((l:any)=>l.closed)).toBe(true);expect(f.registered).toBe(16);
 }finally{for(const l of leases)expect((await call(l,'/resource/release')).status).toBe(200);await f.broker.stop();}
});
