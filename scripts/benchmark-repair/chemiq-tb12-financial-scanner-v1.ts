/** Read-only cross-family financial replay. Never starts/stops TB actors or certifies TB scores. */
import { existsSync, readdirSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { actualPin, demand, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { chemiqOrdinary } from './chemiq-f-journal-contract-v3.ts';
const ROOT=resolve(import.meta.dir,'../..'),FAMILY='terminal-bench-twelve-journal-v1',HOME=join(ROOT,'docs/repair-2026-10-09/tb12-runs-v1');
export function verifyChemiqTb12FinancialRun(registryPin:Pin){
  const row=jsonPin(registryPin),home=join(HOME,row.runId);
  demand(/^repair-[0-9TZ-]+$/.test(row.runId)&&resolve(registryPin.path)===join(home,'tb12-paid-resource-run.json'),'chemiq_tb12_registry_scope');
  demand(row.protocol==='tb12-paid-resource-run-v1'&&row.family===FAMILY&&row.released===true&&row.closedPin&&row.releaseAckPin&&row.admissionPin,'chemiq_tb12_other_unclosed_run');
  const cert=jsonPin(row.closedPin),admitted=jsonPin(row.admissionPin),ack=jsonPin(row.releaseAckPin);
  demand(admitted.protocol==='paid-resource-admission-v2'&&admitted.tb12Protocol==='tb12-paid-resource-admission-v1'&&admitted.family===FAMILY&&admitted.runId===row.runId&&admitted.owned.family===FAMILY&&admitted.owned.runId===row.runId&&admitted.carryNanoCny==='8392180000','chemiq_tb12_admission');
  demand(cert.protocol==='tb12-independent-close-certificate-v1'&&cert.family===FAMILY&&cert.runId===row.runId&&cert.ownerNonce===admitted.owned.ownerNonce&&['score-and-financial','financial-only'].includes(cert.kind)&&cert.modelCallsByAuditor===0&&cert.sourceVerified===true&&cert.rawFinancialVerified===true&&cert.ownedCloseVerified===true&&cert.tokenSecretScanPassed===true,'chemiq_tb12_certificate');
  demand(ack.protocol==='tb12-paid-release-ack-v1'&&ack.family===FAMILY&&ack.runId===row.runId&&same(ack.owned,admitted.owned)&&same(ack.certificatePin,row.closedPin)&&ack.exactCanonicalOwnerRemoved===true&&ack.freshOwnedObservationPin,'chemiq_tb12_committed_owner');
  const snapshotPin=actualPin(join(home,'source-snapshots/manifest.json')),snapshot=jsonPin(snapshotPin);
  demand(snapshot.protocol==='tb12-matching-executed-source-snapshots-v1'&&same(snapshot.files.map((p:any)=>p.originalPin),admitted.sourcePins),'chemiq_tb12_historical_source_inventory');
  const inputPins:Pin[]=[registryPin,row.closedPin,row.releaseAckPin,row.admissionPin,snapshotPin];
  const historicalSourcePinReplays:any[]=[];
  for(const p of cert.inputPins as Pin[]){
    try{verifyPin(p);inputPins.push(p);}catch(error){
      // Only an admitted source may be replayed from its exact immutable per-run snapshot.
      const old=snapshot.files.find((s:any)=>same(s.originalPin,p));
      demand(old&&resolve(old.snapshotPin.path)===join(home,'source-snapshots',p.sha256+'-'+basename(p.path))&&old.snapshotPin.bytes===p.bytes&&old.snapshotPin.sha256===p.sha256,'chemiq_tb12_non_source_pin_changed');
      verifyPin(old.snapshotPin);inputPins.push(old.snapshotPin);historicalSourcePinReplays.push({originalSourcePin:p,immutableSnapshotPin:old.snapshotPin});
    }
  }
  demand(cert.inputPins.some((p:Pin)=>same(p,snapshotPin)),'chemiq_tb12_snapshot_not_in_closed_graph');
  const cash=verifyCashClosure(cert.cashClosePin),journal=inspectCampaignJournal(cash.proof.journalDirectory);
  demand(resolve(cert.cashClosePin.path)===join(home,'cash/cash-close.json')&&resolve(cash.proof.journalDirectory)===join(home,'provider')&&cash.config.runId===row.runId&&cash.config.ownerNonce===admitted.owned.ownerNonce&&cash.config.providerKind==='real-provider'&&cash.config.scope==='production'&&cash.config.carryNanoCny==='8392180000'&&same(cash.config.admissionPin,row.admissionPin)&&same(cash.config.pricesPin,admitted.pricesPin),'chemiq_tb12_cash_identity');
  demand(cash.proof.snapshot.pendingCount===0&&cash.proof.snapshot.newUnknownCount===0&&journal.valid&&journal.accountingClosed&&same(cash.proof.journalPrefix,journal.prefix)&&journal.snapshot!.acceptedRequestCount===journal.snapshot!.finishedRequestCount&&cert.newEstimatedNanoCny===cash.proof.snapshot.newKnownEstimatedNanoCny,'chemiq_tb12_raw_financial_closed');
  const usd=journal.snapshot!.recordedUsageUpperBoundUsd;demand(Number.isFinite(usd)&&usd>=0,'chemiq_tb12_recorded_cost_unknown');
  const fresh=jsonPin(ack.freshOwnedObservationPin);
  demand(fresh.protocol==='tb12-fresh-owned-absence-v1'&&fresh.family===FAMILY&&fresh.runId===row.runId&&fresh.ownerNonce===admitted.owned.ownerNonce&&fresh.allAbsent===true&&fresh.modelCalls===0,'chemiq_tb12_stored_owned_binding');
  const age=Date.parse(ack.observedAtUtc)-Date.parse(fresh.observedAtUtc);demand(Number.isFinite(age)&&age>=0&&age<=30000,'chemiq_tb12_commit_observation_time');
  for(const p of [...fresh.nativeReceiptPins,...fresh.closurePins]){verifyPin(p);inputPins.push(p);}
  inputPins.push(ack.freshOwnedObservationPin,cert.cashClosePin,cash.proof.configPin,cash.proof.cashEventsPin,cash.proof.journalConfigPin);
  // Numeric USD is a legacy reporting guard, with no CNY conversion or invoice claim.
  return {runId:row.runId,financialClosed:true,recordedCostUpperBoundUsd:usd,estimatedNanoCny:cash.proof.snapshot.newKnownEstimatedNanoCny,acceptedProviderRequests:journal.snapshot!.acceptedRequestCount,
    oldUnknownSettled:false,peerScoreCertifiedByThisScanner:false,peerLiveActorsReobserved:false,historicalSourcePinReplays,inputPins};
}
export function scanChemiqTb12FinancialRuns(root:string,currentRun:string){
  demand(resolve(root)===ROOT,'chemiq_tb12_scanner_root');
  const inputPins:Pin[]=[],closedRunIds:string[]=[],runs:any[]=[];let closedRecordedCostUpperBoundUsd=0;
  if(existsSync(HOME)){
    chemiqOrdinary(HOME,ROOT,true);
    for(const runId of readdirSync(HOME)){
      const home=join(HOME,runId);chemiqOrdinary(home,ROOT,true);demand(runId!==currentRun,'chemiq_tb12_cross_family_run_reuse');
      const r=verifyChemiqTb12FinancialRun(actualPin(join(home,'tb12-paid-resource-run.json')));
      closedRecordedCostUpperBoundUsd+=r.recordedCostUpperBoundUsd;inputPins.push(...r.inputPins);closedRunIds.push(runId);runs.push(r);
    }
  }
  demand(new Set(closedRunIds).size===closedRunIds.length,'chemiq_tb12_duplicate_run');
  return {family:FAMILY,closedRecordedCostUpperBoundUsd,inputPins,closedRunIds,runs,modelCalls:0,peerScoresCertified:false,peerLiveActorsReobserved:false};
}
