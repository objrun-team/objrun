/** Close a drained, exited startup attempt by independently replaying its existing USD journal/cash. No model calls. */
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {ROOT,OUT,save} from './prepare.ts';
import {actualPin,hash,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {inspectCampaignJournal} from '../../../repair-2026-10-08/campaign-journal.ts';
import {verifyBenchmarkCashClosure} from '../../../repair-2026-10-08/benchmark-usd-cash.ts';
import {acquireFullFAdmission} from '../shared/shared-admission.ts';
const active=JSON.parse(readFileSync(join(OUT,'active-run.json'),'utf8'));
try{process.kill(active.pid,0);throw Error('Original runner still alive; only recover exited runner');}catch(error){if((error as any).code!=='ESRCH')throw error;}
const output=active.output,store=join(output,'journal'),inspection=inspectCampaignJournal(store);
if(!inspection.valid||!inspection.accountingClosed||inspection.snapshot?.acceptedRequestCount!==inspection.snapshot?.finishedRequestCount)throw Error('Original model requests not durably drained');
const cashDir=join(store,'currency'),configPin=actualPin(join(cashDir,'cash-config.json')),config=JSON.parse(readFileSync(configPin.path,'utf8'));
const events=readFileSync(join(cashDir,'cash-events.jsonl'),'utf8').trim().split('\n').map(s=>JSON.parse(s));
const states=new Map<number,any>();let previous=configPin.sha256;
for(const [i,event]of events.entries()){if(event.index!==i||event.previousSha256!==previous)throw Error('USD cash chain mismatch');previous=hash(JSON.stringify(event)+'\n');const d=event.data;if(event.kind==='start'){states.set(d.ticket.requestSeq,{phase:'pending',ticket:d.ticket});}else if(event.kind==='finish'){if(!states.has(d.ticket.requestSeq))throw Error('Unbound cash finish');states.set(d.ticket.requestSeq,{...d});}else throw Error('Unexpected cash event');}
if([...states.values()].some(s=>s.phase!=='known'))throw Error('Unknown or pending cash; recovery cannot call it zero');
const billedUsd=[...states.values()].reduce((n,s)=>n+s.amountUsd,0);
const snapshot={protocol:'openrouter-usd-cash-state-v1',currency:'USD',runId:active.runId,capUsd:config.capUsd,billedUsd,pendingReservationUsd:0,unknownReservationUsd:0,exposureUpperBoundUsd:billedUsd,remainingUsd:config.capUsd-billedUsd,pendingCount:0,newUnknownCount:0,poisoned:false,poisonReason:null,invoice:false,foreignExchangeConversion:false};
const path=join(cashDir,'cash-close.json');if(existsSync(path))throw Error('Original cash already closed');
writeFileSync(path,JSON.stringify({protocol:'openrouter-usd-cash-close-v1',currency:'USD',configPin,cashEventsPin:actualPin(join(cashDir,'cash-events.jsonl')),snapshot,journalDirectory:store,journalPrefix:inspection.prefix,releasePermitted:true,scoreCertificate:false,invoice:false,foreignExchangeConversion:false},null,2)+'\n');
const cashPin=actualPin(path),verified=verifyBenchmarkCashClosure(cashPin);
save('startup-recovery/cash-replay.json',{protocol:'chemiq-startup-financial-recovery-v1',originalRunnerExited:true,modelCalls:0,originalModelRequests:inspection.snapshot?.acceptedRequestCount,originalCostUsd:billedUsd,cashClosePin:cashPin,independentReplayPassed:verified.proof.releasePermitted,scoredQuestions:0,originalEvidenceUnmodifiedExceptAppendOnlyClosure:true,observedAtUtc:new Date().toISOString()});
const source=join(ROOT,'scripts/repair-2026-10-10/full-f/chemiq/run.ts'),current=readFileSync(source),original=readFileSync(join(OUT,'startup-recovery/original-run.ts'));
const manifest=JSON.parse(readFileSync(join(output,'manifest.json'),'utf8'));
const expected=manifest.sourcePins.find((p:any)=>p.path===source);if(!expected||hash(original)!==expected.sha256)throw Error('Historical source not exact');
// Restore the historical source solely to reclaim this lane's token and close it. Never forward a model request.
try{writeFileSync(source,original);for(const pin of manifest.sourcePins)verifyPin(pin);
  const admission=await acquireFullFAdmission({root:ROOT,output,runId:active.runId,slug:'chemiq',sourcePins:manifest.sourcePins});
  const receipt=await admission.finishLightweight({cashPin});writeFileSync(join(output,'lane-close.json'),JSON.stringify(receipt,null,2)+'\n');
}finally{writeFileSync(source,current);}
writeFileSync(join(output,'currency-close.json'),readFileSync(path));
save('status.json',{protocol:'chemiq-full-f-status-v1',phase:'ready-to-resume',denominator:816,completed:0,knownCostUsd:billedUsd,unknownCostCount:0,pendingRequests:0,modelRequests:1,financialClosed:true,startupFailure:'Task URL maxParamLength, then status rename EPERM; no valid scores; same frozen experiment parameters retained',updatedAtUtc:new Date().toISOString()});
console.log(JSON.stringify({closed:true,costUsd:billedUsd,completed:0,modelCalls:0}));
