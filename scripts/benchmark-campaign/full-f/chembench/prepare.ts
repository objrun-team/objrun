import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { digest, fixedScientificPlan } from '../../../benchmark-repair/scientific-journal-plan.ts';
import { BENCHMARK_INFERENCE } from '../../../benchmark-repair/benchmark-inference.ts';
import { BENCHMARK_PROVIDER } from '../../../benchmark-repair/benchmark-provider.ts';
export const ROOT=resolve(import.meta.dir,'../../../..');
export const OUT=join(ROOT,'docs/repair-2026-10-10/full-f-rerun/chembench');
export const save=(name:string,value:unknown)=>{mkdirSync(OUT,{recursive:true});writeFileSync(join(OUT,name),JSON.stringify(value,null,2)+'\n');};
export function makePlan(campaign:string){
  const paired=fixedScientificPlan(ROOT,campaign,'full',['chembench']);
  const tasks=paired.tasks.filter(t=>t.arm==='F').map((t,index)=>({...t,index}));
  const schedule=tasks.map(({index,benchmark,arm,replica,officialId,promptSha256})=>({index,benchmark,arm,replica,officialId,promptSha256}));
  if(tasks.length!==500||new Set(tasks.map(t=>t.officialId)).size!==500)throw Error('Full F denominator differs');
  return {...paired,tasks,taskSchedule:schedule,taskScheduleSha256:digest(JSON.stringify(schedule))};
}
export function prepare(){
  mkdirSync(OUT,{recursive:true});
  let campaign:string;try{campaign=JSON.parse(readFileSync(join(OUT,'manifest.json'),'utf8')).campaign;}catch{campaign='repair-'+new Date().toISOString().replace(/[:.]/g,'-');}
  const plan=makePlan(campaign);
  const manifest={protocol:'chembench-full-f-v1',campaign,createdAt:new Date().toISOString(),arms:['F'],plannedTaskRuns:500,
    taskSchedule:plan.taskSchedule,taskScheduleSha256:plan.taskScheduleSha256,datasets:plan.datasets,model:BENCHMARK_PROVIDER.model,
    providerSlug:BENCHMARK_PROVIDER.providerSlug,providerRouting:BENCHMARK_PROVIDER.routing,inference:BENCHMARK_INFERENCE,
    solveSeconds:600,checks:5,maxBranches:4,maxDeadSiblings:100000,cyclesMaxUnits:12,feedbackLevel:1,
    allowedTools:['submit','verify','task_tree','node_load'],search:'disabled',perBenchMaxInFlight:2,currency:'USD',
    fullMeaning:'Entire existing pinned 500-task scientific-journal-plan cohort, not all 2785 upstream tasks',
    denominatorPolicy:'All 500 frozen IDs retained including failures/timeouts/infrastructure errors',
    publicU:'Reference only; no U calls; see public-u.json',providerForwardingEnabled:false};
  save('manifest.json',manifest);save('public-tasks.json',plan.catalogs.chembench);
  save('status.json',{stage:'preparing',planned:500,completed:0,graded:0,actualCostUsd:0,modelCalls:0,updatedAt:new Date().toISOString(),
    sharedNeeds:['control.json paidReady and broker/client contract providing journal, USD cash and canonical owner child lane; never acquire own canonical lock'],
    codex:{model:'gpt-6.1-sol',effort:'medium',configServiceTier:'default',turnContextServiceTier:null,fastEnabled:false}});
  return {campaign,planned:500,scheduleSha256:manifest.taskScheduleSha256,output:OUT};
}
if(import.meta.main)console.log(JSON.stringify(prepare()));
