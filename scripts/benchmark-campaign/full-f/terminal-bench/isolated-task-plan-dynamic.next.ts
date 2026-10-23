/** Reject cross-task aliases and preserve original frozen container budgets. */
import {resolve} from 'node:path';
export function validateIsolatedJobs(manifest:any,plan:any){
 const check=(ok:unknown,code:string)=>{if(!ok)throw Error(code);};
 check(manifest.taskIds.length===89&&new Set(manifest.taskIds).size===89,'isolated_full89_required');
 check(plan.protocol==='terminal-isolated-task-plan-v1'&&plan.maximumWorkers===16,'isolated_dynamic_worker_plan_required');
 check(Array.isArray(plan.jobs)&&plan.jobs.length>0,'isolated_jobs_required');
 const ids=new Set(),paths=new Set();
 for(const job of plan.jobs){
  const task=manifest.records.find((t:any)=>t.taskId===job.taskId);
  check(task&&!ids.has(job.taskId),'isolated_task_unique_required');ids.add(job.taskId);
  const path=resolve(job.readinessPin.path);check(!paths.has(path),'isolated_readiness_unique_required');paths.add(path);
  check(job.originalPlannedGrowthBytes===task.officialEnvironment.storage_mb*1024**2,'isolated_original_storage_required');
  check(job.originalPeakMemoryMb===Math.max(4096,2*task.officialEnvironment.memory_mb),'isolated_candidate_and_grader_peak_required');
 }
 return plan.jobs;
}
