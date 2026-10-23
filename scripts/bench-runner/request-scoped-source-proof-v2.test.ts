import {test,expect} from 'bun:test';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';import {tmpdir} from 'node:os';
import {pin} from './manifest.ts';
import {runPinnedSourceRequest,verifyPinInCurrentSourceRequest,currentSourceRequestIdentity,runOutsidePinnedSourceRequest} from './request-scoped-source-proof-v2.ts';
import {asyncAdoptionSource} from './async-adoption-source-v2.ts';
const temp=mkdtempSync(join(tmpdir(),'request-byte-proof-'));
const file=join(temp,'source.txt');writeFileSync(file,'actual original source');
const p=pin(file);
test('each HTTP request gets a new actual-byte nonce; nested scope restores the outer proof',async()=>{
 let outer:any,inner:any;
 await runPinnedSourceRequest({pins:[p,p]},Date.now()+5000,async()=>{
  outer=currentSourceRequestIdentity();verifyPinInCurrentSourceRequest(p);
  await runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{inner=currentSourceRequestIdentity();verifyPinInCurrentSourceRequest(p)});
  expect(currentSourceRequestIdentity()?.nonce).toBe(outer.nonce);
 });
 expect(outer.nonce).not.toBe(inner.nonce);expect(currentSourceRequestIdentity()).toBeNull();
});
test('changed real bytes fail before the guarded callback',async()=>{
 writeFileSync(file,'altered original source');let entered=false;
 await expect(runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{entered=true})).rejects.toThrow();
 expect(entered).toBe(false);writeFileSync(file,'actual original source');
});
test('receipt cannot authorize another descriptor or changed bytes after await',async()=>{
 await runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{
  expect(()=>verifyPinInCurrentSourceRequest({...p,sha256:'0'.repeat(64)})).toThrow('descriptor_changed');
  writeFileSync(file,'changed after worker');expect(()=>verifyPinInCurrentSourceRequest(p)).toThrow();
 });writeFileSync(file,'actual original source');
});
test('escaping asynchronous work cannot reuse a completed request proof',async()=>{
 let later:Promise<any>;
 await runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{later=new Promise(resolve=>setTimeout(()=>{try{verifyPinInCurrentSourceRequest(p);resolve('wrong')}catch(e){resolve(String(e))}},30));});
 expect(await later!).toContain('identity_or_lifetime');
});
test('queued execution survives its HTTP response only by acquiring an independent receipt',async()=>{
 let job:Promise<any>;let httpNonce:string;
 await runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{
  httpNonce=currentSourceRequestIdentity()!.nonce;
  job=runOutsidePinnedSourceRequest(async()=>{await Bun.sleep(30);expect(currentSourceRequestIdentity()).toBeNull();return runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{verifyPinInCurrentSourceRequest(p);return currentSourceRequestIdentity()!.nonce});});
 });expect(await job!).not.toBe(httpNonce!);
});
test('original durable-state check still runs after the worker resumes',async()=>{
 let diskState='original',inMemoryState='original',forwarded=false;
 const wait=runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{if(diskState!==inMemoryState)throw Error('unlimited_durable_financial_state_changed');forwarded=true});
 diskState='mutated';await expect(wait).rejects.toThrow('unlimited_durable_financial_state_changed');expect(forwarded).toBe(false);
});
test('parallel requests retain independent nonces and original serialized ticket consumption',async()=>{
 let pending=true;const outcomes=await Promise.all([1,2].map(()=>runPinnedSourceRequest({pins:[p]},Date.now()+5000,()=>{
  const nonce=currentSourceRequestIdentity()!.nonce;
  if(!pending)return{nonce,dispatched:false};pending=false;return{nonce,dispatched:true};
 })));
 expect(outcomes[0]!.nonce).not.toBe(outcomes[1]!.nonce);expect(outcomes.filter(x=>x.dispatched)).toHaveLength(1);
});
test('exact original broker/parent source anchors compile without changing live sources',()=>{
 const base=join(import.meta.dir,'..'),parent=join(import.meta.dir,'unlimited-adopted-parent.ts'),broker=join(base,'repair-2026-10-10/full-f/novaeve_formal_v1/broker/broker-adoption-v76.ts');
 for(const path of[parent,broker]){const raw=readFileSync(path,'utf8'),candidate=asyncAdoptionSource(path,raw);expect(candidate).not.toBe(raw);expect(()=>new Bun.Transpiler({loader:'ts'}).transformSync(candidate)).not.toThrow();expect(readFileSync(path,'utf8')).toBe(raw);}
 const candidate=asyncAdoptionSource(parent,readFileSync(parent,'utf8'));
 expect(candidate).toContain("'unlimited_durable_financial_state_changed'");expect(candidate).toContain("'single_financial_executor_identity'");expect(candidate).toContain("'original_fresh_actual_prices'");
});
