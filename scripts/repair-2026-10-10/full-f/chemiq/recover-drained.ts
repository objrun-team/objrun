/** Independent append-only closure after safe-stop confirmed zero pending paid requests. */
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {ROOT,OUT,save} from './prepare.ts';
import {actualPin,hash,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {inspectCampaignJournal} from '../../../repair-2026-10-08/campaign-journal.ts';
import {verifyBenchmarkCashClosure} from '../../../repair-2026-10-08/benchmark-usd-cash.ts';
import {acquireFullFAdmission} from '../shared/shared-admission.ts';
const active=JSON.parse(readFileSync(join(OUT,'active-run.json'),'utf8'));
const stop=JSON.parse(readFileSync(join(OUT,'safe-stop.json'),'utf8').replace(/^\uFEFF/,''));if(stop.runId!==active.runId)throw Error('Stop receipt run mismatch');
try{process.kill(active.pid,0);throw Error('Original runner still alive');}catch(error){if((error as any).code!=='ESRCH')throw error;}
const output=active.output,store=join(output,'journal'),inspection=inspectCampaignJournal(store);if(!inspection.valid||!inspection.accountingClosed)throw Error('Journal not independently closed');
const cashDir=join(store,'currency'),configPin=actualPin(join(cashDir,'cash-config.json')),config=JSON.parse(readFileSync(configPin.path,'utf8'));
const events=readFileSync(join(cashDir,'cash-events.jsonl'),'utf8').trim().split('\n').filter(Boolean).map(s=>JSON.parse(s)),states=new Map<number,any>();let previous=configPin.sha256;
for(const [i,event]of events.entries()){if(event.index!==i||event.previousSha256!==previous)throw Error('Cash chain mismatch');previous=hash(JSON.stringify(event)+'\n');const d=event.data;if(event.kind==='start')states.set(d.ticket.requestSeq,{phase:'pending'});else if(event.kind==='finish'){if(!states.has(d.ticket.requestSeq))throw Error('Unbound finish');states.set(d.ticket.requestSeq,d);}else throw Error('Unexpected cash event');}
if([...states.values()].some(s=>s.phase!=='known'))throw Error('Pending/unknown cost cannot be closed');const billedUsd=[...states.values()].reduce((n,s)=>n+s.amountUsd,0);
const snapshot={protocol:'openrouter-usd-cash-state-v1',currency:'USD',runId:active.runId,capUsd:config.capUsd,billedUsd,pendingReservationUsd:0,unknownReservationUsd:0,exposureUpperBoundUsd:billedUsd,remainingUsd:config.capUsd-billedUsd,pendingCount:0,newUnknownCount:0,poisoned:false,poisonReason:null,invoice:false,foreignExchangeConversion:false};
const path=join(cashDir,'cash-close.json');if(!existsSync(path))writeFileSync(path,JSON.stringify({protocol:'openrouter-usd-cash-close-v1',currency:'USD',configPin,cashEventsPin:actualPin(join(cashDir,'cash-events.jsonl')),snapshot,journalDirectory:store,journalPrefix:inspection.prefix,releasePermitted:true,scoreCertificate:false,invoice:false,foreignExchangeConversion:false},null,2)+'\n');
const cashPin=actualPin(path);verifyBenchmarkCashClosure(cashPin);
const manifest=JSON.parse(readFileSync(join(output,'manifest.json'),'utf8'));for(const pin of manifest.sourcePins)verifyPin(pin);
if(!existsSync(join(output,'lane-close.json'))){const admission=await acquireFullFAdmission({root:ROOT,output,runId:active.runId,slug:'chemiq',sourcePins:manifest.sourcePins});writeFileSync(join(output,'lane-close.json'),JSON.stringify(await admission.finishLightweight({cashPin}),null,2)+'\n');}
writeFileSync(join(output,'currency-close.json'),readFileSync(path));
const status=JSON.parse(readFileSync(join(OUT,'status.json'),'utf8'));save('status.json',{...status,phase:'needs-finalization-repair',updatedAtUtc:new Date().toISOString(),knownCostUsd:status.priorCostUsd+billedUsd,cash:snapshot,pendingRequests:0,unknownCostCount:0,financialClosed:true,stoppedPid:active.pid,
  sharedChangesNeeded:['Repeated finalization_pending tasks6/9: onDone settled waits task_repair.done up to16min while deadline-sealed model continuation leaves done=0; outer1050s stops too early. Need actual bounded cancellation/drain completion or production settled hook fix by source owner; do not turn pending into valid timeout. Lane safely stopped and independently closed before any source modification.'],
  stopReceipt:'safe-stop.json',diagnosis:'diagnostics/finalization-diagnosis.md',validResultsPreserved:true});
save('diagnostics/drained-closure.json',{observedAtUtc:new Date().toISOString(),runId:active.runId,cashPin,independentUsdReplayPassed:true,billedUsd,modelCallsByRecovery:0,originalRawEventsUnmodified:true});
console.log(JSON.stringify({closed:true,runCostUsd:billedUsd,completed:status.completed}));
