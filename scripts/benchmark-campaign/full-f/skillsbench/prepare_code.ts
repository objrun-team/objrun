/** Zero-model code adapter preparation, one shared-resource claim only. */
import { spawn } from 'node:child_process';
import { readFileSync,writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { acquireFullFResource } from '../shared/shared-admission.ts';
import { acquirePreparationResource } from './preparation_resource.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench'),taskId='crystallographic-wyckoff-position-analysis';
function read(path:string){return JSON.parse(readFileSync(path,'utf8'));}
function status(update:any){const path=join(home,'status.json');writeFileSync(path,JSON.stringify({...read(path),...update,updatedAtUtc:new Date().toISOString()},null,2)+'\n');}
let heavy:Awaited<ReturnType<typeof acquireFullFResource>>|undefined;
try{
  heavy=await acquirePreparationResource(root);
  status({phase:'preparing',codePreparation:{taskId,pid:process.pid,stage:'three_namespace_build_and_native_controls',modelCalls:0}});
  for(const script of process.argv.includes('--refresh-only')?['verify_native_refresh.py','verify_refresh.py']:['build_code_environment.py','code_controls.py']){
    const child=spawn('python',['-B',join(import.meta.dir,script)],{cwd:root,windowsHide:true,stdio:'inherit'});
    const code=await new Promise<number>((ok,bad)=>{child.once('error',bad);child.once('exit',n=>ok(n??1));});if(code!==0)throw Error(script+' failed with exit '+code);
  }
  status({codePreparation:{taskId,pid:process.pid,stage:'actual_native_controls_complete',modelCalls:0}});
}catch(error){
  let owner:any;try{const c=read(join(home,'../control.json')),h=read(c.broker.healthPath),r=h.resources?.['heavy-container'];if(r)owner={slug:r.slug,pid:r.pid};}catch{}
  status({phase:owner&&owner.slug!=='skillsbench'?'queued':'preparing',codePreparation:{taskId,pid:process.pid,stage:owner&&owner.slug!=='skillsbench'?'resource_queued':'preparation_failed',resourceOwner:owner,error:error instanceof Error?error.message:String(error),modelCalls:0}});process.exitCode=2;
}finally{if(heavy)await heavy.release();}
