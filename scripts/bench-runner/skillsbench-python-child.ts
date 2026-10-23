/** Explicit Python children share one original SkillsBench lease and signed policy mapping. */
import {readFileSync} from 'node:fs';import{resolve,join}from'node:path';
import{observedSpawn}from'./observed-spawn.ts';import{verifyPin,demand}from'./manifest.ts';
export async function runSkillsBenchPythonChild(binding:any,entry:any,args:string[],root:string,timeoutMs:number){
 for(const p of [binding.pythonPin,binding.pythonBootstrap.bootstrapPin,binding.pythonBootstrap.configPin,entry])verifyPin(p);
 const config=JSON.parse(readFileSync(binding.pythonBootstrap.configPin.path,'utf8'));
 demand([config.originalStandPin,...(config.allowedEntryPins??[])].some((p:any)=>resolve(p.path)===resolve(entry.path)&&p.sha256===entry.sha256),'single_task_approved_python_child');
 const argv=['-B','-X','utf8',binding.pythonBootstrap.bootstrapPin.path,'--config',binding.pythonBootstrap.configPin.path,'--original-script',entry.path,'--',...args];
 const child=observedSpawn(binding.pythonPin.path,argv,{cwd:root,env:{...process.env},windowsHide:true,stdio:['ignore','pipe','pipe']});
 const out:Buffer[]=[],err:Buffer[]=[];let captured=0,fault:any,timedOut=false;const capture=(target:Buffer[],b:Buffer)=>{captured+=b.length;if(captured>4*1024**2){fault='single_task_python_capture_bound';child.kill();return}target.push(b)};child.stdout?.on('data',b=>capture(out,b));child.stderr?.on('data',b=>capture(err,b));child.on('error',e=>fault=String(e));
 const timer=setTimeout(()=>{timedOut=true;child.kill()},Math.max(1,timeoutMs));let code:number|null;
 try{code=await new Promise<number|null>(ok=>child.on('close',ok))}finally{clearTimeout(timer)}
 demand(code===0&&!fault&&!timedOut,'single_task_python_child_failed:'+Buffer.concat(err).toString().slice(-4096));
 return{pid:child.pid,exitCode:code,closeObserved:true,stdout:Buffer.concat(out).toString(),stderr:Buffer.concat(err).toString()};
}
