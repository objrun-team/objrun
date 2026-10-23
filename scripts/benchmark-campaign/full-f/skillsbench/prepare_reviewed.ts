/** Durable zero-model preparation queue. One resource claim per task; quit on409. */
import {spawn,spawnSync} from 'node:child_process';
import {closeSync,fsyncSync,mkdirSync,openSync,readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,verifyPin,jsonPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
const read=(path:string)=>JSON.parse(readFileSync(path,'utf8'));
const directory=join(home,'reviewed-preparation-campaign',crypto.randomUUID());mkdirSync(directory,{recursive:true});
function save(path:string,data:any){writeFileSync(path,JSON.stringify(data,null,2)+'\n');const fd=openSync(path,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}return actualPin(path);}
function status(update:any){save(join(home,'status.json'),{...read(join(home,'status.json')),...update,updatedAtUtc:new Date().toISOString()});}
const inventory=read(join(home,'artifact-policy-inventory.json'));if(inventory.denominator!==87||inventory.rows.length!==87)throw Error('full87_inventory_required');
const sourcePins=['prepare_reviewed.ts','prepare_next.ts','preparation_resource.ts','prepare.py','artifact_policies.py','multi_policies.py','recover_build_container.py','build_environment.py','apt_build_proxy.py','apt_transport.py','grade_controls.py','ordinary_artifacts.py','bounded_child.py','private_eval.py','private_eval_v2.py','private_eval_multi.py'].map(n=>actualPin(join(import.meta.dir,n)));
function ready(taskId:string){try{
  const path=join(home,'grader-controls',taskId,'latest.json');if(!existsSync(path))return false;
  const cp=read(path).controlPin;verifyPin(cp);const c=jsonPin(cp);verifyPin(c.builtImagesPin);const b=jsonPin(c.builtImagesPin);verifyPin(b.privateRunnerSourcePin);
  return c.taskId===taskId&&c.controlsPassed&&c.ownedContainersRemaining===0&&b.sourceBeforeAfterEqual&&read(join(home,'environment-preparation',taskId,'latest.json')).builtImagesPin.sha256===c.builtImagesPin.sha256;
}catch{return false;}}
const taskIds=inventory.rows.filter((r:any)=>r.policyReviewed).map((r:any)=>r.taskId);
const manifest={protocol:'skillsbench-reviewed-preparation-campaign-v1',createdAtUtc:new Date().toISOString(),denominator:87,taskIds,sourcePins,inventoryPin:actualPin(join(home,'artifact-policy-inventory.json')),modelCalls:0,formalScoreCertified:false};
const manifestPin=save(join(directory,'manifest.json'),manifest),attempts:any[]=[];
let phase='running',currentChildPid:number|undefined;
function checkpoint(taskId?:string){const summary={protocol:manifest.protocol,phase,pid:process.pid,manifestPin,attempts,taskId,currentChildPid,modelCalls:0,formalScoreCertified:false};const pin=save(join(directory,'state.json'),summary);save(join(home,'reviewed-preparation-campaign/latest.json'),{statePin:pin});status({preparationCampaign:{pid:process.pid,phase,taskId,currentChildPid,statePin:pin,attemptCount:attempts.length,readyCount:taskIds.filter(ready).length,denominator:87,modelCalls:0}});}
try{
  checkpoint();
  for(const taskId of taskIds){
    const stopPath=join(home,'reviewed-preparation-campaign/stop-request.json');
    if(existsSync(stopPath)&&read(stopPath).targetPid===process.pid){phase='stopped_at_task_boundary';break;}
    for(const p of sourcePins)verifyPin(p);verifyPin(manifest.inventoryPin);if(ready(taskId))continue;
    const disk=spawnSync('powershell.exe',['-NoProfile','-Command','Get-PSDrive C,D,F | Select-Object Name,Free | ConvertTo-Json -Compress'],{windowsHide:true,encoding:'utf8'});
    if(disk.status!==0)throw Error('preparation_disk_observation_failed');
    const disks=JSON.parse(disk.stdout);save(join(directory,'disk-'+taskId+'.json'),{disks,atUtc:new Date().toISOString(),modelCalls:0});
    if(disks.some((row:any)=>!Number.isFinite(row.Free)||row.Free<2*1024**3)){phase='filesystem_storage_pressure';break;}
    const prefix=join(directory,taskId),out=openSync(prefix+'.stdout','wx'),err=openSync(prefix+'.stderr','wx');let code:number;
    checkpoint(taskId);
    try{const child=spawn(process.execPath,[join(import.meta.dir,'prepare_next.ts'),'--task',taskId],{cwd:root,windowsHide:true,stdio:['ignore',out,err]});currentChildPid=child.pid;checkpoint(taskId);
      code=await new Promise<number>((ok,bad)=>{child.once('error',bad);child.once('exit',n=>ok(n??1));});
    }finally{fsyncSync(out);fsyncSync(err);closeSync(out);closeSync(err);currentChildPid=undefined;}
    const preparation=read(join(home,'status.json')).environmentPreparation;
    const attempt={taskId,exitCode:code,finishedAtUtc:new Date().toISOString(),actualControlsPassed:ready(taskId),preparation,
      stdoutPin:actualPin(prefix+'.stdout'),stderrPin:actualPin(prefix+'.stderr'),modelCalls:0,formalScoreCertified:false};
    attempts.push(attempt);save(prefix+'.json',attempt);checkpoint();
    if(preparation?.stage==='resource_queued'){phase='resource_queued';break;}
    let failureText=readFileSync(prefix+'.stderr','utf8');
    const failedCommand=failureText.match(/see (.+command-\d+\.json)/)?.[1];
    if(failedCommand&&resolve(failedCommand).startsWith(resolve(home,'environment-preparation',taskId)+require('node:path').sep)){
      const failed=read(failedCommand);for(const pin of [failed.stdoutPin,failed.stderrPin]){verifyPin(pin);failureText+=readFileSync(pin.path,'utf8').slice(-65536);}
    }
    if(/502\s+Bad Gateway|apt_build_proxy|original_controls_pending/.test(failureText)){phase='infrastructure_repair_needed';break;}
    // Failed original controls remain pending; do not loop on the same task or
    // turn a preparation failure into a formal F outcome. Continue other tasks.
  }
  if(phase==='running')phase='reviewed_tasks_attempted';
}catch(error){phase='preparation_campaign_failed';save(join(directory,'failure.json'),{error:String(error),atUtc:new Date().toISOString(),modelCalls:0});process.exitCode=1;}
finally{checkpoint();console.log(JSON.stringify({phase,pid:process.pid,attempts:attempts.length,modelCalls:0}));}
