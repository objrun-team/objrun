/** Dedicated byte verification thread. No broker, provider, queue, resource or financial mutation. */
import {readFileSync} from 'node:fs';import {createHash,verify} from 'node:crypto';
import {verifyPin} from '../repair-2026-10-08/paid-resource-proof-v2.ts';
const digest=(s:string)=>createHash('sha256').update(s).digest('hex');
self.onmessage=(event:any)=>{
 const m=event.data;
 try{
  if(m.protocol!=='bench-pinned-source-worker-request-v1'||m.inputSha256!==digest(JSON.stringify(m.input))||typeof m.nonce!=='string'||!Number.isSafeInteger(m.ownerPid)||!m.ownerIncarnation)throw Error('byte_worker_request_identity');
  for(const p of m.input.pins)verifyPin(p);
  for(const s of m.input.signatures??[]){
   verifyPin(s.envelopePin);verifyPin(s.publicKeyPin);
   if(s.publicKeyPin.sha256!=='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98')throw Error('byte_worker_original_authority');
   const e=JSON.parse(readFileSync(s.envelopePin.path,'utf8'));
   if(e.protocol!==s.protocol||!e[s.payloadField]||!verify(null,Buffer.from(JSON.stringify(e[s.payloadField])),readFileSync(s.publicKeyPin.path),Buffer.from(e.signature,'base64')))throw Error('byte_worker_signature');
  }
  self.postMessage({protocol:'bench-pinned-source-worker-result-v1',nonce:m.nonce,ownerPid:m.ownerPid,ownerIncarnation:m.ownerIncarnation,inputSha256:m.inputSha256,verified:true,pinsReadAndHashed:m.input.pins.length,signaturesVerified:(m.input.signatures??[]).length});
 }catch(error){self.postMessage({protocol:'bench-pinned-source-worker-result-v1',nonce:m?.nonce,ownerPid:m?.ownerPid,ownerIncarnation:m?.ownerIncarnation,inputSha256:m?.inputSha256,verified:false,error:String(error)});}
};
