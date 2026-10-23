/** Independent replay of a normally released historical broker; unknown fees remain unknown. */
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {gunzipSync} from 'node:zlib';
import {jsonPin,verifyPin,same} from '../../benchmark-repair/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from './shared/supplier-usd-cash.ts';
import {inspectCampaignJournal} from './shared/supplier-journal.ts';
function demand(ok:unknown,why:string):asserts ok{if(!ok)throw Error(why);}
export function verifyClosedBrokerHistory(entry:any){
 const h=jsonPin(entry.closedHealthPin),archive=jsonPin(entry.sourceArchivePin);
 demand(h.runId===entry.runId&&h.pid===entry.pid&&!h.canonicalOwner&&h.activeRequests===0&&h.queuedRequests===0
  &&Object.keys(h.resources).length===0&&h.lanes.every((l:any)=>l.closed),'historical_broker_not_closed');
 for(const row of archive.pins){verifyPin(row.archived);demand(row.original.sha256===row.archived.sha256
  &&row.original.bytes===row.archived.bytes,'historical_source_archive_mismatch');}
 const closures=(entry.releasePins??[]).flatMap((pin:any)=>{
  const r=jsonPin(pin);demand(r.currency==='USD'&&r.owned.runId===entry.runId,'historical_parent_release_identity');
  return r.cashClosures.map((cash:any)=>({cash,ownerNonce:r.owned.ownerNonce}));
 });
 const seen=new Set<string>(),generations=new Set<string>();let billedUsd=0,unknownCount=0,unknownReservationUsd=0,responseCostMismatches=0;
 for(const lane of h.lanes){
  const row=closures.find((r:any)=>jsonPin(r.cash.pin).snapshot.runId===lane.runId);
  demand(row&&!seen.has(lane.runId),'historical_lane_release_missing_or_duplicate');seen.add(lane.runId);
  const v=verifyBenchmarkCashClosure(row.cash.pin),s=v.proof.snapshot;
  demand(v.config.ownerNonce===row.ownerNonce&&v.config.capUsd===lane.capUsd&&s.pendingCount===0
   &&row.cash.billedUsd===s.billedUsd&&row.cash.unknownCostCount===s.newUnknownCount,'historical_cash_release_binding');
  const journal=inspectCampaignJournal(v.proof.journalDirectory);demand(journal.valid&&journal.accountingClosed,'historical_journal_not_closed');
  const configuration=jsonPin(v.config.journal.configPin);
  for(const line of readFileSync(join(v.proof.journalDirectory,'api-events.jsonl'),'utf8').trimEnd().split('\n').filter(Boolean)){
   const e=JSON.parse(line);if(e.kind!=='finish')continue;const r=e.record;
   if(r.requestId){demand(!generations.has(r.requestId),'historical_duplicate_generation');generations.add(r.requestId);}
   if(r.costBasis!=='provider_reported_usd')continue;
   const actual=JSON.parse(gunzipSync(readFileSync(r.responseFile)).toString('utf8'));
   if(actual.id!==r.requestId||actual.usage?.cost!==r.billedCostUsd||actual.usage?.cost!==r.usdUpperBound
    ||actual.provider!==configuration.providerName)responseCostMismatches++;
  }
  billedUsd+=s.billedUsd;unknownCount+=s.newUnknownCount;unknownReservationUsd+=s.unknownReservationUsd;
 }
 demand(seen.size===closures.length&&responseCostMismatches===0,'historical_release_or_cost_mismatch');
 return{runId:entry.runId,verified:true,effectiveBilledUsd:billedUsd,originalUnknownCostCount:unknownCount,
  remainingUnknownCostCount:unknownCount,unknownReservationUsd,originalCashUnmodified:true,financiallyResolved:unknownCount===0,
  verifiedLanes:seen.size,generationCount:generations.size,actualResponseCostsMatch:true,releasePins:entry.releasePins};
}
