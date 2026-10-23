/** Fixed ten-task paired recipe. Availability of sources never implies readiness. */
import { join, resolve } from 'node:path';
import { actualPin,demand,hash,jsonPin,same,verifyPin,type Pin } from './paid-resource-proof-v2.ts';
import { loadSkbArtifactSelection,fixedSkbArtifactSchedule,assertSkbArtifactSchedule,SKB_ARTIFACT_FAMILY,SKB_ARTIFACT_MODEL,type SkbScheduleRow } from './skb-artifact-journal-contract-v2.ts';
import { loadSkbStorageDescriptor } from './skb-artifact-storage-v2.ts';

export const SKB_ROOT=resolve(import.meta.dir,'../..');
export type SkbRecipe={protocol:'skillsbench-ten-paired-recipe-v2';family:typeof SKB_ARTIFACT_FAMILY;runId:string;createdAtUtc:string;
  provider?:'openrouter-deepseek';currency?:'USD';
  providerKind:'local-mock'|'real-provider';selectedDistinctTasks:10;plannedTaskRuns:20;output:string;storageDescriptorPin:Pin;initialStorePin:Pin;
  taskDescriptorPins:Pin[];collectionIndexPin:Pin;coldControlIndexPin:Pin;originalShellIndexPin:Pin;fractionalControlPin:Pin;sixToolControlPin:Pin;
  runtimeGatePin?:Pin;sourcePins:Pin[];freezePin:Pin;prices:Pin;balance:Pin;deferredFault:Pin;originalPidClosure:Pin;
  balanceOverride:{authorized:true;userInstruction:'直接试跑 忽略余额';reserveCny:'0';balanceIsPrecondition:false};
  requestedNewEnvelopeCny:'100';capUsd:number;priorCampaignCostUpperBoundUsd:number;taskSchedule:SkbScheduleRow[];taskScheduleSha256:string;model:typeof SKB_ARTIFACT_MODEL;
};
export function validateSkbRecipe(r:SkbRecipe,paid=false){
  demand(r.protocol==='skillsbench-ten-paired-recipe-v2'&&r.family===SKB_ARTIFACT_FAMILY&&/^repair-[0-9TZ-]+$/.test(r.runId)
    &&r.selectedDistinctTasks===10&&r.plannedTaskRuns===20&&['local-mock','real-provider'].includes(r.providerKind),'skb_recipe_scope');
  demand(same(r.model,SKB_ARTIFACT_MODEL),'skb_fixed_model');
  if(r.currency!=='USD')demand(same(r.balanceOverride,{authorized:true,userInstruction:'直接试跑 忽略余额',reserveCny:'0',balanceIsPrecondition:false})&&r.requestedNewEnvelopeCny==='100','skb_legacy_override');
  const s=loadSkbArtifactSelection();assertSkbArtifactSchedule(r.runId,r.taskSchedule,s.tasks,r.taskScheduleSha256);
  demand(r.taskDescriptorPins.length===10&&same(r.taskDescriptorPins.map(p=>jsonPin(p).taskId),s.tasks.map(t=>t.taskId)),'skb_descriptor_order');
  for(const p of [...r.sourcePins,r.freezePin,r.prices,r.balance,r.deferredFault,r.originalPidClosure,r.initialStorePin,
    r.collectionIndexPin,r.coldControlIndexPin,r.originalShellIndexPin,r.fractionalControlPin,r.sixToolControlPin,...r.taskDescriptorPins])verifyPin(p,undefined,512*1024**2);
  demand(new Set(r.sourcePins.map(p=>resolve(p.path))).size===r.sourcePins.length,'skb_duplicate_sources');
  const storage=loadSkbStorageDescriptor(r.storageDescriptorPin,actualPin(join(import.meta.dir,'skb_artifact_storage_v2.py')));
  demand(resolve(r.output)===resolve(storage.directories.taskmeta!,'campaign-'+r.runId),'skb_exact_campaign_output');
  if(r.currency==='USD')demand(r.provider==='openrouter-deepseek'&&r.priorCampaignCostUpperBoundUsd===0&&Number.isFinite(r.capUsd)&&r.capUsd>0
    &&jsonPin(r.prices).protocol==='openrouter-usd-pricing-source-snapshot-v1'&&jsonPin(r.balance).protocol==='openrouter-usd-balance-readonly-v1','skb_openrouter_funding');
  else demand(Number.isFinite(r.priorCampaignCostUpperBoundUsd)&&r.priorCampaignCostUpperBoundUsd>=0&&r.capUsd===r.priorCampaignCostUpperBoundUsd+100,'skb_separate_legacy_usd_cap');
  if(paid)demand(r.providerKind==='real-provider'&&r.runtimeGatePin&&r.currency==='USD','skb_actual_runtime_gate_required');
  if(r.runtimeGatePin)verifyPin(r.runtimeGatePin);
  return {selection:s,storage};
}
