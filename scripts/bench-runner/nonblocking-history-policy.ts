/** Explicit root policy authorizes admission under uncertainty; it never closes old custody. */
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createHash,verify,sign} from 'node:crypto';
const ROOT_AUTHORITY='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98';
function demand(x:any,s:string):asserts x {if(!x)throw Error(s)}
function check(p:any){demand(p?.path&&Number.isSafeInteger(p.bytes)&&/^[a-f0-9]{64}$/.test(p.sha256),'policy_pin_required');const b=readFileSync(p.path);demand(b.length===p.bytes&&createHash('sha256').update(b).digest('hex')===p.sha256,'policy_pin_changed');return b;}
const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
export function verifySignedPolicyData(e:any,key:any,protocol:string,field:string){demand(e?.protocol===protocol&&e[field]&&typeof e.signature==='string'&&verify(null,Buffer.from(JSON.stringify(e[field])),key,Buffer.from(e.signature,'base64')),'root_policy_signature_required');return e[field];}
export function historyAdmission(m:any){
 const c=m.adapterConfig?.nonblockingHistory;if(!c)return null;
 const authority=c.authorityPin??m.adapterConfig.bindingSpec?.authorityPin;demand(authority?.sha256===ROOT_AUTHORITY,'original_root_policy_authority_required');const key=check(authority);
 const p=verifySignedPolicyData(JSON.parse(check(c.policyPin).toString()),key,'bench-root-signed-user-policy-v1','policy');
 demand(p.protocol==='bench-user-authorized-nonblocking-history-policy-v1'&&p.allowedTaskKeys?.includes(m.bench+':'+m.taskId)&&p.historicalFinance?.unverifiedIsBlocking===false&&p.historicalFinance?.unverifiedMustNeverBeZero===true&&p.historicalFinance?.noFakeAccountingOrNativeClosure===true&&p.historicalStart?.uncertainStartIsBlocking===false&&p.historicalStart?.oldLocksKeptAndOldNonceNeverReused===true&&p.validCompletionAlwaysPermanentNoRetry===true&&p.budgets?.parentCapUsd===418.777826378,'exact_user_nonblocking_policy_required');
 const a=verifySignedPolicyData(JSON.parse(check(c.authorizationPin).toString()),key,'bench-root-signed-nonblocking-task-admission-v1','authorization');
 demand(a.protocol==='bench-nonblocking-task-admission-v1'&&a.taskId===m.taskId&&a.bench===m.bench&&same(a.policyPin,c.policyPin)&&same(a.factsPin,c.factsPin)&&same(a.currentActivationPin,c.activationPin)&&Date.parse(a.expiresAtUtc)>Date.now(),'task_scoped_policy_authorization_required');
 demand(a.allowIncompleteHistory===true&&a.noFakeClosure===true&&a.keepOldHolds===true&&a.oldLocksPreserved===true&&a.newIndependentAttemptOnly===true,'honest_uncertain_history_admission_required');
 demand(m.history.validResultPins.length===0,'retained_valid_policy_retry_forbidden');
 const f=JSON.parse(check(c.factsPin).toString());demand(f.protocol==='bench-nonblocking-history-facts-v1'&&f.taskId===m.taskId&&f.bench===m.bench&&f.startState!=='never-started','uncertain_facts_identity_required');
 for(const k of ['verifiedKnownUsd','verifiedUnknownReservationUsd'])demand(typeof f[k]==='number'&&Number.isFinite(f[k])&&f[k]>=0&&a[k]===f[k],'identified_cost_subtotal_preserved');
 if(f.historyCoverageComplete!==true)demand(f.totalKnownUsd===null&&f.totalUnknownReservationUsd===null,'unverified_total_must_remain_null');
 demand(m.original.priorKnownUsd===f.verifiedKnownUsd&&m.original.priorUnknownUsd===f.verifiedUnknownReservationUsd&&m.original.taskCapUsd===a.taskCapUsd,'manifest_identified_subtotals_not_total');
 demand(Number.isFinite(a.maximumNewSpendUsd)&&a.maximumNewSpendUsd>0&&a.maximumNewSpendUsd<=a.taskCapUsd-f.verifiedKnownUsd-f.verifiedUnknownReservationUsd+1e-9,'root_new_allocation_within_task_ceiling');
 demand(['original-task-contract','original-task-cash-config','root-signed-original-task-plan','root-current-conservative-allocation'].includes(a.budgetBasis),'explicit_budget_basis_required');check(a.originalContractPin);check(a.liveScopeEvidencePin);
 for(const k of ['cpu','memoryMb','solveSeconds','gradeSeconds','toolSeconds','providerSeconds','model','provider','reasoning'])demand(a.runtimeLimits?.[k]===m.original[k],'original_runtime_policy_unchanged:'+k);
 demand(a.runtimeLimits.providerSeconds===600&&a.runtimeLimits.model===p.runtimeContractUnchanged.model&&a.runtimeLimits.reasoning==='high','original_model_provider_clock');
 const lp=m.adapterConfig.taskLocks;demand(lp&&same(a.historicalLockPins,lp.historicalLockPins),'all_known_permanent_locks_preserved');for(const pin of [...(a.historicalLockPins??[]),...(f.evidencePins??[]),...(f.priorRunPins??[])])check(pin);
 for(const pin of [c.policyPin,c.authorizationPin,c.factsPin,c.activationPin,authority])demand([...m.provenance.contractPins,...m.provenance.sourcePins].some((p:any)=>same(p,pin)),'signed_policy_data_not_bound');
 check(c.activationPin);return {authorization:a,facts:f,policy:p,authorizationPin:c.authorizationPin};
}
export const hasHistoryAdmission=(m:any)=>!!historyAdmission(m);
export function manifestPinHistoryAdmission(p:any){return hasHistoryAdmission(JSON.parse(check(p).toString()));}
export function policyHistory(m:any){const v=historyAdmission(m);demand(v,'nonblocking_history_authorization_required');return {knownUsd:v.facts.verifiedKnownUsd,unknownUsd:v.facts.verifiedUnknownReservationUsd,calls:v.facts.verifiedCalls??null,remainingUsd:v.authorization.maximumNewSpendUsd,actorCids:v.facts.knownActorCids??[],historicalTotals:{knownUsd:v.facts.totalKnownUsd,unknownReservationUsd:v.facts.totalUnknownReservationUsd},historyCoverageComplete:v.facts.historyCoverageComplete===true,originalNativeClosed:null,originalFinancialClosed:null,uncertaintyAuthorized:true,authorizationPin:v.authorizationPin};}
export function policyRootEntry(m:any,e:any){const v=historyAdmission(m);demand(v&&same(e.rootReview?.nonblockingHistoryAuthorizationPin,v.authorizationPin),'root_signed_attempt_policy_join');return true;}
export function policyOriginalRecovery(m:any){const v=historyAdmission(m);demand(v,'nonblocking_history_authorization_required');return {status:'complete',proofPins:[v.authorizationPin,m.adapterConfig.nonblockingHistory.policyPin,m.adapterConfig.nonblockingHistory.factsPin],nativeClosed:false,financialClosed:false,candidateOrSubmissionPresent:v.facts.candidateOrSubmissionPresent!==false,reason:'root_authorized_uncertainty_no_old_financial_or_native_closure_claimed'};}
if(import.meta.main){demand(process.argv[2]==='--sign-task','root --sign-task exactAuthorizationJSON');const path=resolve(process.argv[3]),a=JSON.parse(readFileSync(path,'utf8'));demand(a.protocol==='bench-nonblocking-task-admission-v1','task_admission_protocol');const key=readFileSync(join(resolve(import.meta.dir,'../..'),'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/review-authority.private.pem'));writeFileSync(path+'.signed.json',JSON.stringify({protocol:'bench-root-signed-nonblocking-task-admission-v1',authorization:a,signature:sign(null,Buffer.from(JSON.stringify(a)),key).toString('base64')},null,2)+'\n',{flag:'wx',mode:0o600});console.log(JSON.stringify({signedPath:path+'.signed.json',modelCalls:0,secretsPrinted:false}));}
