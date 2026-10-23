/** Cash-derived union of broker history and original SB closed/quarantined
 * financial segments. Distinct runs are counted once; unknowns never settled. */
import {writeFileSync,mkdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,jsonPin,verifyPin,same} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from '../../shared/digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from '../../shared/digitalocean-journal.ts';
import {base} from './review-authority-v4.ts';
export async function refreshCompleteUnknownHistory(baselinePin:any,sbExtractionPin:any){
 verifyPin(baselinePin);verifyPin(sbExtractionPin);const baseline=jsonPin(baselinePin),extraction=jsonPin(sbExtractionPin),runs=new Map<string,any>(),sbPins:any[]=[];
 const collect=(pin:any)=>{verifyPin(pin);const proof=jsonPin(pin),snapshot=proof.snapshot;if(!snapshot||snapshot.currency!=='USD'||!snapshot.newUnknownCount)return;const config=jsonPin(proof.configPin);if(!runs.has(config.runId))runs.set(config.runId,pin);};
 for(const pin of baseline.cashClosePins)collect(pin);
 for(const row of extraction.closureRows){verifyPin(row.closurePin);const closure=jsonPin(row.closurePin);if(!same(closure.cashPin,row.cashPin))throw Error('original_SB_closure_cash_identity');collect(row.cashPin);sbPins.push(row.closurePin);}
 const snapshots:any[]=[];
 for(const port of [17888,17889]){const response=await fetch('http://127.0.0.1:'+port+'/health',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('broker_history_unavailable');const h:any=await response.json(),lanes=h.lanes.filter((l:any)=>l.closed&&l.unknownCount>0);snapshots.push({port,runId:h.runId,observedAtUtc:h.atUtc,unknownLanes:lanes.map((l:any)=>({runId:l.runId,output:l.output,unknownCount:l.unknownCount,closed:l.closed}))});for(const lane of lanes){const output=resolve(lane.output);if(!output.startsWith(resolve(base,'../..')+'\\')&&!output.startsWith(resolve(base,'../..')+'/'))throw Error('history_project_output_scope');collect(actualPin(join(output,'cash/cash-close.json')));}}
 const rows:any[]=[];let upper=0,count=0;
 for(const [runId,pin] of runs){const cash=verifyBenchmarkCashClosure(pin),j=inspectCampaignJournal(cash.proof.journalDirectory),s=cash.proof.snapshot;if(!j.valid||!j.accountingClosed||s.pendingCount!==0||cash.config.runId!==runId)throw Error('actual_history_cash_or_journal_unclosed');upper+=s.unknownReservationUsd;count+=s.newUnknownCount;rows.push({runId,cashClosePin:pin,unknownCount:s.newUnknownCount,unknownReservationUsd:s.unknownReservationUsd,knownUsd:s.billedUsd});}
 const path=join(base,'account-history','unknown-complete-'+Date.now()+'.json');mkdirSync(join(base,'account-history'),{recursive:true});writeFileSync(path,JSON.stringify({protocol:'novaeve-account-history-unknown-upper-v6',rootReviewed:false,producerPin:actualPin(import.meta.path),baselinePin,sbExtractionPin,originalSBClosurePins:sbPins,originalBudgetPreserved:true,allHistoricalUnknownUpperBoundsRetained:true,observedAtUtc:new Date().toISOString(),brokerSnapshots:snapshots,cashClosePins:[...runs.values()],rows,unknownCount:count,unknownReservationUsd:upper,conservativeAdditionalUnknownReserveUsd:upper,modelCalls:0,recordedCostsModified:false},null,2)+'\n',{flag:'wx',mode:0o600});return actualPin(path);
}
if(import.meta.main)console.log(JSON.stringify({historyPin:await refreshCompleteUnknownHistory(actualPin(process.argv[2]),actualPin(process.argv[3])),modelCalls:0}));
