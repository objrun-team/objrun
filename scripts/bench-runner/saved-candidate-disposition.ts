/** Same-authority, evidence-preserving original candidate disposition. Never grades or rewrites history. */
import {readFileSync} from 'node:fs';import {Database} from 'bun:sqlite';import {resolve} from 'node:path';import {verify} from 'node:crypto';import {pathToFileURL} from 'node:url';
import {checkPin,readPinned} from './runtime.ts';import {auditOriginalHistory,inspectOriginalHistory} from './original-history.ts';
import type {TaskManifest,Pin,StageResult} from './types.ts';
const need=(x:unknown,s:string)=>{if(!x)throw Error(s)},same=(a:any,b:any)=>!!a&&!!b&&resolve(a.path)===resolve(b.path)&&a.bytes===b.bytes&&a.sha256===b.sha256;
function bound(m:any,p:Pin,parse=true){checkPin(p);need([...m.provenance.sourcePins,...m.provenance.contractPins,...m.history.priorRunPins].some(x=>same(x,p)),'saved_candidate_pin_not_manifest_bound');return parse?readPinned(p):p}
const artifactKeys=['candidateArtifactPin','capsulePin','partialGradePin','originalPid1FramePin','rawCtrfPin','originalContractPin','closureProofPin','frameRecoveryProofPin'] as const;
/** Audit argument must come from auditOriginalHistory; exported separately for isolated signature/DB regression. */
export function verifySavedCandidateDisposition(m:TaskManifest,actual:ReturnType<typeof auditOriginalHistory>){
 const config:any=m.adapterConfig.savedCandidateDisposition;need(config?.protocol==='bench-saved-candidate-disposition-contract-v1','saved_candidate_disposition_required');
 const envelope=bound(m,config.envelopePin);need(envelope.protocol==='bench-root-signed-saved-candidate-disposition-v1'&&typeof envelope.signature==='string','saved_candidate_signed_envelope');const p=envelope.disposition;
 need(p?.protocol==='bench-saved-candidate-disposition-v1'&&p.taskId===m.taskId&&p.bench===m.bench,'saved_candidate_identity');
 need(!m.history.validResultPins.length&&!actual.resultPresent&&!actual.submitPresent&&!actual.unresolvedSubmitPresent,'saved_candidate_original_valid_or_submit_requires_recovery');
 need(Date.parse(p.expiresAtUtc)>Date.now(),'saved_candidate_disposition_expired');
 const old=bound(m,p.predecessorManifestPin),authority=(old.adapterConfig?.bindingSpec as any)?.authorityPin;checkPin(authority);
 need(same(authority,(m.adapterConfig.bindingSpec as any)?.authorityPin)&&same(authority,p.authorityPin),'saved_candidate_same_original_authority_required');
 need(verify(null,Buffer.from(JSON.stringify(p)),readFileSync(authority.path),Buffer.from(envelope.signature,'base64')),'saved_candidate_signature_invalid');
 need(old.taskId===m.taskId&&old.bench===m.bench,'saved_candidate_predecessor_identity');
 const lock=bound(m,p.oldAttemptLockPin),originalEnvelope=bound(m,lock.signedEntryPin);
 need(lock.attemptId===p.attemptId&&lock.taskId===m.taskId&&lock.bench===m.bench&&same(lock.manifestPin,p.predecessorManifestPin),'saved_candidate_old_attempt_lock_join');
 need(originalEnvelope.protocol==='novaeve-root-signed-entry-v4'&&verify(null,Buffer.from(JSON.stringify(originalEnvelope.entry)),readFileSync(authority.path),Buffer.from(originalEnvelope.signature,'base64')),'saved_candidate_original_entry_signature');
 const e=originalEnvelope.entry;need(e.nonce===p.attemptId&&e.taskId===m.taskId&&e.bench===m.bench&&same(e.rootRuntimeBinding?.manifestPin,p.predecessorManifestPin),'saved_candidate_original_signed_identity');
 bound(m,p.aggregateBudgetPin);need(same(p.aggregateBudgetPin,(m.adapterConfig.terminalDriver as any)?.aggregateBudgetPin),'saved_candidate_aggregate_budget_join');
 const history:any=m.adapterConfig.originalHistory;need(history&&JSON.stringify(p.canonicalLockPins)===JSON.stringify(history.canonicalLocks.map((x:any)=>x.pin)),'saved_candidate_canonical_coverage');
 for(const item of history.canonicalLocks){const l=bound(m,item.pin),env=bound(m,item.entryPin);need(same(l.entryPin,item.entryPin)&&l.nonce===item.nonce&&env.protocol==='novaeve-root-signed-entry-v4'&&env.entry.taskId===m.taskId&&env.entry.bench===m.bench&&env.entry.nonce===l.nonce&&verify(null,Buffer.from(JSON.stringify(env.entry)),readFileSync(authority.path),Buffer.from(env.signature,'base64')),'saved_candidate_canonical_original_signature');}
 const attempt=history.attempts.find((a:any)=>a.runId===p.runId);need(attempt&&attempt.mainDatabases.some((d:any)=>same(d.pin,p.mainDatabasePin)&&d.mainTaskId===p.mainTaskId),'saved_candidate_actual_attempt_database');
 const database=new Database(p.mainDatabasePin.path,{readonly:true});try{const row:any=database.query('select id,run,state,result from task where id=?').get(p.mainTaskId);need(row?.run===p.runId&&row.state==='claimed'&&row.result===null,'saved_candidate_actual_main_state');}finally{database.close();}
 const observation=actual.mainObservations.find((x:any)=>x.runId===p.runId&&x.mainTaskId===p.mainTaskId&&same(x.databasePin,p.mainDatabasePin));need(observation&&!observation.resultPresent&&!observation.submitPresent&&observation.submits.length===0,'saved_candidate_actual_main_no_final_result');
 // The audit reads the pinned original DB and every real journal/native ledger. Signed facts cannot override them.
 need(JSON.stringify(p.cashClosePins)===JSON.stringify(history.cashClosePins)&&p.fees.knownUsd===actual.knownUsd&&p.fees.unknownUsd===actual.unknownUsd&&p.fees.calls===actual.calls,'saved_candidate_complete_fee_coverage');
 need(p.originalContract.taskCapUsd===old.original.taskCapUsd&&p.originalContract.solveSeconds===old.original.solveSeconds&&p.originalContract.gradeSeconds===old.original.gradeSeconds&&p.originalContract.providerSeconds===old.original.providerSeconds,'saved_candidate_original_contract_join');
 for(const k of ['taskCapUsd','solveSeconds','gradeSeconds','providerSeconds','cpu','memoryMb','model','provider','reasoning','toolSeconds'])need((m.original as any)[k]===(old.original as any)[k],'saved_candidate_contract_cannot_expand:'+k);
 need(p.decisions?.originalFormalResultUnrecoverable===true&&p.decisions.originalCandidateCompletelyPreserved===true&&p.decisions.allowNewAttempt===true&&p.decisions.promoteOriginalValid===false&&p.decisions.regradeOriginal===false&&p.decisions.restoreCandidateIntoFreshWorkspace===false,'saved_candidate_explicit_narrow_decision');
 const facts=bound(m,p.factsPin);need(facts.taskId===m.taskId&&facts.bench===m.bench&&facts.attemptId===p.attemptId&&facts.runId===p.runId&&facts.originalCandidateOrSubmissionPresent===true&&facts.originalAssistantSubmitCount===0&&facts.originalMainTask?.id===p.mainTaskId&&facts.originalMainTask?.state==='claimed'&&facts.originalMainTask?.result===null&&facts.originalValidatorResult?.valid===false,'saved_candidate_original_rejection_facts');
 need(Array.isArray(config.candidateEvidencePins)&&config.candidateEvidencePins.length===artifactKeys.length,'saved_candidate_complete_artifacts');
 for(const k of artifactKeys){const pin=p[k];bound(m,pin,false);need(same(pin,facts[k])&&config.candidateEvidencePins.some((x:Pin)=>same(x,pin)),'saved_candidate_evidence_join:'+k)}
 need(attempt.closureProofPins.some((x:Pin)=>same(x,p.closureProofPin)),'saved_candidate_closure_not_actual_history');
 need(m.adapterConfig.unresolvedOriginalCandidatePins instanceof Array&&(m.adapterConfig.unresolvedOriginalCandidatePins as Pin[]).length>0&&(m.adapterConfig.unresolvedOriginalCandidatePins as Pin[]).every(x=>same(x,p.candidateArtifactPin)||same(x,p.capsulePin)),'saved_candidate_unresolved_inventory_coverage');
 return {protocol:'bench-verified-saved-candidate-disposition-v1',envelopePin:config.envelopePin,predecessorManifestPin:p.predecessorManifestPin,attemptId:p.attemptId,runId:p.runId,candidateOrSubmissionPresent:true,newAttemptPermitted:true,originalValidPromoted:false,candidateRestored:false};
}
export function inspectDispositionHistory(m:TaskManifest,c:any){
 const candidates=m.adapterConfig.unresolvedOriginalCandidatePins as Pin[]|undefined;
 const detected:Pin[]=[];for(const a of c.attempts??[]){for(const p of a.candidateCustodyPins??[])checkPin(p);for(const p of a.gradePins??[]){const g=readPinned(p);if(g.candidateArtifactPin){checkPin(g.candidateArtifactPin);detected.push(g.candidateArtifactPin)}else need(!g.candidateArtifactCapture&&!g.capsulePath,'original_saved_candidate_artifact_identity_missing')}}
 need(!(c.attempts??[]).some((a:any)=>a.candidateCustodyPins?.length)||!!candidates?.length,'original_saved_candidate_custody_requires_disposition_inventory');
 need(detected.every(p=>candidates?.some(x=>same(x,p))),'original_saved_candidate_requires_explicit_disposition_inventory');
 if(!candidates?.length){need(!m.adapterConfig.savedCandidateDisposition,'saved_candidate_inventory_required');return inspectOriginalHistory(m,c)}
 for(const p of candidates)checkPin(p);
 const actual=auditOriginalHistory(m,c),savedCandidateDisposition=verifySavedCandidateDisposition(m,actual);
 need(actual.rootDispositionApproved,'original_history_root_review_required');return {...actual,candidateOrSubmissionPresent:true,savedCandidateDisposition};
}
export async function inspectDispositionCurrentParent(m:TaskManifest){const d:any=m.adapterConfig.terminalDriver;const load=async(k:string)=>{const b=d.imports[k];checkPin(b.pin);return(await import(pathToFileURL(b.pin.path).href))[b.export]};const fresh=await load('freshHistory'),contract=await load('historyContract');return await fresh(contract());}
/** Rechecks original actual evidence on every host/queue use, never accepts a free-standing boolean. */
export function allowPreservedCandidateResult(m:TaskManifest,r:StageResult){need(r.candidateOrSubmissionPresent===true&&r.status==='retryable'&&r.nativeClosed&&r.financialClosed&&!r.validResult,'saved_candidate_result_not_closed');const actual=inspectDispositionHistory(m,m.adapterConfig.originalHistory);need(r.proofPins.some(x=>same(x,actual.savedCandidateDisposition.envelopePin)),'saved_candidate_result_missing_signed_disposition');return true;}
export function allowPreservedCandidateQueueResult(key:string,r:StageResult){const receipts=r.proofPins.filter(p=>{try{const x=readPinned(p);return x.protocol==='bench-actual-original-history-recovery-v1'&&x.manifestPin}catch{return false}});const unique=[...new Map(receipts.map(p=>[p.sha256+':'+p.bytes,p])).values()];need(unique.length===1,'saved_candidate_unique_recovery_receipt');const receipt=readPinned(unique[0]),m=readPinned(receipt.manifestPin);need(key===m.bench+':'+m.taskId,'saved_candidate_queue_task_join');return allowPreservedCandidateResult(m,r);}
