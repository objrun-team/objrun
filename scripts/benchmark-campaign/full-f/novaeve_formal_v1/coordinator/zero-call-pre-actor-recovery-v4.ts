/** Read-only root-reviewed recovery gate for a constructor failure before any actor exists. */
import {existsSync,readFileSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {verifyPin,jsonPin,same} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from '../../shared/digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from '../../shared/digitalocean-journal.ts';
function absent(pid:number){
 if(!Number.isSafeInteger(pid)||pid<=0)throw Error('pre_actor_exact_pid_required');
 try{process.kill(pid,0);throw Error('pre_actor_old_process_still_exists');}catch(e){if((e as any).code!=='ESRCH')throw e;}
}
export function verifyPreActorClosureProof(proofPin:any){
 verifyPin(proofPin);const p=jsonPin(proofPin);
 if(p.protocol!=='novaeve-zero-call-pre-actor-closure-v1'||p.complete!==true||p.modelCalls!==0||p.ownerCtorFailBeforeNative!==true||p.nativeLedgerCreated!==false||p.nativeCommandCount!==0||p.actorCreated!==false||p.actorCid!==null||p.engineStarted!==false)throw Error('pre_actor_never_created_evidence_required');
 [p.summaryPin,p.standClosePin,p.standStdoutPin,p.standStderrPin,p.providerRoutesPin,p.ownerConstructorSnapshotPin,p.sourceSnapshotManifestPin].forEach((p:any)=>verifyPin(p));
 const summary=jsonPin(p.summaryPin),close=jsonPin(p.standClosePin),routes=jsonPin(p.providerRoutesPin);
 if(summary.modelCalls!==0||summary.recordedTaskRuns!==0||summary.engineClosures.length!==0||summary.fatal?.message!=='tb12_stand_actual_startup'||routes.modelCalls!==0||routes.calls.length!==0||Object.keys(routes.pending??{}).length!==0)throw Error('pre_actor_run_started_provider_or_engine');
 if(!close.exitObserved||!close.closeObserved||close.exitCode!==1||close.port!==null||close.standReceipt!==null||close.faults.length!==0||close.pid!==p.exactStandPid||!same(close.stdout,p.standStdoutPin)||!same(close.stderr,p.standStderrPin)||!same(close.script,p.standScriptPin))throw Error('pre_actor_stand_exit_stream_close_required');
 if(!Array.isArray(close.argv)||resolve(close.argv[4])!==resolve(p.standScriptPin.path)||!close.argv.includes(p.oldReadinessPin.path)||!close.argv.includes(p.nativeOutputDirectory))throw Error('pre_actor_stand_command_identity_mismatch');
 if(resolve(p.nativeOutputDirectory)!==resolve(dirname(p.standClosePin.path),'stand')||resolve(p.nativeLedgerPath)!==resolve(p.nativeOutputDirectory,'owned-native.sqlite')||resolve(p.nativeReceiptsDirectory)!==resolve(p.nativeOutputDirectory,'native-receipts')||resolve(p.nativeSourceCapturePath)!==resolve(p.nativeOutputDirectory,'native-source.py')||resolve(p.nativeStandReceiptPath)!==resolve(p.nativeOutputDirectory,'stand-receipts.json'))throw Error('pre_actor_native_paths_not_bound_to_failed_output');
 const stderr=readFileSync(p.standStderrPin.path,'utf8'),stdout=readFileSync(p.standStdoutPin.path,'utf8');
 if(stdout.length||!stderr.includes('AssertionError')||!stderr.includes('docker_owned_setup_v3.py", line 51, in __init__'))throw Error('pre_actor_constructor_trace_not_proven');
 const snapshotManifest=jsonPin(p.sourceSnapshotManifestPin),constructor=readFileSync(p.ownerConstructorSnapshotPin.path,'utf8');
 if(!snapshotManifest.files.some((r:any)=>same(r.snapshotPin,p.ownerConstructorSnapshotPin)&&same(r.originalPin,p.oldOwnerConstructorSourcePin)))throw Error('pre_actor_constructor_snapshot_join');
 const body=constructor.slice(constructor.indexOf('class OwnedDocker:'));const assertion=body.indexOf('assert self.directory.is_relative_to(');
 if(assertion<0||body.indexOf('self.directory.mkdir')<=assertion||body.indexOf('self.db = sqlite3.connect')<=assertion||constructor.split(/\r?\n/)[50]?.trim().startsWith('assert self.directory.is_relative_to(')!==true)throw Error('pre_actor_native_ctor_order_not_proven');
 if(existsSync(p.nativeLedgerPath)||existsSync(p.nativeReceiptsDirectory)||existsSync(p.nativeSourceCapturePath)||existsSync(p.nativeStandReceiptPath))throw Error('pre_actor_native_artifacts_exist');
 absent(p.exactStandPid);absent(p.exactWorkerPid);
 return p;
}
export async function verifyZeroCallPreActorRecovery(entry:any){
 const r=entry.zeroCallPreActorRecovery;
 if(!r||r.rootReviewed!==true||!r.oldTaskLockPin||!r.oldExitPin||!r.oldCashClosePin||!r.preActorRecoveryPin||!r.changedSetupProofPin)throw Error('root_reviewed_pre_actor_recovery_required');
 [r.oldTaskLockPin,r.oldExitPin,r.oldCashClosePin,r.preActorRecoveryPin,r.changedSetupProofPin].forEach((p:any)=>verifyPin(p));
 const lock=jsonPin(r.oldTaskLockPin),exit=jsonPin(r.oldExitPin),proof=verifyPreActorClosureProof(r.preActorRecoveryPin);
 if(lock.taskId!==entry.taskId||lock.bench!==entry.bench||exit.taskId!==entry.taskId||exit.nonce!==lock.nonce||entry.nonce===lock.nonce||exit.retryAllowed!==false||exit.pid!==proof.exactWorkerPid||!same(proof.oldTaskLockPin,r.oldTaskLockPin)||!same(proof.oldExitPin,r.oldExitPin))throw Error('pre_actor_task_nonce_and_worker_join');
 const cash=verifyBenchmarkCashClosure(r.oldCashClosePin),journal=inspectCampaignJournal(cash.proof.journalDirectory),s=cash.proof.snapshot;
 if(!journal.valid||!journal.accountingClosed||journal.snapshot?.acceptedRequestCount!==0||journal.snapshot?.finishedRequestCount!==0||s.billedUsd!==0||s.pendingCount!==0||s.newUnknownCount!==0||s.pendingReservationUsd!==0||s.unknownReservationUsd!==0||cash.proof.releasePermitted!==true||proof.originalFailureRun!==cash.config.runId||!same(proof.oldCashClosePin,r.oldCashClosePin))throw Error('pre_actor_old_attempt_not_zero_call_closed');
 const change=jsonPin(r.changedSetupProofPin);
 if(change.protocol!=='novaeve-zero-call-changed-setup-v2'||change.rootReviewed!==true||change.taskId!==entry.taskId||!same(change.oldReadinessPin,proof.oldReadinessPin)||!same(change.newReadinessPin,entry.readinessPin)||!Array.isArray(change.newSourcePins)||!change.newSourcePins.length||!change.reason?.trim())throw Error('pre_actor_root_reviewed_changed_setup_required');
 verifyPin(change.oldReadinessPin);verifyPin(change.newReadinessPin);change.newSourcePins.forEach((p:any)=>verifyPin(p));
 if(change.oldReadinessPin.sha256===change.newReadinessPin.sha256||!change.newSourcePins.every((p:any)=>entry.sourcePins.some((s:any)=>same(p,s))))throw Error('pre_actor_new_readiness_source_binding');
 if(!change.newOwnerConstructorSourcePin||change.newOwnerConstructorSourcePin.sha256===proof.oldOwnerConstructorSourcePin.sha256||!change.newSourcePins.some((p:any)=>same(p,change.newOwnerConstructorSourcePin)))throw Error('pre_actor_ctor_source_must_change');
 verifyPin(change.newOwnerConstructorSourcePin);
 return {zeroCallPreActorRecovery:true,oldRunId:cash.config.runId,oldNonce:lock.nonce,newNonce:entry.nonce,actorEverCreated:false,oldStandPid:proof.exactStandPid,oldWorkerPid:proof.exactWorkerPid};
}
