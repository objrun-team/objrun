/** Controlled retirement after drained child exited without an ephemeral lane token. Never claims normal RPC closure. */
import {readFileSync,writeFileSync,mkdirSync,existsSync,readdirSync,unlinkSync} from 'node:fs';
import {join,dirname,resolve} from 'node:path';
import {gunzipSync} from 'node:zlib';
import {actualPin,jsonPin,verifyPin,same} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifyBenchmarkCashClosure} from './digitalocean-usd-cash.ts';
import {inspectCampaignJournal} from './digitalocean-journal.ts';
import {atomicStateJson} from './atomic-state.ts';
function demand(v:unknown,s:string):asserts v{if(!v)throw Error(s);}
const inventory=()=>{const r=Bun.spawnSync(['powershell.exe','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | ForEach-Object { @{pid=$_.ProcessId;createdAtUtc=$_.CreationDate.ToUniversalTime().ToString('o');commandLine=$_.CommandLine} }) | ConvertTo-Json -Compress"]);demand(r.exitCode===0,'process_inventory');return JSON.parse(r.stdout.toString());};
export function verifyControlledBrokerRecovery(pin:any){
 const r=jsonPin(pin),h=jsonPin(r.originalHealthPin),parent=jsonPin(r.parentAdmissionPin),archive=jsonPin(r.sourceArchivePin),events=jsonPin(r.eventsPin),processes=jsonPin(r.exitedProcessesPin);
 demand(r.protocol==='controlled-drained-broker-recovery-v1'&&r.originalCashUnmodified&&r.pendingRequests===0&&r.actualBrokerRpcClosure===false,'controlled_recovery_protocol');
 demand(h.dispatchPaused&&h.activeRequests===0&&h.queuedRequests===0&&h.resourceSlots.length===0&&same(h.canonicalOwner,parent.owned)&&same(r.owned,parent.owned),'controlled_original_drain_identity');
 verifyPin(r.preparedProcessesPin);const before=jsonPin(r.preparedProcessesPin);
 demand(before.some((p:any)=>p.pid===r.owned.pid&&(p.commandLine??'').includes('digitalocean-broker-600.ts')),'controlled_original_owner_process');
 demand(r.owned.family==='four-bench-full-f-v1'&&r.owned.currency==='USD'&&r.owned.pid===41512&&r.owned.runId==='repair-2026-10-10T17-44-07-359Z','controlled_campaign_scope');
 demand(!processes.some((p:any)=>p.pid===r.owned.pid&&Date.parse(p.createdAtUtc)<=Date.parse(r.preparedAtUtc)),'controlled_owner_still_alive');
 for(const p of parent.sourcePins){const row=archive.pins.find((x:any)=>same(x.original,p));demand(row,'controlled_source_missing');verifyPin(row.archived);demand(row.archived.sha256===p.sha256&&row.archived.bytes===p.bytes,'controlled_source_archive');}
 demand(events.filter((e:any)=>e.kind==='lane-created').length===r.lanes.length&&h.lanes.length===r.lanes.length,'controlled_complete_lanes');
 const generations=new Set<string>();let known=0,unknown=0,reserve=0;
 for(const l of r.lanes){
  const e=events.find((e:any)=>e.kind==='lane-created'&&e.runId===l.runId),reg=jsonPin(l.registrationPin),v=verifyBenchmarkCashClosure(l.cashClosePin),s=v.proof.snapshot,j=inspectCampaignJournal(v.proof.journalDirectory);
  demand(e&&reg.runId===l.runId&&same(reg.cashPin,v.proof.configPin)&&v.config.ownerNonce===r.owned.ownerNonce&&same(v.config.admissionPin,e.admissionPin)&&v.config.capUsd===e.capUsd&&s.pendingCount===0&&j.valid&&j.accountingClosed,'controlled_native_cash_binding');
  demand(l.billedUsd===s.billedUsd&&l.unknownCount===s.newUnknownCount&&l.unknownReservationUsd===s.unknownReservationUsd,'controlled_cost_binding');
  const cfg=jsonPin(v.config.journal.configPin);
  for(const line of readFileSync(join(v.proof.journalDirectory,'api-events.jsonl'),'utf8').trimEnd().split('\n').filter(Boolean)){
   const ev=JSON.parse(line);if(ev.kind!=='finish')continue;const rec=ev.record;
   if(rec.requestId){demand(!generations.has(rec.requestId),'controlled_duplicate_generation');generations.add(rec.requestId);}
   if(rec.costBasis==='provider_reported_usd'){const b=JSON.parse(gunzipSync(readFileSync(rec.responseFile)).toString('utf8'));demand(b.id===rec.requestId&&b.usage?.cost===rec.billedCostUsd&&b.provider===cfg.providerName,'controlled_actual_usage_cost');}
  }
  known+=s.billedUsd;unknown+=s.newUnknownCount;reserve+=s.unknownReservationUsd;
 }
 demand(Math.abs(known-r.billedUsd)<1e-9&&unknown===r.unknownCount&&Math.abs(reserve-r.unknownReservationUsd)<1e-9,'controlled_sum');
 return{runId:r.owned.runId,verified:true,effectiveBilledUsd:known,originalUnknownCostCount:unknown,remainingUnknownCostCount:unknown,unknownReservationUsd:reserve,originalCashUnmodified:true,verifiedLanes:r.lanes.length,generationCount:generations.size,actualResponseCostsMatch:true,controlledOwnerRecovery:true,actualBrokerRpcClosure:false,financiallyResolved:unknown===0};
}
if(import.meta.main){
 const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun'),cp=join(home,'control.json'),c=JSON.parse(readFileSync(cp,'utf8')),out=join(home,'chembench-stream-switch','controlled-41512');mkdirSync(out,{recursive:true});
 const save=(n:string,v:any)=>{const p=join(out,n);writeFileSync(p,JSON.stringify(v,null,2)+'\n',{flag:'wx'});return actualPin(p);};
 const path=join(root,'.phase1-data/owned-paid-campaign.lock.json');
 if(process.argv[2]==='--prepare'){
  demand(c.paidReady===false&&c.broker.pid===41512&&c.broker.runId==='repair-2026-10-10T17-44-07-359Z','controlled_scope');
  const h=JSON.parse(readFileSync(c.broker.healthPath,'utf8')),owned=JSON.parse(readFileSync(path,'utf8'));
  demand(h.pid===41512&&h.dispatchPaused&&!h.activeRequests&&!h.queuedRequests&&!h.resourceSlots.length&&same(owned,h.canonicalOwner)&&Date.now()-Date.parse(h.atUtc)<30000,'controlled_not_drained');
  const events=readdirSync(join(dirname(c.broker.healthPath),'events')).sort().map(n=>JSON.parse(readFileSync(join(dirname(c.broker.healthPath),'events',n),'utf8')));events.forEach((e,i)=>demand(e.index===i,'controlled_event_gap'));
  const processes=inventory();demand(processes.some((p:any)=>p.pid===41512&&(p.commandLine??'').includes('digitalocean-broker-600.ts')),'controlled_exact_live_broker');
  const lanes=h.lanes.map((l:any)=>{const registrationPin=actualPin(join(dirname(c.broker.healthPath),'registrations',l.runId+'.json')),reg=jsonPin(registrationPin),cashClosePin=actualPin(join(dirname(reg.cashPin.path),'cash-close.json')),v=verifyBenchmarkCashClosure(cashClosePin),j=inspectCampaignJournal(v.proof.journalDirectory),s=v.proof.snapshot;
   demand(s.pendingCount===0&&j.valid&&j.accountingClosed,'controlled_lane_not_native_closed');
   for(const f of readdirSync(l.output).filter((n:string)=>/parent-process\.json$|engine-.*process\.json$|engine-\d+-\d+\.json$/.test(n))){const m=JSON.parse(readFileSync(join(l.output,f),'utf8'));if(Number.isInteger(m.pid))demand(!processes.some((p:any)=>p.pid===m.pid&&Date.parse(p.createdAtUtc)<=Date.parse(m.createdAtUtc??m.atUtc??h.atUtc)),'controlled_registered_process_alive');}
   return{runId:l.runId,slug:l.slug,registrationPin,cashClosePin,billedUsd:s.billedUsd,unknownCount:s.newUnknownCount,unknownReservationUsd:s.unknownReservationUsd};});
  const pins=c.broker.sourcePins.map((p:any,i:number)=>{verifyPin(p);const archivePath=join(out,'source-'+i+'.ts');writeFileSync(archivePath,readFileSync(p.path),{flag:'wx'});return{original:p,archived:actualPin(archivePath)};});
  const prepared={preparedAtUtc:new Date().toISOString(),owned,originalHealthPin:save('original-health.json',h),parentAdmissionPin:actualPin(join(dirname(c.broker.healthPath),'round-'+h.round,'openrouter-admission.json')),sourceArchivePin:save('source-archive.json',{pins}),eventsPin:save('events.json',events),preparedProcessesPin:save('prepared-processes.json',processes),lanes,billedUsd:lanes.reduce((n:number,l:any)=>n+l.billedUsd,0),unknownCount:lanes.reduce((n:number,l:any)=>n+l.unknownCount,0),unknownReservationUsd:lanes.reduce((n:number,l:any)=>n+l.unknownReservationUsd,0)};
  save('prepared.json',prepared);console.log(JSON.stringify({prepared:true,oldPid:41512,pending:0,resources:0,nativeCashLanes:lanes.length}));
 }else if(process.argv[2]==='--finish'){
  const prepared=JSON.parse(readFileSync(join(out,'prepared.json'),'utf8')),processes=inventory();
  const r={...prepared,protocol:'controlled-drained-broker-recovery-v1',atUtc:new Date().toISOString(),exitedProcessesPin:save('exited-processes.json',processes),originalCashUnmodified:true,pendingRequests:0,actualBrokerRpcClosure:false,reason:'drained child exited without ephemeral lane token; broker intentionally stopped after native cash/resource closure',scoreCertificate:false};
  const recoveryPin=save('recovery.json',r),v=verifyControlledBrokerRecovery(recoveryPin);save('verification.json',v);
  demand(!inventory().some((p:any)=>p.pid===41512&&Date.parse(p.createdAtUtc)<=Date.parse(prepared.preparedAtUtc))&&same(JSON.parse(readFileSync(path,'utf8')),prepared.owned),'controlled_owner_changed');unlinkSync(path);
  const releasePin=save('owner-release.json',{protocol:'controlled-owned-lock-release-v1',owned:prepared.owned,recoveryPin,canonicalOwnerAbsent:!existsSync(path),atUtc:new Date().toISOString()});
  atomicStateJson(cp,{...c,brokerHistory:[...c.brokerHistory,{pid:41512,runId:prepared.owned.runId,healthPath:c.broker.healthPath,controlledRecoveryPin:recoveryPin,releasePin}],chembenchStreamSwitch:{...c.chembenchStreamSwitch,phase:'controlled_old_owner_released',recoveryPin,releasePin},updatedAtUtc:new Date().toISOString()});console.log(JSON.stringify({released:true,verified:true,lanes:v.verifiedLanes,knownUsd:v.effectiveBilledUsd,unknown:v.remainingUnknownCostCount}));
 }else throw Error('prepare_or_finish_required');
}
