/** Actual pinned readiness joins; no Docker/model/admission actions. */
import { readFileSync,writeFileSync,mkdirSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { actualPin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { validateRuntimeReadiness } from './runtime.ts';
const home=resolve(import.meta.dir,'../../../../docs/repair-2026-10-10/full-f-rerun/skillsbench');
const read=(n:string)=>JSON.parse(readFileSync(join(home,n),'utf8'));
const manifest=read('manifest.json'),ready=read('runtime-readiness.json'),cases:string[]=[];
validateRuntimeReadiness(manifest,ready);cases.push('actual_current_ready_controls_with_full87_scope');
for(const [name,change] of [
  ['empty_ready_denied',(r:any)=>r.taskReadiness={}],
  ['foreign_ready_denied',(r:any)=>r.taskReadiness.foreign=Object.values(r.taskReadiness)[0]],
  ['false_full87_claim_denied',(r:any)=>r.full87Validated=true],
  ['unproven_control_denied',(r:any)=>Object.values<any>(r.taskReadiness)[0].controlPin.sha256='0'.repeat(64)],
] as const){const changed=structuredClone(ready);change(changed);let rejected=false;try{validateRuntimeReadiness(manifest,changed);}catch{rejected=true;}if(!rejected)throw Error(name);cases.push(name);}
const dir=join(home,'task-gate-controls',randomUUID());mkdirSync(dir,{recursive:true});
const path=join(dir,'result.json');writeFileSync(path,JSON.stringify({protocol:'skillsbench-full-f-task-gate-controls-v1',verified:true,cases,denominator:87,readyTaskIds:Object.keys(ready.taskReadiness),modelCalls:0,DockerMutations:0,formalScoreCertified:false,sourcePins:['runtime.ts','entry.ts','verify_task_gate.ts'].map(n=>actualPin(join(import.meta.dir,n)))},null,2)+'\n');
writeFileSync(join(home,'task-gate-controls/latest.json'),JSON.stringify({resultPin:actualPin(path)})+'\n');console.log(JSON.stringify({verified:true,cases,readyTaskIds:Object.keys(ready.taskReadiness),denominator:87}));
