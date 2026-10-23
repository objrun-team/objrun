/** Drop-in lane admission + transport for each Bench's ordinary journal/cash proxy. */
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, jsonPin, same, verifyPin, type Pin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { type UsdAdmission } from '../../../benchmark-repair/benchmark-usd-cash.ts';
import { CapturedTransportFailure, ConfirmedNoForwardTransportFailure } from '../../../benchmark-repair/scientific-journal-proxy.ts';

function check(ok:unknown,code:string):asserts ok {if(!ok)throw new Error(code);}
export type FullFConnection={endpoint:string;accessToken:string;runId:string;pid:number;healthPath:string;sourcePins:Pin[]};
export const BENCH_CODES:Record<string,string>={chembench:'11',chemiq:'12',skillsbench:'13','terminal-bench':'14'};
export function fullFConnection(root:string):FullFConnection {const c=JSON.parse(readFileSync(join(root,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8'));check(c.paidReady===true&&c.broker,'shared_broker_not_ready');return c.broker;}
export function fullFRunId(root:string,slug:string) {const c=fullFConnection(root);check(BENCH_CODES[slug],'bench_not_in_requested_scope');return c.runId+'-'+BENCH_CODES[slug]+'-'+new Date().toISOString().replace(/[:.]/g,'-');}
async function rpc(connection:FullFConnection,path:string,body:any,token?:string) {
  const r=await fetch(connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+connection.accessToken,'content-type':'application/json',...(token?{'x-bench-lane-token':token}:{})},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  const d=await r.json() as any;check(r.ok,d.error??'broker_rpc_failed');return d;
}
export type SharedFullFAdmission=UsdAdmission&{root:string;path:string;prices:Pin;balance:Pin;sourcePins:Pin[];connection:FullFConnection;
  transport(raw:string):Promise<{httpStatus:number;rawResponse:string}>;registerOwnedProcess(pin:Pin):Promise<void>;
  finishLightweight(result:{cashPin:Pin;[key:string]:unknown}):Promise<any>;release(result:{cashPin:Pin;[key:string]:unknown}):Promise<void>};
export async function acquireFullFAdmission(input:{root:string;output:string;runId:string;slug:string;sourcePins:Pin[];connection?:FullFConnection;providerSlug?:string}):Promise<SharedFullFAdmission> {
  const connection=input.connection??fullFConnection(input.root),claim=await rpc(connection,'/lane/claim',input),parent=jsonPin(claim.parentAdmissionPin);
  check(claim.protocol==='full-f-shared-lane-v1'&&claim.runId===input.runId&&parent.owned.ownerNonce===claim.owned.ownerNonce,'shared_lane_parent_binding');
  const laneProof=jsonPin(claim.proofPin);check(laneProof.runId===input.runId&&laneProof.capUsd===claim.capUsd&&same(laneProof.parentAdmissionPin,claim.parentAdmissionPin),'shared_lane_proof_binding');
  let closed=false;
  const assertOwned=()=>{check(!closed,'shared_lane_closed');check(same(JSON.parse(readFileSync(claim.canonicalLockPath,'utf8')),parent.owned),'shared_canonical_owner_changed');};
  const validateForwardSource=()=>{assertOwned();verifyPin(claim.proofPin);verifyPin(claim.parentAdmissionPin);for(const pin of [...connection.sourcePins,...input.sourcePins,claim.prices,claim.balance])verifyPin(pin);
    const status=JSON.parse(readFileSync(claim.healthPath,'utf8'));check(status.pid===connection.pid&&status.runId===connection.runId&&status.healthy===true&&Date.now()-Date.parse(status.atUtc)<30000,'shared_broker_unhealthy');
    const prices=jsonPin(claim.prices);check(Date.now()>=Date.parse(prices.observedAtUtc)&&Date.now()-Date.parse(prices.observedAtUtc)<=86400000,'openrouter_price_expired');};
  const close=async(result:{cashPin:Pin;[key:string]:unknown})=>{assertOwned();const receipt=await rpc(connection,'/lane/close?runId='+encodeURIComponent(input.runId),{cashPin:result.cashPin},claim.laneToken);closed=true;return receipt;};
  return {currency:'USD',root:input.root,path:claim.canonicalLockPath,runId:input.runId,capUsd:claim.capUsd,owned:claim.owned,proofPin:claim.proofPin,scope:'production',
    prices:claim.prices,balance:claim.balance,sourcePins:input.sourcePins,connection,assertOwned,validateForwardSource,
    registerCash(pin){assertOwned();verifyPin(pin);mkdirSync(resolve(claim.registrationPath,'..'),{recursive:true});const fd=openSync(claim.registrationPath,'wx',0o600);try{writeFileSync(fd,JSON.stringify({runId:input.runId,cashPin:pin})+'\n');fsyncSync(fd);}finally{closeSync(fd);}},
    async registerOwnedProcess(pin){assertOwned();await rpc(connection,'/lane/process?runId='+encodeURIComponent(input.runId),{pin},claim.laneToken);},
    finishLightweight:close,async release(result){await close(result);},
    async transport(raw){
      try{validateForwardSource();}catch(error){throw new ConfirmedNoForwardTransportFailure(String(error));}
      const headers={authorization:'Bearer '+connection.accessToken,'x-bench-lane-token':claim.laneToken,'content-type':'application/json'};
      // Queue/provider waiting is outside individual HTTP exchanges. Task deadlines stay in the Bench gate.
      const deadline=Date.now()+1200000;
      let response=await fetch(connection.endpoint+'/forward?runId='+encodeURIComponent(input.runId),{method:'POST',headers,body:raw,signal:AbortSignal.timeout(30000)});
      let ticket:string|undefined;
      while(response.status===202){
        const pending=await response.json() as any;
        check(pending.protocol==='full-f-forward-ticket-v1'&&pending.runId===input.runId&&typeof pending.ticket==='string'&&(!ticket||ticket===pending.ticket),'invalid_forward_ticket');
        ticket=pending.ticket;
        check(Date.now()<deadline,'shared_forward_result_deadline');await Bun.sleep(250);
        response=await fetch(connection.endpoint+'/forward/result?runId='+encodeURIComponent(input.runId)+'&ticket='+encodeURIComponent(ticket!),{headers,signal:AbortSignal.timeout(Math.min(30000,deadline-Date.now()))});
      }
      if(response.headers.get('x-bench-provider-attempted')==='false'&&(!ticket||response.headers.get('x-bench-forward-ticket')===ticket)){
        const rejection=await response.json() as any;
        check(rejection?.error?.code==='bench_local_not_forwarded','unproven_local_rejection');
        throw new ConfirmedNoForwardTransportFailure(rejection.error.message);
      }
      const bytes=new Uint8Array(await response.arrayBuffer());if(response.headers.get('x-bench-body-complete')==='false')throw new CapturedTransportFailure({httpStatus:response.status,rawBytes:bytes,bodyComplete:false,fault:response.headers.get('x-bench-fault')??'ProviderResponseBodyError'});
      return {httpStatus:response.status,rawResponse:new TextDecoder('utf8',{fatal:true}).decode(bytes)};
    }};
}
export async function acquireFullFResource(root:string,slug:string,kind:'heavy-container'|'lean-repl',connection=fullFConnection(root)) {
  const result=await rpc(connection,'/resource/acquire',{slug,kind,pid:process.pid});let released=false;
  return {kind,slug,pid:process.pid,async release(){check(!released,'resource_already_released');await rpc(connection,'/resource/release',{slug,kind,pid:process.pid,token:result.token});released=true;}};
}
