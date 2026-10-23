/** Independent >=10 SkillsBench entry. Preparation is the default/no-runtime path. */
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { durableJpgJson } from './jpg-D-paid-resource-admission-v1.ts';
import { fixedSkbArtifactSchedule, loadSkbArtifactSelection, SKB_ARTIFACT_FAMILY, SKB_ARTIFACT_MODEL, type SkbScheduleRow } from './skb-artifact-journal-contract-v2.ts';

const ROOT=resolve(import.meta.dir,'../..');
export const SKB_ARTIFACT_RUNTIME_SOURCE_NAMES=[
  'benchmark-inference.ts','benchmark-provider.ts','benchmark-usd-cash.ts','openrouter-paid-admission.ts',
  'skb-artifact-journal-campaign-v2.ts','skb-artifact-journal-contract-v2.ts','skb-artifact-journal-core-v2.ts','skb-artifact-paid-admission-v2.ts',
  'audit-skb-artifact-journal-v2.py','skb-artifact-native-service-v2.ts','skb-artifact-stand-v2.py','skb-artifact-storage-v2.ts',
  'skb_artifact_storage_v2.py','skb_artifact_task_v2.py','skb_artifact_capture_v2.py','skb_artifact_private_eval_v2.py','skb_artifact_ram_executor_v2.py','skb_artifact_transport_v2.py','skb_artifact_solver_plan_v2.py',
  'skb_artifact_solver_v2.py','skb_artifact_solver_audit_v2.py','skb_artifact_ram_plan_v2.py','skb_artifact_grade_audit_v2.py','skb_artifact_ready_v2.py',
  'skb_artifact_build_audit_v2.py','skb_artifact_build_storage_v1.py','skb_artifact_native_identity_v2.py','skb-artifact-recipe-v2.ts','skb-artifact-runtime-v2.ts',
  'skb-artifact-tool-gateway-v2.ts','skb-artifact-resource-observer-v2.py','audit-skb-artifact-journal-v2.ts','freeze-skb-artifact-v2.py',
  'audit-skb-artifact-readiness-v2.py',
  'skb-artifact-secret-audit-v2.py','skb-artifact-prepare-pilot-v2.ts',
  'skb-tb12-closed-scan-v2.ts','skb_artifact_tb12_scan_v2.py',
];
export type SkbArtifactPreparation={
  protocol:'skillsbench-artifact-journal-preparation-v1';family:typeof SKB_ARTIFACT_FAMILY;runId:string;createdAtUtc:string;purpose:'prospective-ten-task-paired-pilot';
  sourceTaskCount:87;selectedTaskCount:10;unselectedTaskCount:77;plannedTaskRuns:20;arms:['U','F'];taskSchedule:SkbScheduleRow[];taskScheduleSha256:string;
  model:typeof SKB_ARTIFACT_MODEL;sourcePins:Pin[];runtimeSourceSetComplete:boolean;pendingSourceFiles:string[];selectionPin:Pin;publicMetadataPin:Pin;
  taskDescriptorPins:Pin[];descriptorPreparationComplete:boolean;paidReady:false;actualDockerUFPilotValidated:false;modelCalls:0;DockerOperations:0;DWrites:0;locksAcquired:0;
};

/** Only public source identity and prospective plans are read/written here. */
export function prepareSkbArtifactJournal(input:{taskDescriptorPins?:Pin[]}={}){
  const selected=loadSkbArtifactSelection(),runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-'),folder=join(ROOT,'docs/repair-2026-10-08/skillsbench-artifact-preparations-v2',runId);
  demand(!existsSync(folder),'skb_prospective_preparation_exists');mkdirSync(folder,{recursive:true});
  const rows=fixedSkbArtifactSchedule(runId,selected.tasks),sourcePins:Pin[]=[],pendingSourceFiles:string[]=[];
  for(const name of SKB_ARTIFACT_RUNTIME_SOURCE_NAMES){const path=join(import.meta.dir,name);if(existsSync(path))sourcePins.push(actualPin(path));else pendingSourceFiles.push(path);}
  // Source availability is not a reviewed/frozen executable or scoring gate.
  const descriptorPins=input.taskDescriptorPins??[];for(const p of descriptorPins)verifyPin(p);
  demand(new Set(descriptorPins.map(p=>resolve(p.path))).size===descriptorPins.length&&descriptorPins.length<=10,'skb_descriptor_preparation_inventory');
  const descriptors=descriptorPins.map(p=>jsonPin(p));
  if(descriptors.length)demand(same(descriptors.map(d=>d.taskId),selected.tasks.map(t=>t.taskId))&&descriptors.length===10,'skb_descriptors_fixed_order');
  const plan:SkbArtifactPreparation={protocol:'skillsbench-artifact-journal-preparation-v1',family:SKB_ARTIFACT_FAMILY,runId,createdAtUtc:new Date().toISOString(),purpose:'prospective-ten-task-paired-pilot',
    sourceTaskCount:87,selectedTaskCount:10,unselectedTaskCount:77,plannedTaskRuns:20,arms:['U','F'],taskSchedule:rows,taskScheduleSha256:hash(JSON.stringify(rows)),model:SKB_ARTIFACT_MODEL,
    sourcePins,runtimeSourceSetComplete:pendingSourceFiles.length===0,pendingSourceFiles,selectionPin:selected.selectionPin,publicMetadataPin:selected.metadataPin,
    taskDescriptorPins:descriptorPins,descriptorPreparationComplete:descriptors.length===10,paidReady:false,actualDockerUFPilotValidated:false,modelCalls:0,DockerOperations:0,DWrites:0,locksAcquired:0};
  const planPin=durableJpgJson(join(folder,'preparation.json'),plan);
  durableJpgJson(join(folder,'scope.json'),{protocol:'skillsbench-artifact-prospective-scope-v1',family:SKB_ARTIFACT_FAMILY,runId,preparationPin:planPin,sourceTaskCount:87,selectedDistinctTasks:10,plannedTaskRuns:20,
    completed:false,formalScoreCertified:false,modelCalls:0,DockerOperations:0,DWrites:0,locksAcquired:0,minimumTrialDistinctTasks:10,benchmarkTrialRequirementMet:false,
    inputProtocol:'Exact untrimmed raw YAML-frontmatter body, separately from whole task.md SHA.',
    scoreProtocol:'Each original evaluator/complete collected test set; fractional lab reward remains numeric. Source availability/static tests are not actual collection.',
    remainingActualGates:['ten full image/build/depot/source identities','each actual private namespace and read-only original interpreter','each full original collected test set and bounded official empty/oracle/wrong controls','fresh D owner/resource/cache layout','cash/source/raw/owned lifecycle and independent family closing audits','Root-reviewed prospective paired recipe/operator budget']});
  return{preparationPin:planPin,runId,sourceTaskCount:87,selectedDistinctTasks:10,plannedTaskRuns:20,modelCalls:0,DockerOperations:0,DWrites:0,locksAcquired:0,paidReady:false,missingRuntimeSources:pendingSourceFiles.length};
}

if(import.meta.main){
  const [mode='prepare',...args]=process.argv.slice(2),option=(name:string)=>{const n=args.indexOf(name);return n<0?undefined:args[n+1];};
  if(mode==='prepare'){
    const descriptors=option('--task-descriptors');const taskDescriptorPins=descriptors?JSON.parse(readFileSync(verifyPin(actualPin(resolve(descriptors))),'utf8')):undefined;
    console.log(JSON.stringify(prepareSkbArtifactJournal({taskDescriptorPins})));
  }else{
    // The shared runtime will be wired only to the independently reviewed new
    // storage/capture/private executor ABI. Never fall back to the JPG scorer.
    demand(mode==='runtime-control'||mode==='run','skb_explicit_mode');
    const recipe=option('--recipe');demand(recipe,'skb_exact_recipe_required');
    const {runSkbArtifactRuntime}=await import('./skb-artifact-runtime-v2.ts');
    console.log(JSON.stringify(await runSkbArtifactRuntime(actualPin(resolve(recipe)),mode)));
  }
}
