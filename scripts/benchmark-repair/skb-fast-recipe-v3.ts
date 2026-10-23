/** Fixed original list/model/budgets; user requested fast draft and no usage cap. */
import {join,resolve} from 'node:path';
import {actualPin,demand,hash,jsonPin} from './paid-resource-proof-v2.ts';
import {durableJpgJson} from './jpg-paid-resource-admission-v1.ts';
import {loadSkbArtifactSelection,fixedSkbArtifactSchedule,SKB_ARTIFACT_FAMILY,SKB_ARTIFACT_MODEL} from './skb-artifact-journal-contract-v2.ts';
import {prepareOpenRouterFunding} from './openrouter-paid-admission.ts';
const ROOT=resolve(import.meta.dir,'../..');
export async function prepareFastRecipe(file:string){
 const input=jsonPin(actualPin(resolve(file))),selected=loadSkbArtifactSelection(),runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-'),s=jsonPin(input.storageDescriptorPin);
 const schedule=fixedSkbArtifactSchedule(runId,selected.tasks),recipe={...input,protocol:'skillsbench-fast-first-recipe-v3',family:SKB_ARTIFACT_FAMILY,runId,
   output:join(s.directories.taskmeta,'campaign-'+runId),providerKind:'real-provider',selectedDistinctTasks:10,plannedTaskRuns:20,draftFastFirst:true,concurrency:2,
   taskSchedule:schedule,taskScheduleSha256:hash(JSON.stringify(schedule)),model:SKB_ARTIFACT_MODEL,forwardSourcePins:input.sourcePins,
   provider:'openrouter-deepseek',currency:'USD',priorCampaignCostUpperBoundUsd:0,
   deferredFault:actualPin(join(ROOT,'docs/repair-2026-10-08/scientific-campaign-deferred-fault.json')),
   originalPidClosure:actualPin(join(ROOT,'docs/repair-2026-10-08/science1220-oom-original-process-closure.json')),
   userPriority:'最快初版，真实固定10题U/F20次，允许并发，不受余额、API用量、运营预留和旧费用上限限制；完整ZIP，未完成认证明确待补',
   fullEnvironmentCertificationPending:true,formalScoreCertified:false,full87Authorized:false};
 Object.assign(recipe,await prepareOpenRouterFunding(ROOT,recipe.output));
 const p=durableJpgJson(join(recipe.output,'prepared-recipe.json'),recipe);durableJpgJson(join(ROOT,'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/pilot-recipes',runId,'recipe-pointer.json'),{recipePin:p,runId,providerKind:'real-provider',draftFastFirst:true});
 return {recipePin:p,runId,modelCalls:0};
}
if(import.meta.main){demand(process.argv[2],'skb_fast_inputs');console.log(JSON.stringify(await prepareFastRecipe(process.argv[2])));}
