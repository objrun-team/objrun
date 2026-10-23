import {observeMemory} from './next-segment/memory_observe_only_v2.next.ts';
/** Source-frozen production full F scheduler. All 87 routes remain in scope. */
import { randomBytes,timingSafeEqual } from 'node:crypto';
import { spawn,spawnSync } from 'node:child_process';
import { closeSync,existsSync,fsyncSync,mkdirSync,openSync,readFileSync,readdirSync,renameSync,unlinkSync,writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { Database } from 'bun:sqlite';
import { actualPin,demand,hash,jsonPin,verifyPin,type Pin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { BENCHMARK_INFERENCE } from '../shared/digitalocean-inference.ts';
import { BENCHMARK_PROVIDER } from '../shared/digitalocean-provider.ts';
import { tbEngine } from '../../../repair-2026-10-08/tb-engine.ts';
import { SIX_TOOLS } from '../../../repair-2026-10-08/tb-nginx-contract.ts';
import { skbToolGateway } from '../../../repair-2026-10-08/skb-artifact-tool-gateway-v2.ts';
import { skbStoppedSnapshot } from '../../../repair-2026-10-08/skb-artifact-runtime-v2.ts';
import { classifyGeneration } from '../../../repair-2026-10-08/campaign-contract.ts';
import { createFullFFeeQueue } from './fee_queue.ts';
import { taskSegmentBoundary } from './segment_boundary.ts';
import { loadContinuation,taskFitsPriceWindow } from './resume.ts';
import { fullFRunId,acquireFullFResource,acquireFullFAdmission } from '../shared/shared-admission.ts';
import { acquireContainerTaskResource } from '../shared/container-task-resource.ts';
import { checkSkillsBenchDockerDisk } from './next-segment/docker_disk_actual_floor_v2.next.ts';
import { atomicStateJson } from '../shared/atomic-state.ts';
import { validateAccReadiness } from './next-segment/runtime_acc_readiness.next.ts';

const ROOT=resolve(import.meta.dir,'../../../..'),HOME=join(ROOT,'docs/repair-2026-10-10/full-f-rerun/skillsbench');
function read(path:string){return JSON.parse(readFileSync(path,'utf8'));}
function durable(path:string,value:unknown){
  atomicStateJson(path,value);
  return actualPin(path);
}
let workerStatusPath:string|undefined;
function updateStatus(value:any){demand(workerStatusPath,'private_worker_status_required');const old=existsSync(workerStatusPath)?read(workerStatusPath):{};durable(workerStatusPath,{...old,...value,updatedAtUtc:new Date().toISOString()});}
function promptBody(raw:Buffer){const text=new TextDecoder('utf8',{fatal:true}).decode(raw),delimiter=/^---[ \t]*\r?\n/gm;const first=delimiter.exec(text),second=delimiter.exec(text);demand(first?.index===0&&second,'original_prompt_frontmatter');return text.slice(second!.index+second![0].length);}
export function engineTaskId(runId:string,taskId:string){return 'skb-'+hash(runId+'/'+taskId).slice(0,32);}
export function validateRuntimeReadiness(manifest:any,ready:any){
  demand(manifest.denominator===87&&manifest.taskSchedule.length===87&&manifest.arms.length===1&&manifest.arms[0]==='F','full_f_scope');
  demand(ready?.protocol==='skillsbench-full-f-task-gated-runtime-readiness-v2'&&ready.denominator===87,'actual_task_gated_isolation_required');
  const readyIds=Object.keys(ready.taskReadiness??{});
  demand(readyIds.length>0&&readyIds.every(id=>manifest.taskSchedule.some((r:any)=>r.taskId===id)),'ready_tasks_must_belong_to_full87');
  demand(ready.full87Validated===(readyIds.length===87),'full87_readiness_claim_mismatch');
  verifyPin(ready.stateRefreshControlsPin);const refresh=jsonPin(ready.stateRefreshControlsPin);
  demand(['skillsbench-full-f-same-run-state-refresh-control-v1','skillsbench-acc-real-stand-refresh-controls-v1'].includes(refresh.protocol)&&refresh.verified===true&&refresh.modelCalls===0&&refresh.sourcePins.length>0&&JSON.stringify(refresh.steps.map((s:any)=>s.reward))==='[0,1,0]','actual_current_bridge_refresh_required');
  for(const pin of refresh.sourcePins)verifyPin(pin);
  if(refresh.protocol==='skillsbench-acc-real-stand-refresh-controls-v1')demand(refresh.sourcePins.some((p:any)=>p.path.endsWith('data_stand_acc_staged.next.py')&&p.sha256===actualPin(join(import.meta.dir,'data_stand.py')).sha256),'tested_acc_stand_must_equal_installed_source');
  demand(refresh.skillsReadVerified===true&&refresh.skillsHelperExecuted===true,'actual_original_skills_read_and_execution_required');
  const skillsProof=jsonPin(refresh.skillsDeploymentPin);demand(skillsProof.verified===true&&skillsProof.privateVerifierCopied===false&&skillsProof.privateOracleCopied===false,'original_public_skills_control_required');
  demand(new Set(refresh.steps.map((s:any)=>s.gradeOwnerPin.path)).size===3,'distinct_latest_grade_receipts_required');
  for(const step of refresh.steps){verifyPin(step.gradeOwnerPin);const grade=jsonPin(step.gradeOwnerPin);demand(grade.result.complete===true&&grade.result.candidateExecutablesUsed===false&&grade.result.candidateSnapshotUsed===false,'actual_private_refresh_grade_required');}
  for(const row of manifest.taskSchedule){
    if(!readyIds.includes(row.taskId))continue;
    const proof=ready.taskReadiness[row.taskId];demand(['ordinary-data-v1','wyckoff-function-native-v1','acc-independent-v1','group02-adapter3-v1'].includes(proof?.adapter),'task_isolated_execution_adapter_not_implemented');
    if(proof.adapter==='acc-independent-v1'){validateAccReadiness(row,proof);continue;}
    verifyPin(proof.builtImagesPin);verifyPin(proof.controlPin);const built=jsonPin(proof.builtImagesPin),controls=jsonPin(proof.controlPin);
    demand(built.taskId===row.taskId&&controls.taskId===row.taskId&&controls.controlsPassed===true&&controls.ownedContainersRemaining===0&&JSON.stringify(controls.decisions)==='[0,1,0]','actual_original_grader_controls_required');
    demand(hash(JSON.stringify(controls.builtImagesPin))===hash(JSON.stringify(proof.builtImagesPin)),'actual_control_build_join');
    for(const key of ['collectionPin','emptyPin','oraclePin','wrongPin'])verifyPin(controls[key]);
    const collection=jsonPin(controls.collectionPin);demand(collection.complete&&collection.mode==='collect','actual_full_collection_required');
    if(proof.adapter==='group02-adapter3-v1'){
      demand(['enterprise-information-search','fix-build-google-auto','flink-query','paratransit-routing','quantum-numerical-simulation','spring-boot-jakarta-migration','tictoc-unnecessary-abort-detection'].includes(row.taskId),'adapter3_task_ownership');
      demand(resolve(built.privateRunnerSourcePin.path)===join(import.meta.dir,'next-segment/group02_adapter3_v1/private_eval.py'),'adapter3_private_source');
      for(const pin of built.adapterSourcePins)verifyPin(pin);
      verifyPin(built.privateRunnerSourcePin);demand(collection.nodeIds.length>0,'actual_nonempty_pytest_collection_required');
      verifyPin(proof.standProofPin);const standProof=jsonPin(proof.standProofPin);
      demand(standProof.taskId===row.taskId&&standProof.verified===true&&standProof.modelCalls===0&&standProof.ownedContainersRemaining===0,'actual_adapter3_stand_qualification_required');
      demand(standProof.standPin?.sha256===actualPin(join(import.meta.dir,'data_stand_group02_adapter3_v1.next.py')).sha256,'actual_adapter3_stand_source_required');
      verifyPin(standProof.standPin);demand(['up','begin','place','ran','passed','close'].every(step=>standProof.steps?.[step]===true)&&SIX_TOOLS.every(tool=>standProof.toolNames?.includes(tool))&&standProof.skillsReadVerified===true&&standProof.skillsHelperExecuted===true,'actual_adapter3_stand_lifecycle_and_six_tools_required');
      demand(controls.workerRoute?.workerEntryPin?.sha256===actualPin(join(import.meta.dir,'next-segment/private_task_worker_entry_group02_adapter3_v1.next.ts')).sha256&&controls.workerRoute?.runtimePin?.sha256===actualPin(join(import.meta.dir,'runtime_private_task_group02_adapter3_v1.next.ts')).sha256,'native_controls_worker_route_source_mismatch');
      demand(JSON.stringify(standProof.workerRoute)===JSON.stringify(controls.workerRoute),'stand_controls_worker_route_source_mismatch');
      continue;
    }
    if(proof.adapter==='wyckoff-function-native-v1'){
      demand(row.taskId==='crystallographic-wyckoff-position-analysis'&&collection.nodeIds.length===0&&collection.pytestExitCode===5&&collection.nativeCaseCount===11,'actual_native_collection_semantics');
      for(const pin of [...built.sourcePins,...controls.sourcePins])verifyPin(pin);
      verifyPin(proof.environmentControlsPin);const environment=jsonPin(proof.environmentControlsPin);
      demand(environment.protocol==='skillsbench-full-f-native-snapshot-refresh-controls-v1'&&environment.taskId===row.taskId&&environment.verified===true&&environment.candidateEnvironmentParityVerified===true&&environment.originalVerifierBudgetVerified===true&&environment.ownedResourcesRemaining===0,'actual_native_environment_lifecycle_controls_required');
      for(const pin of environment.sourcePins)verifyPin(pin);
      demand(environment.storageBudgetParityVerified===true,'native_source_transport_budget_parity_required');
    }else{
      verifyPin(built.privateRunnerSourcePin);demand(['private_eval.py','private_eval_v2.py','private_eval_multi.py','private_eval_score.py'].some(name=>resolve(built.privateRunnerSourcePin.path)===join(import.meta.dir,name))||(row.taskId==='manufacturing-codebook-normalization'&&resolve(built.privateRunnerSourcePin.path)===join(import.meta.dir,'next-segment/private_eval_codebook_wide_v1.next.py')&&built.dataArtifactPolicy.maximumBytes===64*1024**2),'private_runtime_source');
      demand(collection.nodeIds.length>0,'actual_nonempty_pytest_collection_required');
    }
  }
}

export async function runSkillsBenchPrivateTask(manifest:any,workerPlanPin:Pin){
  verifyPin(workerPlanPin);const workerPlan=jsonPin(workerPlanPin);
  demand(workerPlan.protocol==='skillsbench-private-task-worker-plan-v2'&&workerPlan.denominator===87&&workerPlan.targetTaskId&&workerPlan.planPin&&workerPlan.priorPin&&workerPlan.readinessPin,'private_task_plan_required');
  verifyPin(workerPlan.planPin);verifyPin(workerPlan.priorPin);verifyPin(workerPlan.readinessPin);
  demand(manifest.taskSchedule.some((r:any)=>r.taskId===workerPlan.targetTaskId),'foreign_task_plan');
  workerStatusPath=join(HOME,'parallel-task-status',workerPlan.targetTaskId,String(process.pid)+'.json');
  const ready=jsonPin(workerPlan.readinessPin);validateRuntimeReadiness(manifest,ready);
  for(const pin of manifest.sourceFilePins)verifyPin(pin,undefined,2*1024**3);
  const prior=jsonPin(workerPlan.priorPin);demand(prior.pending.some((r:any)=>r.taskId===workerPlan.targetTaskId)&&!prior.records.some((r:any)=>r.taskId===workerPlan.targetTaskId),'completed_or_unplanned_task');
  if(prior.pending.length===0){updateStatus({phase:'finished_pending_full_audit',recorded:87,costUsd:prior.billedUsd,modelRequests:prior.requestCount});return;}
  const diskReady=new Set<string>(),diskPending:any[]=[];
  for(const row of prior.pending.filter((r:any)=>r.taskId===workerPlan.targetTaskId&&ready.taskReadiness[r.taskId])){
    try{checkSkillsBenchDockerDisk(ROOT,row.taskId,'formal-before-heavy-resource-acquisition');diskReady.add(row.taskId);}
    catch(error){if(!String(error).includes('physical_docker_disk_queued:'))throw error;diskPending.push({taskId:row.taskId,reason:String(error),originalBudgetRetained:true});}
  }
  if(diskReady.size===0){updateStatus({phase:'physical_disk_queue_pending_preparation',physicalDiskPending:diskPending,denominator:87,backgroundPaidProcessPid:null});return;}
  // User-authorized observation only; original container budgets and shared
  // resource admission remain authoritative. Low/unknown free memory does not
  // remove an otherwise ready task from the dispatch set.
  const memoryObservation=observeMemory(()=>Bun.spawnSync(['powershell.exe','-NoProfile','-NonInteractive','-Command','(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory']));
  const hostFreeBytes=memoryObservation.bytes,probeExitCode=memoryObservation.probeExitCode,observationError=memoryObservation.observationError;
  const memoryPending:any[]=[];
  for(const row of prior.pending.filter(r=>diskReady.has(r.taskId))){
    const memoryMb=read(join(HOME,'task-descriptors',row.taskId+'.json')).originalResources.environment.memory_mb;
    demand(Number.isFinite(memoryMb)&&memoryMb>0,'original_task_memory_required');
    const requiredBytes=2*memoryMb*1024**2;
    if(hostFreeBytes===null||hostFreeBytes<requiredBytes)memoryPending.push({taskId:row.taskId,hostFreeBytes,requiredBytes,observationOnly:true,blocksExecution:false,originalContainerMemoryMb:memoryMb,originalConcurrentContainers:2,originalBudgetRetained:true});
  }
  const hostMemoryAdmissionPin=durable(join(HOME,'host-memory-admission',crypto.randomUUID()+'.json'),{atUtc:new Date().toISOString(),hostFreeBytes,probeExitCode,observationError,memoryPending,observationOnly:true,blocksExecution:false,denominator:87,modelCalls:0,resourceClaimed:false});
  const sourcePins:Pin[]=readdirSync(import.meta.dir).filter(n=>n.endsWith('.ts')||n.endsWith('.py')).map(n=>actualPin(join(import.meta.dir,n)));
  for(const filename of readdirSync(join(import.meta.dir,'next-segment/group02_adapter3_v1')).filter(n=>n.endsWith('.py')))sourcePins.push(actualPin(join(import.meta.dir,'next-segment/group02_adapter3_v1',filename)));
  for(const relative of ['app/src/llm/index.ts','scripts/repair-2026-10-08/benchmark-inference.ts','scripts/repair-2026-10-08/benchmark-provider.ts',
    'scripts/repair-2026-10-08/campaign-journal.ts','scripts/repair-2026-10-08/benchmark-usd-cash.ts','scripts/repair-2026-10-08/scientific-journal-proxy.ts',
    'scripts/repair-2026-10-08/tb-engine.ts','scripts/repair-2026-10-08/skb-artifact-tool-gateway-v2.ts'])sourcePins.push(actualPin(join(ROOT,relative)));
  for(const name of ["digitalocean-provider.ts", "digitalocean-inference.ts", "digitalocean-journal.ts", "digitalocean-usd-cash.ts", "digitalocean-proxy.ts", "digitalocean-closed-run-cost.ts", "atomic-state.ts", "controlled-broker-recovery.ts"])sourcePins.push(actualPin(join(import.meta.dir,'../shared',name)));
  sourcePins.push(actualPin(join(import.meta.dir,'next-segment/memory_observe_only_v2.next.ts')),actualPin(join(import.meta.dir,'next-segment/docker_disk_actual_floor_v2.next.ts')),actualPin(join(import.meta.dir,'../shared/actual-physical-disk-floor.next.ts')));
  sourcePins.push(actualPin(join(import.meta.dir,'next-segment/runtime_acc_readiness.next.ts')));
  for(const row of manifest.taskSchedule){const proof=ready.taskReadiness[row.taskId];if(proof?.adapter==='acc-independent-v1')for(const pin of validateAccReadiness(row,proof))if(!sourcePins.some(p=>p.path===pin.path))sourcePins.push(pin);}
  const brokerConnection=read(join(HOME,'../control.json')).broker;
  for(const pin of brokerConnection.sourcePins){
    if(!pin.path.endsWith('.ts'))continue;
    verifyPin(pin);const same=sourcePins.find(p=>resolve(p.path).toLowerCase()===resolve(pin.path).toLowerCase());
    if(same)demand(same.sha256===pin.sha256,'shared_broker_source_identity_changed');else sourcePins.push(pin);
  }
  sourcePins.push(workerPlanPin,workerPlan.planPin,workerPlan.priorPin,workerPlan.readinessPin,actualPin(join(import.meta.dir,'../shared/container-task-resource.ts')));
  const heavy=await acquireContainerTaskResource(ROOT,'skillsbench',{taskId:workerPlan.targetTaskId,planPin:workerPlan.planPin,originalPlannedGrowthBytes:workerPlan.originalPlannedGrowthBytes,originalPeakMemoryMb:workerPlan.originalPeakMemoryMb});
  try {
  demand(read(join(HOME,'../control.json')).broker.runId===workerPlan.sharedBrokerRunId,'resource_admitted_shared_epoch_changed');
  let runId:string,output:string;
  for(;;){runId=fullFRunId(ROOT,'skillsbench');demand(/^repair-[0-9TZ-]+$/.test(runId),'original_shared_run_id_grammar');output=join(HOME,'runs',runId);try{mkdirSync(output);break;}catch(error:any){if(error.code!=='EEXIST')throw error;await Bun.sleep(1);}} 
  // Preserve this segment's exact source bytes and readiness after later
  // legitimate task-boundary preparation updates the live workspace files.
  const frozenSourceDirectory=join(output,'frozen-sources');mkdirSync(frozenSourceDirectory);
  const sourceArchive=sourcePins.map((pin,index)=>{
    verifyPin(pin);const path=join(frozenSourceDirectory,String(index).padStart(3,'0')+'-'+pin.path.split(/[\\/]/).at(-1));
    writeFileSync(path,readFileSync(pin.path),{flag:'wx'});const fd=openSync(path,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}
    const snapshotPin=actualPin(path);demand(snapshotPin.sha256===pin.sha256&&snapshotPin.bytes===pin.bytes,'immutable_source_copy_mismatch');
    return {originalPin:pin,snapshotPin};
  });
  const sourceArchivePin=durable(join(output,'source-archive.json'),{protocol:'skillsbench-immutable-segment-source-v1',runId,entries:sourceArchive,containsEnvironmentFile:false});
  const runtimeReadinessPin=durable(join(output,'runtime-readiness.snapshot.json'),ready);
  const schedule=manifest.taskSchedule.map((r:any)=>({...r,id:engineTaskId(runId,r.taskId),route:runId+'/skillsbench/F/0/'+r.taskId}));
  durable(join(output,'manifest.json'),{...manifest,runId,taskSchedule:schedule,taskScheduleSha256:hash(JSON.stringify(schedule)),preparationManifestPin:actualPin(join(HOME,'manifest.json')),runtimeReadinessPin,originalRuntimeReadinessPin:actualPin(join(HOME,'runtime-readiness.json')),sourceArchivePin,sourcePins});
  
  let admission:Awaited<ReturnType<typeof acquireFullFAdmission>>|undefined,queue:ReturnType<typeof createFullFFeeQueue>|undefined;
  let proxy:ReturnType<typeof Bun.serve>|undefined,gateway:ReturnType<typeof skbToolGateway>|undefined,bridge:ReturnType<typeof spawn>|undefined;
  const engines:Awaited<ReturnType<typeof tbEngine>>[]=[],records:any[]=[...prior.records];const token=randomBytes(32).toString('hex'),proxyToken=randomBytes(32).toString('hex');
  const previous={grader:process.env.TGENGIN_GRADER_TOKEN,origins:process.env.TGENGIN_GRADER_ORIGINS,key:process.env.OBJRUN_SKB_FULL_F_PROXY_KEY};
  let bridgeOrigin='',fault:any,activeRow:any,activeDbPath:string|undefined,interruption:any;
  const scrubDiagnostic=(v:string)=>v.split(token).join('[redacted]').split(proxyToken).join('[redacted]');
  const request=async(path:string,body:any)=>{
    const response=await fetch(bridgeOrigin+path,{method:'POST',headers:{'content-type':'application/json','X-ObjRun-Grader-Token':token},body:JSON.stringify(body),signal:AbortSignal.timeout(2000000)});
    if(!response.ok){const chunks:Buffer[]=[];let bytes=0,readFault:string|null=null;const reader=response.body?.getReader();
      if(reader)try{while(bytes<65536+256){const r=await reader.read();if(r.done)break;const part=Buffer.from(r.value).subarray(0,65536+256-bytes);chunks.push(part);bytes+=part.length;}}catch(error){readFault=scrubDiagnostic(String(error)).slice(0,1024)}finally{try{await reader.cancel()}catch{}}
      const raw=Buffer.concat(chunks),safe=scrubDiagnostic(raw.toString('utf8'));const diagnosticBody=Buffer.from(safe).subarray(0,65536).toString('utf8');
      durable(join(output,'private-stand-request-failure-'+crypto.randomUUID()+'.json'),{path,taskId:activeRow?.taskId??null,phase:activeRow?'task':'bootstrap',status:response.status,body:diagnosticBody,bodyMaximumBytes:65536,bodyTruncated:bytes>65536,readFault,bridgePid:bridge?.pid??null,bridgeExitCode:bridge?.exitCode??null,modelBudgetUnchanged:true});
    }
    demand(response.ok,'actual_data_stand_request_failed');return response.json() as Promise<any>;
  };
  try {
    admission=await acquireFullFAdmission({root:ROOT,output,runId,slug:'skillsbench',sourcePins});
    await admission.registerOwnedProcess(durable(join(output,'parent-process.json'),{protocol:'paid-owned-process-v2',pid:process.pid,role:'skillsbench-full-f-parent',runId,ownerNonce:admission.owned.ownerNonce}));
    queue=createFullFFeeQueue({runId,output,sourcePins,schedule,admission});
    proxy=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(req){
      const supplied=Buffer.from(req.headers.get('authorization')??''),expected=Buffer.from('Bearer '+proxyToken);
      if(supplied.length!==expected.length||!timingSafeEqual(supplied,expected))return Response.json({error:'Unauthorized'},{status:401});
      const path=new URL(req.url).pathname;demand(req.method==='POST'&&path.endsWith('/v1/chat/completions'),'proxy_route');
      const result=await queue!.handle(path.slice(1,-'/v1/chat/completions'.length),await req.text());
      return new Response(result.rawResponse,{status:result.httpStatus,headers:{'content-type':'application/json'}});
    }});
    const probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')});const bridgePort=probe.port!;await probe.stop(true);bridgeOrigin='http://127.0.0.1:'+bridgePort;
    process.env.TGENGIN_GRADER_TOKEN=token;process.env.OBJRUN_SKB_FULL_F_PROXY_KEY=proxyToken;
    const bootstrapBudgetSeconds=schedule.find((r:any)=>r.taskId===workerPlan.targetTaskId)!.originalResources.environment.build_timeout_sec;
    const bootstrapDeadline=Date.now()+bootstrapBudgetSeconds*1000;
    const config=durable(join(output,'stand-config.json'),{output,runId,schedule,taskReadiness:ready.taskReadiness,resourceOwnerPid:process.pid,environmentBootstrapDeadlineUnixMs:bootstrapDeadline});
    bridge=spawn('D:/ProgramData/anaconda3/python.exe',['-B',join(import.meta.dir,'data_stand_group02_adapter3_v1.next.py'),'--config',config.path,'--port',String(bridgePort)],{cwd:ROOT,windowsHide:true,env:{...process.env},stdio:['ignore','pipe','pipe']});let bootStdout='',bootStderr='';const scrub=(v:string)=>v.split(token).join('[redacted]').split(proxyToken).join('[redacted]');
    bridge.stdout?.on('data',b=>{bootStdout=(bootStdout+b.toString()).slice(0,65536+256)});bridge.stderr?.on('data',b=>{bootStderr=(bootStderr+b.toString()).slice(0,65536+256)});
    bridge.once('exit',code=>durable(join(output,'private-stand-process-exit.json'),{pid:bridge?.pid,exitCode:code,stdout:scrub(bootStdout).slice(0,65536),stderr:scrub(bootStderr).slice(0,65536)}));
    demand(bridge.pid,'private_stand_pid');await admission.registerOwnedProcess(durable(join(output,'bridge-process.json'),{protocol:'paid-owned-process-v2',pid:bridge.pid,role:'skillsbench-full-f-bridge',runId,ownerNonce:admission.owned.ownerNonce}));
    let healthy=false;for(let attempt=0;Date.now()<bootstrapDeadline;attempt++){try{const r=await fetch(bridgeOrigin+'/health',{signal:AbortSignal.timeout(Math.max(1,Math.min(1000,bootstrapDeadline-Date.now())))});if(r.ok){const h=await r.json() as any;demand(h.denominator===87&&JSON.stringify(h.readyTaskIds.sort())===JSON.stringify(Object.keys(ready.taskReadiness).sort()),'stand_actual_ready_tasks_health');healthy=true;break;}}catch{}await Bun.sleep(100);}
    durable(join(output,'private-stand-bootstrap.json'),{pid:bridge.pid,healthy,exitCode:bridge.exitCode,stdout:scrub(bootStdout).slice(0,65536),stderr:scrub(bootStderr).slice(0,65536),originalEnvironmentBootstrapSeconds:bootstrapBudgetSeconds,environmentBootstrapDeadlineUnixMs:bootstrapDeadline,healthIntervalMs:100,previousInfrastructureHealthWindowSeconds:10,originalAgentAndVerifierUnchanged:true,executorPin:actualPin('D:/ProgramData/anaconda3/python.exe'),modelCalls:0});
    demand(healthy,'private_stand_start_failed');
    gateway=skbToolGateway({stand:bridgeOrigin,token,store:join(output,'tool-receipts'),beforeCapture:()=>{for(const p of sourcePins)verifyPin(p);},ledger:rows=>durable(join(output,'tool-ledger.json'),rows)});
    process.env.TGENGIN_GRADER_ORIGINS=bridgeOrigin+','+gateway.origin;
    durable(join(output,'continuation.json'),{priorClosurePins:prior.segments.map(s=>s.closurePin),priorTaskIds:prior.records.map(r=>r.taskId),priorBilledUsd:prior.billedUsd,priorModelRequests:prior.requestCount,pendingTaskIds:prior.pending.map(r=>r.taskId),denominator:87});
    updateStatus({phase:'running',runId,output,backgroundPaidProcessPid:process.pid,completed:records.filter(r=>r.officialAcceptance.valid).length,passed:records.filter(r=>r.officialAcceptance.valid&&r.officialAcceptance.passed).length,scored:records.filter(r=>r.officialAcceptance.valid).length,modelRequests:prior.requestCount,costUsd:prior.billedUsd,unknownCostRequests:prior.unknownCostCount,unknownReservationUsd:prior.unknownReservationUsd,runtimeImplemented:true});
    durable(join(output,'dispatch-readiness.json'),{denominator:87,readyTaskIds:Object.keys(ready.taskReadiness),pendingPreparationTaskIds:prior.pending.filter(r=>!ready.taskReadiness[r.taskId]).map(r=>r.taskId),full87Validated:ready.full87Validated});
    const attempts=prior.segments.flatMap(s=>[...s.records,...(s.interruptedAttempts??[])]);
    durable(join(output,'physical-disk-dispatch.json'),{denominator:87,admissibleTaskIds:[...diskReady],pendingTasks:diskPending,originalManifestScheduleUnchanged:true});
    const dispatch=schedule.filter((r:any)=>r.taskId===workerPlan.targetTaskId&&diskReady.has(r.taskId)&&ready.taskReadiness[r.taskId]&&prior.pending.some(p=>p.taskId===r.taskId)).sort((a:any,b:any)=>attempts.filter(r=>r.taskId===a.taskId).length-attempts.filter(r=>r.taskId===b.taskId).length||a.index-b.index);
    durable(join(output,'recovery-dispatch-order.json'),{denominator:87,policy:'unattempted_ready_before_interrupted_retries',taskIds:dispatch.map((r:any)=>r.taskId),originalManifestScheduleUnchanged:true});
    for(const row of dispatch){
      try{checkSkillsBenchDockerDisk(ROOT,row.taskId,'formal-before-task-container');}
      catch(error){if(!String(error).includes('physical_docker_disk_queued:'))throw error;durable(join(output,'physical-disk-pending-'+row.index+'.json'),{taskId:row.taskId,reason:String(error),originalBudgetRetained:true,denominator:87});continue;}
      const window=taskFitsPriceWindow(row,jsonPin(admission.prices).observedAtUtc);
      if(!window.canStart){durable(join(output,'price-window-stop.json'),{nextTaskId:row.taskId,...window,atUtc:new Date().toISOString(),action:'Close this segment before another task; continue only through a fresh coordinator round.'});break;}
      for(const pin of sourcePins)verifyPin(pin);const id=row.id,place='skb:'+id,dir=join(output,'workers',String(row.index));
      const engine=await tbEngine(BENCHMARK_INFERENCE,dir);engines.push(engine);
      await admission.registerOwnedProcess(durable(join(output,'engine-'+row.index+'-process.json'),{protocol:'paid-owned-process-v2',pid:engine.pid,role:'skillsbench-full-f-engine-'+row.index,runId,ownerNonce:admission.owned.ownerNonce}));
      await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_SKB_FULL_F_PROXY_KEY',:model,handle,modes,:base,'[]' from api where key_env='OPENROUTER_API_KEY' and model=:model",params:{model:BENCHMARK_PROVIDER.model,base:'http://127.0.0.1:'+proxy.port+'/'+row.route+'/v1'}});
      const dbPath=join(dir,'data/h2h.sqlite');activeRow=row;activeDbPath=dbPath;const state=()=>{const db=new Database(dbPath,{readonly:true});try{return db.query('select state,created_at,solve_seconds from task where id=?').get(id) as any;}finally{db.close();}};
      gateway.register(place,()=>{const s=state();return !s?'task_not_created':Date.now()>=s.created_at+s.solve_seconds*1000?'task_deadline':['done','failed'].includes(s.state)?'task_terminal':undefined;},()=>{const s=state();return s?s.created_at+s.solve_seconds*1000:Date.now();});
      const objective={nodes:[{name:'verified',domain:'bool',moment:'done',handle:bridgeOrigin+'/'+row.taskId+'/verified'},{name:'passed',domain:'bool',moment:'done',handle:bridgeOrigin+'/'+row.taskId+'/passed'}],edges:[{src:'verified',out:0,dst:'passed'}],sink:'passed',checks:6,reuse:'never'};
      await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:(row.taskSeconds+60)*1000},...['verified','passed'].map(name=>({name:bridgeOrigin+'/'+row.taskId+'/'+name,expectMs:(row.verifierSeconds+240)*1000}))],places:[{place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'skb_full_f',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OBJRUN_SKB_FULL_F_PROXY_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
      await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','verify','submit')"});
      await request('/register',{place,taskId:id,databasePath:dbPath});const ping=await request('/place',{place,op:'ping'});
      const skillsDeploymentPin=ping.skillsDeploymentPin,deployment=jsonPin(skillsDeploymentPin);
      demand(deployment.taskId===row.taskId&&deployment.verified===true&&deployment.sourceBeforeAfterEqual===true&&deployment.privateVerifierCopied===false&&deployment.privateOracleCopied===false,'original_public_skills_deployment_required');
      const catalogProcess=spawnSync('python',['-B',join(import.meta.dir,'task_skills.py'),row.taskId],{cwd:ROOT,windowsHide:true,encoding:'utf8',maxBuffer:4*1024**2});
      demand(catalogProcess.status===0,'original_skill_catalog_failed');const catalog=JSON.parse(catalogProcess.stdout);
      demand(catalog.sourceTreeSha256===deployment.originalSourceTreeSha256,'skills_catalog_deployment_join');
      await engine.api('POST','/declare',{skills:[{identity:'original-task-skills',does:'Read original task skill instructions and bundled public helpers',params:{},role:'skill',usable:true,body:catalog.body,when:[[{dim:'task',key:'id',op:'eq',value:id},{dim:'chain',key:'',op:'not_contains',value:'>'}]]}]});
      const registry=await engine.api<any>('GET','/skills');demand(registry.skills.some((s:any)=>s.identity==='original-task-skills'),'original_skills_registry_required');
      const skillsDiscoveryPin=durable(join(output,'skills-discovery-'+row.index+'.json'),{taskId:row.taskId,skillsDeploymentPin,catalog,registry,sourceTreeSha256:catalog.sourceTreeSha256,modelCallsBeforeTask:queue.state().provider.journal.acceptedRequestCount});
      const prompt=promptBody(readFileSync(row.taskSourcePin.path));demand(hash(prompt)===row.promptBodySha256,'frozen_exact_prompt_changed');
      await engine.api('POST','/tasks',{id,run:runId,mode:'skb_full_f',agent:'bot',place,source:'user',domain:'software',workdir:row.workdir,description:prompt,objective,readable:false,solveSeconds:row.taskSeconds,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
      let terminal:any;const end=Date.now()+(row.taskSeconds+7*row.verifierSeconds+600)*1000;
      while(Date.now()<end){const s=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/status');const result=s.result?JSON.parse(s.result):null;if(['done','failed'].includes(s.state)&&!['finalization_pending','finalization_error'].includes(result?.outcome)){terminal=s;break;}const paid=queue.state();if(taskSegmentBoundary(paid).closeSegment&&paid.provider.activeHandlers===0&&paid.cash.pendingCount===0)throw Error('durable_provider_journal_stopped:'+taskSegmentBoundary(paid).reason);if(paid.provider.activeHandlers===0&&paid.cash.pendingCount===0){const db=new Database(dbPath,{readonly:true});try{const stuck=db.query("select body from agent_bot_msg where json_valid(body) and json_extract(body,'$.stuck')=?").get('The required submit tool was not called exactly once');demand(!stuck,'actual_required_submit_protocol_fault');}finally{db.close();}}await Bun.sleep(300);}
      demand(terminal,'task_terminal_finalization_missing');queue.sealRoute(row.route);gateway.seal(place);const quiet=await gateway.drain(place);await queue.proxy.drain(row.route);await engine.stop();
      const snapshot=skbStoppedSnapshot(dbPath,id),calls=queue.taskReceipts(row.route),verdict=terminal.result?JSON.parse(terminal.result):null;
      const generation=classifyGeneration({runtimeVerdict:verdict,state:terminal.state,calls,trace:snapshot.trace,candidate:snapshot.candidate?.body});
      const officialGrade=await request('/'+row.taskId+'/verified',{place,said:snapshot.candidate?.body??''});
      const nativeHandinQualified=verdict?.valid===true&&snapshot.candidate!=null;
      const officialAcceptance={valid:nativeHandinQualified&&generation.valid&&officialGrade.verified===true,passed:nativeHandinQualified&&generation.valid&&officialGrade.verified===true&&officialGrade.passed===true,gradeOwnerPin:officialGrade.gradeOwnerPin,note:officialGrade.note};
      const closure=await request('/stop',{});const record={...row,runId,protocolValid:true,skillsDeploymentPin,skillsDiscoveryPin,state:terminal.state,verdict,generation,officialAcceptance,trace:snapshot.trace,units:snapshot.units,candidate:snapshot.candidate?.body??'',apiCalls:calls,toolQuiescence:quiet,solverClosure:closure};records.push(record);durable(join(output,'task-'+row.index+'.json'),record);
      activeRow=undefined;activeDbPath=undefined;
      const cash=queue.state().cash;updateStatus({recorded:records.length,completed:records.filter(r=>r.officialAcceptance.valid).length,passed:records.filter(r=>r.officialAcceptance.valid&&r.officialAcceptance.passed).length,scored:records.filter(r=>r.officialAcceptance.valid).length,modelRequests:prior.requestCount+queue.state().provider.journal.acceptedRequestCount,costUsd:prior.billedUsd+cash.billedUsd,unknownCostRequests:prior.unknownCostCount+cash.newUnknownCount,unknownReservationUsd:prior.unknownReservationUsd+cash.unknownReservationUsd,pendingReservationUsd:cash.pendingReservationUsd,cashSnapshot:cash});
      const boundary=taskSegmentBoundary(queue.state());
      if(boundary.closeSegment){durable(join(output,'provider-segment-stop.json'),{...boundary,lastRecordedTaskId:row.taskId,atUtc:new Date().toISOString(),remaining:87-records.length,denominator:87,feeReviewBlocksExecution:false});break;}
      // Close one task segment before handing the heavy resource to another Bench.
      break;
    }
    const accounting=await queue.close();durable(join(output,'accounting-close.json'),accounting);updateStatus({phase:records.length===87?'finished_pending_full_audit':'segment_closed_pending_continuation',recorded:records.length,completed:records.filter(r=>r.officialAcceptance.valid).length,passed:records.filter(r=>r.officialAcceptance.valid&&r.officialAcceptance.passed).length,remaining:87-records.length,accountingClosePin:actualPin(join(output,'accounting-close.json'))});
  }catch(error){fault={type:error instanceof Error?error.name:'Error',detail:error instanceof Error?error.message:String(error)};
    if(activeRow&&activeDbPath&&queue&&gateway){
      try{
        const place='skb:'+activeRow.id;queue.sealRoute(activeRow.route);gateway.seal(place);await gateway.drain(place);await queue.proxy.drain(activeRow.route);
        for(const engine of engines)await engine.stop();
        const candidateSnapshot=await request('/retain-interruption',{});candidateSnapshot.rawImageId=candidateSnapshot.imageId;candidateSnapshot.imageId=candidateSnapshot.imageId.trim().split(/\r?\n/).at(-1);demand(/^sha256:[a-f0-9]{64}$/.test(candidateSnapshot.imageId),'interrupted_candidate_image_id_invalid');
        durable(join(output,'interruption-candidate-snapshot.json'),{runId,taskId:activeRow.taskId,untrustedOnly:true,candidateSnapshot});
        const snapshot=skbStoppedSnapshot(activeDbPath,activeRow.id),backupPath=join(output,'interrupted-engine.sqlite');
        const python=Bun.which('python.exe');demand(python,'physical_backup_python_required');
        // Keep the event loop live while SQLite closes pending handles. A
        // synchronous child wait can block the parent-side close callbacks.
        const backup=await new Promise<{status:number|null,error:any,stdout:string,stderr:string}>(ok=>{
          const child=spawn(python,['-B',join(import.meta.dir,'backup_engine.py'),activeDbPath,backupPath],{cwd:ROOT,windowsHide:true,stdio:['ignore','pipe','pipe']});
          let stdout='',stderr='',error:any=null;
          const timer=setTimeout(()=>{error={name:'TimeoutError',message:'bounded_engine_backup_timeout'};child.kill();},30000);
          const append=(part:'stdout'|'stderr',body:Buffer)=>{if(part==='stdout')stdout+=body.toString();else stderr+=body.toString();if(stdout.length+stderr.length>65536){error={name:'OutputLimitError',message:'bounded_engine_backup_output'};child.kill();}};
          child.stdout?.on('data',b=>append('stdout',b));child.stderr?.on('data',b=>append('stderr',b));
          child.once('error',e=>{error=e;});
          child.once('close',status=>{clearTimeout(timer);ok({status,error,stdout,stderr});});
        });
        durable(join(output,'interruption-engine-backup-diagnostic.json'),{status:backup.status,error:backup.error?{name:backup.error.name,message:backup.error.message}:null,stdout:backup.stdout,stderr:backup.stderr});demand(backup.status===0,'interrupted_engine_backup_failed');
        const solverClosure=await request('/stop',{});
        const handoffPin=durable(join(output,'interruption-handoff.json'),{runId,taskValid:false,requestsDrained:true,toolsDrained:true,reason:fault,engineSnapshotPin:actualPin(backupPath),candidateSnapshot});
        const rawFinishes=readFileSync(join(output,'journal/api-events.jsonl'),'utf8').trim().split(/\r?\n/).filter(Boolean).map(l=>JSON.parse(l)).filter(r=>r.kind==='finish'&&r.record.route===activeRow.route);
        demand(rawFinishes.length===queue.taskReceipts(activeRow.route).length,'interrupted_original_finish_partition');
        interruption={...activeRow,protocol:'skillsbench-full-f-interrupted-attempt-v1',runId,terminal:false,valid:false,countsAsCompleted:false,reason:'actual_execution_or_provider_fault',actualTaskState:snapshot,denominator:87,handoffPin,apiCalls:rawFinishes.map(r=>({requestSeq:r.requestSeq,receipt:r.record})),originalGradePins:readdirSync(join(output,'stand')).filter(n=>/^grade-.*\.json$/.test(n)).map(n=>actualPin(join(output,'stand',n))),solverClosure,opaqueUntrustedCandidateSnapshot:candidateSnapshot};
      }catch(retainError){durable(join(output,'interruption-retention-failure.json'),{errorType:retainError instanceof Error?retainError.name:'Error',detail:retainError instanceof Error?retainError.message:String(retainError),originalFault:fault});}
    }
    updateStatus({phase:'failed',runtimeFailure:fault});throw error;}
  finally {
    for(const engine of engines)try{await engine.stop();}catch{}
    try{await gateway?.stop();}catch{}
    try{if(bridgeOrigin)await request('/shutdown',{});}catch{}
    if(bridge&&bridge.exitCode===null){bridge.kill();await new Promise<void>(ok=>{const timer=setTimeout(ok,3000);bridge!.once('exit',()=>{clearTimeout(timer);ok();});});}
    try{await proxy?.stop(true);}catch{}
    if(fault&&queue){const closure=await queue.retainFailure(fault.detail),financePin=durable(join(output,'accounting-failure.json'),closure);if(interruption){durable(join(output,'interrupted-attempt-'+interruption.index+'.json'),{...interruption,financePin});const cash=queue.state().cash;updateStatus({phase:closure.brokerClose?.closed?'segment_closed_pending_continuation':'native_closed_waiting_broker_recovery',modelRequests:prior.requestCount+queue.state().provider.journal.acceptedRequestCount,costUsd:prior.billedUsd+cash.billedUsd,unknownCostRequests:prior.unknownCostCount+cash.newUnknownCount,unknownReservationUsd:prior.unknownReservationUsd+cash.unknownReservationUsd,ownedContainersRemaining:0,ownedModelPending:0,interruptedAttemptPin:actualPin(join(output,'interrupted-attempt-'+interruption.index+'.json'))});}}
    if(previous.grader===undefined)delete process.env.TGENGIN_GRADER_TOKEN;else process.env.TGENGIN_GRADER_TOKEN=previous.grader;
    if(previous.origins===undefined)delete process.env.TGENGIN_GRADER_ORIGINS;else process.env.TGENGIN_GRADER_ORIGINS=previous.origins;
    if(previous.key===undefined)delete process.env.OBJRUN_SKB_FULL_F_PROXY_KEY;else process.env.OBJRUN_SKB_FULL_F_PROXY_KEY=previous.key;
    // Outer finally covers source archiving and bootstrap failures as well.
  }
  } finally {await heavy.release();}
}
