/** Prepare the next reviewed task. Full denominator is retained; no models. */
import { readFileSync,existsSync,writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { actualPin,verifyPin,jsonPin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { acquireFullFResource } from '../shared/shared-admission.ts';
import { acquirePreparationResource } from './preparation_resource.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
function read(path:string){return JSON.parse(readFileSync(path,'utf8'));}
function status(update:any){const path=join(home,'status.json');writeFileSync(path,JSON.stringify({...read(path),...update,updatedAtUtc:new Date().toISOString()},null,2)+'\n');}
const inventory=read(join(home,'artifact-policy-inventory.json'));if(inventory.denominator!==87)throw Error('full87_scope_drift');
const requestedIndex=process.argv.indexOf('--task'),requested=requestedIndex<0?undefined:process.argv[requestedIndex+1];
if(requestedIndex>=0&&!inventory.rows.some((row:any)=>row.taskId===requested&&row.policyReviewed))throw Error('explicit_reviewed_task_required');
const next=inventory.rows.find((row:any)=>{
  if(requested&&row.taskId!==requested)return false;
  if(!row.policyReviewed)return false;
  const runnerPin=actualPin(join(import.meta.dir,row.taskId==='civ6-adjacency-optimizer'?'private_eval_score.py':['files','directory'].includes(row.policy.kind)||row.taskId==='lab-unit-harmonization'?'private_eval_multi.py':row.taskId==='3d-scan-calc'?'private_eval.py':'private_eval_v2.py'));
  const path=join(home,'grader-controls',row.taskId,'latest.json');if(!existsSync(path))return true;
  try{const cp=read(path).controlPin;verifyPin(cp);const c=jsonPin(cp);verifyPin(c.builtImagesPin);const b=jsonPin(c.builtImagesPin);return !c.controlsPassed||b.privateRunnerSourcePin.sha256!==runnerPin.sha256;}catch{return true;}
});
if(!next){status({phase:'preparing',nextAction:requested?`Requested task ${requested} already has source-current controls; no preparation launched.`:`All ${inventory.reviewedPolicyCount} reviewed policies have controls; ${inventory.policiesPending} policies and full isolation/runtime checks remain pending.`});process.exit(0);}
let heavy:Awaited<ReturnType<typeof acquireFullFResource>>|undefined;
try{
  heavy=await acquirePreparationResource(root);
  status({phase:'preparing',environmentPreparation:{taskId:next.taskId,pid:process.pid,stage:'next_source_bound_environment_and_controls',modelCalls:0}});
  for(const script of ['recover_build_container.py','build_environment.py','grade_controls.py']){
    const child=spawn('python',['-B',join(import.meta.dir,script),'--task',next.taskId],{cwd:root,windowsHide:true,stdio:'inherit'});
    const code=await new Promise<number>((ok,bad)=>{child.once('error',bad);child.once('exit',n=>ok(n??1));});
    if(code!==0)throw Error(script+' failed with exit '+code);
  }
  status({environmentPreparation:{taskId:next.taskId,pid:process.pid,stage:'actual_grader_controls_complete',modelCalls:0}});
}catch(error){
  let owner:any;try{const c=read(join(home,'../control.json')),h=read(c.broker.healthPath),r=h.resources?.['heavy-container'];if(r)owner={slug:r.slug,pid:r.pid};}catch{}
  const resourceQueued=!heavy&&owner&&owner.slug!=='skillsbench';
  status({phase:resourceQueued?'queued':'preparing',environmentPreparation:{taskId:next.taskId,pid:process.pid,stage:resourceQueued?'resource_queued':'preparation_failed',error:error instanceof Error?error.message:String(error),resourceOwner:owner,resourceWasAcquired:!!heavy,modelCalls:0}});process.exitCode=2;
}finally{if(heavy)await heavy.release();}
