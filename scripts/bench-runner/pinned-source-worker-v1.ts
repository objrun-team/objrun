/** Per-request verification only. Callers must retain original admission/cash ordering after await. */
import {createHash,randomUUID} from 'node:crypto';import {lstatSync} from 'node:fs';
import {join} from 'node:path';import {processIdentity} from './runtime.ts';
import {pathToFileURL} from 'node:url';
import {pin,verifyPin,demand} from './manifest.ts';import type {Pin} from './types.ts';
export interface SourceBatch {pins:Pin[];signatures?:{envelopePin:Pin;publicKeyPin:Pin;protocol:string;payloadField:string}[]}
export function assertWorkerReceipt(m:any,expected:{nonce:string;ownerPid:number;ownerIncarnation:string;inputSha256:string}){
 demand(m?.protocol==='bench-pinned-source-worker-result-v1'&&m.nonce===expected.nonce&&m.ownerPid===expected.ownerPid&&m.ownerIncarnation===expected.ownerIncarnation&&m.inputSha256===expected.inputSha256,'byte_worker_response_identity');
 demand(m.verified===true,'byte_worker_verification_failed:'+String(m.error??''));
}
export async function verifySourceBatchInWorker(input:SourceBatch,options:{workerPin:Pin;deadlineMs:number;contextIdentity:()=>string;expectedContextIdentity:string}){
 demand(Array.isArray(input.pins)&&input.pins.length>0&&Number.isSafeInteger(options.deadlineMs)&&options.deadlineMs>Date.now(),'byte_worker_input_and_deadline');
 demand(options.workerPin.path.replaceAll('\\','/').endsWith('/pinned-source-worker-child-v1.ts'),'byte_worker_exact_entry');verifyPin(options.workerPin);
 demand(options.contextIdentity()===options.expectedContextIdentity,'byte_worker_context_changed_before');
 // Supplement actual full hashing with a before/after file identity check, never replace hashing with stat/mtime caching.
 const snapshots=input.pins.map(p=>{const x=lstatSync(p.path);return {size:x.size,mtimeMs:x.mtimeMs,ino:x.ino};});
 const expected={nonce:randomUUID(),ownerPid:process.pid,ownerIncarnation:processIdentity(process.pid).incarnation,inputSha256:createHash('sha256').update(JSON.stringify(input)).digest('hex')};
 const worker=new Worker(pathToFileURL(options.workerPin.path).href);let timer:ReturnType<typeof setTimeout>|undefined;
 try{
  const receipt:any=await new Promise((resolve,reject)=>{
   timer=setTimeout(()=>reject(Error('byte_worker_original_deadline')),Math.max(1,options.deadlineMs-Date.now()));
   worker.onerror=e=>reject(Error('byte_worker_thread_error:'+e.message));
   worker.onmessage=e=>{try{assertWorkerReceipt(e.data,expected);resolve(e.data)}catch(error){reject(error)}};
   worker.postMessage({protocol:'bench-pinned-source-worker-request-v1',...expected,input});
  });
  demand(Date.now()<=options.deadlineMs,'byte_worker_original_deadline');
  demand(createHash('sha256').update(JSON.stringify(input)).digest('hex')===expected.inputSha256,'byte_worker_input_changed_after');
  demand(processIdentity(process.pid).incarnation===expected.ownerIncarnation,'byte_worker_owner_changed');
  demand(options.contextIdentity()===options.expectedContextIdentity,'byte_worker_context_changed_after');
  for(let i=0;i<input.pins.length;i++){const x=lstatSync(input.pins[i].path),before=snapshots[i];demand(x.size===before.size&&x.mtimeMs===before.mtimeMs&&x.ino===before.ino,'byte_worker_file_changed_during_validation');}
  verifyPin(options.workerPin);return {...receipt,noCachedHashUsed:true};
 }finally{if(timer)clearTimeout(timer);worker.terminate();}
}
export const currentByteWorkerPin=()=>pin(join(import.meta.dir,'pinned-source-worker-child-v1.ts'));
