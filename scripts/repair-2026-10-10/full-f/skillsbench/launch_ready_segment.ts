/** Detached task-gated segment launcher. Observe busy slots without acquiring. */
import { existsSync,readFileSync,writeFileSync,openSync,closeSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { actualPin,verifyPin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { validateRuntimeReadiness } from './runtime.ts';
import { loadContinuation } from './resume.ts';
import { atomicStateJson } from '../shared/atomic-state.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const proof=actualPin(join(home,'runtime-readiness.json'));
validateRuntimeReadiness(read(join(home,'manifest.json')),read(proof.path));
const statePath=join(home,'ready-segment-launch.json');
const record=(value:any)=>atomicStateJson(statePath,{pid:process.pid,readinessPin:proof,denominator:87,atUtc:new Date().toISOString(),...value});
let failures=0;
for(;;){
const continuation=loadContinuation(home,read(join(home,'manifest.json')));
if(!continuation.pending.some(r=>read(proof.path).taskReadiness[r.taskId])){record({phase:'ready_tasks_exhausted_pending_preparation',remaining:continuation.pending.length,formalCompleted:continuation.records.length});break;}
record({phase:'waiting_for_digitalocean_broker_and_heavy_slot',modelCalls:0});
for(;;){
  verifyPin(proof);const control=read(join(home,'../control.json'));
  const health=read(control.broker.healthPath);
  const freeSlots=health.availableResourceSlots?.['heavy-container']??0;
  const usedMemory=(health.resourceSlots??[]).filter((r:any)=>r.kind==='heavy-container').reduce((n:number,r:any)=>n+r.memoryMb,0);
  const freeMemory=(health.heavyMemoryMb??0)-usedMemory;
  const providerSlug=typeof control.provider==='string'?control.provider:control.provider?.slug;
  if(providerSlug==='digitalocean'&&control.paidReady&&health.healthy&&Date.now()-Date.parse(health.atUtc)<30000&&freeSlots>=1&&freeMemory>=8192)break;
  await Bun.sleep(30000);
}
verifyPin(proof);
const stdout=openSync(join(home,'ready-segment.stdout'),'a'),stderr=openSync(join(home,'ready-segment.stderr'),'a');
try{
  const child=spawn(process.execPath,[join(import.meta.dir,'entry.ts'),'run'],{cwd:root,windowsHide:true,stdio:['ignore',stdout,stderr]});
  record({phase:'runtime_dispatched',runtimePid:child.pid,modelCalls:null});
  const exitCode=await new Promise<number|null>(ok=>child.once('exit',ok));
  record({phase:exitCode===0?'segment_finished':'segment_failed',runtimePid:child.pid,exitCode});
  failures=exitCode===0?0:failures+1;
  if(!['segment_closed_pending_continuation','finished_pending_full_audit'].includes(read(join(home,'status.json')).phase)){process.exitCode=exitCode??1;break;}
  if(failures>=3){record({phase:'provider_fault_backoff_to_heartbeat',consecutiveFailedSegments:failures});break;}
}finally{closeSync(stdout);closeSync(stderr);}
await Bun.sleep(30000);
}
