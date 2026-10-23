import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {actualPin,jsonPin,same,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {inspectFullFClosedCash} from '../shared/digitalocean-closed-run-cost.ts';
const root=resolve(import.meta.dir,'../../../..'),out=join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq'),active=JSON.parse(readFileSync(join(out,'active-run.json'),'utf8')),control=JSON.parse(readFileSync(join(root,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8'));
try{process.kill(active.pid,0);throw Error('Runner alive; no recovered close needed');}catch(error){if(error.code!=='ESRCH')throw error;}
const cashPin=actualPin(join(active.output,'journal/currency/cash-close.json')),cash=inspectFullFClosedCash(root,cashPin);
const history=control.brokerHistory?.find(h=>h.recoveryPin&&h.releasePin&&active.runId.startsWith(h.runId+'-12-'));if(!history)throw Error('Coordinator recovery not published for this lane');
const recovery=jsonPin(history.recoveryPin),release=jsonPin(history.releasePin);
if(recovery.protocol!=='dead-broker-closed-owner-recovery-v1'||recovery.pendingRequests!==0||!recovery.originalCashUnmodified||!recovery.unknownChargesRetained||!same(release.recoveryPin,history.recoveryPin)||!same(release.owned,recovery.owned)||!release.canonicalOwnerAbsent)throw Error('Coordinator recovery/release binding failed');
const lane=recovery.lanes.find(l=>l.runId===active.runId&&l.slug==='chemiq');if(!lane?.closed||lane.active!==0||!same(lane.cashClosePin,cashPin))throw Error('Recovered lane cash pin not bound');
verifyPin(lane.registrationPin);const registration=jsonPin(lane.registrationPin),proof=jsonPin(cash.config.admissionPin);if(!same(registration.cashPin,cash.proof.configPin)||!same(proof.parentAdmissionPin,recovery.parentAdmissionPin)||proof.ownerNonce!==recovery.owned.ownerNonce)throw Error('Recovered registration/parent owner binding failed');
verifyPin(recovery.eventsPin);verifyPin(recovery.processesPin);
const receipt={protocol:'chemiq-coordinator-recovered-close-v1',atUtc:new Date().toISOString(),runId:active.runId,cashPin,recoveryPin:history.recoveryPin,releasePin:history.releasePin,registrationPin:lane.registrationPin,closed:true,accountingClosed:cash.accountingClosed,unknownCostCount:cash.unknownCostCount,rawEvidenceUnmodified:true,originalRpcLaneClose:false};
writeFileSync(join(active.output,'coordinator-recovered-close.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify({accepted:true,runId:active.runId,unknownRetained:cash.unknownCostCount}));
