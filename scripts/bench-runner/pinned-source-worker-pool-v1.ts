/** Fixed verification threads; every job reads all bytes under a fresh nonce. */
import {createHash,randomUUID} from 'node:crypto';
import {lstatSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {processIdentity} from './runtime.ts';
import {verifyPin,demand} from './manifest.ts';
import {assertWorkerReceipt,type SourceBatch} from './pinned-source-worker-v1.ts';
import type {Pin} from './types.ts';
type Expected={nonce:string;ownerPid:number;ownerIncarnation:string;inputSha256:string};
type Job={input:SourceBatch;expected:Expected;deadline:number;resolve:(x:any)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>;settled:boolean};
type Slot={worker:Worker;job?:Job;broken:boolean};
const MAX_WORKERS=4,MAX_PENDING=64,slots:Slot[]=[],pending:Job[]=[];
let descriptor:string|undefined;
function fail(job:Job,error:Error){if(!job.settled){job.settled=true;clearTimeout(job.timer);job.reject(error)}}
function pump(){
 for(const slot of slots){
  if(slot.broken||slot.job)continue;
  let job:Job|undefined;
  while((job=pending.shift())){if(job.settled)continue;if(Date.now()>job.deadline){fail(job,Error('byte_worker_original_deadline'));continue}break}
  if(!job)continue;
  slot.job=job;slot.worker.ref();
  slot.worker.postMessage({protocol:'bench-pinned-source-worker-request-v1',...job.expected,input:job.input});
 }
}
function initialize(pin:Pin){
 const key=JSON.stringify(pin);demand(!descriptor||descriptor===key,'byte_worker_pool_descriptor_changed');
 if(descriptor)return;descriptor=key;
 for(let i=0;i<MAX_WORKERS;i++){
  const slot:Slot={worker:new Worker(pathToFileURL(pin.path).href),broken:false};
  slot.worker.unref();
  slot.worker.onmessage=e=>{
   const job=slot.job;
   if(!job){slot.broken=true;slot.worker.unref();return}
   try{assertWorkerReceipt(e.data,job.expected);if(!job.settled){demand(Date.now()<=job.deadline,'byte_worker_original_deadline');job.settled=true;clearTimeout(job.timer);job.resolve(e.data)}}catch(error){fail(job,error instanceof Error?error:Error(String(error)))}
   slot.job=undefined;slot.worker.unref();pump();
  };
  slot.worker.onerror=e=>{slot.broken=true;if(slot.job)fail(slot.job,Error('byte_worker_thread_error:'+e.message));slot.job=undefined;slot.worker.unref();for(const job of pending.splice(0))fail(job,Error('byte_worker_pool_failed_closed'))};
  slots.push(slot);
 }
}
export function sourceWorkerPoolState(){return{maximumWorkers:MAX_WORKERS,maximumPending:MAX_PENDING,workers:slots.length,active:slots.filter(x=>x.job).length,pending:pending.length,broken:slots.filter(x=>x.broken).length}}
export async function verifySourceBatchInWorker(input:SourceBatch,options:{workerPin:Pin;deadlineMs:number;contextIdentity:()=>string;expectedContextIdentity:string}){
 demand(Array.isArray(input.pins)&&input.pins.length>0&&Number.isSafeInteger(options.deadlineMs)&&options.deadlineMs>Date.now(),'byte_worker_input_and_deadline');
 demand(options.workerPin.path.replaceAll('\\','/').endsWith('/pinned-source-worker-child-v1.ts'),'byte_worker_exact_entry');verifyPin(options.workerPin);
 demand(options.contextIdentity()===options.expectedContextIdentity,'byte_worker_context_changed_before');
 const snapshots=input.pins.map(p=>{const x=lstatSync(p.path);return{size:x.size,mtimeMs:x.mtimeMs,ino:x.ino}});
 const expected:Expected={nonce:randomUUID(),ownerPid:process.pid,ownerIncarnation:processIdentity(process.pid).incarnation,inputSha256:createHash('sha256').update(JSON.stringify(input)).digest('hex')};
 initialize(options.workerPin);demand(slots.every(x=>!x.broken),'byte_worker_pool_failed_closed');demand(pending.length<MAX_PENDING,'byte_worker_pool_bounded_queue');
 const receipt:any=await new Promise((resolve,reject)=>{
  const job={}as Job;Object.assign(job,{input,expected,deadline:options.deadlineMs,resolve,reject,settled:false});
  job.timer=setTimeout(()=>{fail(job,Error('byte_worker_original_deadline'));const at=pending.indexOf(job);if(at>=0)pending.splice(at,1)},Math.max(1,options.deadlineMs-Date.now()));pending.push(job);pump();
 });
 demand(Date.now()<=options.deadlineMs,'byte_worker_original_deadline');
 demand(createHash('sha256').update(JSON.stringify(input)).digest('hex')===expected.inputSha256,'byte_worker_input_changed_after');
 demand(processIdentity(process.pid).incarnation===expected.ownerIncarnation,'byte_worker_owner_changed');
 demand(options.contextIdentity()===options.expectedContextIdentity,'byte_worker_context_changed_after');
 for(let i=0;i<input.pins.length;i++){const x=lstatSync(input.pins[i].path),b=snapshots[i];demand(x.size===b.size&&x.mtimeMs===b.mtimeMs&&x.ino===b.ino,'byte_worker_file_changed_during_validation')}
 verifyPin(options.workerPin);return{...receipt,noCachedHashUsed:true};
}
