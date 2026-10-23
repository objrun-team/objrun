/** Original SkillsBench CLI/HTTP stand, with explicit pinned bootstrap and shared lease. */
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {observedSpawn,configureObservedSpawn} from './observed-spawn.ts';
import {verifyPin,demand} from './manifest.ts';
import {processIdentity} from './runtime.ts';
export async function startSingleTaskSkillsBenchStand(input:any){
 const {binding,output,config,sourcePins}=input;for(const p of [binding.pythonPin,binding.standEntryPin,binding.pythonBootstrap.bootstrapPin,binding.pythonBootstrap.configPin])verifyPin(p);
 const mapped=JSON.parse(readFileSync(binding.pythonBootstrap.configPin.path,'utf8'));
 demand([mapped.originalStandPin,...(mapped.allowedEntryPins??[])].some((p:any)=>resolve(p.path)===resolve(binding.standEntryPin.path)&&p.sha256===binding.standEntryPin.sha256&&p.bytes===binding.standEntryPin.bytes),'single_task_original_stand_mapping');
 for(const key of ['NOVAEVE_RESOURCE_PARENT_PID','NOVAEVE_RESOURCE_LEASE_PID','NOVAEVE_RESOURCE_MEMORY_MB','NOVAEVE_RESOURCE_GROWTH_BYTES','NOVAEVE_RESOURCE_BENCH','NOVAEVE_RESOURCE_TOKEN','NOVAEVE_RESOURCE_SLOTS'])demand(typeof process.env[key]==='string'&&process.env[key]!.length>0,'single_task_actual_parent_lease:'+key);
 demand(process.env.NOVAEVE_RESOURCE_BENCH==='skillsbench'&&config.resourceOwnerPid===Number(process.env.NOVAEVE_RESOURCE_LEASE_PID),'single_task_sb_owner_scope');
 mkdirSync(output,{recursive:false});configureObservedSpawn(join(output,'process'),sourcePins);
 const probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')});const port=probe.port!;await probe.stop(true);
 const configPath=join(output,'stand-config.json');writeFileSync(configPath,JSON.stringify(config,null,2)+'\n',{flag:'wx'});
 const token=crypto.randomUUID()+crypto.randomUUID(),origin='http://127.0.0.1:'+port;
 const env={...process.env,TGENGIN_GRADER_TOKEN:token,OBJRUN_TB12_STAND_TOKEN:token};
 const argv=['-B','-X','utf8',binding.pythonBootstrap.bootstrapPin.path,'--config',binding.pythonBootstrap.configPin.path,'--original-script',binding.standEntryPin.path,'--','--config',configPath,'--port',String(port)];
 const child=observedSpawn(binding.pythonPin.path,argv,{cwd:input.root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});child.stdout?.resume();child.stderr?.resume();
 let exited=false,closed=false,code:number|null=null,error:any;child.on('error',e=>{error=String(e)});child.on('exit',c=>{exited=true;code=c});const closing=new Promise<void>(ok=>child.on('close',()=>{closed=true;ok()}));
 demand(child.pid,'single_task_original_stand_pid');const identity=processIdentity(child.pid);
 const call=async(path:string,body:any,timeoutMs:number)=>{const response=await fetch(origin+path,{method:'POST',headers:{'content-type':'application/json','X-ObjRun-Grader-Token':token},body:JSON.stringify(body),signal:AbortSignal.timeout(Math.max(1,Math.floor(Math.min(timeoutMs,input.deadline-Date.now()))))});const text=await response.text();demand(response.ok,'single_task_original_stand_http:'+response.status+':'+text.slice(0,4096));return JSON.parse(text)};
 let health:any;const deadline=Math.min(input.deadline,Date.now()+60000);
 while(Date.now()<deadline&&!closed&&!error){try{const response=await fetch(origin+'/health',{signal:AbortSignal.timeout(1000)});if(response.ok){health=await response.json();break}}catch{}await Bun.sleep(100)}
 demand(health?.protocol==='skillsbench-full-f-data-stand-v1'&&health.pid===child.pid,'single_task_actual_original_stand_health');
 demand(JSON.stringify([...health.readyTaskIds].sort())===JSON.stringify(Object.keys(config.taskReadiness).sort()),'single_task_ready_http_identity');
 return {origin,token,pid:child.pid,identity,health,call,async close(){let stop:any,shutdown:any,fault:any;try{stop=await call('/stop',{},60000);shutdown=await call('/shutdown',{},60000)}catch(e){fault=String(e)}
  await Promise.race([closing,new Promise<void>(ok=>{const timer=setTimeout(ok,Math.max(1,Math.min(10000,input.deadline-Date.now())));timer.unref();closing.then(()=>clearTimeout(timer))})]);
  const proof={pid:child.pid,identity,exitObserved:exited,closeObserved:closed,exitCode:code,error:error??fault??null,stop,shutdown};
  writeFileSync(join(output,'stand-close.json'),JSON.stringify(proof,null,2)+'\n',{flag:'wx'});
  demand(exited&&closed&&code===0&&!error&&!fault&&shutdown?.ownedContainersRemaining===0,'single_task_original_stand_closure_unproven');return proof}};
}
