/** Resume only financially closed segments; never regenerate existing outcomes. */
import { existsSync,readFileSync,readdirSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin,demand,jsonPin,verifyPin,type Pin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { inspectFullFClosedCash } from '../shared/digitalocean-closed-run-cost.ts';
import { inspectCampaignJournal } from '../../../repair-2026-10-08/campaign-journal.ts';
import { inspectCampaignJournal as inspectDigitalOceanJournal } from '../shared/digitalocean-journal.ts';
import { verifyControlledBrokerRecovery } from '../shared/controlled-broker-recovery.ts';

export type ClosedSegment={runId:string;records:any[];interruptedAttempts?:any[];billedUsd:number;requestCount:number;closurePin:Pin;unknownCostCount?:number;unknownReservationUsd?:number};
export function taskFitsPriceWindow(row:{taskSeconds:number;verifierSeconds:number},observedAtUtc:string,now=Date.now()){
  const observed=Date.parse(observedAtUtc);
  demand(Number.isFinite(observed)&&observed<=now&&row.taskSeconds>0&&row.verifierSeconds>0,'continuation_price_or_task_budget');
  // Six frozen F checks plus the explicit final original grade. This is a
  // parent orchestration allowance, not a change to any individual deadline.
  const requiredMs=(row.taskSeconds+7*row.verifierSeconds+600)*1000;
  return {canStart:now+requiredMs<observed+86400000,requiredMs,expiresAtUnixMs:observed+86400000};
}
export function planContinuation(schedule:any[],segments:ClosedSegment[]){
  demand(schedule.length===87&&new Set(schedule.map(r=>r.taskId)).size===87&&schedule.every(r=>r.arm==='F'),'resume_full87_f_scope');
  const frozen=new Map(schedule.map(r=>[r.taskId,r])),seen=new Set<string>(),records:any[]=[],nonconformingRecords:any[]=[];
  let billedUsd=0,requestCount=0,unknownCostCount=0,unknownReservationUsd=0;
  for(const segment of segments){
    demand(Number.isFinite(segment.billedUsd)&&segment.billedUsd>=0&&Number.isSafeInteger(segment.requestCount)&&segment.requestCount>=0,'resume_financial_totals');
    const attempts=segment.interruptedAttempts??[];
    for(const attempt of attempts){
      const row=frozen.get(attempt.taskId);
      demand(row&&attempt.runId===segment.runId&&attempt.arm==='F'&&attempt.terminal===false&&attempt.valid===false&&attempt.countsAsCompleted===false,'resume_interrupted_attempt_classification');
      demand(attempt.solverClosure?.ok===true&&attempt.solverClosure.ownedContainersRemaining===0,'resume_interrupted_attempt_cleanup');
      for(const key of ['taskSeconds','verifierSeconds','promptBodySha256','workdir'])demand(attempt[key]===row[key],'resume_interrupted_frozen_task_changed');
    }
    const sequences=[...segment.records,...attempts].flatMap(r=>r.apiCalls.map((c:any)=>c.requestSeq)).sort((a:number,b:number)=>a-b);
    demand(sequences.length===segment.requestCount&&sequences.every((n:number,i:number)=>n===i),'resume_unrecorded_or_duplicate_requests');
    for(const record of segment.records){
      const row=frozen.get(record.taskId);
      demand(row&&!seen.has(record.taskId)&&record.arm==='F'&&record.runId===segment.runId,'resume_duplicate_or_foreign_result');
      for(const key of ['taskSeconds','verifierSeconds','promptBodySha256','workdir'])demand(record[key]===row[key],'resume_frozen_task_changed');
      demand(['done','failed'].includes(record.state)&&record.solverClosure?.ok===true&&record.solverClosure.ownedContainersRemaining===0,'resume_nonterminal_result');
      demand(record.officialAcceptance&&typeof record.officialAcceptance.valid==='boolean'&&typeof record.officialAcceptance.passed==='boolean','resume_result_classification_missing');
      if(record.protocolValid===false){nonconformingRecords.push(record);continue;}
      seen.add(record.taskId);records.push(record);
    }
    billedUsd+=segment.billedUsd;requestCount+=segment.requestCount;
    unknownCostCount+=segment.unknownCostCount??0;unknownReservationUsd+=segment.unknownReservationUsd??0;
  }
  return {records,nonconformingRecords,pending:schedule.filter(r=>!seen.has(r.taskId)),billedUsd,requestCount,unknownCostCount,unknownReservationUsd,segments};
}

export function loadContinuation(home:string,manifest:any){
  const directory=join(home,'runs'),segments:ClosedSegment[]=[];
  if(!existsSync(directory))return planContinuation(manifest.taskSchedule,segments);
  const preparationPin=actualPin(join(home,'manifest.json'));
  for(const name of readdirSync(directory).sort()){
    const output=join(directory,name),path=join(output,'manifest.json');if(!existsSync(path))continue;
    const prior=JSON.parse(readFileSync(path,'utf8'));
    // A resource-queued preparation manifest cannot have dispatched through
    // this runtime before a broker lane and its local journal/cash exist.
    if(!['shared-admission','journal','cash','parent-process.json'].some(n=>existsSync(join(output,n))))continue;
    // An unclosed run must be reconciled before another admission, including
    // runs that died between a provider response and the task receipt.
    let original:any;
    if(prior.preparationManifestPin?.sha256===preparationPin.sha256){verifyPin(prior.preparationManifestPin);original=jsonPin(prior.preparationManifestPin);}
    else{
      const archive=join(output,'preparation-manifest-archived.json');demand(existsSync(archive),'resume_original_preparation_archive_required');
      const pin=actualPin(archive);demand(pin.sha256===prior.preparationManifestPin.sha256&&pin.bytes===prior.preparationManifestPin.bytes,'resume_original_preparation_archive_mismatch');
      original=jsonPin(pin);
    }
    if(JSON.stringify(original)!==JSON.stringify(manifest)){
      demand(original.provider==='relace'&&manifest.provider==='digitalocean','resume_only_authorized_provider_switch');
      demand(JSON.stringify({...original,provider:manifest.provider})===JSON.stringify(manifest),'resume_other_frozen_parameters_changed');
    }
    const closePath=['accounting-close.json','accounting-failure.json'].map(n=>join(output,n)).find(existsSync);
    demand(closePath,'resume_prior_run_requires_reconciliation');
    const closurePin=actualPin(closePath!),closure=jsonPin(closurePin);
    if(closure.brokerClose?.closed!==true){
      const control=readFileSync(join(home,'../control.json'),'utf8');
      const history=JSON.parse(control).brokerHistory??[];
      const controlled=history.find((h:any)=>h.controlledRecoveryPin&&h.releasePin&&prior.runId.startsWith(h.runId+'-'));
      if(controlled){
        const verified=verifyControlledBrokerRecovery(controlled.controlledRecoveryPin),recovery=jsonPin(controlled.controlledRecoveryPin),release=jsonPin(controlled.releasePin);
        demand(verified.verified===true&&recovery.owned.runId===controlled.runId&&release.protocol==='controlled-owned-lock-release-v1'&&release.owned.runId===controlled.runId&&release.canonicalOwnerAbsent===true,'resume_controlled_owner_release_invalid');
        const originalRecovery=jsonPin(release.recoveryPin);demand(JSON.stringify(originalRecovery)===JSON.stringify(recovery),'resume_controlled_recovery_release_join');
        const lane=recovery.lanes.find((l:any)=>l.slug==='skillsbench'&&l.runId===prior.runId);
        demand(lane&&lane.cashClosePin.sha256===closure.cashPin.sha256&&lane.cashClosePin.bytes===closure.cashPin.bytes,'resume_controlled_lane_cash_join');verifyPin(lane.cashClosePin);
      }else{
      const recovered=history.find((h:any)=>h.recoveryPin&&h.releasePin&&prior.runId.startsWith(h.runId+'-'));
      demand(recovered,'resume_dead_broker_recovery_required');
      const recovery=jsonPin(recovered.recoveryPin),release=jsonPin(recovered.releasePin);
      demand(recovery.protocol==='dead-broker-closed-owner-recovery-v1'&&recovery.runId===recovered.runId&&recovery.pendingRequests===0,'resume_dead_broker_recovery_invalid');
      demand(release.protocol==='dead-owned-lock-release-v1'&&release.owned.runId===recovery.runId&&release.canonicalOwnerAbsent===true,'resume_dead_owner_release_invalid');
      const originalRecovery=jsonPin(release.recoveryPin);demand(originalRecovery.runId===recovery.runId&&JSON.stringify(originalRecovery.lanes)===JSON.stringify(recovery.lanes),'resume_recovery_release_join');
      const lane=recovery.lanes.find((l:any)=>l.slug==='skillsbench'&&l.runId===prior.runId);
      demand(lane?.closed===true&&lane.active===0&&lane.cashClosePin.sha256===closure.cashPin.sha256&&lane.cashClosePin.bytes===closure.cashPin.bytes,'resume_dead_lane_cash_join');
      verifyPin(lane.cashClosePin);
      }
    }
    const cash=inspectFullFClosedCash(join(home,'../../../..'),closure.cashPin);
    demand(cash.config.runId===prior.runId&&cash.accountingClosed===true,'resume_foreign_or_unclosed_cash');
    const journalConfig=jsonPin(cash.config.journal.configPin);
    const journal=(journalConfig.providerSlug==='digitalocean'?inspectDigitalOceanJournal:inspectCampaignJournal)(cash.proof.journalDirectory);
    demand(journal.valid&&journal.accountingClosed,'resume_journal_not_closed');
    const records=readdirSync(output).filter(n=>/^task-\d+\.json$/.test(n)).map(n=>JSON.parse(readFileSync(join(output,n),'utf8')));
    const interruptedAttempts=readdirSync(output).filter(n=>/^interrupted-attempt-\d+\.json$/.test(n)).map(n=>JSON.parse(readFileSync(join(output,n),'utf8')));
    for(const attempt of interruptedAttempts){
      demand(attempt.protocol==='skillsbench-full-f-interrupted-attempt-v1','resume_interrupted_protocol');
      verifyPin(attempt.handoffPin);verifyPin(attempt.financePin);
      const handoff=jsonPin(attempt.handoffPin);verifyPin(handoff.engineSnapshotPin);
      const controlledExit=closure.brokerClose?.closed!==true&&handoff.originalParentExited===true&&handoff.originalFinallyCompleted===false&&handoff.candidateSnapshot?.untrustedExecutionOnly===true&&handoff.task?.result&&JSON.parse(handoff.task.result).valid===false;
      demand(handoff.requestsDrained===true&&(handoff.taskValid===false||controlledExit),'resume_interrupted_actual_snapshot_required');
      const raw=readFileSync(join(output,'journal/api-events.jsonl'),'utf8').trim().split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line));
      for(const call of attempt.apiCalls){const finish=raw.find(r=>r.kind==='finish'&&r.requestSeq===call.requestSeq);demand(finish&&JSON.stringify(finish.record)===JSON.stringify(call.receipt),'resume_interrupted_original_receipt_mismatch');}
      for(const pin of attempt.originalGradePins)verifyPin(pin);
    }
    for(const record of records){
      const auditPath=join(output,'task-protocol-audit-'+record.index+'.json');
      if(existsSync(auditPath)){
        const audit=jsonPin(actualPin(auditPath));
        demand(audit.protocol==='skillsbench-task-protocol-audit-v1'&&audit.runId===record.runId&&audit.taskId===record.taskId&&audit.protocolValid===false&&audit.authorizedCompliantAttemptMayRetry===true,'resume_protocol_audit_invalid');
        demand(audit.originalTaskRecordPin.sha256===actualPin(join(output,'task-'+record.index+'.json')).sha256,'resume_protocol_audit_original_join');
        verifyPin(audit.originalTaskRecordPin);record.protocolValid=false;record.protocolAuditPin=actualPin(auditPath);
      }else{
        demand(record.skillsDeploymentPin,'resume_original_skills_evidence_required');
        const deployment=jsonPin(record.skillsDeploymentPin);demand(deployment.verified===true&&deployment.taskId===record.taskId&&deployment.privateVerifierCopied===false&&deployment.privateOracleCopied===false,'resume_skills_deployment_invalid');
      }
      verifyPin(record.officialAcceptance.gradeOwnerPin);
      const grade=jsonPin(record.officialAcceptance.gradeOwnerPin);
      demand(grade.result?.complete===true&&grade.result.taskId===record.taskId&&grade.result.candidateExecutablesUsed===false&&grade.result.candidateSnapshotUsed===false,'resume_actual_private_grade_missing');
    }
    segments.push({runId:prior.runId,records,interruptedAttempts,billedUsd:cash.billedUsd,unknownCostCount:cash.unknownCostCount,unknownReservationUsd:cash.unknownReservationUsd,requestCount:journal.snapshot!.acceptedRequestCount,closurePin});
  }
  return planContinuation(manifest.taskSchedule,segments);
}
