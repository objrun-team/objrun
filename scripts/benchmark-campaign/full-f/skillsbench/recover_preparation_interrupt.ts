/** Exact recovery of the recorded Windows queue interruption, not a sweep. */
import {strict as assert} from 'node:assert';
import {spawnSync} from 'node:child_process';
import {readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,verifyPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench'),read=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const request=read(join(home,'reviewed-preparation-campaign/drain-request.json'));assert.equal(request.queuePid,58628);assert.equal(request.currentChildPid,44600);assert.equal(request.currentTaskId,'court-form-filling');verifyPin(request.originalStatePin);
const state=read(request.originalStatePin.path),manifest=read(state.manifestPin.path);verifyPin(state.manifestPin);for(const pin of manifest.sourcePins)verifyPin(pin);
const absent=spawnSync('powershell.exe',['-NoProfile','-Command','if(Get-Process -Id 44600 -ErrorAction SilentlyContinue){exit 0}else{exit 1}'],{windowsHide:true});assert.equal(absent.status,1,'original_child_must_be_dead');
const control=read(join(home,'../control.json')),connection=control.broker,health=read(connection.healthPath),resource=health.resources?.['heavy-container'];
assert.equal(health.pid,connection.pid);assert.equal(health.runId,connection.runId);assert(Date.now()-Date.parse(health.atUtc)<30000);assert.equal(resource.slug,'skillsbench');assert.equal(resource.pid,44600);
const docker='D:/Program/resources/bin/docker.exe',id='35f942ca2b9a5edccefba587b417e2f20fc42a0ac3d381e5fb6f21e7ba9ab6de';
const commands:any[]=[];
function command(args:string[]){const r=spawnSync(docker,['-H','npipe:////./pipe/dockerDesktopLinuxEngine',...args],{windowsHide:true,encoding:'utf8',timeout:30000,maxBuffer:1024**2});assert.equal(r.status,0,'exact_owned_recovery_docker_operation');commands.push({argv:args,httpOrExitStatus:r.status});return r.stdout;}
const container=JSON.parse(command(['inspect',id]))[0];assert.equal(container.Id,id);assert.equal(container.Image,'sha256:d2d889c8e054a8fa159269d8ec3d28b91822d386c1c4666c935e632091ca4e66');
const expected='/bin/sh -c apt-get update && apt-get install -y python3 python3-pip python3-venv poppler-utils && rm -rf /var/lib/apt/lists/*';assert.equal(container.Config.Cmd.join(' ').replace(/\s+/g,' ').trim(),expected);
assert(!container.HostConfig.Binds?.length&&!container.HostConfig.Mounts?.length);assert.equal(container.Config.Labels['org.opencontainers.image.version'],'24.04');
const prior=read(join(home,'reviewed-preparation-campaign/ad99da4f-fe41-4a74-b9dc-694a3eb20fbb/citation-check.json'));
assert(Date.parse(container.Created)>=Date.parse(prior.finishedAtUtc)&&Date.parse(container.Created)<=Date.parse(request.atUtc));assert.equal(state.taskId,'court-form-filling');
const source=join(root,'.phase1-data/skillsbench/vendor/skillsbench/tasks/court-form-filling/environment/Dockerfile');
const frozen=read(join(home,'manifest.json')).sourceFilePins.find((p:any)=>resolve(p.path)===resolve(source));assert(frozen);verifyPin(frozen);
const observation={containerId:id,imageId:container.Image,createdAtUtc:container.Created,command:expected,hostBinds:false,
  exclusiveResourceOwner:{slug:resource.slug,pid:resource.pid,brokerPid:connection.pid,brokerRunId:connection.runId},sourcePin:frozen,originalStatePin:request.originalStatePin};
writeFileSync(join(home,'reviewed-preparation-campaign/interruption-ownership.json'),JSON.stringify(observation,null,2)+'\n');
command(['rm','-f',id]);
// Use the original authenticated /resource/release protocol and original
// resource token/PID. No acquire, lane, owner or supplier endpoint is called.
const response=await fetch(connection.endpoint+'/resource/release',{method:'POST',headers:{authorization:'Bearer '+connection.accessToken,'content-type':'application/json'},body:JSON.stringify({slug:'skillsbench',kind:'heavy-container',pid:44600,token:resource.token}),signal:AbortSignal.timeout(30000)});assert(response.ok,'original_owned_resource_release_failed');
const path=join(home,'reviewed-preparation-campaign/interruption-recovery.json');writeFileSync(path,JSON.stringify({protocol:'skillsbench-owned-preparation-interruption-recovery-v1',atUtc:new Date().toISOString(),ownershipPin:actualPin(join(home,'reviewed-preparation-campaign/interruption-ownership.json')),containerRemoved:true,resourceReleased:true,originalChildDead:true,commands,modelCalls:0,formalScoreCertified:false},null,2)+'\n');
const status=read(join(home,'status.json'));status.preparationCampaign.phase='interrupted_for_transport_repair';status.preparationCampaign.interruptionRecoveryPin=actualPin(path);status.environmentPreparation={...status.environmentPreparation,stage:'preparation_interrupted',reason:'Windows parent termination also ended owned child; original build container removed and original resource released',modelCalls:0};writeFileSync(join(home,'status.json'),JSON.stringify(status,null,2)+'\n');
console.log(JSON.stringify({containerRemoved:true,resourceReleased:true,recoveryPin:actualPin(path),modelCalls:0}));
