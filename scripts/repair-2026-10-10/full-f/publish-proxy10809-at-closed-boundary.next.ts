/** One bounded root publisher, no model calls or duplicate broker. */
import {readFileSync,writeFileSync,mkdirSync,existsSync,openSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {actualPin,verifyPin} from '../../repair-2026-10-08/paid-resource-proof-v2.ts';
const root=resolve(import.meta.dir,'../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun');
const dir=join(home,'local-proxy10809-broker-switch');mkdirSync(dir,{recursive:true});
const ownPin=actualPin(import.meta.path),statePath=join(dir,'publisher-state.json');
if(existsSync(statePath))throw Error('one_shot_publisher_already_recorded');
const original=JSON.parse(readFileSync(join(home,'control.json'),'utf8')).broker;
if(original.pid!==311252||original.runId!=='repair-2026-10-11T11-50-05-363Z')throw Error('original_exact_broker_required');
const expectedBirth='2026-10-11T11:50:05.2493020Z';
const state=(extra:any)=>writeFileSync(statePath,JSON.stringify({atUtc:new Date().toISOString(),pid:process.pid,ownPin,oldPid:original.pid,expectedBirth,modelCalls:0,...extra},null,2)+'\n');
async function run(name:string){
 const entry=join(import.meta.dir,name),pin=actualPin(entry);const fd=openSync(join(dir,name+'.log'),'a');
 const p=spawn(process.execPath,['run',entry],{cwd:root,windowsHide:true,stdio:['ignore',fd,fd]});
 const code=await new Promise<number>((ok,bad)=>{p.once('error',bad);p.once('exit',n=>ok(n??1));});verifyPin(pin);if(code!==0)throw Error(name+'_exit_'+code);
}
function ps(command:string){const p=Bun.spawnSync(['powershell.exe','-NoProfile','-NonInteractive','-Command',command]);if(p.exitCode!==0)throw Error('exact_identity_command_failed');return p.stdout.toString();}
try{
 state({phase:'waiting_original_native_closed_boundary'});const deadline=Date.now()+1200000;
 while(true){
  verifyPin(ownPin);for(const p of original.sourcePins)verifyPin(p);
  const current=JSON.parse(readFileSync(join(home,'control.json'),'utf8'));
  if(current.broker.pid!==original.pid||current.broker.runId!==original.runId)throw Error('broker_changed_no_second_publication');
  const h=await(await fetch(original.endpoint+'/health')).json();
  const empty=h.healthy&&h.pid===original.pid&&h.runId===original.runId&&h.activeRequests===0&&h.queuedRequests===0&&!h.canonicalOwner&&h.lanes.every((x:any)=>x.closed)&&(h.resourceSlots??[]).length===0;
  if(empty&&!existsSync(join(root,'.phase1-data/owned-paid-campaign.lock.json')))break;
  if(Date.now()>=deadline)throw Error('bounded_wait_closed_without_interrupting_health');
  await Bun.sleep(15000);
 }
 state({phase:'native_history_and_source_archive_verification'});
 try{await run('prepare-proxy10809-broker-switch.next.ts');}
 catch(error){state({phase:'prepare_failed_requires_review',error:String(error),automaticRetry:false});throw error;}
 state({phase:'old_native_verified_exact_retirement'});
 ps(`$p=Get-CimInstance Win32_Process -Filter 'ProcessId=311252'; if(!$p -or $p.CreationDate.ToUniversalTime().ToString('o') -ne '${expectedBirth}' -or $p.CommandLine -notlike '*digitalocean-broker-dynamic-sixteen-actual-disk.next.ts --serve*'){throw 'exact old identity mismatch'}; Stop-Process -Id 311252; if(Get-Process -Id 311252 -ErrorAction SilentlyContinue){throw 'old identity not exited'}`);
 const entry=join(import.meta.dir,'shared/digitalocean-broker-sixteen-proxy10809.next.ts');verifyPin(actualPin(entry));
 const out=openSync(join(dir,'new-broker.stdout'),'a'),err=openSync(join(dir,'new-broker.stderr'),'a');
 const child=spawn(process.execPath,[entry,'--serve'],{cwd:root,windowsHide:true,detached:true,stdio:['ignore',out,err]});child.unref();
 state({phase:'new_unique_proxy_broker_starting',newPid:child.pid});
 const startDeadline=Date.now()+30000;
 while(true){const c=JSON.parse(readFileSync(join(home,'control.json'),'utf8'));if(c.broker.pid===child.pid)break;if(Date.now()>=startDeadline)throw Error('new_broker_start_receipt_pending_no_duplicate');await Bun.sleep(500);}
 await run('finalize-proxy10809-broker-switch.next.ts');
 state({phase:'proxy_published',newPid:child.pid,proofPath:join(dir,'switch-complete.json')});
}catch(error){state({phase:'publisher_closed_requires_review',error:String(error)});process.exitCode=1;}
