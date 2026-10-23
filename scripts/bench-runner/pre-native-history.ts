/** Root-signed closed pre-native attempts are honest zero-native history, not transport retries. */
import {verify} from 'node:crypto';import {readFileSync} from 'node:fs';
import type {TaskManifest,Pin} from './types.ts';import {readPinned,checkPin} from './runtime.ts';
import {verifyBenchmarkCashClosure} from '../repair-2026-10-10/full-f/shared/digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from '../repair-2026-10-10/full-f/shared/digitalocean-journal.ts';
export function inspectPreNativeHistory(m:TaskManifest,budget:any,seen:Set<string>) {
 let knownUsd=0,unknownUsd=0,calls=0;
 const need=(x:unknown,s:string)=>{if(!x)throw Error(s);};
 for(const h of (m.adapterConfig.preNativeRecoveryHistory??[]) as any[]) {
  const envelope=readPinned(h.reviewEnvelopePin),r=envelope.review,authority=(m.adapterConfig.bindingSpec as any)?.authorityPin;checkPin(authority);
  need(envelope.protocol==='bench-root-signed-pre-native-reconciliation-v1'&&r?.protocol==='bench-pre-native-reconciliation-v1'&&verify(null,Buffer.from(JSON.stringify(r)),readFileSync(authority.path),Buffer.from(envelope.signature,'base64')),'pre_native_root_signature');
  need(r.taskId===m.taskId&&r.bench===m.bench&&r.attemptId===h.attemptId&&r.runId===h.runId&&r.cashClosePin.sha256===h.cashClosePin.sha256&&r.closureAuditPin.sha256===h.closureAuditPin.sha256,'pre_native_history_identity');
  const audit=readPinned(h.closureAuditPin),context=readPinned(r.contextPin),process=readPinned(r.processReceiptPin);checkPin(r.manifestPin);
  need(context.attemptId===h.attemptId&&context.manifestPin.sha256===r.manifestPin.sha256&&process.attemptId===h.attemptId&&process.manifestPin.sha256===r.manifestPin.sha256,'pre_native_actual_context');
  need(audit.taskId===m.taskId&&audit.bench===m.bench&&audit.attemptId===h.attemptId&&audit.runId===h.runId&&audit.nativeCommandCount===0&&audit.actorsEverCreated===false&&audit.candidateOrSubmissionPresent===false&&audit.resourceReleased===true&&audit.brokerLaneClosed===true,'pre_native_zero_custody');
  need(audit.evidencePins?.length>0,'pre_native_raw_evidence');for(const p of audit.evidencePins)checkPin(p);for(const p of r.permanentLockPins)checkPin(p);
  need(audit.exactPidAbsence?.some((x:any)=>x.pid===process.pid&&x.incarnation===process.incarnation),'pre_native_incarnation_closure');
  const cash=verifyBenchmarkCashClosure(h.cashClosePin),j=inspectCampaignJournal(cash.proof.journalDirectory),s=cash.proof.snapshot;
  need(!seen.has(cash.config.runId)&&cash.config.runId===h.runId&&budget.cashClosePins.some((p:Pin)=>p.path===h.cashClosePin.path&&p.sha256===h.cashClosePin.sha256),'pre_native_cash_chain');seen.add(h.runId);
  need(j.valid&&j.accountingClosed&&j.snapshot?.acceptedRequestCount===0&&j.snapshot?.finishedRequestCount===0&&s.pendingCount===0&&s.billedUsd===0&&s.unknownReservationUsd===0&&cash.config.capUsd<=m.original.taskCapUsd,'pre_native_actual_zero_cash');
  knownUsd+=s.billedUsd;unknownUsd+=s.unknownReservationUsd;calls+=j.snapshot!.acceptedRequestCount;
 }
 return {knownUsd,unknownUsd,calls};
}
