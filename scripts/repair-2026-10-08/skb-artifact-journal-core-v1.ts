/** Shared single-proxy accounting lifecycle for the prospective artifact pilot.
 * No source-family score audit or paid-lock release is performed by this core.
 */
import { join, resolve } from 'node:path';
import { createCampaignJournal, inspectCampaignJournal } from './campaign-journal.ts';
import { ScientificJournalProxy, type TaskReceipt } from './scientific-journal-proxy.ts';
import { createCnyCashShadow, type CashTicket } from './cny-cash-shadow-v2.ts';
import { actualPin, demand, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { type AdmissionLease } from './paid-resource-admission-v2.ts';
import { SKB_ARTIFACT_FAMILY, type SkbScheduleRow } from './skb-artifact-journal-contract.ts';
import { type SkbStorageDescriptor } from './skb-artifact-storage.ts';

const JOURNAL_SOURCE_SHA='139a28eadf4fd570c04796430a419bfbba6ec0cc8d14eb28c2a4ef480cc90a56';
export const SKB_CAPTURE_RESERVE_PER_PENDING_BYTES=72*1024**2;
export const SKB_CAPTURE_RESERVE_ALL_PENDING_BYTES=4*SKB_CAPTURE_RESERVE_PER_PENDING_BYTES;
export type SkbFeeQueueInput={
  runId:string;providerKind:'real-provider'|'local-mock';capUsd:number;priorCostUpperBoundUsd:number;prices:Pin;admission?:AdmissionLease;
  storage:SkbStorageDescriptor;sourcePins:Pin[];schedule:SkbScheduleRow[];
  beforeProducerAdmission(reservationBytes:number):void;
  transport(raw:string,route:string):Promise<{httpStatus:number;rawResponse:string}>;
};
/** Configure only after exact family/scope/resource/source gates have passed. */
export function createSkbArtifactFeeQueue(input:SkbFeeQueueInput){
  demand(input.schedule.length===20&&new Set(input.schedule.map(r=>r.route)).size===20,'skb_shared_proxy_twenty_routes');
  const routes=new Set(input.schedule.map(r=>r.route)),sealed=new Set<string>(),tickets=new Map<number,CashTicket>(),receipts=new Map<string,TaskReceipt[]>();
  for(const route of routes)receipts.set(route,[]);
  if(input.providerKind==='real-provider')demand(input.admission?.scope==='production'&&input.admission.owned.family===SKB_ARTIFACT_FAMILY&&input.admission.runId===input.runId,'skb_explicit_own_family_admission');
  else demand(input.providerKind==='local-mock'&&input.admission===undefined,'skb_fixture_no_production_owner');
  const sourceCheck=()=>{for(const p of input.sourcePins)verifyPin(p);verifyPin(input.prices);input.admission?.validateForwardSource();};
  sourceCheck();input.beforeProducerAdmission(SKB_CAPTURE_RESERVE_ALL_PENDING_BYTES);
  const directory=input.storage.directories.journal!,output=input.storage.directories.taskmeta!;
  const journal=createCampaignJournal({directory,campaign:input.runId,capUsd:input.capUsd,priorCampaignCostUpperBoundUsd:input.priorCostUpperBoundUsd,outputDirectory:output});
  let cash:ReturnType<typeof createCnyCashShadow>;
  try{cash=createCnyCashShadow({directory:input.storage.directories.cash!,runId:input.runId,providerKind:input.providerKind,admission:input.admission,prices:input.prices,
    journal:{directory,configPin:actualPin(join(directory,'journal-config.json')),sourcePin:{path:join(import.meta.dir,'campaign-journal.ts'),sha256:JOURNAL_SOURCE_SHA}}});}
  catch(error){journal.close();throw error;}
  const proxy=new ScientificJournalProxy(journal,{routes,failureDirectory:join(input.storage.directories.raw!,'failure-receipts'),
    beforeAdmission:()=>{demand(!cash.snapshot().poisoned,'skb_cash_admission_poisoned');sourceCheck();input.beforeProducerAdmission(SKB_CAPTURE_RESERVE_ALL_PENDING_BYTES);},
    beforeForward:(a,prefix,raw,route)=>{
      const funding=cash.beforeForward({id:input.runId+'/'+a.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(a.requestFile),journal:{admitted:a,startPrefix:prefix}});
      tickets.set(a.requestSeq,funding.ticket);demand(funding.admitted,'skb_cash_envelope_exhausted');
    },
    afterDurableFinish:r=>{const ticket=tickets.get(r.requestSeq);if(ticket)cash.finish(ticket,{kind:'journal-finish',journalRef:{...r.journalRef,callId:String(r.requestSeq)}});},
    // The original finish is not silently repaired/repeated. This independent
    // evidence preserves every late complete gzip even after a global poison.
    afterFailedJournalCapture:(a,_f,e:any)=>{
      if(!a)return;const ticket=tickets.get(a.requestSeq);if(!ticket)return;
      if(e.journalRef)cash.finish(ticket,{kind:'journal-finish',journalRef:{...e.journalRef,callId:String(a.requestSeq)}});
      else cash.finish(ticket,{kind:'failed-capture',requestSeq:a.requestSeq,evidence:{files:e.files,responsePin:e.files.find((p:Pin)=>p.path.endsWith('response.json.gz')),rawResponseSha256:e.rawResponseSha256,usage:e.usage,httpStatus:e.httpStatus,providerAttempted:e.providerAttempted,originalPrefix:e.journalSnapshot.durablePrefix,reason:e.error}});
    },transport:input.transport});
  let stopping=false,closed=false,closeProof:Pin|undefined;
  const stop=(reason:string)=>{if(stopping)return;stopping=true;proxy.stop(reason);};
  const poison=(reason:string)=>{stop(reason);cash.poison(reason);};
  const record=(r:TaskReceipt)=>{demand(receipts.has(r.route),'skb_task_local_route');receipts.get(r.route)!.push(r);};
  return Object.freeze({
    family:SKB_ARTIFACT_FAMILY,journal,cash,proxy,record,poison,stop,
    sealRoute(route:string){demand(routes.has(route),'skb_unknown_route_seal');sealed.add(route);},
    async handle(route:string,raw:string){demand(routes.has(route)&&!sealed.has(route)&&!stopping&&!closed,'skb_delivered_or_closed_model_route');return proxy.handle(route,raw);},
    taskReceipts(route:string){demand(receipts.has(route),'skb_task_local_route');return receipts.get(route)!.slice().sort((a,b)=>a.requestSeq-b.requestSeq);},
    async drain(){stop('delivery_closed');await proxy.drain();},
    /** Exactly one terminal export. Caller first closes all owned producers. */
    async exportClosedAccounting(){
      demand(!closed&&!closeProof,'skb_export_once');stop('all_generation_closed');await proxy.drain();sourceCheck();
      const inspection=inspectCampaignJournal(directory);demand(inspection.valid&&inspection.accountingClosed&&inspection.eligibleForScoreCertification&&proxy.anomalies.length===0,'skb_journal_or_receipts_unclosed');
      const all=[...receipts.values()].flat().map(r=>r.requestSeq).sort((a,b)=>a-b);
      demand(all.length===inspection.snapshot!.acceptedRequestCount&&all.every((n,i)=>n===i),'skb_exact_task_request_partition');
      const exported=journal.exportLegacyLedger(join(output,'api-ledger.json'));closeProof=cash.close();journal.close();closed=true;
      return{protocol:'skillsbench-artifact-accounting-close-v1',family:SKB_ARTIFACT_FAMILY,runId:input.runId,journalPrefix:inspection.prefix,journalConfigPin:actualPin(join(directory,'journal-config.json')),journalFilePin:actualPin(join(directory,'api-events.jsonl')),ledgerPin:actualPin(join(output,'api-ledger.json')),cashPin:closeProof,exported,
        realProviderRequests:input.providerKind==='real-provider'?inspection.snapshot!.acceptedRequestCount:0,localMockRequests:input.providerKind==='local-mock'?inspection.snapshot!.acceptedRequestCount:0,scoreCertificate:false,releasePaidLock:false};
    },
    /** Typed partial closure never certifies scores or releases the owner. */
    async retainFailure(reason:string){poison(reason);await proxy.drain();if(!closeProof)closeProof=cash.close();journal.close();closed=true;return{family:SKB_ARTIFACT_FAMILY,runId:input.runId,cashPin:closeProof,journal:journal.snapshot(),provider:proxy.state(),anomalies:proxy.anomalies,scoreCertificate:false,releasePaidLock:false};},
    state(){return{stopping,closed,provider:proxy.state(),cash:cash.snapshot()};},
  });
}

/** Every closure is attempted; a single failure cannot skip the remaining owners. */
export async function stopSkbOwnedProducers(input:{queue:{stop(reason:string):void;drain():Promise<void>};sealAndDrainTools():Promise<unknown>;stopEngines:Array<()=>Promise<unknown>>;stopBridge():Promise<unknown>;stopListeners:Array<()=>unknown|Promise<unknown>>}){
  input.queue.stop('all_generation_closed');
  const errors:{stage:string;errorType:string}[]=[],attempt=async(stage:string,fn:()=>unknown|Promise<unknown>)=>{try{return await fn();}catch(error){errors.push({stage,errorType:error instanceof Error?error.name:'OwnedCloseFailure'});}};
  // No new tools after delivery; admitted effects really complete before grade.
  await attempt('tools_sealed_and_drained',input.sealAndDrainTools);
  const engineResults=await Promise.allSettled(input.stopEngines.map(fn=>fn()));for(let i=0;i<engineResults.length;i++)if(engineResults[i]!.status==='rejected')errors.push({stage:'engine-'+i,errorType:'EngineCloseFailure'});
  await attempt('provider_actual_inflight_drained',()=>input.queue.drain());
  await attempt('native_bridge_stopped',input.stopBridge);
  for(let i=0;i<input.stopListeners.length;i++)await attempt('listener-'+i,input.stopListeners[i]!);
  return{errors,closed:errors.length===0,allSettledEngineResults:engineResults.map(r=>r.status),scoreCertificate:false,releasePaidLock:false};
}
