/** Default draft; --execute requires the original sole broker lease. No models. */
import {spawn} from 'node:child_process';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,demand} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
import {acquireContainerTaskResource} from '../../shared/container-task-resource.ts';
const args=process.argv.slice(2),value=(key:string)=>{const i=args.indexOf(key);return i<0?undefined:args[i+1];};
const task=value('--task'),outputArg=value('--output'),stage=value('--stage')??'build';
demand(task&&['fix-visual-stability','multilingual-video-dubbing','reserves-at-risk-calc'].includes(task),'owned_task_required');
demand(outputArg&&['build','collection','controls','stand','draft'].includes(stage),'explicit_output_and_stage_required');
const root=resolve(import.meta.dir,'../../../../..'),output=resolve(outputArg!);mkdirSync(output,{recursive:true});
const descriptor=JSON.parse(readFileSync(join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench/task-descriptors',task+'.json'),'utf8'));
const e=descriptor.originalResources.environment;
const plan={protocol:'group01-adapter2-native-preparation-plan-v1',taskId:task,stage,modelCalls:0,published:false,readyRegistered:false,
 originalPeakMemoryMb:Math.max(8192,2*e.memory_mb),originalPlannedGrowthBytes:e.storage_mb*1024**2,
 sourcePins:['../adapter2_20261013_v1.py','../pipeline_adapter2_20261013_v1.py','../stand_contract_adapter2_20261013_v1.py','../data_stand_adapter2_20261013_v1.py','../runtime_private_task_adapter2_20261013_v1.ts','private_task_worker_entry_adapter2_20261013_v1.ts','draft_publication_adapter2_20261013_v1.ts'].map(n=>actualPin(join(import.meta.dir,n))),
 originalResources:descriptor.originalResources,oracleExecutionRequested:args.includes('--allow-original-oracle-once'),
 resourcePlan:'two live original-memory containers; original signed task storage growth ceiling with shared image layers; stopped controls never run concurrently'};
const planPath=join(output,'preparation-plan-'+crypto.randomUUID()+'.json');writeFileSync(planPath,JSON.stringify(plan,null,2),{flag:'wx'});
if(!args.includes('--execute')){console.log(JSON.stringify({draftPlanPin:actualPin(planPath),modelCalls:0,dockerActions:0,registered:false}));}
else{
 const lease=await acquireContainerTaskResource(root,'skillsbench',{taskId:task!,planPin:actualPin(planPath),originalPeakMemoryMb:plan.originalPeakMemoryMb,originalPlannedGrowthBytes:plan.originalPlannedGrowthBytes});
 const run=async(command:string,argv:string[])=>{
   const child=spawn(command,argv,{cwd:root,windowsHide:true,stdio:['ignore','inherit','inherit'],env:{...process.env,PYTHONIOENCODING:'utf-8'}});
   const code=await new Promise<number>((ok,bad)=>{child.once('error',bad);child.once('exit',n=>ok(n??1));});
   demand(code===0,'native_preparation_child_failed');
 };
 try{
   if(stage==='draft')await run(process.execPath,[join(import.meta.dir,'draft_publication_adapter2_20261013_v1.ts'),join(output,'controls.json'),join(output,'publication-draft-'+crypto.randomUUID()),...(value('--inputs')?['--inputs',resolve(value('--inputs')!)]:[])]);
   else if(stage==='stand')await run('D:/ProgramData/anaconda3/python.exe',['-B',join(import.meta.dir,'../stand_contract_adapter2_20261013_v1.py'),'--task',task!,'--output',output,'--resource-owner-pid',String(process.pid)]);
   else await run('D:/ProgramData/anaconda3/python.exe',['-B',join(import.meta.dir,'../pipeline_adapter2_20261013_v1.py','../stand_contract_adapter2_20261013_v1.py'),'--task',task!,'--output',output,'--resource-owner-pid',String(process.pid),'--stage',stage,...(args.includes('--allow-original-oracle-once')?['--allow-original-oracle-once']:[])]);
 }finally{await lease.release();}
}
