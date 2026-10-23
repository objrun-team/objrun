/** Release only this campaign's dead owner after independent native accounting replay. */
import {existsSync,readFileSync,readdirSync,writeFileSync,unlinkSync,mkdirSync} from 'node:fs';
import {join,dirname,resolve} from 'node:path';
import {actualPin,jsonPin,same,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from './digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from './digitalocean-journal.ts';
import {atomicStateJson} from './atomic-state.ts';
import {gunzipSync} from 'node:zlib';
function demand(ok:unknown,why:string):asserts ok {if(!ok)throw Error(why);}
function processInventory(){const r=Bun.spawnSync(['powershell.exe','-NoProfile','-NonInteractive','-Command',"@(Get-CimInstance Win32_Process | ForEach-Object { @{pid=$_.ProcessId;parentPid=$_.ParentProcessId;commandLine=$_.CommandLine;createdAtUtc=$_.CreationDate.ToUniversalTime().ToString('o')} }) | ConvertTo-Json -Compress"]);demand(r.exitCode===0,'process_inventory_failed');return JSON.parse(r.stdout.toString());}
export function verifyDeadBrokerRecovery(pin:any){
 const r=jsonPin(pin);demand(r.protocol==='dead-broker-closed-owner-recovery-v1'&&r.pendingRequests===0&&r.originalCashUnmodified&&r.unknownChargesRetained,'recovery_protocol');
 const h=jsonPin(r.staleHealthPin),parent=jsonPin(r.parentAdmissionPin),a=jsonPin(r.sourceArchivePin);
 demand(same(parent.owned,r.owned)&&h.runId===r.runId&&h.pid===r.owned.pid,'recovery_identity');
 for(const p of parent.sourcePins){const row=a.pins.find((x:any)=>same(x.original,p));demand(row,'recovery_source_missing');verifyPin(row.archived);demand(row.archived.sha256===p.sha256&&row.archived.bytes===p.bytes,'recovery_source_mismatch');}
 verifyPin(r.eventsPin);verifyPin(r.processesPin);verifyPin(r.crashPin);verifyPin(r.resourceClosurePin);
 demand(readFileSync(r.crashPin.path,'utf8').includes('EPERM'),'recovery_crash_evidence');
 const inventory=jsonPin(r.processesPin);demand(Number.isFinite(Date.parse(r.crashObservedAtUtc))&&inventory.every((p:any)=>Number.isInteger(p.pid)&&Number.isFinite(Date.parse(p.createdAtUtc))),'recovery_process_time_evidence');
 const alive=(pid:number)=>inventory.some((p:any)=>p.pid===pid&&Date.parse(p.createdAtUtc)<=Date.parse(r.crashObservedAtUtc));
 demand(!alive(r.owned.pid)&&!(h.resourceSlots??[]).some((x:any)=>alive(x.pid)),'recovery_processes_not_dead');
 const tb=jsonPin(r.resourceClosurePin);demand(tb.modelCalls===0&&tb.nativeReceipts.every((x:any)=>x.closeObserved===true&&x.exitCode!==null&&!alive(x.nativePid)),'recovery_resource_not_closed');
 const events=jsonPin(r.eventsPin),created=events.filter((e:any)=>e.kind==='lane-created');
 demand(created.length===r.lanes.length&&h.lanes.length===r.lanes.length,'recovery_full_lane_denominator');
 let known=0,unknown=0,reservation=0;const generations=new Set<string>();
 for(const l of r.lanes){
  const event=created.find((e:any)=>e.runId===l.runId);demand(event,'recovery_lane_not_created');
  const reg=jsonPin(l.registrationPin),v=verifyBenchmarkCashClosure(l.cashClosePin),s=v.proof.snapshot,j=inspectCampaignJournal(v.proof.journalDirectory);
  demand(reg.runId===l.runId&&same(reg.cashPin,v.proof.configPin)&&v.config.ownerNonce===r.owned.ownerNonce&&same(v.config.admissionPin,event.admissionPin)
   &&v.config.capUsd===event.capUsd&&s.pendingCount===0&&j.valid&&j.accountingClosed,'recovery_native_cash_not_closed');
  demand(l.billedUsd===s.billedUsd&&l.unknownCount===s.newUnknownCount&&l.unknownReservationUsd===s.unknownReservationUsd,'recovery_cost_mismatch');
  const config=jsonPin(v.config.journal.configPin);
  for(const line of readFileSync(join(v.proof.journalDirectory,'api-events.jsonl'),'utf8').trimEnd().split('\n').filter(Boolean)){
   const e=JSON.parse(line);if(e.kind!=='finish')continue;const x=e.record;
   if(x.requestId){demand(!generations.has(x.requestId),'recovery_duplicate_generation');generations.add(x.requestId);}
   if(x.costBasis==='provider_reported_usd') {const response=JSON.parse(gunzipSync(readFileSync(x.responseFile)).toString('utf8'));
    demand(response.id===x.requestId&&response.usage?.cost===x.billedCostUsd&&response.provider===config.providerName,'recovery_actual_response_cost_mismatch');}
  }
  known+=s.billedUsd;unknown+=s.newUnknownCount;reservation+=s.unknownReservationUsd;
 }
 demand(Math.abs(known-r.billedUsd)<1e-9&&unknown===r.unknownCount&&Math.abs(reservation-r.unknownReservationUsd)<1e-9,'recovery_totals');
 return{runId:r.runId,verified:true,effectiveBilledUsd:known,originalUnknownCostCount:unknown,remainingUnknownCostCount:unknown,unknownReservationUsd:reservation,originalCashUnmodified:true,financiallyResolved:unknown===0,verifiedLanes:r.lanes.length,crashedOwnerReleased:true,generationCount:generations.size,actualResponseCostsMatch:true};
}
if(import.meta.main){
 const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun'),controlPath=join(home,'control.json');
 const c=JSON.parse(readFileSync(controlPath,'utf8')),recovery=c.providerRecovery;
 demand(c.paidReady===false&&recovery.phase==='closing_crashed_digitalocean'&&recovery.oldPid===51680,'recovery_scope');
 const lockPath=join(root,'.phase1-data/owned-paid-campaign.lock.json'),owned=JSON.parse(readFileSync(lockPath,'utf8'));
 const h=JSON.parse(readFileSync(c.broker.healthPath,'utf8')),directory=dirname(c.broker.healthPath),parentPath=join(directory,'round-1/openrouter-admission.json');
 demand(same(owned,h.canonicalOwner)&&owned.pid===recovery.oldPid&&owned.runId===recovery.oldRunId&&owned.family==='four-bench-full-f-v1','foreign_owner');
 const inventory=processInventory();
 const alive=(pid:number)=>inventory.some((p:any)=>p.pid===pid&&Date.parse(p.createdAtUtc)<=Date.parse(recovery.atUtc));
 demand(!alive(owned.pid),'broker_still_alive');
 demand(!inventory.some((p:any)=>(p.commandLine??'').includes(owned.runId)),'old_lane_process_still_alive');
 for(const r of h.resourceSlots??[])demand(!alive(r.pid),'owned_resource_process_alive');
 const tbPath=join(home,'terminal-bench/private-context-v1/dead-broker-handoff.json');const tb=JSON.parse(readFileSync(tbPath,'utf8'));
 demand(tb.modelCalls===0&&tb.nativeReceipts.every((r:any)=>r.closeObserved===true&&r.exitCode!==null&&!alive(r.nativePid)),'old_terminal_native_still_active');
 const eventFiles=readdirSync(join(directory,'events')).sort(),events=eventFiles.map(f=>JSON.parse(readFileSync(join(directory,'events',f),'utf8')));
 events.forEach((e,i)=>demand(e.index===i,'broker_event_gap'));
 const created=events.filter(e=>e.kind==='lane-created'),lanes=created.map(e=>{
  const lane=h.lanes.find((l:any)=>l.runId===e.runId);demand(lane,'stale_health_missing_lane');
  const registrationPin=actualPin(join(directory,'registrations',e.runId+'.json')),reg=jsonPin(registrationPin);
  const cashClosePin=actualPin(join(dirname(reg.cashPin.path),'cash-close.json')),v=verifyBenchmarkCashClosure(cashClosePin),s=v.proof.snapshot;
  const j=inspectCampaignJournal(v.proof.journalDirectory);demand(j.valid&&j.accountingClosed&&s.pendingCount===0,'lane_not_closed');
  // Independently reject any live registered lane/engine PID.
  for(const f of readdirSync(lane.output).filter((n:string)=>/process.*\.json$|engine-.*\.json$/.test(n))){
   const p=JSON.parse(readFileSync(join(lane.output,f),'utf8').replace(/^\uFEFF/,''));
   if(Number.isInteger(p.pid))demand(!alive(p.pid),'registered_lane_process_alive');
  }
  return{slug:lane.slug,runId:e.runId,registrationPin,cashClosePin,capUsd:lane.capUsd,dispatched:events.filter(x=>x.kind==='dispatch'&&x.runId===e.runId).length,billedUsd:s.billedUsd,unknownCount:s.newUnknownCount,unknownReservationUsd:s.unknownReservationUsd,closed:true,active:0};
 });
 const out=join(home,'digitalocean-switch','dead-owner-release-'+Date.now());mkdirSync(out,{recursive:true});
 const save=(name:string,value:any)=>{const p=join(out,name);writeFileSync(p,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(p);};
 const report={protocol:'dead-broker-closed-owner-recovery-v1',atUtc:new Date().toISOString(),crashObservedAtUtc:recovery.atUtc,runId:owned.runId,owned,
  staleHealthPin:actualPin(c.broker.healthPath),parentAdmissionPin:actualPin(parentPath),sourceArchivePin:recovery.sourceArchivePin,crashPin:recovery.crashPin,
  eventsPin:save('events.json',events),processesPin:save('processes.json',inventory),resourceClosurePin:actualPin(tbPath),lanes,
  billedUsd:lanes.reduce((n:number,l:any)=>n+l.billedUsd,0),unknownCount:lanes.reduce((n:number,l:any)=>n+l.unknownCount,0),unknownReservationUsd:lanes.reduce((n:number,l:any)=>n+l.unknownReservationUsd,0),
  pendingRequests:0,originalCashUnmodified:true,unknownChargesRetained:true,scoreCertificate:false,currency:'USD',costPolicy:'record_and_continue'};
 const recoveryPin=save('recovery.json',report);verifyDeadBrokerRecovery(recoveryPin);
 demand(!processInventory().some((p:any)=>p.pid===owned.pid)&&same(JSON.parse(readFileSync(lockPath,'utf8')),owned),'owner_changed_before_release');
 unlinkSync(lockPath);const releasePin=save('owner-release.json',{protocol:'dead-owned-lock-release-v1',owned,recoveryPin,atUtc:new Date().toISOString(),canonicalOwnerAbsent:!existsSync(lockPath)});
 atomicStateJson(controlPath,{...c,brokerHistory:[...(c.brokerHistory??[]),{pid:owned.pid,runId:owned.runId,healthPath:c.broker.healthPath,sourceArchivePin:recovery.sourceArchivePin,recoveryPin,releasePin}],providerRecovery:{...recovery,phase:'dead_owner_released',recoveryPin,releasePin},updatedAtUtc:new Date().toISOString()});
 console.log(JSON.stringify({runId:owned.runId,verifiedLanes:lanes.length,knownUsd:report.billedUsd,unknown:report.unknownCount,ownerReleased:true,recoveryPath:recoveryPin.path}));
}
