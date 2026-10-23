import {test,expect} from 'bun:test';import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';
import {pin} from './manifest.ts';import {verifySourceBatchInWorker,currentByteWorkerPin,assertWorkerReceipt} from './pinned-source-worker-v1.ts';
const dir=mkdtempSync(join(tmpdir(),'byte-worker-')),path=join(dir,'neutral.txt');writeFileSync(path,'neutral metadata fixture\n');
const options=(context=()=> 'lane:nonce:cash0')=>({workerPin:currentByteWorkerPin(),deadlineMs:Date.now()+20000,contextIdentity:context,expectedContextIdentity:context()});
test('every call actually rehashes bytes, rejecting later mutation without a hash cache',async()=>{
 const p=pin(path);const r=await verifySourceBatchInWorker({pins:[p]},options());expect(r.verified).toBe(true);expect(r.pinsReadAndHashed).toBe(1);expect(r.noCachedHashUsed).toBe(true);
 writeFileSync(path,'mutated bytes\n');await expect(verifySourceBatchInWorker({pins:[p]},options())).rejects.toThrow('byte_worker_verification_failed');writeFileSync(path,'neutral metadata fixture\n');
});
test('per-request nonce, actual process identity and request digest all bind replies',()=>{
 const e={nonce:'n',ownerPid:100,ownerIncarnation:'ft',inputSha256:'digest'},r={protocol:'bench-pinned-source-worker-result-v1',...e,verified:true};
 expect(()=>assertWorkerReceipt(r,e)).not.toThrow();for(const k of ['nonce','ownerPid','ownerIncarnation','inputSha256'])expect(()=>assertWorkerReceipt({...r,[k]:'other'},e)).toThrow('byte_worker_response_identity');
 expect(()=>assertWorkerReceipt({...r,verified:false},e)).toThrow('byte_worker_verification_failed');
});
test('real original Ed-signed source config verifies; payload rewrite with a new full hash still rejects',async()=>{
 const h=resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013'),good=pin(join(h,'coordinator/universal-runner/provider-switch-preparation/signed-fireworks-probe-preparation-v1/source-loader.task-route-v3.infra-signed.json')),key=pin(join(h,'coordinator/review-authority.public.pem'));
 const input={pins:[good],signatures:[{envelopePin:good,publicKeyPin:key,protocol:'bench-signed-financial-source-config-v1',payloadField:'config'}]};expect((await verifySourceBatchInWorker(input,options())).signaturesVerified).toBe(1);
 const bad=JSON.parse(readFileSync(good.path,'utf8'));bad.config.reviewedBy='fixture-tamper';const q=join(dir,'tampered-envelope.json');writeFileSync(q,JSON.stringify(bad));const badPin=pin(q);
 await expect(verifySourceBatchInWorker({pins:[badPin],signatures:[{...input.signatures[0],envelopePin:badPin}]},options())).rejects.toThrow('byte_worker_signature');
});
test('cash or lane generation mutation while validation runs prevents commit/forward',async()=>{
 let context='lane:nonce:cash0',forwards=0;const p=pin(process.execPath),o=options(()=>context);const promise=verifySourceBatchInWorker({pins:Array(4).fill(p)},o).then(()=>forwards++);setTimeout(()=>{context='lane:nonce:cash1'},1);
 await expect(promise).rejects.toThrow('byte_worker_context_changed_after');expect(forwards).toBe(0);
});
test('two concurrent same-context requests cannot both commit after the first cash generation changes',async()=>{
 let generation=0,forwards=0;const context=()=>String(generation),o=options(context);
 const execute=()=>verifySourceBatchInWorker({pins:[pin(process.execPath)]},o).then(()=>{forwards++;generation++;});
 const results=await Promise.allSettled([execute(),execute()]);expect(results.filter(r=>r.status==='fulfilled')).toHaveLength(1);expect(results.filter(r=>r.status==='rejected')).toHaveLength(1);expect(forwards).toBe(1);
});
test('expired original deadline rejects without starting a worker',async()=>{
 await expect(verifySourceBatchInWorker({pins:[pin(path)]},{...options(),deadlineMs:Date.now()-1})).rejects.toThrow('byte_worker_input_and_deadline');
});
test('a caller cannot change the descriptor after the worker has received a clone',async()=>{
 const input={pins:Array(4).fill(pin(process.execPath))};const running=verifySourceBatchInWorker(input,options());setTimeout(()=>{input.pins=[]},1);
 await expect(running).rejects.toThrow('byte_worker_input_changed_after');
});
