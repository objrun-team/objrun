/** Includes the independently recovered failed V2 once, without changing its original registry or score. */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_ROOT as ROOT, chemiqOrdinary } from './chemiq-f-journal-contract-v2.ts';
import { verifyChemiqCertificate } from './chemiq-f-paid-admission-v2.ts';
import { auditChemiqFailedFinancialRecovery } from './chemiq-failure-financial-recovery-v1.ts';
import { assertChemiqOwnedFrame, chemiqActorCommand } from './chemiq-f-owned-v2.ts';

const FAILED='repair-2026-10-09T09-40-03-707Z', NONCE='4bdb76b522e42c56d8a12e6e3df6cf2c0bb5f4524dcbecf8';
const RECOVERY_SOURCE_SHA='3d0fbfe7dc9d19861d2399950cd1ceadd9a503588581e6636d8028905a3b2287';
export function verifyRecoveredChemiqV2(registryPin:Pin){
  const home=join(ROOT,'docs/repair-2026-10-08/chemiq-f-financial-recoveries-v2',FAILED);
  const indexPin=actualPin(join(home,'recovery-index.json')),index=jsonPin(indexPin),registry=jsonPin(registryPin);
  demand(registry.protocol==='chemiq-f-paid-resource-run-v2'&&registry.family==='chemiq-f-journal-v2'&&registry.runId===FAILED&&registry.providerKind==='real-provider'&&registry.released===false&&registry.certificationPin===null,'chemiq_recovered_original_failed_registry');
  demand(index.protocol==='chemiq-failed-run-financial-recovery-index-v1'&&index.runId===FAILED&&index.financialClosed===true&&index.scoreCertificateValid===false&&same(index.originalRegistryPin,registryPin)&&index.sourcePin.sha256===RECOVERY_SOURCE_SHA,'chemiq_recovered_index_binding');
  verifyPin(index.sourcePin);
  const audited=auditChemiqFailedFinancialRecovery();
  demand(same(audited.certificatePin,index.certificatePin)&&audited.scoreCertificateValid===false&&audited.financialClosed===true&&audited.newPendingCount===0&&audited.newUnknownCount===0&&audited.oldUnknownSettled===false&&audited.originalPoisonPreserved===true&&index.recordedCostUpperBoundUsd===audited.recordedCostUpperBoundUsd,'chemiq_recovered_actual_cash_and_journal');
  const cert=jsonPin(index.certificatePin),ack=jsonPin(index.releaseCommittedPin),auth=jsonPin(ack.authorizationPin),admission=jsonPin(registry.admissionPin);
  demand(cert.ownerNonce===NONCE&&admission.owned.ownerNonce===NONCE&&ack.protocol==='chemiq-failed-run-exact-lock-release-committed-v1'&&ack.runId===FAILED&&ack.ownerNonce===NONCE&&ack.released===true&&ack.financialOnly===true&&ack.scoreCertificateValid===false&&ack.originalV2RegistryUnchanged===true&&ack.oldUnknownSettled===false,'chemiq_recovered_exact_commit');
  demand(auth.protocol==='chemiq-failed-run-exact-lock-release-authorization-v1'&&auth.runId===FAILED&&auth.ownerNonce===NONCE&&auth.financialOnly===true&&auth.scoreCertificateValid===false&&auth.oldUnknownSettled===false&&same(auth.certificatePin,index.certificatePin)&&same(auth.sourcePin,index.sourcePin),'chemiq_recovered_exact_authorization');
  const expectedOwnerBytes=Buffer.from(JSON.stringify(admission.owned,null,2)+'\n');
  const {createHash}=require('node:crypto');
  demand(resolve(auth.lockPin.path)===join(ROOT,'.phase1-data/owned-paid-campaign.lock.json')&&auth.lockPin.bytes===expectedOwnerBytes.length&&auth.lockPin.sha256===createHash('sha256').update(expectedOwnerBytes).digest('hex'),'chemiq_recovered_removed_lock_identity');
  const owned=jsonPin(auth.ownedClosePin),request=jsonPin(owned.requestPin),transcript=jsonPin(owned.transcriptPin);
  const prepared=jsonPin(cert.ownedClosePin),preparedRequest=jsonPin(prepared.requestPin);
  demand(owned.protocol==='chemiq-failure-recovery-owned-close-v1'&&owned.closed===true&&owned.modelCalls===0&&request.stage==='release'&&request.sourcePin.sha256===RECOVERY_SOURCE_SHA&&same(request.pids,preparedRequest.pids)&&same(request.ports,preparedRequest.ports)&&request.pids.length===18&&request.ports.length===18&&request.command===chemiqActorCommand(request.pids,request.ports),'chemiq_recovered_release_actor_inventory');
  demand(transcript.status===0&&!transcript.timedOut&&!transcript.stderr.trim()&&same(JSON.parse(transcript.stdout.trim()),owned.parsed),'chemiq_recovered_release_raw_native');
  assertChemiqOwnedFrame(owned.parsed,request.pids,request.ports);verifyPin(request.executablePin);verifyPin(request.sourcePin);
  const elapsed=Date.parse(auth.createdAtUtc)-Date.parse(transcript.completedAtUtc);
  demand(Number.isFinite(elapsed)&&elapsed>=0&&elapsed<=60000&&Date.parse(ack.createdAtUtc)>=Date.parse(auth.createdAtUtc),'chemiq_recovered_release_observation_time');
  demand(auth.reviewPins.length===2,'chemiq_recovered_independent_reviews');
  const axes=new Set<string>();
  for(const p of auth.reviewPins){const review=jsonPin(p);demand(review.protocol==='chemiq-failed-financial-recovery-independent-review-v1'&&review.remainingFinancialReleaseBlockers===0&&review.scoreCertificateValid===false&&review.modelCalls===0&&same(review.recoverySourcePin,index.sourcePin)&&same(review.financialCertificatePin,index.certificatePin),'chemiq_recovered_review_binding');axes.add(review.axis);}
  demand(axes.has('Spec')&&axes.has('Standards'),'chemiq_recovered_review_axes');
  const inputPins=[registryPin,indexPin,index.sourcePin,index.certificatePin,index.releaseCommittedPin,ack.authorizationPin,auth.ownedClosePin,owned.requestPin,owned.transcriptPin,request.executablePin,request.sourcePin,...auth.reviewPins,registry.admissionPin,actualPin(join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-campaigns-v2',FAILED,'api-ledger.json'))];
  for(const p of inputPins)verifyPin(p,undefined,512*1024**2);
  return {recordedCostUpperBoundUsd:audited.recordedCostUpperBoundUsd,inputPins,scoreCertificateValid:false,originalPoisonPreserved:true};
}
export async function scanChemiqV2RecoveredPaidRuns(root:string,currentRun:string){
  demand(resolve(root)===ROOT,'chemiq_v2_recovered_scanner_root');
  const home=join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-campaigns-v2'),inputPins:Pin[]=[],closedRunIds:string[]=[];
  let closedRecordedCostUpperBoundUsd=0;
  if(existsSync(home)){
    chemiqOrdinary(home,ROOT,true);
    for(const runId of readdirSync(home)){
      demand(runId!==currentRun,'chemiq_no_failed_run_id_reuse');
      const registryPin=actualPin(join(home,runId,'chemiq-paid-resource-run.json')),row=jsonPin(registryPin);
      if(runId===FAILED){const recovery=verifyRecoveredChemiqV2(registryPin);closedRecordedCostUpperBoundUsd+=recovery.recordedCostUpperBoundUsd;inputPins.push(...recovery.inputPins);}
      else{
        demand(row.protocol==='chemiq-f-paid-resource-run-v2'&&row.family==='chemiq-f-journal-v2'&&row.runId===runId&&row.providerKind==='real-provider'&&row.released===true&&row.certificationPin&&row.releaseCommittedPin&&row.releasePin&&row.admissionPin,'chemiq_other_v2_unclosed_run');
        const graph=await verifyChemiqCertificate(row.certificationPin,runId),ack=jsonPin(row.releaseCommittedPin),release=jsonPin(row.releasePin),admitted=jsonPin(row.admissionPin);
        demand(ack.protocol==='chemiq-f-lock-release-committed-v2'&&ack.family==='chemiq-f-journal-v2'&&ack.runId===runId&&ack.released===true&&ack.ownerNonce===admitted.owned.ownerNonce&&same(ack.authorizationPin,row.releasePin)&&same(release.certificationPin,row.certificationPin)&&release.originalUnknownSettled===false,'chemiq_other_v2_committed_release');
        const raw=jsonPin(graph.certificate.raw);demand(Number.isFinite(raw.recordedUsageUpperBoundUsd)&&raw.recordedUsageUpperBoundUsd>=0,'chemiq_other_v2_cost_unknown');
        closedRecordedCostUpperBoundUsd+=raw.recordedUsageUpperBoundUsd;inputPins.push(registryPin,row.certificationPin,row.releaseCommittedPin,row.releasePin);
      }
      closedRunIds.push(runId);
    }
  }
  demand(new Set(closedRunIds).size===closedRunIds.length,'chemiq_v2_recovery_duplicate');
  return {family:'chemiq-f-journal-v2',closedRecordedCostUpperBoundUsd,inputPins,closedRunIds,financialOnlyRecoveredRunId:closedRunIds.includes(FAILED)?FAILED:null};
}
