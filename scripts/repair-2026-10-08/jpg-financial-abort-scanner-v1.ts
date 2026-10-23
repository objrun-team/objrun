/** Prospective JPG preflight only. No factory, provider, lock mutation or general skip list. */
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, verifyPin } from './paid-resource-proof-v2.ts';
import { scanOtherPaidRuns } from './paid-resource-admission-v2.ts';
import { actualJpgPriorUsd, scanJpgPaidRuns } from './jpg-paid-resource-admission-v1.ts';
import { FINANCIAL_RUN } from './financial-interruption-release.ts';
import { FINANCIAL_KNOWN_USD, verifyFinancialInterruptedBoundary, type FinancialInterruptedBoundary } from './financial-interruption-closure-v1.ts';
const ROOT=resolve(import.meta.dir,'../..');
export function addSingleInterruptedPrior(base:number,originalLedgerExists:boolean){demand(Number.isFinite(base)&&base>=0,'historical_prior_invalid');demand(originalLedgerExists===false,'historical_ledger_would_repeat_cost');return base+FINANCIAL_KNOWN_USD;}
export async function prospectiveJpgFinancialPreflight(root:string,newRunId:string,boundary:FinancialInterruptedBoundary){
  demand(resolve(root)===ROOT&&/^repair-[0-9TZ-]+$/.test(newRunId)&&newRunId!==FINANCIAL_RUN,'prospective_jpg_scope');
  demand(!existsSync(join(ROOT,'docs/repair-2026-10-08/campaigns',newRunId))&&!existsSync(join(ROOT,'docs/repair-2026-10-08/jpg-journal-campaigns',newRunId)),'prospective_jpg_run_already_exists');
  verifyPin({path:join(import.meta.dir,'paid-resource-admission-v2.ts'),bytes:41347,sha256:'0b752576bd37235140a7b97dafee16741ebaadd9cafda3370e20317d9fdddb0e'});
  verifyPin({path:join(import.meta.dir,'jpg-paid-resource-admission-v1.ts'),bytes:16915,sha256:'f815f002fc0413c09e8fc0bbf28c96af19d41e608c8967ce601d8dcf0dae75d7'});
  const verified=await verifyFinancialInterruptedBoundary(boundary);
  // The old scanner's only excluded current name is this already verified immutable historical run.
  scanOtherPaidRuns(ROOT,FINANCIAL_RUN);scanJpgPaidRuns(ROOT,newRunId);
  const oldLedger=join(ROOT,'docs/repair-2026-10-08/campaigns',FINANCIAL_RUN,'api-ledger.json');
  const prior=addSingleInterruptedPrior(actualJpgPriorUsd(ROOT),existsSync(oldLedger));
  return Object.freeze({protocol:'jpg-financial-abort-preflight-v1',family:'jpg-journal-v1',purpose:'prospective-jpg-prior-and-cross-family-scan',newRunId,fixedFinancialAbort:verified,priorCampaignCostUpperBoundUsd:prior,knownInterruptedUsdAddedOnce:FINANCIAL_KNOWN_USD,sourcePins:[actualPin(import.meta.path),actualPin(join(import.meta.dir,'financial-interruption-closure-v1.ts'))],scoreCertificate:false,admissionAuthorized:false,canonicalWxAndAssertOwnedRequired:true,modelCalls:0,paidLockOperations:0});
}
