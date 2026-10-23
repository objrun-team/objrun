/** Per-process, per-task claim for the root-authorized parallel container pool. */
import {fullFConnection} from './supplier-shared-admission.ts';
import {verifyPin,type Pin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
export async function acquireContainerTaskResource(root:string,slug:'skillsbench'|'terminal-bench',plan:{taskId:string;planPin:Pin;originalPlannedGrowthBytes:number;originalPeakMemoryMb:number}){
 verifyPin(plan.planPin);
 if(!plan.taskId||!Number.isSafeInteger(plan.originalPlannedGrowthBytes)||plan.originalPlannedGrowthBytes<0||!Number.isSafeInteger(plan.originalPeakMemoryMb)||plan.originalPeakMemoryMb<(slug==='skillsbench'?8192:4096))throw Error('original_task_resource_plan_required');
 const c=fullFConnection(root),body={slug,kind:'heavy-container',pid:process.pid,slots:1,memoryMb:plan.originalPeakMemoryMb,plannedGrowthBytes:plan.originalPlannedGrowthBytes};
 const request=async(path:string,value:any)=>{const r=await fetch(c.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+c.accessToken,'content-type':'application/json'},body:JSON.stringify(value)});const v=await r.json() as any;if(!r.ok)throw Object.assign(new Error(v.reason??v.error??'resource_admission_failed'),{status:r.status,waiting:v.waiting});return v;};
 const claim=await request('/resource/acquire',body);let released=false;
 return {taskId:plan.taskId,pid:process.pid,kind:body.kind,originalPlanPin:plan.planPin,async release(){if(released)throw Error('resource_already_released');await request('/resource/release',{...body,token:claim.token});released=true;}};
}
