/** Draft only. Coordinator must add actual Stand acceptance before publishing. */
import {mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,jsonPin,verifyPin,demand} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {validateRuntimeReadiness} from '../runtime_private_task_adapter2_20261013_v1.ts';
const controlPin=actualPin(process.argv[2]),output=resolve(process.argv[3]);verifyPin(controlPin);
const control=jsonPin(controlPin);
demand(['fix-visual-stability','multilingual-video-dubbing','reserves-at-risk-calc'].includes(control.taskId),'owned_task_required');
demand(control.controlsPassed&&control.modelCalls===0&&control.ownedContainersRemaining===0&&JSON.stringify(control.decisions)==='[0,1,0]','original_controls_required');
for(const key of ['builtImagesPin','collectionPin','emptyPin','oraclePin','wrongPin'])verifyPin(control[key]);
const collection=jsonPin(control.collectionPin);demand(collection.complete&&collection.mode==='collect'&&collection.nodeIds.length>0,'actual_collection_required');
const draft={protocol:'group01-adapter2-publication-draft-v1',taskId:control.taskId,published:false,readyRegistered:false,native_ready:false,modelCalls:0,
  controlPin,builtImagesPin:control.builtImagesPin,adapter:'group01-adapter2-v1',
  workerEntryPin:actualPin(join(import.meta.dir,'private_task_worker_entry_adapter2_20261013_v1.ts')),
  workerSourcePin:actualPin(join(import.meta.dir,'../runtime_private_task_adapter2_20261013_v1.ts')),
  standSourcePin:actualPin(join(import.meta.dir,'../data_stand_adapter2_20261013_v1.py')),
  coordinatorIntegration:'Require actual six-tool Stand up/begin/place/ran/passed/close receipts, retain DeepSeek solver configuration, select this worker in sole existing scheduler. No automatic ready registration.'};
mkdirSync(output,{recursive:true});writeFileSync(join(output,'publication-draft.json'),JSON.stringify(draft,null,2),{flag:'wx'});
const at=process.argv.indexOf('--inputs');
if(at>=0){
 const inputPin=actualPin(resolve(process.argv[at+1])),input=jsonPin(inputPin);
 for(const name of ['manifestPin','priorPin','productionPlanPin','readinessPin','standContractPin'])verifyPin(input[name]);
 const manifest=jsonPin(input.manifestPin),prior=jsonPin(input.priorPin),ready=jsonPin(input.readinessPin),production=jsonPin(input.productionPlanPin);
 demand(manifest.denominator===87&&manifest.taskSchedule.length===87&&manifest.taskSchedule.some((r:any)=>r.taskId===control.taskId),'original_full87_manifest');
 demand(prior.pending.some((r:any)=>r.taskId===control.taskId)&&![...(prior.records??[]),...(prior.nonconformingRecords??[])].some((r:any)=>r.taskId===control.taskId),'paid_or_terminal_repeat_forbidden');
 const proof={adapter:'group01-adapter2-v1',builtImagesPin:control.builtImagesPin,controlPin,standContractPin:input.standContractPin};
 const next={...ready,taskReadiness:{...ready.taskReadiness,[control.taskId]:proof}};next.full87Validated=Object.keys(next.taskReadiness).length===87;
 validateRuntimeReadiness(manifest,next);
 const save=(name:string,value:any)=>{const path=join(output,name);writeFileSync(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(path);};
 const readinessPin=save('runtime-readiness.snapshot.json',next);
 const root=resolve(import.meta.dir,'../../../../..'),descriptorPin=actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench/task-descriptors',control.taskId+'.json')),descriptor=jsonPin(descriptorPin);
 const sourcePins=[actualPin(import.meta.path),draft.workerEntryPin,draft.workerSourcePin,draft.standSourcePin,...jsonPin(input.standContractPin).sourcePins];
 const workerPlan={protocol:'skillsbench-private-task-worker-plan-v2',denominator:87,targetTaskId:control.taskId,sharedBrokerRunId:input.sharedBrokerRunId??production.sharedBrokerRunId,
  runIdAssignedAfterResourceAdmission:true,manifestPin:input.manifestPin,priorPin:input.priorPin,readinessPin,planPin:descriptorPin,
  originalPlannedGrowthBytes:descriptor.originalResources.environment.storage_mb*1024**2,originalPeakMemoryMb:Math.max(8192,2*descriptor.originalResources.environment.memory_mb),
  sourcePins,productionPlanPin:input.productionPlanPin,qualificationPin:controlPin,standContractPin:input.standContractPin,coordinatorReviewed:false,dispatchEnabled:false};
 demand(typeof workerPlan.sharedBrokerRunId==='string'&&workerPlan.sharedBrokerRunId.length>0,'existing_shared_broker_epoch_required');
 const workerPlanPin=save('worker-plan.json',workerPlan);
 const eventJobPin=save('event-job.json',{protocol:'skillsbench-task-adapter-unregistered-job-v1',taskId:control.taskId,modelCalls:0,readyRegistration:false,published:false,dispatchEnabled:false,
  workerEntryPin:draft.workerEntryPin,workerSourcePin:draft.workerSourcePin,workerPlanPin,readinessPin,inputPin,productionPlanPin:input.productionPlanPin,
  taskWorkerRoutes:{[control.taskId]:{workerEntryPin:draft.workerEntryPin,runtimePin:draft.workerSourcePin}},
  argv:[process.execPath,'run',draft.workerEntryPin.path,workerPlanPin.path],solverConfiguration:'existing DeepSeek/DigitalOcean configuration preserved',remainingPublicationGate:'coordinator source review and existing sole scheduler publication; draft worker refuses dispatch until explicitly reviewed'});
 console.log(JSON.stringify({draftPin:actualPin(join(output,'publication-draft.json')),workerPlanPin,eventJobPin,published:false}));
}else console.log(JSON.stringify({draftPin:actualPin(join(output,'publication-draft.json')),published:false,workerPlanRequiresOptionalInputs:true}));
