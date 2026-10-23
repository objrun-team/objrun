/** Resume accounting without making fee reconciliation a run gate. Raw evidence remains immutable. */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { verifyBenchmarkCashClosure } from './digitalocean-usd-cash.ts';
import { same, type Pin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { verifyReconciliation } from './cash-reconciliation.ts';

const cache = new Map<string, ReturnType<typeof verifyReconciliation>>();
export function inspectFullFClosedCash(root:string, pin:Pin) {
  const verified=verifyBenchmarkCashClosure(pin),snapshot=verified.proof.snapshot;
  const control=JSON.parse(readFileSync(join(root,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8'));
  let billedUsd=snapshot.billedUsd,unknownCostCount=snapshot.newUnknownCount,unknownReservationUsd=snapshot.unknownReservationUsd;
  if(unknownCostCount&&control.legacyReconciliationPin){
    const proof=control.legacyReconciliationPin as Pin,key=proof.path+':'+proof.sha256;
    let report=cache.get(key);if(!report){report=verifyReconciliation(proof);cache.set(key,report);}
    const resolved=report.lanes.find(lane=>same(lane.originalCashClosePin,pin));
    if(resolved){billedUsd=resolved.effectiveBilledUsd;unknownCostCount=resolved.remainingUnknownCostCount;unknownReservationUsd=0;}
  }
  if(unknownCostCount&&control.costPolicy?.mode!=='record_and_continue')throw Error('Previous cash requires continuation authorization');
  return {...verified,billedUsd,unknownCostCount,unknownReservationUsd,accountingClosed:true,
    financiallyResolved:unknownCostCount===0,originalReleasePermitted:verified.proof.releasePermitted,
    rawEvidenceUnmodified:true,scoreCertificate:false};
}
