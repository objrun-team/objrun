/** Concrete paired pilot recipe from actual closed cold controls; zero models. */
import { join,resolve } from 'node:path';
import { actualPin,demand,hash,jsonPin,type Pin } from './paid-resource-proof-v2.ts';
import { durableJpgJson } from './jpg-paid-resource-admission-v1.ts';
import { fixedSkbArtifactSchedule,loadSkbArtifactSelection,SKB_ARTIFACT_FAMILY,SKB_ARTIFACT_MODEL } from './skb-artifact-journal-contract-v2.ts';
import { validateSkbRecipe,type SkbRecipe } from './skb-artifact-recipe-v2.ts';
import { prepareOpenRouterFunding } from './openrouter-paid-admission.ts';

export async function prepareSkbPilot(p:{providerKind:'local-mock'|'real-provider';storageDescriptorPin:Pin;initialStorePin:Pin;freezePin:Pin;collectionIndexPin:Pin;coldControlIndexPin:Pin;originalShellIndexPin:Pin;fractionalControlPin:Pin;sixToolControlPin:Pin;prices:Pin;balance:Pin;runtimeGatePin?:Pin}){
  const root=resolve(import.meta.dir,'../..'),selected=loadSkbArtifactSelection(),runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-');
  const storage=jsonPin(p.storageDescriptorPin),frozen=jsonPin(p.freezePin),collections=jsonPin(p.collectionIndexPin),schedule=fixedSkbArtifactSchedule(runId,selected.tasks);
  // Mock controls do not need the unrelated live paid family's prior scanner.
  const prior=0;
  const r:SkbRecipe={protocol:'skillsbench-ten-paired-recipe-v2',family:SKB_ARTIFACT_FAMILY,runId,createdAtUtc:new Date().toISOString(),providerKind:p.providerKind,
    selectedDistinctTasks:10,plannedTaskRuns:20,output:join(storage.directories.taskmeta,'campaign-'+runId),...p,sourcePins:frozen.sourcePins,
    taskDescriptorPins:collections.taskDescriptorPins,taskSchedule:schedule,taskScheduleSha256:hash(JSON.stringify(schedule)),model:SKB_ARTIFACT_MODEL,
    deferredFault:actualPin(join(root,'test/fixtures/repair/scientific-campaign-deferred-fault.json')),
    originalPidClosure:actualPin(join(root,'test/fixtures/repair/science1220-oom-original-process-closure.json')),
    balanceOverride:{authorized:true,userInstruction:'直接试跑 忽略余额',reserveCny:'0',balanceIsPrecondition:false},requestedNewEnvelopeCny:'100',priorCampaignCostUpperBoundUsd:prior,capUsd:prior+100};
  if(p.providerKind==='real-provider')Object.assign(r,await prepareOpenRouterFunding(root,r.output),{provider:'openrouter-deepseek',currency:'USD',priorCampaignCostUpperBoundUsd:0});
  validateSkbRecipe(r,p.providerKind==='real-provider');const pin=durableJpgJson(join(r.output,'prepared-recipe.json'),r);
  const pointer=durableJpgJson(join(root,'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/pilot-recipes',runId,'recipe-pointer.json'),{protocol:'skillsbench-ten-pilot-recipe-pointer-v2',recipePin:pin,providerKind:p.providerKind,runId,modelCalls:0,paidReady:false});
  return {recipePin:pin,pointerPin:pointer,runId,modelCalls:0,paidLockAcquired:false};
}
if(import.meta.main){const file=process.argv[2];demand(file,'skb_actual_pilot_inputs');const value=jsonPin(actualPin(resolve(file)));console.log(JSON.stringify(await prepareSkbPilot(value)));}
