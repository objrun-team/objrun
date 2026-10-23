/** Pure-data successor derivation. No dispatch, signing, resource RPC or Bench invocation. */
import {readFileSync,mkdirSync,writeFileSync,existsSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {verify,createHash} from 'node:crypto';
import {Database} from 'bun:sqlite';
import type {TaskManifest,AttemptContext,StageResult,Pin,Bench} from './types.ts';
import {pin,verifyPin,loadManifest,demand} from './manifest.ts';
import {verifyBenchmarkCashClosure} from '../benchmark-campaign/full-f/shared/digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from '../benchmark-campaign/full-f/shared/digitalocean-journal.ts';

export interface RetryClosureEvidence {
 protocol:'bench-retryable-closure-v1';taskId:string;bench:Bench;attemptId:string;runId:string;
 failureClass:string;cashClosePin:Pin;faultReceiptPin:Pin;nativeClosurePin:Pin;
}
export interface RetryPolicy {
 protocol:'bench-automatic-retry-policy-v1';scope:{benches:Bench[];taskIds:string[]};
 allowedFailureClasses:string[];maxAttempts:number;minBackoffMs:number;expiresAtUtc:string;
}
export interface RetryPolicyEnvelope {protocol:'bench-root-signed-retry-policy-v1';policy:RetryPolicy;signature:string}
export type RetryResult=StageResult&{retryEvidencePin?:Pin};
export interface RetryInput {manifestPath:string;context:AttemptContext;result:RetryResult;policyPin:Pin;now?:number|Date}
const read=(p:Pin):any=>{verifyPin(p);return JSON.parse(readFileSync(p.path,'utf8').replace(/^\uFEFF/,''))};
const same=(a:any,b:any)=>a?.path===b?.path&&a?.bytes===b?.bytes&&a?.sha256===b?.sha256;
const equal=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
function nativeClosure(p:Pin,e:RetryClosureEvidence){
 const n=read(p);demand(n.taskId===e.taskId&&n.runId===e.runId,'retry_native_identity');
 demand(n.resourceReleased===true&&n.brokerLaneClosed===true,'retry_native_lease_or_lane_open');
 demand(n.allNativeCommandStreamsClosed===true||n.allNativeCommandsClosed===true,'retry_native_commands_open');
 const ledger=n.ownedLedgerPin;
 demand(ledger,'retry_original_owned_ledger_required');verifyPin(ledger);
 for(const suffix of ['-wal','-shm'])if(existsSync(ledger.path+suffix)){
  const sidecar=n.ownedLedgerPins?.find((p:Pin)=>resolve(p.path)===resolve(ledger.path+suffix));
  demand(sidecar,'retry_native_ledger_sidecar_unpinned');verifyPin(sidecar);
 }
 const db=new Database(ledger.path,{readonly:true});let actors:any[];
 try {actors=db.query('select cid,closed from actor').all();demand(actors.every(a=>a.closed===1),'retry_owned_actor_open');
  for(const row of db.query('select json from command').all() as any[]){const c=JSON.parse(row.json);demand(c.closeObserved===true&&Number.isInteger(c.exitCode)&&!c.captureFaults?.length,'retry_native_command_receipt_open');}}
 finally{db.close()}
 verifyPin(ledger);for(const p of n.ownedLedgerPins??[])verifyPin(p);
 const absent=n.exactOwnedContainerApi404??[];
 demand(actors.every(a=>absent.some((x:any)=>x.cid===a.cid&&x.status===404)),'retry_actor_absence_not_bound');
 if(!actors.length)demand(n.noActorsEverCreated===true,'retry_empty_ledger_is_not_no_actor_proof');
 if(actors.length)demand(n.standClosePin&&n.engineClosePin,'retry_actor_process_receipts_required');
 for(const p of [n.standClosePin,n.engineClosePin].filter(Boolean)){const c=read(p);demand(c.exitObserved===true&&c.closeObserved===true,'retry_original_process_stream_open');for(const s of [c.stdout,c.stderr])verifyPin(s)}
 demand(Array.isArray(n.exactPidAbsence)&&n.exactPidAbsence.length>0&&n.exactPidAbsence.every((x:any)=>Number.isSafeInteger(x.pid)&&x.pid>0&&x.currentlyAbsent===true),'retry_exact_process_closure_required');
 return n;
}
function actualFault(p:Pin,e:RetryClosureEvidence,now:number){
 const f=read(p);demand(f.runId===e.runId&&f.taskId===e.taskId&&f.attemptId===e.attemptId,'retry_fault_identity');
 const at=Date.parse(f.atUtc??f.finishedAtUtc);demand(Number.isFinite(at)&&at<=now,'retry_fault_time');
 const code=f.transportFault??f.error?.code??f.code;
 const status=f.httpStatus;
 // A provider dispatch is not free merely because its upstream receipt was lost.
 demand(f.providerAttempted===true,'retry_actual_provider_attempt_not_proven');
 demand(['ECONNRESET','ETIMEDOUT'].includes(code)||[502,503,504].includes(status),'retry_unclassified_fault');
 demand(Number.isSafeInteger(f.requestSeq)&&f.requestSeq>=0,'retry_fault_request_sequence');
 return {at,transportFault:code??null,httpStatus:status??null,requestSeq:f.requestSeq};
}
function replacePin(value:any,old:Pin|undefined,next:Pin):any {
 if(old&&value&&typeof value==='object'&&same(value,old))return next;
 if(Array.isArray(value))return value.map(x=>replacePin(x,old,next));
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,replacePin(v,old,next)]));return value;
}
/** Returns pending-signature data only; caller must separately obey durable intake/backoff. */
export function deriveRetryManifest(input:RetryInput){
 const {context:c,result:r}=input,now=input.now instanceof Date?input.now.getTime():input.now??Date.now();
 demand(Number.isFinite(now),'retry_now');const manifestPin=pin(input.manifestPath),m=loadManifest(input.manifestPath);
 demand(same(manifestPin,c.manifestPin)&&c.taskId===m.taskId&&c.bench===m.bench,'retry_context_identity');
 demand(r.status==='retryable'&&r.nativeClosed===true&&r.financialClosed===true&&r.candidateOrSubmissionPresent===false&&!r.validResult,'retry_only_closed_no_candidate');
 demand(!m.history.validResultPins.length,'valid_never_retry');
 const authority:any=(m.adapterConfig.bindingSpec as any)?.authorityPin??m.adapterConfig.retryAuthorityPin;
 demand(authority&&m.provenance.contractPins.some(p=>same(p,authority)),'retry_root_authority_not_bound');verifyPin(authority);
 const envelope:RetryPolicyEnvelope=read(input.policyPin);demand(envelope.protocol==='bench-root-signed-retry-policy-v1','retry_signed_policy_required');
 demand(verify(null,Buffer.from(JSON.stringify(envelope.policy)),readFileSync(authority.path),Buffer.from(envelope.signature,'base64')),'retry_policy_signature');
 const policy=envelope.policy;demand(policy.protocol==='bench-automatic-retry-policy-v1'&&policy.scope.benches.includes(m.bench)&&policy.scope.taskIds.includes(m.taskId),'retry_policy_scope');
 demand(Number.isSafeInteger(policy.maxAttempts)&&policy.maxAttempts>0&&policy.maxAttempts<=3&&Number.isSafeInteger(policy.minBackoffMs)&&policy.minBackoffMs>=30000&&Date.parse(policy.expiresAtUtc)>now,'retry_policy_bounds');
 const history:any[]=Array.isArray(m.adapterConfig.retryHistory)?m.adapterConfig.retryHistory:[];
 demand(history.length<policy.maxAttempts,'retry_attempt_limit');
 if(r.retryEvidencePin)demand(r.proofPins.some(p=>same(p,r.retryEvidencePin)),'retry_evidence_not_in_result_proofs');
 const proofs=(r.retryEvidencePin?[r.retryEvidencePin]:r.proofPins).map(p=>{verifyPin(p);let value:any=null;
  if(p.bytes<=2*1024**2)try{value=JSON.parse(readFileSync(p.path,'utf8').replace(/^\uFEFF/,''))}catch{}
  return {pin:p,value};});
 const candidates=proofs.filter(x=>x.value?.protocol==='bench-retryable-closure-v1');demand(candidates.length===1,'retry_explicit_closure_evidence_required');
 const {pin:evidencePin,value:e}=candidates[0] as {pin:Pin;value:RetryClosureEvidence};
 demand(e.taskId===m.taskId&&e.bench===m.bench&&e.attemptId===c.attemptId&&typeof e.runId==='string'&&e.runId.length>0,'retry_closed_attempt_identity');
 demand(policy.allowedFailureClasses.includes(e.failureClass),'retry_failure_class_not_approved');
 const fault=actualFault(e.faultReceiptPin,e,now);nativeClosure(e.nativeClosurePin,e);
 const config:any=m.adapterConfig,oldBudgetPin:Pin|undefined=config.aggregateBudgetPin??config.terminalDriver?.aggregateBudgetPin;
 const oldBudget=oldBudgetPin?read(oldBudgetPin):undefined;
 const oldPins:Pin[]=config.historicalCashPins??oldBudget?.cashClosePins??[];
 demand(Array.isArray(oldPins),'retry_historical_cash_pins_required');
 if(oldBudget)demand(Array.isArray(oldBudget.cashClosePins)&&equal(oldBudget.cashClosePins,oldPins),'retry_history_chain_not_exact');
 let known=0,unknown=0,unknownCount=0;const seen=new Set<string>();const cashRows:any[]=[];
 const replay=(p:Pin)=>{const cash=verifyBenchmarkCashClosure(p),journal=inspectCampaignJournal(cash.proof.journalDirectory),s=cash.proof.snapshot;
  demand(cash.config.protocol==='openrouter-usd-cash-config-v1'&&cash.config.currency==='USD'&&journal.valid&&journal.accountingClosed&&s.pendingCount===0&&s.pendingReservationUsd===0,'retry_cash_journal_not_closed');
  demand(!seen.has(cash.config.runId),'retry_duplicate_cash_run');seen.add(cash.config.runId);
  demand(cash.config.capUsd<=m.original.taskCapUsd+1e-9&&s.billedUsd>=0&&s.unknownReservationUsd>=0,'retry_original_task_cap');
  known+=s.billedUsd;unknown+=s.unknownReservationUsd;unknownCount+=s.newUnknownCount;cashRows.push({runId:cash.config.runId,cashClosePin:p,knownUsd:s.billedUsd,unknownUsd:s.unknownReservationUsd});return cash;};
 for(const p of oldPins)replay(p);
 demand(Math.abs(known-m.original.priorKnownUsd)<1e-9&&Math.abs(unknown-m.original.priorUnknownUsd)<1e-9,'retry_previous_expense_coverage');
 const current=replay(e.cashClosePin);demand(current.config.runId===e.runId,'retry_cash_failed_run_identity');
 const actualJournal=inspectCampaignJournal(current.proof.journalDirectory),offset=actualJournal.offsets.get(fault.requestSeq);
 demand(offset,'retry_fault_not_in_actual_journal');
 const event=JSON.parse(readFileSync(actualJournal.journalPath).subarray(offset.offset,offset.offset+offset.bytes).toString('utf8'));
 demand(event.kind==='finish'&&event.requestSeq===fault.requestSeq&&event.record.providerAttempted===true&&
  (fault.transportFault?event.record.fault===fault.transportFault:event.record.httpStatus===fault.httpStatus),'retry_fault_actual_journal_mismatch');
 const finishedAt=Date.parse(event.record.finishedAt);demand(Number.isFinite(finishedAt)&&finishedAt<=now,'retry_actual_fault_finish_time');
 const allPins=[...oldPins,e.cashClosePin],first=verifyBenchmarkCashClosure(allPins[0]);
 demand(first.config.capUsd===m.original.taskCapUsd,'retry_first_actual_task_cap');
 const remaining=m.original.taskCapUsd-known-unknown;demand(remaining>0,'retry_original_budget_exhausted');
 const notBeforeUtc=new Date(Math.max(now,Math.max(fault.at,finishedAt)+policy.minBackoffMs)).toISOString();
 // All checks above are read-only. The unique directory contains no authority signature or runnable child.
 const identity={manifestPin,attemptId:c.attemptId,runId:e.runId,policyPin:input.policyPin,evidencePin};
 const key=createHash('sha256').update(JSON.stringify([m.bench,m.taskId,manifestPin.sha256,c.attemptId,e.runId])).digest('hex');
 const directory=join(resolve(c.runDir),'retry-data-'+key.slice(0,32)),completedPath=join(directory,'derivation-complete.json');
 if(existsSync(directory)){
  demand(existsSync(completedPath),'retry_partial_derivation_quarantined');
  const completed=read(pin(completedPath));demand(equal(completed.inputIdentity,identity),'retry_existing_derivation_identity_changed');
  for(const p of completed.outputPins)verifyPin(p);
  demand(completed.result.directory===directory&&completed.result.rootSignatureRequired===true&&completed.result.spawned===false&&
   completed.outputPins.some((p:Pin)=>same(p,completed.result.successorManifestPin))&&completed.outputPins.some((p:Pin)=>same(p,completed.result.retryProofPin)),'retry_completed_output_binding');
  const savedProof=read(completed.result.retryProofPin);demand(same(savedProof.predecessorManifestPin,manifestPin)&&savedProof.predecessorAttemptId===c.attemptId&&savedProof.predecessorRunId===e.runId,'retry_completed_lineage');
  loadManifest(completed.result.successorManifestPin.path);return completed.result as {directory:string;successorManifestPin:Pin;templatePin?:Pin;aggregateBudgetPin:Pin;retryProofPin:Pin;notBeforeUtc:string;remainingUsd:number;rootSignatureRequired:true;spawned:false};
 }
 mkdirSync(directory,{recursive:false});
 const save=(name:string,v:any)=>{const p=join(directory,name);writeFileSync(p,JSON.stringify(v,null,2)+'\n',{flag:'wx'});return pin(p)};
 const aggregateBudgetPin=save('aggregate-budget.pending-root.json',{...(oldBudget??{}),protocol:oldBudget?.protocol??'bench-original-task-budget-v1',rootReviewed:false,derivedFromReviewedPolicyPin:input.policyPin,taskId:m.taskId,cashClosePins:allPins,originalTaskCashConfigPin:first.proof.configPin,originalTaskCapUsd:m.original.taskCapUsd,knownUsd:known,unknownReservationUsd:unknown,unknownCount,exposureUpperBoundUsd:known+unknown,newAttemptMaxSpendUsd:remaining});
 const retryProofPin=save('retry-derivation.json',{protocol:'bench-data-retry-derivation-v1',rootReviewed:false,derivedFromReviewedPolicyPin:input.policyPin,predecessorManifestPin:manifestPin,predecessorAttemptId:c.attemptId,predecessorRunId:e.runId,evidencePin,cashClosePin:e.cashClosePin,faultReceiptPin:e.faultReceiptPin,nativeClosurePin:e.nativeClosurePin,cashRows,aggregateBudgetPin,notBeforeUtc,ordinal:history.length+1,newSignatureRequired:true,modelCalls:0});
 let successor:any=replacePin(structuredClone(m),oldBudgetPin,aggregateBudgetPin);
 successor.original.priorKnownUsd=known;successor.original.priorUnknownUsd=unknown;
 successor.adapterConfig.historicalCashPins=allPins;successor.adapterConfig.aggregateBudgetPin=aggregateBudgetPin;
 successor.adapterConfig.retryHistory=[...history,{proofPin:retryProofPin,attemptId:c.attemptId,runId:e.runId,notBeforeUtc}];
 successor.adapterConfig.pendingRootSignature=true;successor.adapterConfig.retryNotBeforeUtc=notBeforeUtc;
 let templatePin:Pin|undefined;
 if(config.bindingSpec){const oldTemplate=read(config.bindingSpec.entryTemplatePin);let template=replacePin(oldTemplate,oldBudgetPin,aggregateBudgetPin);
  template.coordinatorReviewed=false;template.phase='draft';template.nonce='{{bindings.NONCE}}';template.retryDerivationPin=retryProofPin;
  templatePin=save('entry-template.pending-root.json',template);successor.adapterConfig.bindingSpec.entryTemplatePin=templatePin;
  successor.provenance.contractPins=successor.provenance.contractPins.map((p:Pin)=>same(p,config.bindingSpec.entryTemplatePin)?templatePin:p);}
 successor.history.originalResultRecoveryRequired=true;
 successor.history.priorRunPins=[...m.history.priorRunPins,evidencePin,e.cashClosePin,e.faultReceiptPin,e.nativeClosurePin,retryProofPin];
 successor.provenance.contractPins.push(input.policyPin,retryProofPin,aggregateBudgetPin);
 demand(equal(successor.provenance.sourcePins,m.provenance.sourcePins)&&successor.original.taskCapUsd===m.original.taskCapUsd&&equal(successor.history.successfulStageProofs,m.history.successfulStageProofs),'retry_original_source_checkpoint_changed');
 const successorManifestPin=save('manifest.pending-root.json',successor);loadManifest(successorManifestPin.path);
 const result={directory,successorManifestPin,templatePin,aggregateBudgetPin,retryProofPin,notBeforeUtc,remainingUsd:remaining,rootSignatureRequired:true as const,spawned:false as const};
 save('derivation-complete.json',{protocol:'bench-data-retry-output-v1',inputIdentity:identity,result,outputPins:[successorManifestPin,aggregateBudgetPin,retryProofPin,...(templatePin?[templatePin]:[])]});
 return result;
}
