import {execFileSync} from 'node:child_process';import {resolve} from 'node:path';
import {inspectZeroNewLaneState} from './zero-new-lane-state-v48.ts';
import {verifyPin,jsonPin} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {readFileSync} from 'node:fs';
import {verifyNativeResourceMapping} from './adopted-parent-v48.ts';
const demand=(v:unknown,c:string)=>{if(!v)throw Error(c)};
export async function preflightAdoption(plan:any){
 for(const p of [plan.rehydrateProofPin,plan.restartProofPin,plan.previousAdoptionGuardPin,...plan.sourcePins])verifyPin(p);const restart=jsonPin(plan.restartProofPin),previousGuard=jsonPin(plan.previousAdoptionGuardPin);demand(previousGuard.liveExecutorPid===1304&&previousGuard.directory===restart.previousDirectory&&JSON.stringify(previousGuard.signedPlanPin)===JSON.stringify(restart.previousSignedPlanPin),'exact_previous_global_adoption_guard');if(JSON.stringify(inspectZeroNewLaneState(restart.previousDirectory))!==JSON.stringify(restart))throw Error('actual_previous_durable_state_changed');
 verifyPin(plan.secondRebootObservationPin);const proof=jsonPin(plan.rehydrateProofPin);verifyNativeResourceMapping(proof);
 for(const p of [proof.canonicalLockPin,proof.parentPin,proof.allocationPin,proof.originalGlobalDelegationGuardPin,proof.historyPin,proof.nativeMappingPin,...proof.originalRetirementPins,...proof.resourceEventPins])verifyPin(p);
 const parent=jsonPin(proof.parentPin);for(const p of [...parent.sourcePins,parent.pricesPin,parent.balancePin])verifyPin(p);
 const price=jsonPin(parent.pricesPin);demand(Date.now()-Date.parse(price.observedAtUtc)>=0&&Date.now()-Date.parse(price.observedAtUtc)<86400000,'actual_price_freshness');
 const absence=JSON.parse(execFileSync('D:/ProgramData/anaconda3/python.exe',[resolve(import.meta.dir,'port-absence-v48.py')],{timeout:10000,encoding:'utf8',windowsHide:true}));demand(absence.previousExecutorAbsent&&absence.localTCPListenersAbsent&&JSON.stringify(absence.exclusiveBindPassed)==='[17889,17895]','actual_local_port_absence');
 const disk=JSON.parse(readFileSync(plan.remoteDiskObservationPath,'utf8'));demand(disk.probeExitCode===0&&disk.freeBytes>=5*1024**3&&Date.now()-disk.observedAtMs>=0&&Date.now()-disk.observedAtMs<=10000,'actual_remote_disk_floor_freshness');
 const info=await(await fetch('http://127.0.0.1:18750/info',{signal:AbortSignal.timeout(5000)})).json() as any;demand(info.ID==='dc87b6a7-ed03-4ccf-8d26-89709287b80a'&&info.DockerRootDir==='/data/wpx/tgengin/docker','actual_original_daemon_identity');
 const inventory:any[]=await(await fetch('http://127.0.0.1:18750/containers/json?all=1',{signal:AbortSignal.timeout(5000)})).json();const owned=inventory.filter(c=>c.Labels?.['objrun.tb12.owner']);demand(owned.length===proof.actualInventory.length&&owned.every(c=>proof.actualInventory.some((r:any)=>r.cid===c.Id)),'current_unmapped_owned_actor_failclosed');
 for(const row of proof.actualInventory){const r=await fetch('http://127.0.0.1:18750/containers/'+row.cid+'/json',{signal:AbortSignal.timeout(5000)});demand(r.ok,'native_hold_changed_requires_exact_signed_closure');const n:any=await r.json();demand(n.Config.Labels['objrun.tb12.owner']===row.labels['objrun.tb12.owner']&&n.Config.Labels['objrun.tb12.role']===row.labels['objrun.tb12.role'],'native_hold_identity_changed');}
 return {productionPreflight:true,originalCapUsd:proof.originalCapUsd,resourceHoldSlots:3,modelCalls:0,beforeGlobalWX:true};
}
