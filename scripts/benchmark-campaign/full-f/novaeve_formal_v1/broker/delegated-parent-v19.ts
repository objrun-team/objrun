/** One original USD parent, with an explicit root-reviewed delegation and durable additional allocations. */
import {readFileSync,writeFileSync,mkdirSync,existsSync,openSync,closeSync,fsyncSync} from 'node:fs';
import {join,dirname,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {actualPin,jsonPin,verifyPin,same,REAL_CLOCK} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {atomicStateJson} from '../../shared/atomic-state.ts';
import {verifyBenchmarkCashClosure} from '../../shared/supplier-usd-cash.ts';
import {verifyAccountHistoryUnknownUpper} from '../coordinator/failure-recovery-v6-final.ts';
import {verifyRootEntry} from '../coordinator/review-authority-v4.ts';
const demand=(x:unknown,c:string)=>{if(!x)throw Error(c);};
const save=(p:string,v:any)=>{mkdirSync(dirname(p),{recursive:true});const f=openSync(p,'wx',0o600);try{writeFileSync(f,JSON.stringify(v,null,2)+'\n');fsyncSync(f);}finally{closeSync(f);}return actualPin(p);};
export function claimGlobalDelegation(root:string,directory:string,owned:any,parentPin:any,signedPlanPin:any){
 const guard=join(root,'.phase1-data','delegated-parent-'+createHash('sha256').update(owned.runId+':'+owned.ownerNonce).digest('hex')+'.json');
 demand(!existsSync(guard),'delegation_already_has_global_owner');
 return save(guard,{pid:process.pid,runId:owned.runId,directory,originalParentAdmissionPin:parentPin,originalOwnerUnchanged:true,signedPlanPin,resumeRequiresReviewedPersistentAllocation:true});
}
export function reserveDelegatedBudget(s:any,runId:string,capUsd:number){
 demand(Number.isFinite(capUsd)&&capUsd>0&&!s.lanes[runId],'delegated_unique_positive_lane');
 demand(s.oldAllocationHighWaterUsd+s.historyUnknownUpperUsd+s.additionalAllocatedUsd+capUsd<=s.originalCapUsd+1e-9,'delegated_original_parent_budget_exhausted');
 return {...s,additionalAllocatedUsd:s.additionalAllocatedUsd+capUsd,lanes:{...s.lanes,[runId]:{capUsd,status:'reserved',retainedUsd:capUsd}}};
}
export async function createDelegatedParent(root:string,directory:string,signedPlanPath:string){
 const plan=verifyRootEntry(JSON.parse(readFileSync(signedPlanPath,'utf8')));
 demand(plan.protocol==='novaeve-root-reviewed-parent-delegation-v19'&&plan.originalLockMustRemainUnchanged===true&&plan.oldBrokerMustRemainStopped===true&&plan.allResourcesUseOriginalPool===true&&plan.noNewFunding===true,'explicit_same_parent_delegation_required');
 for(const p of [plan.parentAdmissionPin,plan.canonicalLockPin,plan.accountHistoryPin,plan.originalConnectionPin,...plan.sourcePins])verifyPin(p);
 const parent=jsonPin(plan.parentAdmissionPin),owned=jsonPin(plan.canonicalLockPin),connection=jsonPin(plan.originalConnectionPin);
 demand(resolve(plan.canonicalLockPin.path)===join(root,'.phase1-data/owned-paid-campaign.lock.json')&&connection.endpoint==='http://127.0.0.1:17889','delegated_exact_original_canonical_scope');
 demand(parent.protocol==='openrouter-usd-admission-v1'&&same(parent.owned,owned)&&parent.runId===connection.runId&&owned.pid===connection.pid,'delegated_original_owner_binding');
 const history=verifyAccountHistoryUnknownUpper(plan.accountHistoryPin,plan.historyPolicy);
 demand(history.unknownCount>=41&&history.unknownReservationUsd>=5.270266799999999-1e-9,'delegated_full_original_history_required');
 for(const p of [...parent.sourcePins,parent.pricesPin,parent.balancePin])verifyPin(p);
 const originalPrices=jsonPin(parent.pricesPin);demand(Number.isFinite(Date.parse(originalPrices.observedAtUtc))&&Date.now()>=Date.parse(originalPrices.observedAtUtc)&&Date.now()-Date.parse(originalPrices.observedAtUtc)<=86400000,'delegated_original_price_expired');
 mkdirSync(directory,{recursive:true});const guard=join(root,'.phase1-data','delegated-parent-'+createHash('sha256').update(owned.runId+':'+owned.ownerNonce).digest('hex')+'.json');
 // Never reuse a live delegation. Restart requires a separate root-reviewed adoption, not a new empty budget.
 demand(!existsSync(guard),'delegation_already_has_global_owner');
 const statePath=join(directory,'allocation.json');demand(!existsSync(statePath),'delegated_state_requires_reviewed_resume');
 let oldHealth:any,lastObserved=0,refreshFault:string|undefined;
 async function refresh(){const r=await fetch(connection.endpoint+'/health',{signal:AbortSignal.timeout(5000)});const h:any=await r.json();
  demand(r.ok&&h.pid===owned.pid&&h.runId===parent.runId&&h.healthy===false&&h.stopReason==='lane_journal_registration_invalid'&&h.activeRequests===0&&h.queuedRequests===0&&same(h.canonicalOwner,owned)&&h.parentCapUsd===parent.capUsd,'original_poisoned_parent_not_quiescent');
  demand(Number.isFinite(h.allocation?.allocatedUsd)&&h.allocation.allocatedUsd>=0&&h.allocation.allocatedUsd<=parent.capUsd,'original_allocation_invalid');
  const held=(h.resourceSlots??[]).filter((s:any)=>s.kind==='heavy-container').reduce((a:number,s:any)=>a+s.slots,0);demand(h.targetMax===16&&held+(h.availableResourceSlots?.['heavy-container']??-1)===16&&held<=16,'delegated_exact_original_resource_pool');
  const oldOpenCap=(h.lanes??[]).filter((l:any)=>!l.closed).reduce((a:number,l:any)=>a+l.capUsd,0);demand(h.allocation.allocatedUsd+1e-9>=oldOpenCap,'delegated_old_open_lane_caps_not_reserved');
  oldHealth=h;lastObserved=Date.now();return h;
 }
 await refresh();
 claimGlobalDelegation(root,directory,owned,plan.parentAdmissionPin,actualPin(signedPlanPath));
 let state:any={protocol:'novaeve-delegated-allocation-v19',originalParentAdmissionPin:plan.parentAdmissionPin,originalCapUsd:parent.capUsd,oldAllocationHighWaterUsd:oldHealth.allocation.allocatedUsd,historyUnknownUpperUsd:history.unknownReservationUsd,additionalAllocatedUsd:0,lanes:{},oldOpenLanes:oldHealth.lanes.filter((l:any)=>!l.closed).map((l:any)=>({runId:l.runId,capUsd:l.capUsd,output:l.output})),cashClosures:[],originalLockUnchanged:true};
 atomicStateJson(statePath,state);
 const checkOwner=()=>{demand(!refreshFault,'delegated_old_health_refresh_failed');verifyPin(plan.parentAdmissionPin);verifyPin(plan.canonicalLockPin);demand(same(jsonPin(plan.canonicalLockPin),owned),'delegated_original_owner_changed');demand(Date.now()-lastObserved<10000,'delegated_old_health_observation_stale');for(const p of plan.sourcePins)verifyPin(p);};
 const allocation=()=>({allocatedUsd:state.oldAllocationHighWaterUsd+state.historyUnknownUpperUsd+state.additionalAllocatedUsd,capUsd:parent.capUsd});
 async function refreshState(){try{await refresh();refreshFault=undefined;}catch(error){refreshFault=error instanceof Error?error.message:String(error);throw error;}state.oldAllocationHighWaterUsd=Math.max(state.oldAllocationHighWaterUsd,oldHealth.allocation.allocatedUsd);demand(allocation().allocatedUsd<=parent.capUsd+1e-9,'delegated_total_exposure_exceeded');atomicStateJson(statePath,state);}
 const registered=new Map<string,any>();
 const lease:any={currency:'USD',root,path:plan.canonicalLockPin.path,runId:parent.runId,capUsd:parent.capUsd,owned,proofPin:plan.parentAdmissionPin,prices:parent.pricesPin,balance:parent.balancePin,sourcePins:parent.sourcePins,clock:REAL_CLOCK,scope:'production',assertOwned:checkOwner,allocation,
  validateForwardSource(){checkOwner();for(const p of [...parent.sourcePins,parent.pricesPin,parent.balancePin])verifyPin(p);const prices=jsonPin(parent.pricesPin);demand(Date.now()-Date.parse(prices.observedAtUtc)<=86400000,'delegated_original_price_expired');},
  registerOwnedProcess(pin:any){checkOwner();verifyPin(pin);save(join(directory,'processes',pin.sha256+'.json'),{pin});},
  forkLane(runId:string,output:string,capUsd:number){checkOwner();demand(runId.startsWith(parent.runId+'-'),'delegated_original_epoch_required');state=reserveDelegatedBudget(state,runId,capUsd);atomicStateJson(statePath,state);
   const lanePin=save(join(output,'openrouter-lane-admission.json'),{protocol:'openrouter-usd-lane-admission-v1',runId,capUsd,currency:'USD',parentAdmissionPin:plan.parentAdmissionPin,ownerNonce:owned.ownerNonce,delegationPin:actualPin(signedPlanPath)});
   state.lanes[runId].admissionPin=lanePin;atomicStateJson(statePath,state);
   return {...lease,runId,capUsd,proofPin:lanePin,registerCash(pin:any){checkOwner();const c=jsonPin(pin);demand(!registered.has(runId)&&c.runId===runId&&c.ownerNonce===owned.ownerNonce&&c.currency==='USD'&&c.capUsd===capUsd&&same(c.admissionPin,lanePin),'delegated_actual_cash_binding');registered.set(runId,{pin,admissionPin:lanePin,capUsd});state.lanes[runId].cashPin=pin;atomicStateJson(statePath,state);}};
  },
  retireClosedLane(pin:any){checkOwner();const c=verifyBenchmarkCashClosure(pin),rec=registered.get(c.config.runId),row=state.lanes[c.config.runId];demand(rec&&row&&row.status==='reserved'&&same(rec.pin,c.proof.configPin)&&same(rec.admissionPin,c.config.admissionPin)&&c.config.ownerNonce===owned.ownerNonce&&c.config.capUsd===row.capUsd&&c.proof.snapshot.pendingCount===0,'delegated_actual_closed_cash_binding');const upper=c.proof.snapshot.exposureUpperBoundUsd;demand(Number.isFinite(upper)&&upper>=0&&upper<=row.capUsd,'delegated_closed_cash_upper');state.additionalAllocatedUsd-=row.capUsd-upper;row.retainedUsd=upper;row.status='closed';row.cashClosePin=pin;state.cashClosures.push(pin);atomicStateJson(statePath,state);},
  finishLightweight(result:any){checkOwner();demand(result.ownedGenerationClosed===true&&result.pendingRequests===0&&Object.values(state.lanes).every((l:any)=>l.status==='closed'),'delegated_round_not_closed');return save(join(directory,'round-close-'+Date.now()+'.json'),{protocol:'novaeve-delegated-round-close-v19',originalParentAdmissionPin:plan.parentAdmissionPin,oldOwnerStillOwnsOriginalLock:true,originalLockReleased:false,allocation:allocation(),cashClosures:state.cashClosures,...result});}
 };
 return {lease,refreshState,guard:()=>lease.validateForwardSource(),health:()=>{try{lease.validateForwardSource();demand(!refreshFault,'delegated_old_health_refresh_failed');return {healthy:true};}catch(error){return {healthy:false,stopReason:error instanceof Error?error.message:String(error)};}},oldHealth:()=>oldHealth,originalConnection:connection,plan};
}
