/** Stable Terminal-Bench lifecycle. Task semantics stay in pinned, qualified campaign modules. */
import { readFileSync,existsSync,mkdirSync,readdirSync } from 'node:fs';
import { resolve,join,relative,isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Database } from 'bun:sqlite';
import type { TaskManifest,AttemptContext,Pin } from './types.ts';
import { loadManifest } from './manifest.ts';
import { checkPin,readPinned,filePin,wxJson,assertContext,processIdentity } from './runtime.ts';
import { loadPreparedContext } from './bindings.ts';
import { assertAdmission } from './admission.ts';
import { verifyBenchmarkCashClosure,createBenchmarkCash } from '../repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts';
import { inspectCampaignJournal,createCampaignJournal } from '../repair-2026-10-10/full-f/shared/digitalocean-journal.ts';

export interface ImportBinding {pin:Pin;export:string}
export interface TerminalDriverConfig {
  protocol:'bench-terminal-driver-v1';
  imports:Record<'campaign'|'formalRunId'|'formalExecuteOptions'|'activated'|'resource'|'ownedGuard'|'hostGuard'|'acquireAdmission'|'freshHistory'|'historyContract'|'provider'|'inspectClosedCash',ImportBinding>;
  activationPin:Pin;readinessPin:Pin;identityPin:Pin;closureReviewPin:Pin;aggregateBudgetPin:Pin;
  retainedAuditPin:Pin;assetProjectionPin:Pin;hostCapacityPolicy:unknown;
  resource:{memoryMb:number;growthBytes:number;slots:1};outputBinding:string;
  native:{standCloseRelative:string;ledgerRelative:string};
}
function demand(x:unknown,message:string):asserts x {if(!x)throw Error(message);}
function codePath(m:TaskManifest,path:string){const rel=relative(resolve(m.root),resolve(path));return !!rel&&!rel.startsWith('..')&&!isAbsolute(rel);}
export function validateTerminalDriverData(m:TaskManifest):TerminalDriverConfig {
  demand(m.bench==='terminal-bench','terminal_driver_bench');const d=m.adapterConfig.terminalDriver as unknown as TerminalDriverConfig;
  demand(d?.protocol==='bench-terminal-driver-v1','terminal_driver_protocol');
  for(const key of ['campaign','formalRunId','formalExecuteOptions','activated','resource','ownedGuard','hostGuard','acquireAdmission','freshHistory','historyContract','provider','inspectClosedCash']) {
    const binding=d.imports?.[key as keyof typeof d.imports];demand(binding&&/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(binding.export),'reviewed_import_export:'+key);checkPin(binding.pin);
    demand(codePath(m,binding.pin.path)&&m.provenance.sourcePins.some(p=>p.path===binding.pin.path&&p.sha256===binding.pin.sha256),'reviewed_import_source:'+key);
  }
  for(const pin of [d.activationPin,d.readinessPin,d.identityPin,d.closureReviewPin,d.aggregateBudgetPin,d.retainedAuditPin,d.assetProjectionPin])checkPin(pin);
  demand(d.resource?.slots===1&&Number.isSafeInteger(d.resource.memoryMb)&&d.resource.memoryMb>=m.original.memoryMb&&Number.isSafeInteger(d.resource.growthBytes)&&d.resource.growthBytes>0,'original_aggregate_resource_data');
  demand(/^[A-Z][A-Z0-9_]*$/.test(d.outputBinding),'output_binding_name');
  return d;
}
async function importsFor(d:TerminalDriverConfig){const result:any={};for(const [name,b]of Object.entries(d.imports)){checkPin(b.pin);const module=await import(pathToFileURL(b.pin.path).href);demand(b.export in module,'pinned_export_missing:'+name);result[name]=module[b.export];}return result;}
export async function inspectLegacyActorAbsence(d:TerminalDriverConfig,actorCids:string[]) {
  const activation=readPinned(d.activationPin),docker=activation.dockerHost?.replace(/^tcp:/,'http:');
  demand(typeof docker==='string'&&/^http:\/\/127\.0\.0\.1:\d+$/.test(docker),'reviewed_private_docker_endpoint');
  const evidence=[];
  for(const cid of actorCids) {const response=await fetch(docker+'/containers/'+cid+'/json',{signal:AbortSignal.timeout(5000)});demand(response.status===404,'legacy_actor_current_custody_not_closed');evidence.push({cid,status:404});}
  return evidence;
}

export function inspectLegacyHistory(m:TaskManifest,d:TerminalDriverConfig) {
  const identity=readPinned(d.identityPin),closure=readPinned(d.closureReviewPin),budget=readPinned(d.aggregateBudgetPin),retained=readPinned(d.retainedAuditPin);
  demand(identity.taskId===m.taskId&&identity.bench===m.bench&&closure.taskId===m.taskId&&budget.taskId===m.taskId,'legacy_task_identity');
  demand(identity.originalCoordinatorNonce===null&&identity.originalRootTaskLockPin===null,'honest_legacy_null_identity_required');
  demand(!retained.tasks?.some((x:any)=>(x.officialId??x.taskId)===m.taskId&&x.valid===true)&&!retained.validTaskIds?.includes(m.taskId),'valid_wrong_must_never_repeat');
  const retries=(m.adapterConfig.retryHistory??[]) as any[];
  demand(Array.isArray(retries)&&Array.isArray(identity.attempts)&&identity.attempts.length>0&&identity.attempts.length+retries.length===budget.cashClosePins?.length,'complete_legacy_attempts');
  let known=0,unknown=0,calls=0;const seen=new Set<string>(),actorCids:string[]=[];
  for(const attempt of identity.attempts) {
    const cash=verifyBenchmarkCashClosure(attempt.cashClosePin),journal=inspectCampaignJournal(cash.proof.journalDirectory);
    demand(!seen.has(cash.config.runId)&&cash.config.runId===attempt.runId,'unique_actual_legacy_cash_run');seen.add(cash.config.runId);
    demand(budget.cashClosePins.some((p:Pin)=>p.path===attempt.cashClosePin.path&&p.sha256===attempt.cashClosePin.sha256),'legacy_cash_not_omitted');
    demand(journal.valid&&journal.accountingClosed&&cash.proof.snapshot.pendingCount===0,'legacy_cash_pending');
    known+=cash.proof.snapshot.billedUsd;unknown+=cash.proof.snapshot.unknownReservationUsd;calls+=journal.snapshot!.acceptedRequestCount;
    const summary=readPinned(attempt.summaryPin);demand(summary.fatal,'original_failed_summary_required');
    for(const p of [attempt.processPin,...attempt.databasePins,...attempt.ownedLedgerPins])checkPin(p);
    for(const p of [attempt.standClosePin,attempt.engineClosePin]) {const close=readPinned(p);demand(close.exitObserved===true&&close.closeObserved===true,'legacy_original_process_not_closed');for(const stream of [close.stdout,close.stderr])checkPin(stream);}
    const ledgerPin=attempt.ownedLedgerPins.find((p:Pin)=>p.path.endsWith('.sqlite'));demand(ledgerPin,'legacy_ledger_required');
    const db=new Database(ledgerPin.path,{readonly:true});try {
      demand((db.query('select count(*) as n from actor where closed<>1').get() as any).n===0,'legacy_actor_open');
      for(const a of db.query('select cid from actor').all() as any[]) {demand(/^[a-f0-9]{64}$/.test(a.cid),'legacy_exact_actor_cid');actorCids.push(a.cid);}
      for(const row of db.query('select json from command').all() as any[]) {const c=JSON.parse(row.json);demand(c.closeObserved===true&&Number.isInteger(c.exitCode)&&!c.captureFaults?.length,'legacy_native_command_unclosed');}
    } finally {db.close();}
    // Original DB claimed state is not candidate content; explicit custody review must say no final hand-in/grade to recover.
    const reviewed=closure.attempts?.find((x:any)=>x.runId===attempt.runId);demand(reviewed?.closed===true&&reviewed.noRecordedOriginalGrade===true&&reviewed.allCommandsCloseObserved===true,'legacy_closure_attempt_missing');
    demand(Array.isArray(summary.taskPins)&&summary.taskPins.length===0,'original_task_results_require_recovery');
    const mainDbPin=attempt.databasePins.find((p:Pin)=>p.path.endsWith('.sqlite'));demand(mainDbPin,'legacy_original_main_db_required');
    const mainDb=new Database(mainDbPin.path,{readonly:true});try {
      const rows=mainDb.query("select id,result from task where source='user'").all() as any[];
      demand(rows.length>0&&rows.every(x=>x.result===null),'original_candidate_result_must_recover');
    } finally {mainDb.close();}
  }
  for(const retry of retries) {
    const proof=readPinned(retry.proofPin);
    demand(proof.protocol==='bench-data-retry-derivation-v1'&&proof.predecessorAttemptId===retry.attemptId&&proof.predecessorRunId===retry.runId,'retry_history_identity');
    const evidence=readPinned(proof.evidencePin),native=readPinned(proof.nativeClosurePin);checkPin(proof.faultReceiptPin);
    demand(evidence.protocol==='bench-retryable-closure-v1'&&evidence.taskId===m.taskId&&evidence.bench===m.bench&&evidence.attemptId===retry.attemptId&&evidence.runId===retry.runId,'retry_original_evidence_identity');
    demand(evidence.cashClosePin.sha256===proof.cashClosePin.sha256&&evidence.nativeClosurePin.sha256===proof.nativeClosurePin.sha256&&evidence.faultReceiptPin.sha256===proof.faultReceiptPin.sha256,'retry_original_evidence_join');
    demand(native.taskId===m.taskId&&native.runId===retry.runId&&native.resourceReleased===true&&native.brokerLaneClosed===true&&(native.allNativeCommandStreamsClosed===true||native.allNativeCommandsClosed===true),'retry_actual_custody_not_closed');
    checkPin(native.ownedLedgerPin);for(const p of native.ownedLedgerPins??[])checkPin(p);
    const db=new Database(native.ownedLedgerPin.path,{readonly:true});try {
      for(const a of db.query('select cid,closed from actor').all() as any[]){demand(a.closed===1,'retry_actor_open');actorCids.push(a.cid);}
      for(const row of db.query('select json from command').all() as any[]){const command=JSON.parse(row.json);demand(command.closeObserved===true&&Number.isInteger(command.exitCode)&&!command.captureFaults?.length,'retry_command_unclosed');}
    }finally{db.close();}
    const cash=verifyBenchmarkCashClosure(proof.cashClosePin),journal=inspectCampaignJournal(cash.proof.journalDirectory);
    demand(!seen.has(cash.config.runId)&&cash.config.runId===retry.runId&&budget.cashClosePins.some((p:Pin)=>p.path===proof.cashClosePin.path&&p.sha256===proof.cashClosePin.sha256),'retry_cash_chain_identity');seen.add(cash.config.runId);
    demand(journal.valid&&journal.accountingClosed&&cash.proof.snapshot.pendingCount===0&&cash.config.capUsd<=m.original.taskCapUsd,'retry_cash_not_closed');
    known+=cash.proof.snapshot.billedUsd;unknown+=cash.proof.snapshot.unknownReservationUsd;calls+=journal.snapshot!.acceptedRequestCount;
  }
  demand(typeof closure.originalResultRecoveryFinding==='string'&&closure.originalResultRecoveryFinding.length>0,'explicit_no_original_result_recovery_finding');
  demand(Math.abs(known-m.original.priorKnownUsd)<1e-9&&Math.abs(unknown-m.original.priorUnknownUsd)<1e-9&&budget.originalTaskCapUsd===m.original.taskCapUsd&&Math.abs(budget.knownUsd-known)<1e-9&&Math.abs(budget.unknownReservationUsd-unknown)<1e-9,'all_original_cost_unknown_preserved');
  return {knownUsd:known,unknownUsd:unknown,calls,remainingUsd:m.original.taskCapUsd-known-unknown,legacyIdentityPreserved:true,actorCids:[...new Set(actorCids)]};
}
function nativeClosed(output:string,d:TerminalDriverConfig) {
  const close=join(output,d.native.standCloseRelative),ledger=join(output,d.native.ledgerRelative);
  if(!existsSync(close)&&!existsSync(ledger))return !existsSync(join(output,'stand-process'));
  if(!existsSync(close)||!existsSync(ledger))return false;
  const c=JSON.parse(readFileSync(close,'utf8'));if(c.exitObserved!==true||c.closeObserved!==true)return false;
  const db=new Database(ledger,{readonly:true});try{return (db.query('select count(*) as n from actor where closed<>1').get() as any).n===0&&(db.query('select json from command').all() as any[]).every(row=>{const c=JSON.parse(row.json);return c.closeObserved===true&&Number.isInteger(c.exitCode)&&!c.captureFaults?.length;});}finally{db.close();}
}
export async function preflightTerminalDriver(m:TaskManifest,initial:AttemptContext) {
  assertContext(m,initial);const c=loadPreparedContext(m,initial),d=validateTerminalDriverData(m),entry=JSON.parse(readFileSync(c.bindings!.RECOVERY_ENTRY,'utf8'));
  demand(entry.rootReview?.legacyNullIdentityApproved===true&&entry.rootReview?.closureReviewPin?.sha256===d.closureReviewPin.sha256&&entry.rootReview?.aggregateBudgetPin?.sha256===d.aggregateBudgetPin.sha256,'root_reviewed_legacy_data_required');
  const history=inspectLegacyHistory(m,d);demand(history.remainingUsd>0,'original_task_budget_exhausted');
  const api=await importsFor(d),ready=readPinned(d.readinessPin);
  demand(ready.nativeReady===true&&ready.publishAllowed===true&&ready.readyTaskIds?.length===1&&ready.readyTaskIds[0]===m.taskId&&ready.actualPrivateImportsValidated===true&&ready.allOwnedBuildersClosed===true,'original_qualification_required');
  const original=readPinned(ready.contextManifest),task=original.tasks?.find((x:any)=>x.taskId===m.taskId);
  demand(task?.agentSeconds===m.original.solveSeconds&&task?.verifierSeconds===m.original.gradeSeconds&&
    ready.officialEnvironment?.cpus===m.original.cpu&&ready.officialEnvironment?.memory_mb===m.original.memoryMb&&
    ready.officialEnvironment?.storage_mb*1024**2===d.resource.growthBytes,'original_task_time_cpu_memory_growth_contract');
  demand(api.provider.model===m.original.model&&api.provider.providerSlug===m.original.provider&&m.original.reasoning==='high'&&m.original.providerSeconds===600,'original_model_provider_reasoning_timeout');
  const {activation,connection}=await api.activated(d.activationPin.path),output=resolve(c.bindings![d.outputBinding]);
  await inspectLegacyActorAbsence(d,history.actorCids);
  demand(!existsSync(output),'fresh_output_already_exists');
  const projection=readPinned(d.assetProjectionPin);
  for(const asset of m.provenance.sourcePins.filter(p=>!codePath(m,p.path))) {checkPin(asset);demand(projection.assets?.some((p:Pin)=>p.path===asset.path&&p.sha256===asset.sha256&&p.bytes===asset.bytes),'external_asset_projection_missing');}
  demand(codePath(m,d.assetProjectionPin.path),'asset_carrier_must_be_in_code_root');
  const sourcePins=[...m.provenance.sourcePins.filter(p=>codePath(m,p.path)),d.assetProjectionPin,...m.provenance.contractPins.filter(p=>codePath(m,p.path)),filePin(c.manifestPath)];
  demand(codePath(m,c.manifestPath),'manifest_carrier_must_be_in_code_root');
  const freshParent=await api.freshHistory(api.historyContract());
  return {m,c,d,entry,history,api,ready,activation,connection,output,sourcePins,freshParent};
}
export async function runTerminalDriver(m:TaskManifest,initial:AttemptContext) {
  const {c,d,history,api,activation,connection,output,sourcePins}=await preflightTerminalDriver(m,initial);
  assertAdmission(c.admissionControlPath,m.bench+':'+m.taskId,c.stage,true);
  const locks=readPinned(filePin(join(c.runDir,'locks-receipt.json')));checkPin(locks.canonicalPin);checkPin(locks.attemptLockPin);
  const lock=readPinned(locks.attemptLockPin);
  demand(lock.attemptId===c.attemptId&&lock.taskId===m.taskId&&lock.bench===m.bench&&lock.manifestPin.sha256===c.manifestPin.sha256&&lock.signedEntryPin.sha256===filePin(c.bindings!.ENTRY_ENVELOPE).sha256,'actual_permanent_attempt_lock_join');
  const lease=await api.resource(connection,{planPin:d.readinessPin,originalPeakMemoryMb:d.resource.memoryMb,originalPlannedGrowthBytes:d.resource.growthBytes});let lane:any,runId:string|undefined,campaignEntered=false,financialClosed=false;
  try {
    mkdirSync(output,{recursive:false});runId=api.formalRunId(connection.runId);
    process.env.DOCKER_HOST=activation.dockerHost;process.env.NOVAEVE_ACTIVATION_PATH=d.activationPin.path;process.env.NOVAEVE_BROKER_CONTROL_PATH=activation.brokerControlPath;process.env.NOVAEVE_LEASE_PID=String(process.pid);
    const host=api.hostGuard(d.hostCapacityPolicy,output),owned=api.ownedGuard(connection,lease),guard=()=>{host();owned();};guard();
    await api.freshHistory(api.historyContract());
    lane=await api.acquireAdmission({ownedResource:{pid:process.pid,token:lease.token},root:m.root,output,runId,slug:m.bench,sourcePins,connection});
    const fresh=await api.freshHistory(api.historyContract(),lane.proofPin),maximum=Math.min(history.remainingUsd,lane.capUsd,fresh.maximumAdditionalSpendUsd);
    demand(maximum>0,'actual_parent_and_original_task_budget_exhausted');
    const processPath=join(output,'process.json');wxJson(processPath,{pid:process.pid,incarnation:processIdentity(process.pid).incarnation,runId,taskId:m.taskId,bench:m.bench,output});await lane.registerOwnedProcess(filePin(processPath));
    wxJson(join(output,'universal-original-budget-binding.json'),{protocol:'bench-real-lane-original-budget-v1',manifestPin:c.manifestPin,aggregateBudgetPin:d.aggregateBudgetPin,actualLanePin:lane.proofPin,originalTaskCapUsd:m.original.taskCapUsd,...history,maximumNewSpendUsd:maximum,oldRootIdentityWasNull:true});
    const freshMaximumNewSpendUsd=async()=>{guard();const h=await api.freshHistory(api.historyContract(),lane.proofPin);return Math.min(history.remainingUsd,lane.capUsd,h.maximumAdditionalSpendUsd);};
    campaignEntered=true;
    const result=await api.campaign(api.formalExecuteOptions({task:m.taskId,runId,output,sourcePins,prices:lane.prices,provider:api.provider,admission:lane,
      transport:async(raw:string)=>{guard();return lane.transport(raw);},freshMaximumNewSpendUsd,recoveryParentMaximumNewSpendUsd:maximum,
      recoveryBudgetProofPin:d.aggregateBudgetPin,hostCapacityGuard:guard,recoveryAgentSeconds:m.original.solveSeconds,readinessPath:d.readinessPin.path}));
    demand(result.financialClose?.cashClose,'original_cash_close_missing');const closed=api.inspectClosedCash(m.root,result.financialClose.cashClose,activation.brokerControlPath);
    demand(closed.accountingClosed,'original_cash_journal_not_closed');await lane.finishLightweight({cashPin:result.financialClose.cashClose,summaryPin:result.summary});financialClosed=true;
  } catch(error) {
    const fault={message:String(error),campaignEntered,runId:runId??null,laneCreated:!!lane,atUtc:new Date().toISOString()};
    wxJson(join(c.runDir,'driver-failure.json'),fault);
    if(lane&&runId)try {
      const existingCash=join(output,'cash/cash-close.json'),existingSummary=join(output,'summary.json');
      if(existsSync(existingCash)&&existsSync(existingSummary)&&nativeClosed(output,d)) {
        const cashPin=filePin(existingCash),verified=verifyBenchmarkCashClosure(cashPin),journal=inspectCampaignJournal(verified.proof.journalDirectory);
        demand(verified.config.runId===runId&&journal.valid&&journal.accountingClosed&&verified.proof.snapshot.pendingCount===0,'original_failure_cash_not_closed');
        await lane.finishLightweight({cashPin,summaryPin:filePin(existingSummary)});financialClosed=true;
      } else if(!campaignEntered&&!existsSync(join(output,'provider'))&&!existsSync(join(output,'cash'))&&!existsSync(join(output,'stand-process'))) {
        // No native/campaign call occurred. Confirm the actual lane has not dispatched before producing real zero cash.
        const healthResponse=await fetch(connection.endpoint+'/health',{signal:AbortSignal.timeout(5000)}),health:any=await healthResponse.json();
        const actual=health.lanes?.find((x:any)=>x.runId===runId);
        demand(healthResponse.ok&&health.healthy===true&&actual&&!actual.closed&&actual.dispatched===0&&actual.active===0,'pre_native_lane_not_proven_zero');
        const directory=join(output,'provider'),journal=createCampaignJournal({directory,campaign:runId,capUsd:lane.capUsd,priorCampaignCostUpperBoundUsd:0,provider:api.provider});
        const cash=createBenchmarkCash({directory:join(output,'cash'),runId,providerKind:'real-provider',admission:lane,prices:lane.prices,
          journal:{directory,configPin:filePin(join(directory,'journal-config.json')),sourcePin:filePin(resolve(import.meta.dir,'../repair-2026-10-10/full-f/shared/digitalocean-journal.ts'))},unknownCostPolicy:'record_and_continue'},api.provider);
        journal.exportLegacyLedger();const cashClose=cash.close();journal.close();const inspection=inspectCampaignJournal(directory);
        demand(inspection.valid&&inspection.accountingClosed&&inspection.snapshot?.acceptedRequestCount===0,'actual_zero_journal_not_closed');
        wxJson(existingSummary,{protocol:'bench-pre-native-denial-original-zero-cash-v1',runId,executingTaskIds:[m.taskId],taskPins:[],formalScoreCertified:false,modelCalls:0,fatal:'pre_native_denial',fault,financialClose:{cashClose},actorEverCreated:false});
        await lane.finishLightweight({cashPin:cashClose,summaryPin:filePin(existingSummary)});financialClosed=true;
      }
    } catch(closureError) {wxJson(join(c.runDir,'failure-custody-unresolved.json'),{originalFault:fault,closureError:String(closureError),financialClosed:false,resourceReleaseForbidden:true});}
    throw error;
  } finally {
    if(nativeClosed(output,d)&&(!lane||financialClosed)) {await lease.release();wxJson(join(c.runDir,'driver-resource-release.json'),{pid:process.pid,incarnation:processIdentity(process.pid).incarnation,resourceReleased:true,originalPool:true,financialClosed:lane?financialClosed:null});}
    else wxJson(join(c.runDir,'native-custody-held.json'),{pid:process.pid,resourceReleaseForbidden:true,reason:'original_native_closure_unproven'});
  }
}
if(import.meta.main) {
  if(!['--run','--preflight'].includes(process.argv[2])||!process.argv[3]||!process.argv[4])throw Error('explicit_root_authorized_run_or_preflight_manifest_context_required');
  const m=loadManifest(process.argv[3]),c=JSON.parse(readFileSync(process.argv[4],'utf8'));
  if(process.argv[2]==='--preflight') {
    const p=await preflightTerminalDriver(m,c);
    console.log(JSON.stringify({verified:true,taskId:m.taskId,bench:m.bench,originalCalls:p.history.calls,priorKnownUsd:p.history.knownUsd,priorUnknownUsd:p.history.unknownUsd,remainingTaskCapUsd:p.history.remainingUsd,oldActorsCurrently404:p.history.actorCids.length,resourceAcquisitions:0,laneClaims:0,modelCalls:0,newGrades:0,newOracles:0}));
  } else await runTerminalDriver(m,c);
}
