/** Append-only observations for one completed V3 runtime-abort. No score certificate, model or grade request. */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { actualPin, demand, gzipProof, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v3.ts';
import { CHEMIQ_F_ROOT as ROOT, loadChemiqFPlan, assertChemiqRecordSet, validateChemiqRecipe } from './chemiq-f-journal-contract-v3.ts';
import { loadChemiqProvenance } from './chemiq-nextwave-contract.ts';
import { assertChemiqPrivateBridgeObservation } from './chemiq-private-boundary-v3.ts';
import { chemiqActorCommand, assertChemiqOwnedFrame } from './chemiq-f-owned-v3.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { assertChemiqJournalExport } from './audit-chemiq-f-journal-v3.ts';

const RUN='repair-2026-10-09T12-21-50-354Z';
const OUTPUT=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-campaigns-v3',RUN);
const STORE=join(ROOT,'.phase1-data/chemiq-f-journal-v3',RUN);
const HOME=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v3/independent-v3-closed-runtime-recovery-v1',RUN);
const PS='C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
const utc=()=>new Date().toISOString();
function inventory(root:string):Pin[]{return readdirSync(root,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name)).flatMap(d=>d.isDirectory()?inventory(join(root,d.name)):d.isFile()?[actualPin(join(root,d.name))]:(()=>{throw Error('Recovery refuses nonordinary member');})());}
async function actors(pids:number[],ports:number[],admissionPin:Pin,registrationPins:Pin[]){
  const command=chemiqActorCommand(pids,ports),sourcePin=actualPin(import.meta.path),executablePin=actualPin(PS),startedAtUtc=utc();
  const requestPin=durableChemiqJson(join(HOME,'owned-recovery-request.json'),{protocol:'chemiq-v3-recovery-native-owned-request-v1',runId:RUN,command,pids,ports,admissionPin,registrationPins,sourcePin,executablePin,startedAtUtc,timeoutMs:10000});
  const env={...process.env};for(const key of Object.keys(env))if(key.toLowerCase()==='psmodulepath')delete env[key];env.PSModulePath='C:/Windows/System32/WindowsPowerShell/v1.0/Modules';
  const result=await new Promise<any>((yes,no)=>{const child=spawn(PS,['-NoProfile','-NonInteractive','-Command',command],{windowsHide:true,env,stdio:['ignore','pipe','pipe']});let stdout='',stderr='',timedOut=false;const timer=setTimeout(()=>{timedOut=true;child.kill('SIGKILL');},10000);child.stdout.on('data',b=>{stdout+=b.toString('utf8');if(Buffer.byteLength(stdout)>262144){timedOut=true;child.kill('SIGKILL');}});child.stderr.on('data',b=>{stderr+=b.toString('utf8');if(Buffer.byteLength(stderr)>65536){timedOut=true;child.kill('SIGKILL');}});child.once('error',e=>{clearTimeout(timer);no(e);});child.once('close',status=>{clearTimeout(timer);yes({status,stdout,stderr,timedOut,completedAtUtc:utc()});});});
  const transcriptPin=durableChemiqJson(join(HOME,'owned-recovery-transcript.json'),result);demand(result.status===0&&!result.timedOut&&!result.stderr.trim(),'chemiq_recovery_actual_owned_probe');
  const parsed=JSON.parse(result.stdout.trim());assertChemiqOwnedFrame(parsed,pids,ports);verifyPin(sourcePin);verifyPin(executablePin);
  return durableChemiqJson(join(HOME,'owned-recovery-observation.json'),{protocol:'chemiq-v3-recovery-owned-observation-v1',runId:RUN,requestPin,transcriptPin,parsed,closed:true,modelCalls:0,gradeCalls:0});
}
async function observe(inspectPath:string,bridgePath:string,resourcesPath:string){
  demand(!existsSync(HOME),'chemiq_recovery_append_only_home');mkdirSync(HOME,{recursive:true});
  const sourcePin=actualPin(import.meta.path),manifestPin=actualPin(join(OUTPUT,'manifest.json')),manifest=jsonPin(manifestPin),recipe=jsonPin(manifest.recipePin),plan=validateChemiqRecipe(recipe);
  demand(plan.runId===RUN&&plan.scope==='pilot16'&&plan.tasks.length===16&&resolve(recipe.store)===STORE,'chemiq_recovery_scope');
  const before=[...inventory(OUTPUT),...inventory(STORE)],inventoryBeforePin=durableChemiqJson(join(HOME,'original-inventory-before.json'),{protocol:'chemiq-v3-recovery-original-inventory-v1',runId:RUN,observedAtUtc:utc(),pins:before});
  const originalCertificatePin=actualPin(join(OUTPUT,'close-certificate.json')),certificate=jsonPin(originalCertificatePin),summary=jsonPin(certificate.summary),audit=jsonPin(certificate.auditor),registryPin=actualPin(join(OUTPUT,'chemiq-paid-resource-run.json')),registry=jsonPin(registryPin);
  demand(certificate.kind==='runtime-abort'&&certificate.scoreCertificateValid===false&&certificate.financialClosed===true&&summary.fatal==='private_shutdown_audit_failed'&&summary.runtimeAbortReason===summary.fatal&&summary.operationalComplete===false&&summary.recordedTaskRuns===16&&summary.financialStopReason===null,'chemiq_recovery_sole_runtime_abort');
  demand(audit.integrityValid===true&&audit.financialClosed===true&&audit.actualModelForwarded===46&&audit.actualDifferentTasksForwarded===16&&audit.recordedTaskRuns===16&&audit.scoreCertificateValid===false,'chemiq_recovery_original_complete_common_audit');
  for(const p of audit.inputArtifacts)verifyPin(p,undefined,512*1024**2);
  const admissionPin=actualPin(join(OUTPUT,'chemiq-admission.json')),admission=jsonPin(admissionPin),owned=jsonPin(certificate.owned),releasePin=registry.releaseCommittedPin,release=jsonPin(releasePin),authorization=jsonPin(release.authorizationPin);
  demand(registry.released===true&&same(registry.certificationPin,originalCertificatePin)&&release.released===true&&release.ownerNonce===admission.owned.ownerNonce&&release.runId===RUN&&authorization.ownerNonce===admission.owned.ownerNonce&&same(authorization.certificationPin,originalCertificatePin)&&authorization.scoreCertificateValid===false,'chemiq_recovery_nonce_financial_release');
  const pids=[...owned.registrationPins.map((p:Pin)=>jsonPin(p).pid),admission.owned.pid],ports=[...new Set([...owned.registrationPins.map((p:Pin)=>Number(new URL(jsonPin(p).base).port)),owned.proxyPort,owned.gradePort])];
  demand(pids.length===17&&new Set(pids).size===17&&ports.length===18,'chemiq_recovery_exact_actor_inventory');
  const ownedObservationPin=await actors(pids,ports,admissionPin,owned.registrationPins);
  for(const p of [...recipe.sourcePins,...Object.values(recipe.hostExecutors) as Pin[]])verifyPin(p);
  const records=plan.tasks.map(t=>jsonPin(actualPin(join(OUTPUT,'task-'+t.index+'.json'))));assertChemiqRecordSet(plan,records);
  const ledger=jsonPin(actualPin(join(OUTPUT,'api-ledger.json'))),journal=inspectCampaignJournal(STORE),cash=verifyCashClosure(certificate.cash);
  assertChemiqJournalExport(ledger,journal,RUN,new Set(plan.tasks.map(t=>t.route)));
  demand(journal.valid&&journal.accountingClosed&&ledger.calls.length===46&&ledger.calls.every((c:any)=>c.providerAttempted===true&&c.httpStatus===200)&&new Set(ledger.calls.map((c:any)=>c.route)).size===16&&cash.proof.snapshot.pendingCount===0&&cash.proof.snapshot.newUnknownCount===0&&cash.proof.snapshot.poisoned===false&&cash.config.carryNanoCny==='8392180000','chemiq_recovery_raw_financial_complete');
  const grading=jsonPin(certificate.grading),receipts=grading.physicalGradeReceiptPins.map((p:Pin)=>{const r=jsonPin(p),request=JSON.parse(gzipProof(r.requestPin,r.requestRawSha256,undefined,4*1024**2).toString('utf8')),response=JSON.parse(gzipProof(r.responsePin,r.responseRawSha256,undefined,4*1024**2).toString('utf8'));demand(r.runId===RUN&&r.fixtureOnly===false&&r.modelCalls===0&&r.valid&&r.httpStatus===200&&r.bodyComplete&&!r.fault&&response.value===r.value,'chemiq_recovery_actual_grade_receipt');return {...r,request};});
  demand(grading.generationClosedBeforeAllFinalGrading===true&&receipts.length===106&&receipts.filter((r:any)=>r.phase==='independent-final').length===32,'chemiq_recovery_grade_complete');
  for(const row of records){
    demand(hash(row.answer)===row.candidateSha256&&row.generationValid&&row.acceptance.valid&&row.acceptance.passed&&row.declaredDeadlineAt===row.actualCreatedAt+900000,'chemiq_recovery_candidate_record');
    const final=receipts.filter((r:any)=>r.phase==='independent-final'&&r.taskIndex===row.index);demand(final.length===2&&final.every((r:any)=>r.valid&&r.value===true&&r.request.input.result.body===row.answer&&r.request.input.task.id===row.taskId&&Date.parse(r.startedAtUtc)>=Date.parse(summary.generationClosedAtUtc))&&same(final.map((r:any)=>r.node).sort(),['correct','parsed']),'chemiq_recovery_exact_final_pair');
  }
  const secretAuditPin=summary.secretAuditPin,secret=jsonPin(secretAuditPin);demand(secret.passed&&secret.valuesChecked===2&&secret.findings.length===0&&secret.rawGzipExpanded&&secret.headersArchived===false,'chemiq_recovery_original_secret_audit');
  process.env.PATH='D:/Program/resources/bin;'+process.env.PATH;
  const provenance=loadChemiqProvenance(ROOT,join(HOME,'private-runtime'));const runtime=provenance.audit('post-close-recovery');provenance.validate();
  const runtimeAuditPin=actualPin(join(HOME,'private-runtime/grader-provenance/chemiq/post-close-recovery-runtime-audit.json'));
  demand(runtime.valid===true&&runtime.stage==='post-close-recovery','chemiq_recovery_original_full_runtime_predicate');
  const inspectPin=actualPin(resolve(inspectPath)),bridgePin=actualPin(resolve(bridgePath)),resourcePin=actualPin(resolve(resourcesPath));const inspect=assertChemiqPrivateBridgeObservation(jsonPin(inspectPin),ROOT),bridge=jsonPin(bridgePin),resource=jsonPin(resourcePin);
  const baseline=jsonPin(jsonPin(recipe.runtimeGate).privateGrader.inspectPin);
  demand(inspect.inspect.State.StartedAt===baseline.inspect.State.StartedAt&&inspect.inspect.State.Pid===baseline.inspect.State.Pid&&inspect.inspect.State.Restarting===false,'chemiq_recovery_same_running_instance');
  demand(bridge.validated===true&&bridge.actualPid===42580&&resource.modelCalls===0&&resource.summary.cDiskFloorPassed===true&&resource.disks.F.free>=1024**3&&resource.memory.availablePhysical>=1024**3,'chemiq_recovery_fresh_bridge_resources');
  for(const frame of [inspect,bridge,resource])demand(Date.now()-Date.parse(frame.observedAtUtc)>=0&&Date.now()-Date.parse(frame.observedAtUtc)<=120000,'chemiq_recovery_fresh_native_observation');
  for(const p of [bridge.processSourcePin,bridge.javaPin,bridge.jarPin,bridge.pythonPin])verifyPin(p);
  const after=[...inventory(OUTPUT),...inventory(STORE)];demand(same(before,after),'chemiq_recovery_original_files_changed');verifyPin(sourcePin);
  const pin=durableChemiqJson(join(HOME,'recovery-observation.json'),{protocol:'chemiq-v3-completed-pilot-recovery-observation-v1',runId:RUN,sourcePin,manifestPin,recipePin:manifest.recipePin,originalCertificatePin,originalRegistryPin:registryPin,originalInventoryBeforePin:inventoryBeforePin,originalAllFilesUnchanged:true,originalScoreCertificateValid:false,originalRuntimeAbortRetained:true,ownedObservationPin,runtimeAuditPin,inspectPin,bridgePin,resourcePin,secretAuditPin,sourcePinsVerified:recipe.sourcePins.length,modelCallsByRecovery:0,gradeCallsByRecovery:0,paidLockTaken:false,containerMutated:false,recordedTaskRuns:16,actualModelCalls:46,physicalGradeReceipts:106,independentFinalReceipts:32,recordedPassedTasks:16,newKnownEstimatedNanoCny:cash.proof.snapshot.newKnownEstimatedNanoCny,newPendingCount:0,newUnknownCount:0,oldUnknownCarryNanoCny:'8392180000',taskDatabaseReplay:'Must be independently replayed on copies by both review reports before a separate recovery certificate is issued',recoveredPilotValidated:false,full816ScoreCertified:false,failedRoundPooled:false,rootCauseOfOriginalSystemError:'unknown; no traceback/code/stage was preserved by the original name-only catch',observedAtUtc:utc()});
  return {observationPin:pin,fullRuntimeObserved:true,originalAllFilesUnchanged:true,modelCalls:0,gradeCalls:0,recoveredPilotValidated:false};
}
if(import.meta.main){const [inspect,bridge,resources]=process.argv.slice(2);demand(inspect&&bridge&&resources,'chemiq_recovery_explicit_native_inputs');console.log(JSON.stringify(await observe(inspect,bridge,resources)));}
