import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { Database } from 'bun:sqlite';
import type { Bench, BenchAdapter, TaskManifest, StageSpec, AttemptContext, StageResult, Pin } from '../types.ts';
import { assertContext, checkPin, readPinned, filePin, expand, executeCommand, inspectActualSolver, wxJson } from '../runtime.ts';
import { loadPreparedContext } from '../bindings.ts';
import { validateTerminalDriverData,inspectLegacyHistory,inspectLegacyActorAbsence } from '../terminal-driver.ts';
import { verifyBenchmarkCashClosure } from '../../repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts';
import { inspectCampaignJournal } from '../../repair-2026-10-10/full-f/shared/digitalocean-journal.ts';
import { terminalBenchAdapter } from './terminal-bench.ts';
import { skillsbenchAdapter } from './skillsbench.ts';

function requireTrue(value: unknown, message: string): asserts value { if (!value) throw Error(message); }
export function validateFor(bench: Bench, m: TaskManifest): void {
  requireTrue(m.bench === bench && m.schemaVersion === 1 && m.taskId.length > 0, 'adapter_identity');
  const o = m.original;
  for (const n of [o.cpu,o.memoryMb,o.solveSeconds,o.gradeSeconds,o.toolSeconds,o.providerSeconds,o.taskCapUsd]) requireTrue(Number.isFinite(n) && n > 0, 'original_positive_contract');
  requireTrue(o.providerSeconds === 600 && o.priorKnownUsd >= 0 && o.priorUnknownUsd >= 0 && o.priorKnownUsd + o.priorUnknownUsd <= o.taskCapUsd, 'original_cost_provider_contract');
  requireTrue(m.provenance.sourcePins.length && m.provenance.contractPins.length, 'source_and_contract_required');
  for (const [stage,spec] of Object.entries(m.stages)) {
    if (!spec) continue;
    requireTrue(spec.kind === 'reuse' || spec.kind === 'command', 'stage_kind');
    requireTrue(spec.timeoutSeconds > 0, 'stage_deadline');
    if (stage === 'solve') requireTrue(spec.timeoutSeconds <= o.solveSeconds, 'solve_timeout_expansion');
    if (stage === 'grade') requireTrue(spec.timeoutSeconds <= o.gradeSeconds, 'grade_timeout_expansion');
    if(spec.bundledStages?.length) {
      requireTrue(new Set(spec.bundledStages).size===spec.bundledStages.length&&spec.bundledStages.includes(stage as any),'bundled_stage_identity');
      requireTrue(Number.isFinite(spec.outerTimeoutSeconds)&&spec.outerTimeoutSeconds!>=spec.timeoutSeconds,'explicit_bundled_custody_deadline');
    } else requireTrue(spec.outerTimeoutSeconds===undefined,'outer_deadline_requires_bundle');
    if(spec.effect==='oracle'&&spec.kind==='command') {
      requireTrue(m.history.stateKnown&&!!spec.originalSuccessKey,'oracle_requires_known_checkpoint_identity');
      const checkpoints=m.adapterConfig.successfulCheckpoints as Record<string,unknown>|undefined;
      requireTrue(!checkpoints?.[spec.originalSuccessKey!],'successful_reference_is_reuse_only');
    }
    if (spec.kind === 'reuse') requireTrue(spec.evidencePins.length > 0 && !!spec.successEvidence, 'reuse_requires_pinned_success_predicates');
    if (spec.kind === 'command' && spec.effect !== 'read-only') requireTrue(spec.resourceMode === 'driver-owned', 'original_driver_owned_resource_required');
  }
}
const unknown = (reason: string, proofPins: Pin[] = []): StageResult => ({status:'unknown',proofPins,nativeClosed:false,financialClosed:false,candidateOrSubmissionPresent:false,reason});
function at(value: any, path: string): any { return path.split('.').reduce((x,k) => x?.[k], value); }
function predicates(value: any, equals: Record<string, unknown>): boolean {
  return Object.entries(equals).every(([key,v]) => JSON.stringify(at(value,key)) === JSON.stringify(v));
}
function nativeClosed(pin: Pin, taskId?:string, runId?:string): boolean {
  const p = readPinned(pin);
  requireTrue((!p.taskId||!taskId||p.taskId===taskId)&&(!p.runId||!runId||p.runId===runId),'native_closure_task_run_identity');
  // Native closure is explicit evidence, never inferred from exit code or numeric PID absence.
  const closed = p.allExactOwnedActorsAbsent === true || p.allActorsClosed === true ||
    (p.resourceReleased === true && p.brokerLaneClosed === true && Array.isArray(p.exactOwnedContainerApi404) && p.exactOwnedContainerApi404.length > 0 && p.exactOwnedContainerApi404.every((x:any)=>x.status===404));
  const rootRetained=p.rootReviewed===true&&Number.isSafeInteger(p.nativeActorsClosed)&&p.nativeActorsClosed>=0&&p.workerAbsent===true&&p.originalEngineExitCloseObserved===true&&p.laneClosed===true&&p.resourceReleased===true&&p.rootDerivedCleanupPin&&p.originalGradeAuditPin;
  if(rootRetained){
    const cleanup=readPinned(p.rootDerivedCleanupPin),audit=readPinned(p.originalGradeAuditPin);
    requireTrue(cleanup.taskId===p.taskId&&cleanup.runId===p.runId&&cleanup.laneClosed===true&&cleanup.resourceReleased===true&&cleanup.exactProcessHandleTerminated===true,'root_exact_custody_cleanup');
    requireTrue(audit.taskId===p.taskId&&audit.runId===p.runId&&audit.nativeActorsClosed===true&&audit.nativeCommandsAllCloseObserved===true&&audit.currentActorApi404?.length===p.nativeActorsClosed&&audit.currentActorApi404.every((x:any)=>x.status===404),'root_original_actor_command_audit');
    checkPin(cleanup.originalEngineClosePin);
  }
  requireTrue(rootRetained||(closed && (p.allNativeCommandsClosed === true || p.allNativeCommandStreamsClosed === true || p.nativeClosed === true)), 'native_closure_not_proven');
  return true;
}
function linkedPins(value:any,seen=new Set<string>(),depth=0):void {
  requireTrue(depth<=12&&seen.size<=2048,'bounded_grade_receipt_links');
  if(!value||typeof value!=='object')return;
  if(typeof value.path==='string'&&Number.isSafeInteger(value.bytes)&&typeof value.sha256==='string') {
    const key=value.path+'|'+value.sha256;if(seen.has(key))return;seen.add(key);checkPin(value);
    if(value.path.endsWith('.json')&&value.bytes<=4*1024**2)linkedPins(readPinned(value),seen,depth+1);
    return;
  }
  for(const item of Object.values(value))linkedPins(item,seen,depth+1);
}
function financeClosed(pin: Pin, runId?:string, cap?:number): boolean {
  const cash = verifyBenchmarkCashClosure(pin), journal = inspectCampaignJournal(cash.proof.journalDirectory);
  requireTrue(journal.valid && journal.accountingClosed && cash.proof.snapshot.pendingCount === 0, 'original_cash_journal_not_closed');
  requireTrue((!runId||cash.config.runId===runId)&&(cap===undefined||cash.config.capUsd<=cap),'original_cash_run_cap_identity');
  return true;
}

async function mappedNative(m:TaskManifest,c:AttemptContext,mapping:any):Promise<Pin> {
  const names=['standClosePath','engineClosePath','ownedLedgerPath'];
  for(const name of names)requireTrue(typeof mapping?.[name]==='string','native_mapping_'+name);
  const stand=filePin(expand(mapping.standClosePath,c)),engine=filePin(expand(mapping.engineClosePath,c)),ledger=filePin(expand(mapping.ownedLedgerPath,c));
  for(const p of [stand,engine]) {
    const close=readPinned(p);requireTrue(close.exitObserved===true&&close.closeObserved===true&&Number.isSafeInteger(close.pid),'original_process_close_receipt');
    for(const stream of [close.stdout,close.stderr])checkPin(stream);
  }
  const db=new Database(ledger.path,{readonly:true});let actors:any[],commands:any[];
  try {actors=db.query('select cid,closed from actor').all();commands=db.query('select json from command').all();}
  finally {db.close();}
  requireTrue(actors.every(x=>x.closed===1),'original_owned_actor_open');
  for(const row of commands) {const command=JSON.parse(row.json);requireTrue(command.closeObserved===true&&Number.isInteger(command.exitCode)&&!command.captureFaults?.length,'original_native_command_unclosed');}
  requireTrue(typeof mapping.dockerEndpoint==='string'&&/^http:\/\/127\.0\.0\.1:\d+$/.test(mapping.dockerEndpoint),'reviewed_private_docker_endpoint');
  const absent=[];
  for(const actor of actors) {
    requireTrue(/^[a-f0-9]{64}$/.test(actor.cid),'original_exact_actor_cid');
    const response=await fetch(mapping.dockerEndpoint+'/containers/'+actor.cid+'/json',{signal:AbortSignal.timeout(5000)});
    requireTrue(response.status===404,'original_actor_custody_pending');absent.push({cid:actor.cid,status:404});
  }
  requireTrue(typeof mapping.brokerHealthUrl==='string'&&typeof mapping.resourceOwnerProcessPath==='string','native_resource_owner_mapping_required');
  const ownerPin=filePin(expand(mapping.resourceOwnerProcessPath,c)),owner=readPinned(ownerPin);
  requireTrue(Number.isSafeInteger(owner.pid)&&typeof owner.incarnation==='string','exact_original_resource_owner');
  const brokerResponse=await fetch(mapping.brokerHealthUrl,{signal:AbortSignal.timeout(3000)});
  requireTrue(brokerResponse.ok,'native_broker_health_unavailable');const broker:any=await brokerResponse.json();
  requireTrue(broker.healthy===true&&!broker.resourceSlots?.some((x:any)=>x.pid===owner.pid&&x.ownerIncarnation===owner.incarnation),'original_resource_still_held');
  const path=join(c.runDir,'derived-native-closure.json');
  const value={protocol:'bench-derived-original-native-closure-v1',artifactOrigin:'derived-from-original-receipts',
    taskId:m.taskId,standClosePin:stand,engineClosePin:engine,ownedLedgerPin:ledger,allActorsClosed:true,
    allNativeCommandsClosed:true,exactOwnedContainerApi404:absent,originalCommands:commands.length,resourceOwnerProcessPin:ownerPin,resourceReleased:true};
  if(!existsSync(path))wxJson(path,value);
  else requireTrue(JSON.stringify(JSON.parse(readFileSync(path,'utf8')))===JSON.stringify(value),'derived_native_changed');
  return filePin(path);
}
async function originalRecords(m:TaskManifest,c:AttemptContext):Promise<any[]> {
  const records=Array.isArray(m.adapterConfig.originalResults)?[...m.adapterConfig.originalResults]:[];
  const paths=m.adapterConfig.originalResultsPaths;
  if(c.attemptId!=='original-recovery'&&Array.isArray(paths))for(const r of paths) {
    const record:any={};
    for(const [field,name]of Object.entries({taskPin:'taskPath',summaryPin:'summaryPath',financialClosurePin:'financialClosurePath',nativeClosurePin:'nativeClosurePath',gradePin:'gradePath',standReceiptsPin:'standReceiptPath'})) {
      if(r[name])record[field]=filePin(expand(r[name],c));
    }
    if(!record.nativeClosurePin&&r.nativeMapping)record.nativeClosurePin=await mappedNative(m,c,r.nativeMapping);
    record.candidateSha256=r.candidateSha256;record.output=r.output?expand(r.output,c):undefined;records.push(record);
  }
  return records;
}

/** Original records are only read. No replacement generation verdict or grading invocation. */
export async function recoverFor(bench: Bench, m: TaskManifest, c: AttemptContext): Promise<StageResult> {
  validateFor(bench,m); assertContext(m,c);
  if(bench==='terminal-bench'&&c.attemptId==='original-recovery'&&m.adapterConfig.terminalDriver&&m.history.validResultPins.length===0)try {
    const data=validateTerminalDriverData(m),history=inspectLegacyHistory(m,data),actors=await inspectLegacyActorAbsence(data,history.actorCids);
    const path=join(c.runDir,'original-legacy-recovery.json');wxJson(path,{protocol:'bench-actual-legacy-original-recovery-v1',taskId:m.taskId,bench,manifestPin:c.manifestPin,
      identityPin:data.identityPin,closureReviewPin:data.closureReviewPin,aggregateBudgetPin:data.aggregateBudgetPin,history,actualActorApi404:actors,
      noOriginalCandidateOrGrade:true,originalNullIdentityPreserved:true,newModelGradeNativeMutations:0});
    return {status:'retryable',proofPins:[filePin(path),data.identityPin,data.closureReviewPin,data.aggregateBudgetPin],nativeClosed:true,financialClosed:true,candidateOrSubmissionPresent:false,reason:'strict_original_legacy_cash_native_no_result_reconciled'};
  }catch(error){return unknown('original_legacy_reconciliation_failed:'+String(error));}
  if(c.attemptId!=='original-recovery'&&m.adapterConfig.bindingSpec&&!c.bindings)try {c=loadPreparedContext(m,c,true);}catch(error){return unknown('original_binding_custody_pending:'+String(error));}
  let records:any[];
  try {records=await originalRecords(m,c);} catch(error){return unknown('original_artifact_mapping_pending:'+String(error));}
  if ((!Array.isArray(records) || records.length === 0)&&!m.adapterConfig.closedFailure) return unknown('original_result_mapping_required');
  const failures:string[]=[];
  for (const r of records) {
    try {
      const task = readPinned(r.taskPin), summary = readPinned(r.summaryPin);
      requireTrue((bench==='terminal-bench'?(task.officialId??task.taskId):task.taskId) === m.taskId && (summary.runId === task.runId || summary.output === r.output), 'original_run_identity');
      const acceptance = bench === 'skillsbench' ? task.officialAcceptance : task.acceptance;
      const generationValid = bench === 'skillsbench' ? task.generation?.valid : task.generationValid;
      // A policy-derived override cannot turn an invalid generation into a valid one.
      requireTrue(generationValid === true && acceptance?.valid === true && (bench !== 'skillsbench' || task.protocolValid === true), 'original_generation_and_acceptance_required');
      const budget = acceptance.outcome === 'budget_exhausted' || task.outcome === 'budget_exhausted' || task.generation?.outcome === 'budget_exhausted';
      let gradePin = acceptance.gradeOwnerPin ?? r.gradePin;
      const proofs: Pin[] = [r.taskPin,r.summaryPin,r.financialClosurePin,r.nativeClosurePin];
      if (!budget) {
        const text=bench==='terminal-bench'?task.answer:task.candidate;
        const candidate=typeof text==='string'?createHash('sha256').update(text).digest('hex'):(task.candidateSha256??task.candidate?.sha256);
        requireTrue(typeof candidate==='string'&&(!r.candidateSha256||candidate===r.candidateSha256),'original_candidate_content_binding');
        if(bench==='terminal-bench') {
          requireTrue(candidate===task.candidateLabelSha256&&candidate===acceptance.candidateSha256,'original_tb_answer_acceptance_binding');
          requireTrue(r.standReceiptsPin,'original_tb_stand_receipts_required');const stand=readPinned(r.standReceiptsPin);
          const rows=stand.rows?.filter((x:any)=>['grade','snapshot-grade'].includes(x.kind)&&x.taskId===m.taskId&&x.place===task.place&&x.attemptId===task.taskId&&x.labelSha256===candidate&&x.protectedInputsUnchanged===true);
          requireTrue(rows?.length>0,'original_tb_grade_row_missing');const row=rows[rows.length-1];gradePin=filePin(row.gradePath);
          requireTrue(gradePin.sha256===row.gradeSha256,'original_tb_grade_row_hash');const grade=readPinned(gradePin),result=grade.result,ctrf=result?.ctrf?.results;
          requireTrue(grade.protocol==='tb12-snapshot-grade-v1'&&grade.taskId===m.taskId&&grade.candidateCid===task.candidateCid&&grade.invocationId===row.invocationId&&result?.invocationId===row.invocationId,'original_tb_candidate_invocation_identity');
          requireTrue(result.collectOnly===false&&[0,1].includes(result.exitCode)&&[0,1].includes(result.reward)&&result.reward===row.originalReward&&(result.reward===1)===acceptance.passed,'original_tb_grader_reward');
          requireTrue(ctrf?.summary?.tests>0&&Array.isArray(ctrf.tests)&&ctrf.tests.length===ctrf.summary.tests&&ctrf.summary.pending===0&&ctrf.summary.other===0,'original_tb_collection_complete');
          requireTrue(grade.removal?.exitCode===0&&grade.removal.closeObserved===true&&grade.absence?.exitCode===1&&grade.absence.closeObserved===true,'original_tb_checker_closed');
          proofs.push(r.standReceiptsPin);
        } else {
          requireTrue(gradePin, 'same_candidate_original_grade_required'); const grade=readPinned(gradePin),result=grade.result??grade;
          requireTrue(result.complete===true&&grade.candidateAnswerSha256===candidate,'original_sb_grade_complete_candidate');
          requireTrue(!result.taskId||result.taskId===m.taskId,'original_sb_grade_task_identity');
          for(const p of [result.ownerReceiptPin,result.ownerClosurePin,grade.builtImagesPin,grade.controlPin])if(p){linkedPins(p);proofs.push(p);}
          requireTrue(task.toolQuiescence?.sealed===true&&task.toolQuiescence?.outstanding===0&&task.solverClosure?.ok===true&&task.solverClosure?.ownedContainersRemaining===0,'original_sb_quiescence_native_closure');
        }
        proofs.push(gradePin);
      }
      financeClosed(r.financialClosurePin,task.runId??summary.runId,m.original.taskCapUsd); nativeClosed(r.nativeClosurePin,m.taskId,task.runId??summary.runId);
      return {status:'valid',proofPins:proofs,nativeClosed:true,financialClosed:true,candidateOrSubmissionPresent:!budget,
        validResult:{passed:acceptance.passed === true,outcome:budget?'budget_exhausted':(acceptance.passed?'passed':'wrong'),proofPin:r.taskPin}};
    } catch (error) { failures.push(String(error)); }
  }
  // An explicitly mapped failed original may authorize a later new attempt, never a hidden retry here.
  const failure=m.adapterConfig.closedFailure as any;
  if(failure&&c.attemptId==='original-recovery')try {
    const p=readPinned(failure.proofPin);
    requireTrue(p.taskId===m.taskId&&p.noOriginalGradeToRecover===true&&p.candidateOrSubmissionPresent===false,'no_candidate_recovery_required');
    requireTrue(p.valid===false&&p.rootReviewed===true,'reviewed_failed_original_required');
    financeClosed(failure.financialClosurePin,p.runId,m.original.taskCapUsd);nativeClosed(failure.nativeClosurePin);
    return {status:'retryable',proofPins:[failure.proofPin,failure.financialClosurePin,failure.nativeClosurePin],nativeClosed:true,financialClosed:true,candidateOrSubmissionPresent:false,reason:'original_failed_attempt_explicitly_closed_new_attempt_only'};
  } catch(error){failures.push(String(error));}
  return unknown('original_result_unverified:'+failures.join(';'),records.map((r:any)=>r.taskPin).filter(Boolean));
}

export async function executeFor(bench: Bench, m: TaskManifest, spec: StageSpec, c: AttemptContext): Promise<StageResult> {
  validateFor(bench,m); assertContext(m,c);
  if (m.history.validResultPins.length) return recoverFor(bench,m,c);
  if(m.history.originalResultRecoveryRequired||c.inventoryTask.state==='recoverable') {
    if(!c.originalRecoveryProofPin)return recoverFor(bench,m,c);
    const proof=readPinned(c.originalRecoveryProofPin),r=proof.result;
    requireTrue(proof.taskId===m.taskId&&proof.bench===bench&&JSON.stringify(proof.manifestPin)===JSON.stringify(c.manifestPin),'original_recovery_identity');
    requireTrue(['retryable','complete'].includes(r?.status)&&r.nativeClosed===true&&r.financialClosed===true&&r.candidateOrSubmissionPresent===false&&!r.validResult,'original_recovery_closed_no_candidate');
    requireTrue(Array.isArray(r.proofPins)&&r.proofPins.length>0,'original_recovery_proofs_required');for(const p of r.proofPins)checkPin(p);
  }
  for (const pin of spec.evidencePins) checkPin(pin);
  if (spec.kind === 'reuse') {
    const path = resolve(expand(spec.successEvidence!.path,c));
    requireTrue(spec.evidencePins.some(p=>resolve(p.path)===path), 'reuse_success_file_not_pinned');
    const value = JSON.parse(readFileSync(path,'utf8').replace(/^\uFEFF/,''));
    requireTrue(predicates(value,spec.successEvidence!.equals), 'reuse_success_predicate_failed');
    return {status:'complete',proofPins:spec.evidencePins,nativeClosed:false,financialClosed:false,candidateOrSubmissionPresent:false,reason:'verified_prior_stage_reused_no_execution'};
  }
  if(m.adapterConfig.bindingSpec)c=loadPreparedContext(m,c);
  // Driver continues to own COMMON81/106, owner FILETIME/token, original broker and before-journal gates.
  const contract = m.adapterConfig.driverContract as any;
  requireTrue(contract?.ownedLease === true && contract?.beforeJournal === true && contract?.beforeForward === true && contract?.originalBudget === true, 'qualified_deep_driver_contract_required');
  requireTrue(contract.pin && m.provenance.contractPins.some(p=>p.sha256===contract.pin.sha256 && resolve(p.path)===resolve(contract.pin.path)), 'driver_contract_pin_required');
  checkPin(contract.pin);
  const receipt = await executeCommand(m,{...spec,timeoutSeconds:spec.outerTimeoutSeconds??spec.timeoutSeconds},c);
  const custody = [receipt.processPin,receipt.stdoutPin,receipt.stderrPin];
  if (!receipt.closeObserved || receipt.timedOut) return unknown('driver_custody_unresolved_no_retry',custody);
  if(Array.isArray(m.adapterConfig.originalResultsPaths)) {
    const recovered=await recoverFor(bench,m,c);
    if(recovered.status==='valid') {
      const completedStages:NonNullable<StageResult['completedStages']>={};
      for(const stage of spec.bundledStages??[c.stage])if(['solve','grade','cleanup','reconcile'].includes(stage))completedStages[stage]={proofPins:recovered.proofPins};
      return {...recovered,proofPins:[...custody,...recovered.proofPins],completedStages};
    }
    return {...recovered,proofPins:[...custody,...recovered.proofPins]};
  }
  const config = m.adapterConfig.driverResult as any;
  if (!config?.path || config.protocol !== 'bench-driver-result-v1') return unknown('driver_result_protocol_mapping_required',custody);
  const path = expand(config.path,c);
  if (!existsSync(path)) return unknown('driver_result_missing',custody);
  const envelope = JSON.parse(readFileSync(path,'utf8').replace(/^\uFEFF/,''));
  requireTrue(envelope.protocol===config.protocol && envelope.taskId===c.taskId && envelope.bench===bench && envelope.attemptId===c.attemptId && envelope.stage===c.stage, 'driver_result_identity');
  const result = envelope.result as StageResult;
  requireTrue(['complete','retryable','invalid','unknown','valid'].includes(result?.status) && Array.isArray(result.proofPins), 'driver_result_shape');
  for (const pin of result.proofPins) checkPin(pin);
  if(receipt.exitCode!==0&&result.status!=='valid')return unknown('driver_nonzero_exit_not_success',[filePin(path),...custody,...result.proofPins]);
  // Driver booleans do not certify finance/native/valid acceptance. Recover from original artifacts instead.
  if (result.status === 'valid' || result.validResult || result.nativeClosed || result.financialClosed || result.status === 'retryable') {
    const recovery = await recoverFor(bench,m,c);
    return recovery.status === 'valid' ? recovery : unknown('driver_closure_requires_original_artifact_mapping',[filePin(path),...custody,...result.proofPins]);
  }
  // The optional observational evidence is verified independently; unverified driver counters are discarded.
  let actualSolver:StageResult['actualSolver'];
  if (envelope.actualSolverEvidencePin) actualSolver=await inspectActualSolver(envelope.actualSolverEvidencePin);
  return {...result,proofPins:[filePin(path),...custody,...result.proofPins],actualSolver,nativeClosed:false,financialClosed:false};
}
export function getAdapter(bench: Bench): BenchAdapter {
  if (bench === 'terminal-bench') return terminalBenchAdapter;
  if (bench === 'skillsbench') return skillsbenchAdapter;
  throw Error('unknown_bench');
}
