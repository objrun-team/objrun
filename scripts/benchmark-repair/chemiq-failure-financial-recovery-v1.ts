/** Append-only financial recovery for an exited ChemIQ V2 owner; never creates a score or model call. */
import { closeSync, fsyncSync, openSync, readFileSync, readdirSync, unlinkSync, existsSync } from 'node:fs';
import { join, resolve, basename } from 'node:path';
import { spawn } from 'node:child_process';
import { actualPin, demand, gzipProof, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { CHEMIQ_F_ROOT as ROOT, loadChemiqFPlan, chemiqOrdinary } from './chemiq-f-journal-contract-v2.ts';
import { assertChemiqJournalExport } from './audit-chemiq-f-journal-v2.ts';
import { chemiqActorCommand, assertChemiqOwnedFrame } from './chemiq-f-owned-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';
const RUN='repair-2026-10-09T09-40-03-707Z',OUTPUT=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-campaigns-v2',RUN),STORE=join(ROOT,'.phase1-data/chemiq-f-journal-v2',RUN);
const HOME=join(ROOT,'docs/repair-2026-10-08/chemiq-f-financial-recoveries-v2',RUN),LOCK=join(ROOT,'.phase1-data/owned-paid-campaign.lock.json');
const PS='C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
export const CHEMIQ_FAILED_RECOVERY_SOURCE=actualPin(import.meta.path);
function inputs(){
  const manifestPin=actualPin(join(OUTPUT,'manifest.json')),manifest=jsonPin(manifestPin),recipe=jsonPin(manifest.recipePin),admissionPin=actualPin(join(OUTPUT,'chemiq-admission.json')),admission=jsonPin(admissionPin);
  demand(manifest.family==='chemiq-f-journal-v2'&&manifest.runId===RUN&&manifest.scope==='pilot16'&&manifest.plannedTaskRuns===16&&manifest.taskSeconds===900&&recipe.output===OUTPUT&&recipe.store===STORE,'recovery_exact_failed_scope');
  const plan=loadChemiqFPlan(RUN,'pilot16'),failurePin=actualPin(join(OUTPUT,'failure.json')),failure=jsonPin(failurePin);
  demand(failure.protocol==='chemiq-f-failure-v2'&&failure.runId===RUN&&failure.lockRetained===true&&failure.originalUnknownSettled===false&&failure.modelForwardingEnabled===true,'recovery_original_failure');
  demand(admission.owned.pid===122388&&admission.owned.runId===RUN&&admission.owned.ownerNonce==='4bdb76b522e42c56d8a12e6e3df6cf2c0bb5f4524dcbecf8','recovery_exact_original_nonce');
  for(const p of [...recipe.sourcePins,...Object.values(recipe.hostExecutors) as Pin[]])verifyPin(p);
  const nativeExitPin=actualPin(join(OUTPUT,'native-paid-entry-exit-01.log')),nativeExit=readFileSync(nativeExitPin.path,'utf8');
  demand(nativeExit.includes('pid: 122452')&&nativeExit.includes('spawnSync docker ETIMEDOUT')&&nativeExit.includes('objrun-repair-chemiq-local-opsin-raw-length'),'recovery_exact_inspect_child');
  const registrations=readdirSync(OUTPUT).filter(n=>/^paid-process-\d+\.json$/.test(n)).sort((a,b)=>Number(a.match(/\d+/)![0])-Number(b.match(/\d+/)![0])).map(n=>actualPin(join(OUTPUT,n)));
  demand(registrations.length===16&&registrations.every((p,i)=>{const r=jsonPin(p);return r.protocol==='paid-owned-process-v2'&&r.family===manifest.family&&r.runId===RUN&&r.taskIndex===i&&r.ownerNonce===admission.owned.ownerNonce;}),'recovery_complete_worker_registry');
  const portPin=actualPin(join(OUTPUT,'failed-owned-grading-port-recovery.json')),portProof=jsonPin(portPin),copyPin=actualPin(join(OUTPUT,'failed-owned-sqlite-copy-observation.json')),copy=jsonPin(copyPin);
  demand(copy.protocol==='chemiq-failed-owned-sqlite-copy-observation-v2'&&copy.originalChanged===false&&copy.ownedTaskRows.length===1&&copy.ownedTaskRows[0][0]===plan.tasks[12].taskId&&copy.ownedTaskRows[0][4]===900,'recovery_owned_db_identity');
  for(const p of copy.sourcePins)verifyPin(p);for(const p of portProof.sourcePins)verifyPin(p);
  demand(same(portProof.copyObservationPin,copyPin)&&portProof.originalChanged===false&&portProof.gradePort===64182&&portProof.providerPort===64184&&same(portProof.declaredHandles,['http://127.0.0.1:64182/correct','http://127.0.0.1:64182/parsed']),'recovery_owned_gateway_ports');
  const workers=registrations.map(p=>jsonPin(p));
  const pids=[...workers.map(r=>r.pid),admission.owned.pid,122452],ports=[...new Set([...workers.map(r=>Number(new URL(r.base).port)),64182,64184])];
  demand(new Set(pids).size===pids.length,'recovery_actor_inventory');
  return {manifestPin,manifest,recipe,plan,admissionPin,admission,failurePin,failure,nativeExitPin,registrations,portPin,copyPin,pids,ports};
}
async function observe(stage:string){
  const input=inputs(),command=chemiqActorCommand(input.pids,input.ports),requestPin=durableChemiqJson(join(HOME,'owned-'+stage+'-request.json'),{protocol:'chemiq-failure-recovery-native-request-v1',stage,command,pids:input.pids,ports:input.ports,registrationPins:input.registrations,admissionPin:input.admissionPin,portRecoveryPin:input.portPin,nativeExitPin:input.nativeExitPin,sourcePin:CHEMIQ_FAILED_RECOVERY_SOURCE,executablePin:actualPin(PS),startedAtUtc:new Date().toISOString(),timeoutMs:10000});
  const env={...process.env};for(const key of Object.keys(env))if(key.toLowerCase()==='psmodulepath')delete env[key];env.PSModulePath='C:/Windows/System32/WindowsPowerShell/v1.0/Modules';
  const result=await new Promise<any>((resolve,reject)=>{const child=spawn(PS,['-NoProfile','-NonInteractive','-Command',command],{windowsHide:true,env,stdio:['ignore','pipe','pipe']});let stdout='',stderr='',timedOut=false;const timer=setTimeout(()=>{timedOut=true;child.kill('SIGKILL');},10000);child.stdout.on('data',b=>{stdout+=b.toString();if(stdout.length>262144)child.kill('SIGKILL');});child.stderr.on('data',b=>{stderr+=b.toString();if(stderr.length>65536)child.kill('SIGKILL');});child.once('error',e=>{clearTimeout(timer);reject(e);});child.once('close',status=>{clearTimeout(timer);resolve({status,stdout,stderr,timedOut,completedAtUtc:new Date().toISOString()});});});
  const transcriptPin=durableChemiqJson(join(HOME,'owned-'+stage+'-transcript.json'),result);
  demand(result.status===0&&!result.timedOut&&!result.stderr.trim(),'recovery_native_observation_failed');const parsed=JSON.parse(result.stdout.trim());assertChemiqOwnedFrame(parsed,input.pids,input.ports);
  return durableChemiqJson(join(HOME,'owned-'+stage+'-observation.json'),{protocol:'chemiq-failure-recovery-owned-close-v1',requestPin,transcriptPin,parsed,closed:true,modelCalls:0});
}
function verifyOwned(pin:Pin){
  const input=inputs(),proof=jsonPin(pin),request=jsonPin(proof.requestPin),transcript=jsonPin(proof.transcriptPin);
  demand(proof.protocol==='chemiq-failure-recovery-owned-close-v1'&&proof.closed===true&&proof.modelCalls===0&&same(request.pids,input.pids)&&same(request.ports,input.ports)&&same(request.registrationPins,input.registrations)&&request.command===chemiqActorCommand(input.pids,input.ports),'recovery_owned_binding');
  demand(transcript.status===0&&!transcript.timedOut&&!transcript.stderr.trim()&&same(JSON.parse(transcript.stdout.trim()),proof.parsed),'recovery_native_raw_binding');
  assertChemiqOwnedFrame(proof.parsed,input.pids,input.ports);verifyPin(request.executablePin);verifyPin(request.sourcePin);
  demand(request.sourcePin.sha256===CHEMIQ_FAILED_RECOVERY_SOURCE.sha256,'recovery_observer_source');return {proof,request,transcript};
}
export function auditChemiqFailedFinancialRecovery(){
  const input=inputs(),proofPin=actualPin(join(HOME,'financial-only-certificate.json')),proof=jsonPin(proofPin),cash=verifyCashClosure(proof.cashClosePin),journal=inspectCampaignJournal(STORE),ledger=jsonPin(actualPin(join(OUTPUT,'api-ledger.json')));
  demand(proof.protocol==='chemiq-failed-run-financial-only-certificate-v1'&&proof.runId===RUN&&proof.ownerNonce===input.admission.owned.ownerNonce&&proof.scoreCertificateValid===false&&proof.originalRunSucceeded===false&&proof.originalPoisonPreserved===true&&proof.oldUnknownSettled===false,'recovery_financial_only_certificate');
  demand(journal.valid&&journal.accountingClosed&&cash.proof.snapshot.poisoned===true&&cash.proof.snapshot.poisonReason==='unacknowledged_admission'&&cash.proof.snapshot.pendingCount===0&&cash.proof.snapshot.newUnknownCount===0&&cash.config.carryNanoCny==='8392180000'&&same(cash.proof.snapshot,input.failure.cash),'recovery_preserved_cash_state');
  assertChemiqJournalExport(ledger,journal,RUN,new Set(input.plan.tasks.map(t=>t.route)));
  demand(ledger.calls.length===367&&ledger.calls.every((r:any)=>r.providerAttempted===true&&r.httpStatus===200)&&new Set(ledger.calls.map((r:any)=>r.route)).size===16,'recovery_exact_actual_calls');
  const failed=jsonPin(proof.undispatchedFailurePin),unadmitted=gzipProof(failed.files[0],failed.requestSha256,undefined,4*1024**2);
  demand(failed.stage==='admission'&&failed.requestSeq===undefined&&failed.providerAttempted===false&&failed.confirmedNoForward===true&&failed.independentCost.usdUpperBound===0&&failed.independentCost.deltaUsd===0&&failed.files.length===1&&hash(unadmitted)===failed.requestSha256&&!ledger.calls.some((r:any)=>r.requestSha256===failed.requestSha256),'recovery_undispatched_not_unknown_or_overlap');
  demand(readdirSync(join(STORE,'journal-failures')).filter(n=>/^failure-\d+-receipt\.json$/.test(n)).length===1,'recovery_failure_inventory');
  verifyOwned(proof.ownedClosePin);verifyPin(proof.sourcePin);demand(proof.sourcePin.sha256===CHEMIQ_FAILED_RECOVERY_SOURCE.sha256,'recovery_certificate_source');
  return {protocol:'chemiq-failed-run-financial-audit-v1',runId:RUN,certificatePin:proofPin,sourcePin:CHEMIQ_FAILED_RECOVERY_SOURCE,financialClosed:true,scoreCertificateValid:false,originalPoisonPreserved:true,actualModelCalls:367,actualDifferentTasks:16,recordedTaskRows:15,originalMissingTaskIndex:12,oldUnknownSettled:false,oldUnknownCarryNanoCny:'8392180000',newPendingCount:0,newUnknownCount:0,estimatedCny:cash.proof.snapshot.newKnownEstimatedNanoCny,recordedCostUpperBoundUsd:ledger.recordedUsageUpperBoundUsd,modelCallsByAuditor:0};
}
async function prepare(){
  const input=inputs();demand(existsSync(LOCK)&&same(JSON.parse(readFileSync(LOCK,'utf8')),input.admission.owned),'recovery_current_exact_owner');
  const ownedClosePin=await observe('prepare'),configPin=actualPin(join(STORE,'currency/cash-config.json')),config=jsonPin(configPin),eventsPin=actualPin(join(STORE,'currency/cash-events.jsonl'));
  const raw=readFileSync(eventsPin.path);let seq=0,bytes=0,last=configPin.sha256;for(const lineText of raw.toString('utf8').split('\n')){if(!lineText)continue;const line=Buffer.from(lineText+'\n'),e=JSON.parse(lineText);demand(Buffer.from(JSON.stringify(e)+'\n').equals(line)&&e.eventSeq===seq&&e.previousEventSha256===last,'recovery_cash_chain');seq++;bytes+=line.length;last=hash(line);}demand(bytes===raw.length,'recovery_cash_exact_eof');
  const journal=inspectCampaignJournal(STORE);demand(journal.valid&&journal.accountingClosed,'recovery_journal_closed');
  const cashClosePin=durableChemiqJson(join(HOME,'cash-close-replayed.json'),{protocol:'cny-shadow-close-v2',runId:RUN,ownerNonce:config.ownerNonce,configPin,cashEventsPin:eventsPin,cashPrefix:{bytes,eventCount:seq,lastSha256:last},journalConfigPin:config.journalConfigPin,journalSourcePin:config.journalSourcePin,journalDirectory:STORE,journalPrefix:journal.prefix,journalValid:true,journalAccountingClosed:true,snapshot:input.failure.cash,releasePermitted:true,poisonReason:input.failure.cash.poisonReason,invoice:false,foreignExchangeConversion:false,replayedAfterOwnerExit:true,originalRuntimeCashCloseCreated:false,recoverySourcePin:CHEMIQ_FAILED_RECOVERY_SOURCE});
  verifyCashClosure(cashClosePin);
  const certificatePin=durableChemiqJson(join(HOME,'financial-only-certificate.json'),{protocol:'chemiq-failed-run-financial-only-certificate-v1',runId:RUN,family:'chemiq-f-journal-v2',ownerNonce:input.admission.owned.ownerNonce,createdAtUtc:new Date().toISOString(),admissionPin:input.admissionPin,originalFailurePin:input.failurePin,nativeExitPin:input.nativeExitPin,ownedClosePin,cashClosePin,undispatchedFailurePin:actualPin(join(STORE,'journal-failures/failure-0-receipt.json')),originalRunSucceeded:false,scoreCertificateValid:false,originalPoisonPreserved:true,oldUnknownSettled:false,sourcePin:CHEMIQ_FAILED_RECOVERY_SOURCE});
  const audit=auditChemiqFailedFinancialRecovery(),auditPin=durableChemiqJson(join(HOME,'financial-only-audit.json'),audit);
  console.log(JSON.stringify({certificatePin,auditPin,financialClosed:true,scoreCertificateValid:false,canonicalLockReleased:false,modelCalls:0}));
}
async function release(){
  const input=inputs(),audit=auditChemiqFailedFinancialRecovery(),source=CHEMIQ_FAILED_RECOVERY_SOURCE;
  const reviewHome=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/independent-failed-financial-recovery-review-v1');
  const reviewPins=['spec-review.json','standards-review.json'].map(n=>actualPin(join(reviewHome,n)));
  for(const p of reviewPins){const r=jsonPin(p);demand(r.protocol==='chemiq-failed-financial-recovery-independent-review-v1'&&r.remainingFinancialReleaseBlockers===0&&r.scoreCertificateValid===false&&same(r.recoverySourcePin,source)&&same(r.financialCertificatePin,audit.certificatePin)&&r.modelCalls===0,'recovery_independent_reviews_required');}
  const ownedClosePin=await observe('release'),fresh=verifyOwned(ownedClosePin);demand(Date.now()-Date.parse(fresh.transcript.completedAtUtc)<=60000,'recovery_live_closure_stale');
  const lockPin=actualPin(LOCK);demand(same(JSON.parse(readFileSync(LOCK,'utf8')),input.admission.owned),'recovery_foreign_owner');verifyPin(source);auditChemiqFailedFinancialRecovery();verifyPin(lockPin);
  const authorizationPin=durableChemiqJson(join(HOME,'exact-lock-release-authorization.json'),{protocol:'chemiq-failed-run-exact-lock-release-authorization-v1',runId:RUN,ownerNonce:input.admission.owned.ownerNonce,lockPin,certificatePin:audit.certificatePin,ownedClosePin,reviewPins,sourcePin:source,financialOnly:true,scoreCertificateValid:false,oldUnknownSettled:false,createdAtUtc:new Date().toISOString()});
  verifyPin(lockPin);demand(same(JSON.parse(readFileSync(LOCK,'utf8')),input.admission.owned),'recovery_owner_changed_before_unlink');unlinkSync(LOCK);
  const ackPin=durableChemiqJson(join(HOME,'exact-lock-release-committed.json'),{protocol:'chemiq-failed-run-exact-lock-release-committed-v1',runId:RUN,ownerNonce:input.admission.owned.ownerNonce,released:true,authorizationPin,financialOnly:true,scoreCertificateValid:false,originalV2RegistryUnchanged:true,oldUnknownSettled:false,createdAtUtc:new Date().toISOString()});
  durableChemiqJson(join(HOME,'recovery-index.json'),{protocol:'chemiq-failed-run-financial-recovery-index-v1',runId:RUN,originalRegistryPin:actualPin(join(OUTPUT,'chemiq-paid-resource-run.json')),certificatePin:audit.certificatePin,releaseCommittedPin:ackPin,sourcePin:source,recordedCostUpperBoundUsd:audit.recordedCostUpperBoundUsd,financialClosed:true,scoreCertificateValid:false});
  console.log(JSON.stringify({ackPin,financialClosed:true,scoreCertificateValid:false,canonicalLockReleased:true,modelCalls:0}));
}
if(import.meta.main){const mode=process.argv[2];if(mode==='prepare')await prepare();else if(mode==='audit')console.log(JSON.stringify(auditChemiqFailedFinancialRecovery()));else if(mode==='release')await release();else throw Error('Use prepare, audit or release; only release mutates this exact owned canonical lock');}
