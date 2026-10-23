/** One canonical USD owner, independent cash lanes, and a shared request/resource queue. */
import {observeDockerDisk,evaluateDockerDisk,GiB} from '../../shared/actual-physical-disk-floor.next.ts';
import { randomBytes, createHash } from 'node:crypto';
import { captureApprovedSupplierStream } from '../../chembench/supplier-stream-continuation.ts';
import { captureChemiqStream } from '../../chemiq/upstream-stream-length-staged.ts';
import {CHEMBENCH_SUPPLIERS,supplierProfile} from '../../shared/chembench-supplier-profiles.ts';

import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { acquireOpenRouterAdmission, cashClosureAllowsContinuation } from '../../shared/supplier-admission.ts';
import { BENCHMARK_PROVIDER, benchmarkFetch, benchmarkProviderKey, officialOpenRouterFault, openRouterRateLimitRejection } from '../../shared/digitalocean-provider-600-proxy10809.next.ts';
import { CapturedTransportFailure, captureProviderResponse } from '../../shared/digitalocean-proxy.ts';
import { verifyBenchmarkCashClosure } from '../../shared/supplier-usd-cash.ts';
import { actualPin, jsonPin, same, verifyPin, type Pin } from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import { BENCH_CODES } from '../../shared/shared-admission.ts';
import { atomicStateJson } from '../../shared/atomic-state.ts';

export const BENCH_WEIGHTS: Record<string, number> = { chembench:.10, chemiq:.20, skillsbench:.30, 'terminal-bench':.35 };
const HEAVY = new Set(['skillsbench','terminal-bench']);
const hash = (value:string|Buffer) => createHash('sha256').update(value).digest('hex');
function check(ok:unknown, code:string):asserts ok { if (!ok) throw new Error(code); }
export function atomicJson(path:string, value:any) {
  atomicStateJson(path,value);
}
function immutableJson(path:string,value:any) {
  mkdirSync(dirname(path),{recursive:true});const fd=openSync(path,'wx',0o600);
  try{writeFileSync(fd,JSON.stringify(value,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}return actualPin(path);
}
function within(root:string,path:string) { const r=relative(resolve(root),resolve(path));return r!==''&&!r.startsWith('..')&&!isAbsolute(r); }
type Lane={slug:string;providerSlug:string;runId:string;output:string;token:string;admission:any;sourcePins:Pin[];registrationPath:string;cashPin?:Pin;closed?:Pin;forwarded:Set<number>;cashOffset:number;cashIndex:number;cashHash?:string;cashStates:Map<number,any>;provisionalCosts:Map<number,number>;active:number;registeredProcesses:Pin[]};
type Job={lane:Lane;raw:string;resolve:(value:Response)=>void|Promise<void>};
type ForwardResult={lane:Lane;rawSha256:string;responsePin?:Pin;httpStatus?:number;headers?:Record<string,string>};
export type BrokerOptions={root:string;output:string;runId:string;port?:number;maxInFlight?:number;perBenchMax?:number;localMock?:boolean;
  targetMax?:number;heavyCapacity?:number;heavyMemoryMb?:number;perBenchHeavySlots?:number;diskObserver?:()=>any;hostDiskObserver?:()=>any;
  recordAndContinue?:boolean; remoteDiskObservationPath?:string;
  beforeAccept?:()=>void; initialParent?:any; retainCanonicalParent?:boolean; externalHealth?:()=>{healthy:boolean;stopReason?:string}; initialRound?:number; initialRoundReceipts?:Pin[]; externalResources?:()=>any[]; externalLanes?:()=>any[]; initialResources?:any[];aliasPorts?:number[];adoptionMetadata?:()=>any;adoptionResourceRelease?:(body:any)=>Promise<string>;resourceProxy?:(request:Request)=>Promise<Response>; leaseFactory?:(input:any)=>Promise<any>;transport?:(raw:string)=>Promise<{httpStatus:number;rawResponse:string}>};

export async function startFullFBroker(options:BrokerOptions) {
  const {root,output,runId}=options;mkdirSync(output,{recursive:true});
  const accessToken=randomBytes(24).toString('hex'),lanes=new Map<string,Lane>(),resources=new Map<string,any>((options.initialResources??[]).map(r=>[r.kind+'/'+r.slug+'/'+r.pid,{...r}]));
  const perBenchLimits:Record<string,number>=Object.fromEntries(Object.keys(BENCH_WEIGHTS).map(slug=>[slug,options.perBenchMax??16]));
  let dispatchPaused=false;
  const approvedPrices=(slug:string)=>actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/chembench-supplier-prices',slug,'openrouter-prices.json'));
  let parent:any=options.initialParent,round=options.initialRound??0,parentCreation:Promise<any>|undefined,active=0,max=options.maxInFlight??4,stopReason:string|undefined,backoffUntil=0,successes=0;
  const queue:Job[]=[],events:any[]=[],roundReceipts:Pin[]=[...(options.initialRoundReceipts??[])],forwardResults=new Map<string,ForwardResult>();
  const commonSources=[import.meta.path,...['shared-admission.ts','closed-run-cost.ts','cash-reconciliation.ts','digitalocean-provider.ts','digitalocean-inference.ts','digitalocean-journal.ts','digitalocean-usd-cash.ts','digitalocean-proxy.ts','digitalocean-admission.ts','digitalocean-closed-run-cost.ts'].map(n=>join(resolve(import.meta.dir,'../../shared'),n)),...['benchmark-provider.ts','benchmark-inference.ts','benchmark-usd-cash.ts','campaign-journal.ts','campaign-contract.ts','paid-resource-proof-v2.ts','scientific-journal-proxy.ts'].map(n=>join(root,'scripts/benchmark-repair',n))].map(actualPin);
  commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'atomic-state.ts')));
  const cqAuthorizationPin=actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq/task39-supplier-human-authorization.json'));
  commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'container-task-resource.ts')));commonSources.push(actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/eight-per-bench-user-authorization-20261011.json')));commonSources.push(actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/throughput-user-authorization-20261011.json')));commonSources.push(cqAuthorizationPin);commonSources.push(actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/actual-disk-dynamic-sixteen-human-authorization-20261011.json')));commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'actual-physical-disk-floor.next.ts')));
  commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'digitalocean-provider-600.ts')));commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'digitalocean-provider-600-proxy10809.next.ts')));commonSources.push(actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/local-proxy10809-human-authorization.json')));
  for(const name of ['chembench-supplier-profiles.ts','supplier-journal.ts','supplier-usd-cash.ts','supplier-admission.ts','supplier-proxy.ts','supplier-inference.ts','supplier-shared-admission.ts','supplier-closed-run-cost.ts'])commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),name)));
  commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'../chembench/supplier-stream-continuation.ts')));
  commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'../chemiq/upstream-stream-length-staged.ts')));
  for(const slug of Object.keys(CHEMBENCH_SUPPLIERS))commonSources.push(approvedPrices(slug));
  commonSources.push(actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/chembench-supplier-prices/official-endpoints.json')));
  const healthPath=join(output,'broker-status.json'),registrationDir=join(output,'registrations');mkdirSync(registrationDir,{recursive:true});
  const log=(event:any)=>{const value={index:events.length,atUtc:new Date().toISOString(),localMock:!!options.localMock,...event};immutableJson(join(output,'events',String(value.index).padStart(7,'0')+'.json'),value);events.push(value);};
  const snapshot=()=>({protocol:'full-f-broker-status-v1',localMock:!!options.localMock,pid:process.pid,runId,atUtc:new Date().toISOString(),healthy:!stopReason&&(options.externalHealth?.().healthy??true),stopReason:stopReason??options.externalHealth?.().stopReason??null,
    providerName:BENCHMARK_PROVIDER.providerName,providerSlug:BENCHMARK_PROVIDER.providerSlug,
    costPolicy:options.recordAndContinue?'record_and_continue':'strict',
    transportPolicy:{chembench:'digitalocean-nonstream-600s-approved-supplier-sse-length-v2',chemiq:'pinned-task39-sse-length-aware-approved-supplier-length-v2',others:'original-nonstream-600s',timeoutMs:600000},
    activeRequests:active,queuedRequests:queue.length,maxInFlight:max,perBenchMax:Math.max(...Object.values(perBenchLimits)),perBenchLimits,dispatchPaused,targetMax:options.targetMax??options.maxInFlight??16,backoffUntilUtc:backoffUntil?new Date(backoffUntil).toISOString():null,
    adoption:options.adoptionMetadata?.()??null,canonicalOwner:parent?.owned??null,parentCapUsd:parent?.capUsd??null,allocation:parent?.allocation?.()??null,round,roundReceipts,
    resources:Object.fromEntries(['heavy-container','lean-repl'].flatMap(kind=>{const first=[...resources.values()].find(r=>r.kind===kind);return first?[[kind,first]]:[];})),resourceSlots:[...resources.values()],
    perBenchHeavySlots:options.perBenchHeavySlots??16,defaultPerBenchHeavySlots:8,dynamicBorrowUnusedSlots:true,actualDiskFloorGiB:5,diskGrowthObservationBytes:[...resources.values()].reduce((n,r)=>n+r.plannedGrowthBytes,0),availableResourceSlots:{'heavy-container':(options.heavyCapacity??16)-[...resources.values()].filter(r=>r.kind==='heavy-container').reduce((n,r)=>n+r.slots,0)},heavyMemoryMb:options.heavyMemoryMb??262144,
    lanes:[...(options.externalLanes?.()??[]),...[...lanes.values()].map(l=>({slug:l.slug,providerSlug:l.providerSlug,runId:l.runId,capUsd:l.admission.capUsd,active:l.active,cashRegistered:!!l.cashPin,closed:!!l.closed,dispatched:l.forwarded.size,output:l.output,
      billedUsd:[...l.cashStates.values()].filter(s=>s.phase==='known').reduce((n,s)=>n+s.amount,0),unknownCount:[...l.cashStates.values()].filter(s=>s.phase==='unknown').length}))]});
  let snapshotWriteFailure:string|undefined;
  const persist=()=>{try {atomicJson(healthPath,{...snapshot(),snapshotWriteFailure:snapshotWriteFailure??null});atomicJson(join(output,'resource-pool.json'),{protocol:'novaeve-adopted-resource-pool-v48',capacity:16,rows:[...resources.values()]});snapshotWriteFailure=undefined;}catch(error){snapshotWriteFailure=(error as any)?.code??'snapshot_write_failed';console.error(JSON.stringify({kind:'snapshot-write-retry-next-tick',code:snapshotWriteFailure,atUtc:new Date().toISOString()}));}};
  const poison=(reason:string)=>{if(stopReason)return;stopReason=reason;log({kind:'stop',reason});persist();};
  const noForward=(why:string,status=503)=>Response.json({error:{message:why,code:'bench_local_not_forwarded'}},{status,headers:{'x-bench-provider-attempted':'false'}});
  async function getParent() {
    if(parent)return parent;if(parentCreation)return parentCreation;
    const directory=join(output,'round-'+String(++round));mkdirSync(directory,{recursive:true});
    parentCreation=(options.leaseFactory??acquireOpenRouterAdmission)({root,output:directory,runId,family:'four-bench-full-f-v1',entry:import.meta.path,sourcePins:commonSources,allowUnsettledCash:options.recordAndContinue});
    try{parent=await parentCreation;log({kind:'canonical-owner-acquired',round,admissionPin:parent.proofPin,capUsd:parent.capUsd});return parent;}finally{parentCreation=undefined;persist();}
  }
  function register(lane:Lane) {
    if(lane.cashPin)return;
    const record=JSON.parse(readFileSync(lane.registrationPath,'utf8')),pin=record.cashPin as Pin,config=jsonPin(pin);
    check(record.runId===lane.runId&&within(lane.output,pin.path)&&config.runId===lane.runId&&config.currency==='USD'&&config.ownerNonce===lane.admission.owned.ownerNonce
      &&same(config.admissionPin,lane.admission.proofPin)&&config.capUsd===lane.admission.capUsd&&config.providerKind===(options.localMock?'local-mock':'real-provider'),'lane_cash_registration_invalid');
    verifyPin(config.journal.configPin);verifyPin(config.journal.sourcePin);verifyPin(config.sourcePin);
    const journal=jsonPin(config.journal.configPin);check(journal.campaign===lane.runId&&journal.currency==='USD'&&journal.provider==='openrouter-deepseek'&&journal.capUsd===lane.admission.capUsd,'lane_journal_registration_invalid');
    lane.admission.registerCash(pin);lane.cashPin=pin;lane.cashHash=pin.sha256;log({kind:'cash-registered',runId:lane.runId,cashPin:pin});
  }
  function syncCash(lane:Lane) {
    if(!lane.cashPin)return;verifyPin(lane.cashPin);
    const raw=readFileSync(join(dirname(lane.cashPin.path),'cash-events.jsonl'));check(raw.length>=lane.cashOffset,'cash_events_shrank');
    const next=raw.subarray(lane.cashOffset);check(!next.length||next[next.length-1]===10,'cash_events_incomplete');
    for(const line of next.toString('utf8').split('\n').filter(Boolean)) {
      const e=JSON.parse(line);check(e.protocol==='openrouter-usd-cash-event-v1'&&e.index===lane.cashIndex&&e.previousSha256===lane.cashHash,'cash_chain_changed');
      const d=e.data;if(e.kind==='start') {check(!lane.cashStates.has(d.ticket.requestSeq)&&d.ticket.currency==='USD','cash_start_duplicate');lane.cashStates.set(d.ticket.requestSeq,{...d,phase:d.ticket.dispatchAllowed?'pending':'denied',amount:0});}
      else {check(e.kind==='finish'&&lane.cashStates.has(d.ticket.requestSeq),'cash_finish_without_start');const state=lane.cashStates.get(d.ticket.requestSeq);check(state.phase==='pending'||state.phase==='denied','cash_finish_duplicate');check(Number.isFinite(d.amountUsd)&&d.amountUsd>=0&&['known','unknown'].includes(d.phase),'cash_finish_amount');Object.assign(state,{phase:d.phase,amount:d.amountUsd});}
      lane.cashHash=hash(line+'\n');lane.cashIndex++;
    }
    lane.cashOffset=raw.length;
    if(!options.recordAndContinue)check([...lane.cashStates.values()].every(s=>s.phase!=='unknown'),'unsettled_lane_cost');
    check([...lane.cashStates].reduce((n,[seq,s])=>n+(s.phase==='pending'?Math.max(s.ticket.reservationUsd,lane.provisionalCosts.get(seq)??0):s.amount),0)<=lane.admission.capUsd+1e-9,'lane_exposure_exceeded_cap');
  }
  function assertLane(lane:Lane) {options.beforeAccept?.();check(options.externalHealth?.().healthy??true,'adopted_execution_health_guard');
    check(!stopReason&&!lane.closed,'broker_or_lane_stopped');lane.admission.validateForwardSource();for(const pin of lane.sourcePins)verifyPin(pin);register(lane);syncCash(lane);
  }
  async function maybeRelease() {if(options.retainCanonicalParent)return;
    if(!parent||active||queue.length||[...lanes.values()].some(l=>!l.closed))return;
    const receipt=parent.finishLightweight({ownedGenerationClosed:true,pendingRequests:0,multiBench:true,scoreCertificate:false});roundReceipts.push(receipt);parent=undefined;log({kind:'canonical-owner-released',receipt});persist();
  }
  async function execute(job:Job) {
    const {lane,raw}=job;let dispatched=false;
    try {
      assertLane(lane);for(const other of lanes.values())if(!other.closed&&other.cashPin)syncCash(other);
      const digest=hash(raw),candidates=[...lane.cashStates].filter(([seq,s])=>s.phase==='pending'&&s.requestSha256===digest&&!lane.forwarded.has(seq));
      check(candidates.length>0,'request_has_no_durable_cash_ticket');const [seq,ticket]=candidates[0]!;verifyPin(ticket.requestPin);
      lane.forwarded.add(seq);log({kind:'dispatch',runId:lane.runId,slug:lane.slug,requestSeq:seq,requestSha256:digest});dispatched=true;
      const cqScope=lane.sourcePins.find(p=>p.path===join(lane.output,'stream-task-scope.json'));
      const result=options.transport?await options.transport(raw):lane.slug==='chemiq'&&cqScope&&lane.providerSlug==='digitalocean'
        ? await captureChemiqStream(raw,benchmarkProviderKey(root),join(output,'chemiq-stream-evidence',lane.runId+'-'+seq))
        : ['chembench','chemiq'].includes(lane.slug)&&lane.providerSlug!=='digitalocean'
        ? await captureApprovedSupplierStream(raw,benchmarkProviderKey(root),join(output,'stream-evidence',lane.runId+'-'+seq))
        : await captureProviderResponse(await benchmarkFetch(raw,benchmarkProviderKey(root)));
      const responsePath=join(output,'responses',lane.runId+'-'+seq+'.json');mkdirSync(dirname(responsePath),{recursive:true});
      const fd=openSync(responsePath,'wx',0o600);try{writeFileSync(fd,result.rawResponse);fsyncSync(fd);}finally{closeSync(fd);}
      let body:any;try{body=JSON.parse(result.rawResponse);}catch{}
      const expectedProvider=supplierProfile(lane.providerSlug).providerName;
      const rate=openRouterRateLimitRejection(body,result.httpStatus,expectedProvider);
      const valid=result.httpStatus===200&&!officialOpenRouterFault(body,expectedProvider);
      if(valid)lane.provisionalCosts.set(seq,body.usage.cost);
      log({kind:'response',runId:lane.runId,requestSeq:seq,httpStatus:result.httpStatus,responsePin:actualPin(responsePath),generationId:body?.id??null,
        billedUsd:valid?body.usage.cost:null,explicitRateRejection:!!rate,scoreCertificate:false});
      if(result.httpStatus===429){max=Math.max(1,Math.floor(max/2));backoffUntil=Date.now()+10000;successes=0;}
      else if(valid){try{syncCash(lane);}catch(error){poison(error instanceof Error?error.message:'cash_sync_after_response_failed');}if(++successes>=32&&max<(options.targetMax??options.maxInFlight??16)){max=Math.min(options.targetMax??options.maxInFlight??16,max+4);successes=0;}}
      else if(options.recordAndContinue){
        if(result.httpStatus===200 && body?.provider && body.provider!==expectedProvider || result.httpStatus===200 && body?.model && ![BENCHMARK_PROVIDER.model,BENCHMARK_PROVIDER.canonicalModel].includes(body.model))poison('provider_protocol_mismatch');
        else log({kind:'unsettled-cost-retained',runId:lane.runId,requestSeq:seq,httpStatus:result.httpStatus,unknownCostRetained:true,scoreCertificate:false});
      }else poison('provider_response_requires_cost_review');
      await job.resolve(new Response(result.rawResponse,{status:result.httpStatus,headers:{'content-type':'application/json','x-bench-provider-attempted':'true'}}));
    }catch(error) {
      if(dispatched&&options.recordAndContinue)log({kind:'unsettled-cost-retained',runId:lane.runId,reason:'incomplete_provider_transport',errorName:error instanceof Error?error.name:null,errorCode:typeof (error as any)?.code==='string'?(error as any).code:null,unknownCostRetained:true,scoreCertificate:false});
      else if(dispatched)poison('incomplete_provider_transport');else {log({kind:'lane-validation-quarantined',runId:lane.runId,reason:error instanceof Error?error.message:'broker_validation_failed',originalCapRetained:true,providerAttempted:false});}
      if(error instanceof CapturedTransportFailure){await job.resolve(new Response(error.capture.rawBytes as any,{status:error.capture.httpStatus,headers:{'x-bench-body-complete':'false','x-bench-fault':error.capture.fault,'x-bench-provider-attempted':'true'}}));}
      else await job.resolve(dispatched?Response.json({error:{message:'Shared Bench broker stopped',code:'bench_broker_stopped'}},{status:503,headers:{'x-bench-provider-attempted':'true'}}):noForward('Shared Bench broker stopped before dispatch'));
    }finally{active--;lane.active--;persist();pump();}
  }
  let pumpTimer:ReturnType<typeof setTimeout>|undefined;
  function pump() {
    if(stopReason){while(queue.length)void queue.shift()!.resolve(noForward('Broker stopped before queued dispatch'));return;}
    if(Date.now()<backoffUntil){if(!pumpTimer)pumpTimer=setTimeout(()=>{pumpTimer=undefined;pump();},backoffUntil-Date.now());return;}
    while(active<max){const at=queue.findIndex(j=>j.lane.active<perBenchLimits[j.lane.slug]!);if(at<0)break;const job=queue.splice(at,1)[0]!;active++;job.lane.active++;void execute(job);}
    persist();
  }
  const fetchHandler=async(request:Request)=>{
    const url=new URL(request.url);if(options.externalResources){resources.clear();for(const r of options.externalResources())resources.set(r.kind+'/'+r.slug+'/'+r.pid,r);}
    if(url.pathname==='/health')return Response.json(snapshot());
    if(request.headers.get('authorization')!=='Bearer '+accessToken)return Response.json({error:'unauthorized'},{status:401});
    try {
      if(['/lane/claim','/forward','/resource/acquire'].includes(url.pathname)){options.beforeAccept?.();check(options.externalHealth?.().healthy??true,'delegated_external_guard_unhealthy');}
      if(url.pathname==='/adoption/resource-release'){check(options.adoptionResourceRelease,'adoption_release_unavailable');const key=await options.adoptionResourceRelease(await request.json());check(resources.get(key)?.adoptedOrphanHold===true,'not_an_adopted_orphan_resource');resources.delete(key);log({kind:'adopted-orphan-resource-closed',key});persist();return Response.json({released:true,originalBudgetReleased:false});}
      if(url.pathname==='/admin/pause'){dispatchPaused=true;log({kind:'new-dispatch-paused'});persist();return Response.json({paused:true,active,queued:queue.length});}
      if(url.pathname==='/admin/concurrency'){
        const d=await request.json() as any;check(Number.isInteger(d.total)&&d.total>=1&&d.total<=50,'invalid_global_concurrency');
        for(const [slug,n] of Object.entries(d.perBench??{})){check(Object.hasOwn(perBenchLimits,slug)&&Number.isInteger(n)&&Number(n)>=1&&Number(n)<=50,'invalid_bench_concurrency');perBenchLimits[slug]=Number(n);}
        max=d.total;log({kind:'concurrency-updated',max,perBenchLimits:{...perBenchLimits}});pump();return Response.json({max,perBenchLimits});
      }
      if(url.pathname==='/lane/claim') {
        const data=await request.json() as any;check(!stopReason&&(!dispatchPaused||lanes.has(data.runId)),'broker_not_accepting_new_lanes');
        check(data.slug!=='chembench'||data.providerSlug==='digitalocean'||Object.hasOwn(CHEMBENCH_SUPPLIERS,data.providerSlug),'unapproved_chembench_lane_provider');
        check(Object.hasOwn(BENCH_WEIGHTS,data.slug)&&typeof data.runId==='string'&&data.runId.startsWith(runId+'-'+BENCH_CODES[data.slug]+'-')&&/^repair-[0-9TZ-]+$/.test(data.runId),'invalid_bench_run_id');
        const allowed=join(root,'docs/repair-2026-10-10/full-f-rerun',data.slug);check(within(allowed,data.output)&&Array.isArray(data.sourcePins)&&data.sourcePins.length>0,'invalid_lane_output_or_sources');
        for(const pin of data.sourcePins){check(within(root,pin.path),'lane_source_outside_code_root');verifyPin(pin);}
        const cqScopePath=join(resolve(data.output),'stream-task-scope.json');
        const cqScopePin=data.sourcePins.find((p:Pin)=>p.path===cqScopePath);
        check(data.slug!=='chemiq'||!data.providerSlug||data.providerSlug==='digitalocean'||cqScopePin,'chemiq_supplier_scope_required');
        if(cqScopePin&&data.providerSlug&&data.providerSlug!=='digitalocean'){
          const scope=jsonPin(cqScopePin),authorization=jsonPin(cqAuthorizationPin);
          check(data.slug==='chemiq'&&authorization.authorizedByUser===true&&same(authorization.eligibleIndices,[39])
            &&scope.protocol==='chemiq-task39-supplier-scope-v1'&&same(scope.eligibleIndices,[39])
            &&scope.officialId===authorization.officialId&&scope.retainedValid===815&&scope.solveSeconds===900
            &&scope.maxTokens===16384&&scope.reasoning==='high'&&scope.allowFallbacks===false
            &&scope.provider===data.providerSlug&&authorization.providerOrder.includes(data.providerSlug)
            &&same(scope.authorizationPin,cqAuthorizationPin),'invalid_chemiq_task39_supplier_scope');
        } else if(cqScopePin){
          const scope=jsonPin(cqScopePin);
          check(data.slug==='chemiq'&&scope.protocol==='chemiq-task39-stream-scope-v1'
            &&same(scope.eligibleIndices,[39])&&scope.officialId==='chemiq-1b8804c1-d279-422a-ad63-755bb021b922'
            &&scope.retainedValid===815&&scope.solveSeconds===900&&scope.maxTokens===16384
            &&scope.provider==='digitalocean'&&scope.reasoning==='high'&&scope.allowFallbacks===false,
            'invalid_chemiq_task39_stream_scope');
        }
        if(HEAVY.has(data.slug)&&!lanes.has(data.runId))check([...resources.values()].some(r=>r.kind==='heavy-container'&&r.slug===data.slug&&!r.adoptedOrphanHold),'heavy_container_slot_required_before_lane');
        let lane=lanes.get(data.runId);
        if(!lane) {
          check([...lanes.values()].filter(l=>l.slug===data.slug&&!l.closed).length<(HEAVY.has(data.slug)?(options.perBenchHeavySlots??16):1),'bench_already_active');if(HEAVY.has(data.slug))check([...lanes.values()].filter(l=>l.slug===data.slug&&!l.closed).length<[...resources.values()].filter(r=>r.kind==='heavy-container'&&r.slug===data.slug&&!r.adoptedOrphanHold).reduce((n,r)=>n+r.slots,0),'independent_heavy_container_slot_required_before_lane');const owner=await getParent();
          check([...lanes.values()].filter(l=>l.slug===data.slug&&!l.closed).length<(HEAVY.has(data.slug)?(options.perBenchHeavySlots??16):1),'bench_already_active');if(HEAVY.has(data.slug))check([...lanes.values()].filter(l=>l.slug===data.slug&&!l.closed).length<[...resources.values()].filter(r=>r.kind==='heavy-container'&&r.slug===data.slug&&!r.adoptedOrphanHold).reduce((n,r)=>n+r.slots,0),'independent_heavy_container_slot_required_before_lane');
          const capUsd=Math.floor(owner.capUsd*BENCH_WEIGHTS[data.slug]!/(HEAVY.has(data.slug)?Math.min(options.perBenchHeavySlots??16,8):1)*1e6)/1e6;check(capUsd>0,'empty_lane_budget');
          const admission=owner.forkLane(data.runId,join(data.output,'shared-admission'),capUsd);
          const providerSlug=['chembench','chemiq'].includes(data.slug)?(data.providerSlug??'digitalocean'):'digitalocean';check(data.slug!=='chembench'||providerSlug==='digitalocean'||Object.hasOwn(CHEMBENCH_SUPPLIERS,providerSlug),'unapproved_chembench_lane_provider');
          lane={slug:data.slug,providerSlug,runId:data.runId,output:resolve(data.output),token:randomBytes(24).toString('hex'),admission,sourcePins:data.sourcePins,
            registrationPath:join(registrationDir,data.runId+'.json'),forwarded:new Set(),cashOffset:0,cashIndex:0,cashStates:new Map(),provisionalCosts:new Map(),active:0,registeredProcesses:[]};lanes.set(data.runId,lane);
          log({kind:'lane-created',slug:data.slug,runId:data.runId,capUsd,admissionPin:admission.proofPin,sourcePins:data.sourcePins});
        } else check(!lane.closed&&(!['chembench','chemiq'].includes(lane.slug)||lane.providerSlug===(data.providerSlug??'digitalocean'))&&same(lane.sourcePins,data.sourcePins)&&lane.output===resolve(data.output),'lane_reclaim_changed');
        persist();return Response.json({protocol:'full-f-shared-lane-v1',runId:lane.runId,capUsd:lane.admission.capUsd,owned:lane.admission.owned,proofPin:lane.admission.proofPin,
          parentAdmissionPin:parent.proofPin,canonicalLockPath:parent.path,prices:['chembench','chemiq'].includes(lane.slug)&&lane.providerSlug!=='digitalocean'?approvedPrices(lane.providerSlug):parent.prices,balance:parent.balance,sourcePins:lane.sourcePins,
          registrationPath:lane.registrationPath,laneToken:lane.token,healthPath,brokerPid:process.pid});
      }
      if(url.pathname==='/resource/acquire'||url.pathname==='/resource/release') {if(options.resourceProxy)return await options.resourceProxy(request);
        const d=await request.json() as any;check(Object.hasOwn(BENCH_WEIGHTS,d.slug)&&['heavy-container','lean-repl'].includes(d.kind)&&Number.isSafeInteger(d.pid)&&d.pid>0,'resource_request_invalid');
        const key=d.kind+'/'+d.slug+'/'+d.pid;
        if(url.pathname.endsWith('/release')){const owned=resources.get(key);check(owned?.token===d.token&&!owned.adoptedOrphanHold,'resource_not_owned_or_adopted_hold');resources.delete(key);log({kind:'resource-released',resource:d.kind,slug:d.slug,pid:d.pid});persist();return Response.json({released:true});}
        check(!dispatchPaused,'resource_admission_paused');const held=resources.get(key);const slots=d.slots??1,memoryMb=d.memoryMb??(d.slug==='skillsbench'?8192:4096);
        check(Number.isInteger(slots)&&slots>=1&&slots<=2&&Number.isInteger(memoryMb)&&memoryMb>0,'resource_budget_invalid');
        const sameKind=[...resources.values()].filter(r=>r.kind===d.kind);const capacity=d.kind==='heavy-container'?(options.heavyCapacity??16):2;
        const plannedGrowthBytes=d.kind==='heavy-container'?(d.plannedGrowthBytes??10*GiB):0;check(Number.isSafeInteger(plannedGrowthBytes)&&plannedGrowthBytes>=0,'invalid_planned_disk_growth');
        if(!held&&d.kind==='heavy-container'&&sameKind.filter(r=>r.slug===d.slug).reduce((n,r)=>n+r.slots,0)+slots>(options.perBenchHeavySlots??16))return Response.json({waiting:true,reason:'per_bench_resource_capacity'},{status:409});
        if(!held&&d.kind==='heavy-container'){const remoteObservation=options.remoteDiskObservationPath?JSON.parse(readFileSync(options.remoteDiskObservationPath,'utf8')):null; const observation=remoteObservation ? {drive:'E:',driveType:3,freeBytes:remoteObservation.freeBytes??remoteObservation.availableBytes,observedAtMs:remoteObservation.observedAtMs??Date.parse(remoteObservation.observedAtUtc)} : options.localMock?options.diskObserver?.():observeDockerDisk('E:/Docker/wsl/disk/docker_data.vhdx'); check(!remoteObservation || (remoteObservation.protocol==='novaeve-runtime-disk-v1' && remoteObservation.dataRoot==='/data/wpx/tgengin/docker' || remoteObservation.protocol==='novaeve-docker-storage-observation-v1' && remoteObservation.dockerRootDir==='/data/wpx/tgengin/docker' && remoteObservation.probeExitCode===0),'remote_disk_scope_invalid');if(!options.localMock||options.diskObserver){const gate=evaluateDockerDisk(observation??null,{nowMs:Date.now(),expectedDrive:'E:',plannedGrowthBytes});if(!gate.admissible)return Response.json({waiting:true,reason:gate.reason},{status:409});}const hostObservation=options.localMock?options.hostDiskObserver?.():observeDockerDisk('F:/git');if(!options.localMock||options.hostDiskObserver){const hostGate=evaluateDockerDisk(hostObservation??null,{nowMs:Date.now(),expectedDrive:'F:',plannedGrowthBytes});if(!hostGate.admissible)return Response.json({waiting:true,reason:hostGate.reason,drive:'F:'},{status:409});}}
        if(!held&&(sameKind.reduce((n,r)=>n+r.slots,0)+slots>capacity))return Response.json({waiting:true,reason:'resource_capacity_or_memory',owner:sameKind[0]?.slug??null},{status:409});
        check(!held||!held.adoptedOrphanHold,'adopted_orphan_cannot_be_reclaimed_by_reused_pid');check(!held||held.slots===slots&&held.memoryMb===memoryMb&&held.plannedGrowthBytes===plannedGrowthBytes,'resource_reclaim_changed');const reservation=held??{kind:d.kind,slug:d.slug,pid:d.pid,slots,memoryMb,plannedGrowthBytes,token:randomBytes(16).toString('hex')};resources.set(key,reservation);
        if(!held)log({kind:'resource-acquired',resource:d.kind,slug:d.slug,pid:d.pid});persist();return Response.json(reservation);
      }
      const lane=lanes.get(url.searchParams.get('runId')??'');check(lane&&request.headers.get('x-bench-lane-token')===lane.token,'lane_authentication_failed');
      if(url.pathname==='/lane/process') {const d=await request.json() as any;check(within(lane.output,d.pin.path),'process_pin_outside_lane');verifyPin(d.pin);lane.admission.registerOwnedProcess(d.pin);lane.registeredProcesses.push(d.pin);return Response.json({registered:true});}
      if(url.pathname==='/lane/close') {check(!lane.active&&!queue.some(j=>j.lane===lane),'lane_still_forwarding');register(lane);const d=await request.json() as any;
        check(within(lane.output,d.cashPin.path),'cash_closure_outside_lane');const closed=verifyBenchmarkCashClosure(d.cashPin);
        check(cashClosureAllowsContinuation(closed.proof,options.recordAndContinue)
          &&same(closed.proof.configPin,lane.cashPin)&&closed.config.ownerNonce===lane.admission.owned.ownerNonce,'lane_cash_not_closed');syncCash(lane);
        lane.closed=d.cashPin;parent.retireClosedLane?.(d.cashPin);log({kind:'lane-closed',runId:lane.runId,cashClosePin:d.cashPin,billedUsd:closed.proof.snapshot.billedUsd});await maybeRelease();persist();return Response.json({closed:true,ownerReleased:!parent});}
      if(url.pathname==='/forward/result') {
        const ticket=url.searchParams.get('ticket')??'',result=forwardResults.get(ticket);
        check(result&&result.lane===lane,'forward_ticket_not_owned');
        if(!result.responsePin)return Response.json({protocol:'full-f-forward-ticket-v1',runId:lane.runId,ticket},{status:202});
        verifyPin(result.responsePin);return new Response(readFileSync(result.responsePin.path),{status:result.httpStatus,headers:{...result.headers,'x-bench-forward-ticket':ticket}});
      }
      if(url.pathname==='/forward') {check(!stopReason&&!dispatchPaused&&!lane.closed&&queue.length<256,'broker_queue_unavailable');const raw=await request.text();const d=JSON.parse(raw);
        const expectedRoute=supplierProfile(lane.providerSlug);
        check(d.model===expectedRoute.model&&same(d.provider,expectedRoute.routing)&&d.reasoning?.enabled===true&&d.reasoning?.effort==='high'&&d.stream!==true,'broker_requires_frozen_digitalocean_reasoning_request');
        const ticket=randomBytes(24).toString('hex'),result:ForwardResult={lane,rawSha256:hash(raw)};forwardResults.set(ticket,result);
        queue.push({lane,raw,async resolve(response){
          const path=join(output,'forward-results',ticket+'.bin');mkdirSync(dirname(path),{recursive:true});
          const body=new Uint8Array(await response.arrayBuffer()),fd=openSync(path,'wx',0o600);
          try{writeFileSync(fd,body);fsyncSync(fd);}finally{closeSync(fd);}
          result.httpStatus=response.status;result.headers=Object.fromEntries(response.headers);result.responsePin=actualPin(path);
          log({kind:'forward-result',runId:lane.runId,ticket,rawSha256:result.rawSha256,httpStatus:result.httpStatus,providerAttempted:result.headers['x-bench-provider-attempted']==='true',responsePin:result.responsePin});
          persist();
        }});pump();return Response.json({protocol:'full-f-forward-ticket-v1',runId:lane.runId,ticket},{status:202});}
      return Response.json({error:'unknown_route'},{status:404});
    }catch(error){return url.pathname==='/forward'?noForward(error instanceof Error?error.message:'broker_error',409):Response.json({error:error instanceof Error?error.message:'broker_error'},{status:409});}
  };
  const server=Bun.serve({hostname:'127.0.0.1',port:options.port??17895,idleTimeout:255,maxRequestBodySize:4*1024**2,fetch:fetchHandler});
  const aliasServers=(options.aliasPorts??[]).map(port=>Bun.serve({hostname:'127.0.0.1',port,idleTimeout:255,maxRequestBodySize:4*1024**2,fetch:fetchHandler}));
  const timer=setInterval(()=>{try{for(const lane of lanes.values())if(!lane.closed&&lane.cashPin)syncCash(lane);persist();}catch(error){poison(error instanceof Error?error.message:'cash_monitor_failure');}},5000);
  const connection={endpoint:`http://127.0.0.1:${server.port}`,accessToken,runId,pid:process.pid,healthPath,sourcePins:commonSources};
  persist();return {server,aliasEndpoints:aliasServers.map(s=>'http://127.0.0.1:'+s.port),connection,snapshot,async stop(){check(!active&&!queue.length,'cannot_stop_active_broker');check(!parent,'cannot_stop_with_owned_cash');clearInterval(timer);if(pumpTimer)clearTimeout(pumpTimer);await server.stop(true);for(const alias of aliasServers)await alias.stop(true);}};
}

