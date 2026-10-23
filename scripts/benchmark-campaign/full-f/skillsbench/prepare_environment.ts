/** Resource-coordinated zero-model environment build. A 409 is a queue state. */
import { spawn } from 'node:child_process';
import { readFileSync,writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { acquireFullFResource } from '../shared/shared-admission.ts';
import { acquirePreparationResource } from './preparation_resource.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
const task=process.argv[2]??'3d-scan-calc';
const controlsOnly=process.argv.includes('--controls-only');
const refreshOnly=process.argv.includes('--refresh-only');
const status=(update:any)=>{const path=join(home,'status.json'),old=JSON.parse(readFileSync(path,'utf8'));writeFileSync(path,JSON.stringify({...old,...update,updatedAtUtc:new Date().toISOString()},null,2)+'\n');};
let heavy:Awaited<ReturnType<typeof acquireFullFResource>>|undefined;
try {
  heavy=await acquirePreparationResource(root);
  status({phase:'preparing',sharedPaidReady:true,blockers:['full_87_ordinary_artifact_and_private_grader_generalization_pending'],environmentPreparation:{taskId:task,pid:process.pid,stage:'building_original_and_private_images',modelCalls:0}});
  const child=spawn('python',['-B',join(import.meta.dir,refreshOnly?'verify_refresh.py':controlsOnly?'grade_controls.py':'build_environment.py'),...(refreshOnly?[]:['--task',task])],{cwd:root,windowsHide:true,stdio:'inherit'});
  const code=await new Promise<number>((ok,bad)=>{child.once('error',bad);child.once('exit',n=>ok(n??1));});
  status({environmentPreparation:{taskId:task,pid:process.pid,childPid:child.pid,stage:code===0?(refreshOnly?'same_run_refresh_controls_complete':controlsOnly?'actual_grader_controls_complete':'images_built_cold_controls_pending'):'preparation_failed',exitCode:code,modelCalls:0}});
  process.exitCode=code;
} catch(error) {
  const message=error instanceof Error?error.message:String(error);
  // Current shared adapter reports a generic broker_rpc_failed on 409. Join its
  // latest health snapshot to classify queue state without claiming the slot
  // again, and never include its private resource token in Bench output.
  let resourceOwner:any;
  try {const control=JSON.parse(readFileSync(join(home,'../control.json'),'utf8'));const health=JSON.parse(readFileSync(control.broker.healthPath,'utf8'));const owner=health.resources?.['heavy-container'];if(owner)resourceOwner={slug:owner.slug,pid:owner.pid};}catch{}
  status({phase:resourceOwner?.slug!=='skillsbench'&&resourceOwner?'queued':'preparing',sharedPaidReady:true,environmentPreparation:{taskId:task,pid:process.pid,stage:resourceOwner?'resource_queued':'preparation_failed',resourceOwner,error:message,modelCalls:0}});
  console.error(message);process.exitCode=2;
} finally {if(heavy)await heavy.release();}
