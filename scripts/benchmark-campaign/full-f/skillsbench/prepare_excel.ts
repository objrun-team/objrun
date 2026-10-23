/** Standalone isolated Excel preparation. One shared claim; no paid lane. */
import {spawn} from 'node:child_process';
import {readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {acquirePreparationResource} from './preparation_resource.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench'),task=process.argv[2];
if(!['weighted-gdp-calc','reserves-at-risk-calc','shock-analysis-demand'].includes(task))throw Error('explicit_excel_task_required');
function status(update:any){const path=join(home,'status.json');writeFileSync(path,JSON.stringify({...JSON.parse(readFileSync(path,'utf8')),...update,updatedAtUtc:new Date().toISOString()},null,2)+'\n');}
let resource:Awaited<ReturnType<typeof acquirePreparationResource>>|undefined;
try{
 resource=await acquirePreparationResource(root);status({excelPreparation:{taskId:task,pid:process.pid,stage:'isolated_conversion_build_and_original_controls',modelCalls:0}});
 for(const script of ['build_excel_conversion.py','excel_controls.py']){
  const child=spawn('python',['-B',join(import.meta.dir,script),'--task',task],{cwd:root,windowsHide:true,stdio:'inherit'});
  const code=await new Promise<number>((ok,bad)=>{child.once('error',bad);child.once('exit',n=>ok(n??1));});if(code!==0)throw Error(script+' failed with exit '+code);
 }
 status({excelPreparation:{taskId:task,pid:process.pid,stage:'actual_excel_controls_complete',modelCalls:0}});
}catch(error){status({excelPreparation:{taskId:task,pid:process.pid,stage:resource?'preparation_failed':'resource_queued',error:String(error),modelCalls:0}});process.exitCode=2;}
finally{if(resource)await resource.release();}
