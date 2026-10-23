/** Enforce the first task cap across real closed cash from every prior attempt. */
import {jsonPin,verifyPin,demand,type Pin} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from '../../shared/digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from '../../shared/digitalocean-journal.ts';
export function recoveryJournalBudget(historyPin:Pin,laneCapUsd:number){
 verifyPin(historyPin);const h=jsonPin(historyPin);
 demand(h.originalTaskCashConfigPin&&h.cashClosePins?.length,'task_recovery_cash_chain_required');
 verifyPin(h.originalTaskCashConfigPin);const original=jsonPin(h.originalTaskCashConfigPin);
 demand(original.protocol==='openrouter-usd-cash-config-v1'&&original.currency==='USD'&&Number.isFinite(original.capUsd),'first_task_cash_cap_required');
 let prior=0;const seen=new Set<string>();let containsFirst=false;
 for(const p of h.cashClosePins){verifyPin(p);const cash=verifyBenchmarkCashClosure(p),journal=inspectCampaignJournal(cash.proof.journalDirectory);
  demand(!seen.has(cash.config.runId)&&journal.valid&&journal.accountingClosed&&cash.proof.snapshot.pendingCount===0,'old_cash_chain_closed_unique');seen.add(cash.config.runId);
  prior+=cash.proof.snapshot.billedUsd+cash.proof.snapshot.unknownReservationUsd;
  if(cash.config.runId===original.runId){demand(cash.proof.configPin.sha256===h.originalTaskCashConfigPin.sha256,'first_task_config_join');containsFirst=true;}
 }
 demand(containsFirst&&Number.isFinite(laneCapUsd)&&laneCapUsd>0,'original_first_attempt_coverage');
 const remaining=original.capUsd-prior,capUsd=Math.min(laneCapUsd,remaining);
 demand(capUsd>0&&prior+capUsd<=original.capUsd+1e-9,'original_task_budget_exhausted');
 if(h.originalTaskCapUsd!==undefined)demand(h.originalTaskCapUsd===original.capUsd,'root_task_cap_exact');
 if(h.exposureUpperBoundUsd!==undefined)demand(Math.abs(h.exposureUpperBoundUsd-prior)<1e-12,'root_prior_expense_exact');
 return {capUsd,priorCampaignCostUpperBoundUsd:0,priorTaskCostUpperBoundUsd:prior,originalTaskCapUsd:original.capUsd,newAttemptMaxSpendUsd:capUsd,historyPin,oldCashClosePins:h.cashClosePins,originalTaskCashConfigPin:h.originalTaskCashConfigPin,equivalentRemainingBudgetEnforced:true};
}
