/** A proof is usable only inside the request which actually read every byte. */
import {AsyncLocalStorage} from 'node:async_hooks';
import {lstatSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {processIdentity} from './runtime.ts';
import {verifyPin as originalVerifyPin,demand} from '../repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifySourceBatchInWorker,type SourceBatch} from './pinned-source-worker-v1.ts';
import type {Pin} from './types.ts';
type Scope={nonce:string;ownerPid:number;ownerIncarnation:string;deadlineMs:number;descriptors:Map<string,{descriptor:string;size:number;mtimeMs:number;ino:number}>;closed:boolean};
const scope=new AsyncLocalStorage<Scope>();
const workerPin:Pin={path:join(import.meta.dir,'pinned-source-worker-child-v1.ts'),bytes:1688,sha256:'faed27b74294f97816cff82bccb18d820ad1b5d19258ebfa99f6530b1f418356'};
const descriptor=(p:Pin)=>JSON.stringify([resolve(p.path),p.bytes,p.sha256]);
export function verifyPinInCurrentSourceRequest(p:Pin){
 const s=scope.getStore();
 if(!s)return originalVerifyPin(p);
 demand(!s.closed&&Date.now()<=s.deadlineMs&&process.pid===s.ownerPid&&processIdentity(process.pid).incarnation===s.ownerIncarnation,'request_byte_proof_identity_or_lifetime');
 const verified=s.descriptors.get(resolve(p.path));
 // A pin not covered by this exact nonce must still execute the original verifier.
 if(!verified)return originalVerifyPin(p);
 demand(verified.descriptor===descriptor(p),'request_byte_proof_descriptor_changed');
 const now=lstatSync(p.path);
 demand(now.size===verified.size&&now.mtimeMs===verified.mtimeMs&&now.ino===verified.ino,'request_byte_proof_file_changed_after_worker');
}
export async function runPinnedSourceRequest<T>(input:SourceBatch,deadlineMs:number,fn:()=>T|Promise<T>){
 const owner=processIdentity(process.pid),identity=JSON.stringify([process.pid,owner.incarnation]);
 // Never reuse the enclosing request's receipt, even for nested calls.
 const receipt=await verifySourceBatchInWorker(input,{workerPin,deadlineMs,contextIdentity:()=>JSON.stringify([process.pid,processIdentity(process.pid).incarnation]),expectedContextIdentity:identity});
 const descriptors=new Map<string,{descriptor:string;size:number;mtimeMs:number;ino:number}>();
 for(const p of input.pins){const x=lstatSync(p.path),key=resolve(p.path),prior=descriptors.get(key);demand(!prior||prior.descriptor===descriptor(p),'request_byte_proof_conflicting_descriptors');descriptors.set(key,{descriptor:descriptor(p),size:x.size,mtimeMs:x.mtimeMs,ino:x.ino});}
 const s:Scope={nonce:receipt.nonce,ownerPid:process.pid,ownerIncarnation:owner.incarnation,deadlineMs,descriptors,closed:false};
 try{return await scope.run(s,fn)}finally{s.closed=true;}
}
export function currentSourceRequestIdentity(){const s=scope.getStore();return s?{nonce:s.nonce,ownerPid:s.ownerPid,ownerIncarnation:s.ownerIncarnation,closed:s.closed,descriptorCount:s.descriptors.size}:null;}
/** A queued job outlives the HTTP 202 response and must obtain its own receipt. */
export function runOutsidePinnedSourceRequest<T>(fn:()=>T):T{return scope.exit(fn);}
