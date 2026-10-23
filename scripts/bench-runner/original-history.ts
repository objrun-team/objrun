/** Shared paid-history admission: preserve real canonical identities and recover original results first. */
import {readFileSync,existsSync} from 'node:fs';import {resolve} from 'node:path';import {Database} from 'bun:sqlite';
import type {Pin,TaskManifest} from './types.ts';import {checkPin,readPinned} from './runtime.ts';
import {verifyBenchmarkCashClosure} from '../repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from '../repair-2026-10-10/full-f/shared/digitalocean-journal.ts';
import {inspectPreNativeHistory} from './pre-native-history.ts';
import {createHash} from 'node:crypto';
export interface OriginalHistoryAttempt {
 runId:string;cashClosePin:Pin;summaryPin:Pin;processPin:Pin;standClosePin:Pin;
 engineClosePins:Pin[];ownedLedgerPins:Pin[];closureProofPins:Pin[];
 mainDatabases:{pin:Pin;sidecarPins:Pin[];mainTaskId:string}[];gradePins:Pin[];
}
export interface OriginalHistoryConfig {
 protocol:'bench-original-history-v1';taskId:string;bench:string;reviewPin:Pin;cashClosePins:Pin[];
 originalTaskCashConfigPin:Pin;attempts:OriginalHistoryAttempt[];
 canonicalLocks:{pin:Pin;nonce:string;entryPin:Pin}[];
 preservedSnapshotPins:Pin[];
  originalResultDispositionPin?:Pin;
}
const need=(x:unknown,message:string):void=>{if(!x)throw Error(message);};
const same=(a:Pin,b:Pin)=>a?.path===b?.path&&a?.sha256===b?.sha256&&a?.bytes===b?.bytes;
function checkedPin(m:TaskManifest,p:Pin){checkPin(p);need([...m.provenance.sourcePins,...m.provenance.contractPins,...m.history.priorRunPins].some(x=>same(x,p)),'original_history_pin_not_manifest_bound:'+p.path);}
function streams(m:TaskManifest,p:Pin){checkedPin(m,p);const c=readPinned(p);need(c.exitObserved===true&&c.closeObserved===true,'original_process_close_unproven');for(const s of [c.stdout,c.stderr])checkPin(s);return c;}
function finalHandIn(database:Database,id:string){
 const task:any=database.query('select id,run,mode,result,created_at,solve_seconds from task where id=?').get(id);need(task,'original_main_task_missing');
 if(task.result!==null)return {task,resultPresent:true,submitPresent:false,submits:[]};
 need(/^[A-Za-z0-9_]+$/.test(task.mode),'original_mode_identifier');
 const deadline=Number(task.created_at)+Number(task.solve_seconds)*1000;need(Number.isFinite(deadline)&&task.solve_seconds>0,'original_task_clock');
 const units=database.query('select agent,instance,unit from "task_'+task.mode+'" where task=?').all(id) as any[];const submits:any[]=[];
 for(const u of units){need(/^[A-Za-z0-9_]+$/.test(u.agent),'original_agent_identifier');for(const row of database.query('select seq,at,body from "agent_'+u.agent+'_msg" where instance=? and unit=? and kind=\'call\' and at<=?').all(u.instance,u.unit,deadline) as any[]){let payload:any;try{payload=JSON.parse(row.body);}catch{throw Error('original_call_payload_unparseable');}for(const call of payload.calls??[])if(call.name==='submit')submits.push({agent:u.agent,instance:u.instance,unit:u.unit,seq:row.seq,at:row.at,callId:call.id,answerSha256:createHash('sha256').update(typeof call.input?.answer==='string'?call.input.answer:'').digest('hex')});}}
 // Without a hand-in station the original policy may use last words; never infer their absence here.
 const station:any=database.query('select count(*) n from cycle where mode=? and cycle=\'submit\'').get(task.mode);need(station.n>0,'original_final_candidate_policy_requires_adapter_recovery');
 return {task,resultPresent:false,submitPresent:submits.length>0,submits};
}
/** Factual replay only. Root disposition is reported, never manufactured by this function. */
export function auditOriginalHistory(m:TaskManifest,c:OriginalHistoryConfig){
 need(c?.protocol==='bench-original-history-v1'&&c.taskId===m.taskId&&c.bench===m.bench,'original_history_identity');
 need(c.attempts.length>0&&c.attempts.length+((m.adapterConfig.preNativeRecoveryHistory??[]) as any[]).length===c.cashClosePins.length,'original_history_complete_cash_attempts');
 need(m.history.validResultPins.length===0,'valid_wrong_must_never_repeat');
 checkedPin(m,c.reviewPin);const review=readPinned(c.reviewPin);need(review.protocol==='bench-original-history-review-v1'&&review.taskId===m.taskId&&review.bench===m.bench,'original_history_review_identity');
 need(JSON.stringify(review.cashClosePins)===JSON.stringify(c.cashClosePins)&&JSON.stringify(review.attemptRunIds)===JSON.stringify(c.attempts.map(x=>x.runId)),'original_history_review_coverage');
 checkedPin(m,c.originalTaskCashConfigPin);const original=readPinned(c.originalTaskCashConfigPin);need(original.capUsd===m.original.taskCapUsd,'original_task_cap_config');
 let knownUsd=0,unknownUsd=0,calls=0,resultPresent=false,submitPresent=false;const seen=new Set<string>(),actorCids:string[]=[],nativeRows:any[]=[],mainObservations:any[]=[];
 for(const a of c.attempts){
  need(c.cashClosePins.some(p=>same(p,a.cashClosePin)),'original_cash_coverage');checkedPin(m,a.cashClosePin);
  const cash=verifyBenchmarkCashClosure(a.cashClosePin),journal=inspectCampaignJournal(cash.proof.journalDirectory),s=cash.proof.snapshot;
  need(!seen.has(a.runId)&&cash.config.runId===a.runId,'original_history_unique_actual_run');seen.add(a.runId);
  need(cash.config.capUsd<=m.original.taskCapUsd+1e-9&&journal.valid&&journal.accountingClosed&&s.pendingCount===0&&s.pendingReservationUsd===0,'original_history_cash_not_closed');
  knownUsd+=s.billedUsd;unknownUsd+=s.unknownReservationUsd;calls+=journal.snapshot!.acceptedRequestCount;
  checkedPin(m,a.summaryPin);const summary=readPinned(a.summaryPin);need(summary.runId===a.runId,'original_summary_run');
  if(summary.taskPins?.length)resultPresent=true;
  checkedPin(m,a.processPin);const process=readPinned(a.processPin);need(process.runId===a.runId,'original_process_run');streams(m,a.standClosePin);for(const p of a.engineClosePins)streams(m,p);
  need(a.ownedLedgerPins.length>0&&a.closureProofPins.length>0,'original_native_custody_required');for(const p of [...a.ownedLedgerPins,...a.closureProofPins])checkedPin(m,p);
  const custody=review.attemptClosures?.find((x:any)=>x.runId===a.runId);need(custody&&custody.brokerLaneClosed===true&&custody.resourceReleased===true&&custody.originalProcessesClosed===true&&JSON.stringify(custody.proofPins)===JSON.stringify(a.closureProofPins),'original_custody_review_coverage');
  const ledger=a.ownedLedgerPins.find(p=>p.path.endsWith('.sqlite'));need(ledger,'original_native_ledger_required');
  for(const suffix of ['-wal','-shm'])if(existsSync(ledger!.path+suffix))need(a.ownedLedgerPins.some(p=>resolve(p.path)===resolve(ledger!.path+suffix)),'original_native_sidecar_unpinned');
  const db=new Database(ledger!.path,{readonly:true});let actors=0,commands=0;const runActorCids:string[]=[];try{
   for(const row of db.query('select cid,closed from actor').all() as any[]){need(row.closed===1&&/^[a-f0-9]{64}$/.test(row.cid),'original_actor_custody_open');actorCids.push(row.cid);runActorCids.push(row.cid);actors++;}
   for(const row of db.query('select json from command').all() as any[]){const command=JSON.parse(row.json);need(command.closeObserved===true&&Number.isInteger(command.exitCode)&&!command.captureFaults?.length,'original_command_capture_open');commands++;}
  }finally{db.close();}nativeRows.push({runId:a.runId,actors,commands,actorCids:runActorCids});
  for(const d of a.mainDatabases){checkedPin(m,d.pin);for(const p of d.sidecarPins)checkedPin(m,p);for(const suffix of ['-wal','-shm'])if(existsSync(d.pin.path+suffix))need(d.sidecarPins.some(p=>resolve(p.path)===resolve(d.pin.path+suffix)),'original_main_db_sidecar_unpinned');
   const db=new Database(d.pin.path,{readonly:true});try{const f=finalHandIn(db,d.mainTaskId);need(f.task.run===a.runId,'original_main_run');resultPresent ||= f.resultPresent;submitPresent ||= f.submitPresent;mainObservations.push({runId:a.runId,mainTaskId:d.mainTaskId,databasePin:d.pin,resultPresent:f.resultPresent,submitPresent:f.submitPresent,submits:f.submits});}finally{db.close();}
  }
  for(const p of a.gradePins){checkedPin(m,p);const grade=readPinned(p);need(grade.taskId===m.taskId,'original_grade_task_identity');if(grade.result)resultPresent=true;}
 }
 const preNative=inspectPreNativeHistory(m,{cashClosePins:c.cashClosePins},seen);knownUsd+=preNative.knownUsd;unknownUsd+=preNative.unknownUsd;calls+=preNative.calls;
 need(seen.size===c.cashClosePins.length&&Math.abs(knownUsd-m.original.priorKnownUsd)<1e-9&&Math.abs(unknownUsd-m.original.priorUnknownUsd)<1e-9,'original_all_cash_exposure_preserved');
 need(c.canonicalLocks.length>0,'real_historical_canonical_required');for(const l of c.canonicalLocks){checkedPin(m,l.pin);checkedPin(m,l.entryPin);const lock=readPinned(l.pin),entry=readPinned(l.entryPin);need(lock.taskId===m.taskId&&lock.bench===m.bench&&lock.nonce===l.nonce&&same(lock.entryPin,l.entryPin),'real_canonical_nonce_entry_join');const e=entry.entry??entry;need(e.taskId===m.taskId&&e.nonce===l.nonce,'historical_entry_identity');}
 need(JSON.stringify(review.canonicalLockPins)===JSON.stringify(c.canonicalLocks.map(x=>x.pin)),'review_canonical_coverage');for(const p of c.preservedSnapshotPins)checkedPin(m,p);
 let resolvedSubmits=0,dispositionApproved=false;const resolutionProofPins:Pin[]=[];
 if(c.originalResultDispositionPin){checkedPin(m,c.originalResultDispositionPin);const disposition=readPinned(c.originalResultDispositionPin);need(disposition.protocol==='bench-original-result-disposition-v1'&&disposition.taskId===m.taskId&&disposition.bench===m.bench,'original_disposition_identity');
  for(const resolution of disposition.resolutions??[]){checkedPin(m,resolution.proofPin);const proof=readPinned(resolution.proofPin);need(proof.protocol==='bench-original-result-recovery-readonly-review-v1'&&proof.taskId===m.taskId&&proof.bench===m.bench&&proof.runId===resolution.runId,'original_disposition_proof_identity');
   need(proof.validResultRecoverableFromExistingGrade===false&&proof.originalGrade?.standGradeRows===0&&proof.originalGrade?.gradeJsonFiles?.length===0&&proof.originalGrade?.taskResult===null&&proof.originalCandidate?.existed===true&&proof.originalCandidate?.ownedLedgerClosed===true&&proof.originalCandidate?.filesystemSnapshotOrCapsulePresentInRun===false&&proof.originalSubmit?.ran===false&&proof.originalSubmit?.exactOriginalToolReason==='this station ended before the call was run','original_disposition_not_unexecuted_destroyed_candidate');
   const observation=mainObservations.find(x=>x.runId===resolution.runId&&x.mainTaskId===resolution.mainTaskId);need(observation&&!observation.resultPresent,'original_disposition_main_identity');checkPin(proof.originalSubmit.extractPin);const extract=readPinned(proof.originalSubmit.extractPin),call=extract.assistantSubmit,tool=extract.matchingToolResponse;
   need(nativeRows.some(x=>x.runId===resolution.runId&&x.actorCids.includes(proof.originalCandidate.cid)),'original_disposition_destroyed_candidate_identity');
   need(extract.task?.id===observation.mainTaskId&&extract.task?.run===observation.runId&&extract.databasePins?.some((p:Pin)=>same(p,observation.databasePin)),'original_submit_extract_database_join');
   const agent=observation.submits.find((s:any)=>s.callId===proof.originalSubmit.callId)?.agent;need(typeof agent==='string'&&/^[A-Za-z0-9_]+$/.test(agent),'original_disposition_agent_identity');
   const db=new Database(observation.databasePin.path,{readonly:true});try{for(const row of [call,tool]){const actual:any=db.query('select body,at,kind from "agent_'+agent+'_msg" where instance=? and unit=? and seq=?').get(row.instance,row.unit,row.seq);need(actual&&actual.body===row.body&&actual.at===row.at&&actual.kind===row.kind,'original_submit_extract_actual_row_mismatch');}}finally{db.close();}
   const response=JSON.parse(tool.body);need(response.id===proof.originalSubmit.callId&&response.name==='submit'&&response.value?.ran===false&&response.value?.why===proof.originalSubmit.exactOriginalToolReason,'original_submit_tool_not_unexecuted');
   const matches=observation.submits.filter((s:any)=>s.callId===response.id&&s.instance===call.instance&&s.unit===call.unit&&s.seq===call.seq&&s.answerSha256===proof.originalSubmit.answerSha256);need(matches.length===1,'original_submit_resolution_not_exact');
   need(!resolutionProofPins.some(p=>same(p,resolution.proofPin)),'duplicate_original_submit_resolution');resolutionProofPins.push(resolution.proofPin);resolvedSubmits++;
  }
  dispositionApproved=disposition.rootReviewed===true;
 }
 const submitCount=mainObservations.reduce((n,x)=>n+x.submits.length,0),unresolvedSubmitPresent=submitCount>0&&(!dispositionApproved||resolvedSubmits!==submitCount);
 return {knownUsd,unknownUsd,calls,remainingUsd:m.original.taskCapUsd-knownUsd-unknownUsd,actorCids:[...new Set(actorCids)],nativeRows,mainObservations,resultPresent,submitPresent,unresolvedSubmitPresent,resolvedSubmits,dispositionApproved,resolutionProofPins,
  candidateOrSubmissionPresent:resultPresent||submitPresent,preservedIntermediateSnapshotCount:c.preservedSnapshotPins.length,canonicalIdentityPreserved:true,
  rootDispositionApproved:review.rootReviewed===true&&review.resultDisposition==='closed-failure-no-final-handin'};
}
export function inspectOriginalHistory(m:TaskManifest,c:OriginalHistoryConfig){const actual=auditOriginalHistory(m,c);need(!actual.resultPresent&&!actual.unresolvedSubmitPresent,'original_result_requires_adapter_recovery');need(actual.rootDispositionApproved,'original_result_disposition_requires_root_review');return {...actual,candidateOrSubmissionPresent:false,historicalSubmitPresent:actual.submitPresent,legacyIdentityPreserved:false};}
