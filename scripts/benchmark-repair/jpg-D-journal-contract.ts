/** Independent prospective D variant. Original JPG/scientific contracts remain frozen. */
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { JPG_EXECUTION_FILES, JPG_FAMILY, JPG_FROZEN, JPG_IMAGE, jpgSourceFiles as baseSourceFiles, loadJpgGates, assertJpgClosureShape, type JpgRecipe as BaseRecipe } from './jpg-journal-contract.ts';
import { loadJpgDDescriptor, type JpgDDescriptor } from './jpg-d-storage-profile.ts';
import { type FinancialInterruptedBoundary } from './financial-interruption-closure-v1.ts';
import { TASK_ID, PROTOCOL, ARTIFACT, SECONDS, VERIFY_SECONDS, CHECKS } from './skb-jpg-contract.ts';
export { JPG_FAMILY, JPG_FROZEN, JPG_IMAGE, loadJpgGates, assertJpgClosureShape, TASK_ID, PROTOCOL, ARTIFACT, SECONDS, VERIFY_SECONDS, CHECKS };

export const JPG_D_RECIPE_PROTOCOL='jpg-D-journal-recipe-v1';
export const JPG_D_EXECUTION_NAMES=[
  'skb-jpg-D-journal-campaign.ts','jpg-D-paid-resource-admission-v1.ts','audit-jpg-D-journal-campaign.py','jpg-D-journal-contract.ts',
  'jpg-D-native-service-v1.ts','jpg-D-stand-v1.py','jpg-D-store-init-v1.py','jpg-D-grade-parent-v1.py','jpg-d-storage-profile.ts','jpg_d_storage_profile.py','jpg_private_ram_profile.py','jpg_private_ram_executor.py',
  'financial-interruption-closure-v1.ts','jpg-financial-abort-scanner-v1.ts','financial-interruption-release.ts',
];
export const JPG_D_EXECUTION_FILES=[...JPG_EXECUTION_FILES,...JPG_D_EXECUTION_NAMES.map(n=>'scripts/benchmark-repair/'+n)];
export const JPG_D_FROZEN_BASE={
  'skb-jpg-journal-campaign.ts':'a03704a6eab65706e90a6bdf3e60f785e7930dcb24ec73fdccbe8d5cf72350cf',
  'audit-jpg-journal-campaign.py':'cb33c62c6f5f912e2309832532add56ec36d8239248355f304d3e52e800d8857',
  'jpg-paid-resource-admission-v1.ts':'f815f002fc0413c09e8fc0bbf28c96af19d41e608c8967ce601d8dcf0dae75d7',
  'jpg-journal-contract.ts':'b15a108e3d90b1626277368678e2593a6d8f2c883deb3a98a454f052912c301f',
  'skb-jpg-stand.py':'505d08b6862ffeace1bc693b44ade351e19ebcdee6041c8e2509e3ac0637c189',
  'skb-jpg-native-python.ts':'2a718024e4496bb7a3c05a4f095d22a24dd72cd51070f01bb367f60e15ab7db5',
};
export const JPG_D_FIXED_PRIVATE_SOURCES={
  'jpg_d_storage_profile.py':'0d0b20832d60248605a3e0314aa5e029091c536dc6f80e3bccf5623da1f18c17',
  'jpg_private_ram_profile.py':'00a9f978b9e2ae90d912a7bd48bc522107c6c0db50a6a6c91df5b800df122ee3',
  'jpg_private_ram_executor.py':'c00404ce4700a1702572f1960877ca7ff178b12dd35e01ead356064d469a5e59',
  'jpg-d-storage-profile.ts':'afbfb9d71fcc0652acb96bbfe72c05c8ae9889821127a1bceab158fbd202c7cc',
};
export type JpgDStorage={
  descriptorPin:Pin;storageSourcePin:Pin;storageModulePin:Pin;ramPlanPin:Pin;ramSourcePin:Pin;executorSourcePin:Pin;profileReviewPin:Pin;
  dockerClientPin:Pin;namespaceProofPin?:Pin;
};
export type JpgRecipe=Omit<BaseRecipe,'protocol'|'output'|'store'> & {
  protocol:typeof JPG_D_RECIPE_PROTOCOL;output:string;store:string;DStorage:JpgDStorage;financialBoundary:FinancialInterruptedBoundary;
};
/** This one implemented task is an engineering foundation, not the >=10 trial. */
export function assertJpgFoundationColdOnly(mode:string):void{
  demand(mode!=='run'&&mode!=='real-provider','jpg_foundation_cold_only_requires_at_least_ten_distinct_SKB_tasks');
}
const ROOT=resolve(import.meta.dir,'../..');
export function jpgSourceFiles(root:string){
  demand(resolve(root)===ROOT,'jpg_D_source_root');
  return [...new Map([...baseSourceFiles(root),...JPG_D_EXECUTION_NAMES.map(n=>actualPin(join(root,'scripts/benchmark-repair',n)))].map(p=>[resolve(p.path),p])).values()].sort((a,b)=>a.path.localeCompare(b.path));
}
export function loadDStorage(recipe:JpgRecipe):JpgDDescriptor{
  const s=recipe.DStorage;
  for(const p of Object.values(s))if(p)verifyPin(p);
  demand(resolve(s.storageSourcePin.path)===join(import.meta.dir,'jpg_d_storage_profile.py')&&resolve(s.storageModulePin.path)===join(import.meta.dir,'jpg-d-storage-profile.ts')&&resolve(s.ramSourcePin.path)===join(import.meta.dir,'jpg_private_ram_profile.py')&&resolve(s.executorSourcePin.path)===join(import.meta.dir,'jpg_private_ram_executor.py'),'jpg_D_actual_module_roles');
  const d=loadJpgDDescriptor(s.descriptorPin,s.storageSourcePin);
  demand(resolve(recipe.store)===resolve(d.storePhysical)&&resolve(recipe.output)===resolve(d.directories.taskmeta!),'jpg_D_recipe_stage_scope');
  const plan=jsonPin(s.ramPlanPin);
  demand(plan.protocol==='jpg-private-original-image-shared-ram-v1'&&plan.imageId===JPG_IMAGE&&plan.nonce===d.ownerNonce&&plan.privateSharedRamMaximumBytes===512*1024**2&&plan.privateMemoryBytes===4096*1024**2&&plan.privateCPUs===4&&plan.officialVerifierSeconds===600&&plan.hostBinds.length===0&&plan.actualReady===false,'jpg_D_private_planned_variant');
  demand(plan.sourceSha256===s.ramSourcePin.sha256,'jpg_D_ram_plan_source');
  const reviewed=jsonPin(s.profileReviewPin);
  demand(s.profileReviewPin.sha256==='2e4fa6841bf562da743150c127a2343c97c6267e17b5de8147c740c97b133d8f'&&reviewed.protocol==='jpg-D-storage-private-ram-review-exact-missing-target-r1'&&reviewed.paidReady===false&&reviewed.formalScoreCertified===false&&reviewed.models===0&&reviewed.DockerMutations===0&&reviewed.DWriteOperations===0&&reviewed.actualNamespaceProofPin===null&&reviewed.actualGradingControlsPin===null,'jpg_D_reviewed_preparation_only');
  demand(reviewed.executionPins.length===4,'jpg_D_reviewed_profile_source_count');
  for(const p of [s.storageSourcePin,s.storageModulePin,s.ramSourcePin,s.executorSourcePin])demand(reviewed.executionPins.some((row:Pin)=>same(row,p)),'jpg_D_reviewed_profile_sources');
  for(const [name,sha256]of Object.entries(JPG_D_FIXED_PRIVATE_SOURCES))verifyPin({path:join(import.meta.dir,name),sha256});
  for(const row of reviewed.executionPins)verifyPin(row);
  verifyPin(reviewed.executorSourceSnapshotPin);demand(reviewed.executorSourceSnapshotPin.sha256===s.executorSourcePin.sha256&&reviewed.executorSourceSnapshotPin.bytes===s.executorSourcePin.bytes,'jpg_D_executor_snapshot');
  for(const key of ['baseReviewPin','preRevisionArchivePin','necessaryDeltaControlsPin','actualReadOnlyObservationPin'])verifyPin(reviewed[key]);
  demand(reviewed.baseReviewPin.sha256==='d22c9b00a5c15a9088871f0eccc69c2725377cd10a241637bea4995aa8c037cd'&&reviewed.testCount===5&&reviewed.testExitCode===0,'jpg_D_source_revision_provenance');
  return d;
}
export function validateJpgRecipe(r:JpgRecipe){
  demand(r.protocol===JPG_D_RECIPE_PROTOCOL&&r.family===JPG_FAMILY&&/^repair-[0-9TZ-]+$/.test(r.runId),'jpg_D_recipe_scope');
  demand(['real-provider','local-mock'].includes(r.mode)&&r.formalPaidReady===false&&r.sourceTaskCount===87&&same(r.supportedTaskIds,[TASK_ID])&&r.unsupportedTaskCount===86,'jpg_D_denominator');
  demand(r.taskSeconds===SECONDS&&r.verifierSeconds===VERIFY_SECONDS&&r.checks===CHECKS&&Number.isFinite(r.capUsd)&&Number.isFinite(r.priorCampaignCostUpperBoundUsd)&&r.priorCampaignCostUpperBoundUsd>=0&&r.capUsd>r.priorCampaignCostUpperBoundUsd,'jpg_D_frozen_task_limits');
  demand(new Set(r.sourcePins.map(p=>resolve(p.path))).size===r.sourcePins.length,'jpg_D_source_duplicate');
  const expected=jpgSourceFiles(ROOT);demand(expected.length===r.sourcePins.length&&expected.every(p=>r.sourcePins.some(q=>resolve(p.path)===resolve(q.path)&&p.bytes===q.bytes&&p.sha256===q.sha256)),'jpg_D_complete_execution_source_set');
  for(const [name,sha256]of Object.entries(JPG_D_FROZEN_BASE))verifyPin({path:join(import.meta.dir,name),sha256});
  demand(r.artifacts.every(row=>/^(runtime|grader-dependencies|official|gates|storage)\//.test(row.name)&&!row.name.split(/[\\/]/).includes('..')&&!row.name.includes('\\'))&&new Set(r.artifacts.map(r=>r.name)).size===r.artifacts.length,'jpg_D_public_artifact_names');
  for(const p of [...r.sourcePins,...r.artifacts.map(row=>row.pin),...Object.values(r.gates),r.publicDependencyArchive,r.approvedNativeProfile,r.readinessPlan,r.prices,r.deferredFault,r.originalPidClosure,...Object.values(r.financialBoundary)])verifyPin(p);
  demand(r.hostRuntime.bunVersion===Bun.version&&resolve(r.hostRuntime.bun.path)===resolve(process.execPath)&&r.hostRuntime.distributionArchived===false,'jpg_D_host_runtime');verifyPin(r.hostRuntime.bun);verifyPin(r.hostRuntime.python);
  const oldPlan=jsonPin(r.readinessPlan);demand(oldPlan.protocol==='jpg-journal-paid-readiness-plan-v1'&&oldPlan.sourceTaskCount===87&&oldPlan.unsupportedTaskCount===86&&oldPlan.imageId===JPG_IMAGE&&r.gates.controls.sha256===oldPlan.gradingControls.sha256,'jpg_D_old_functional_gate');
  verifyPin(oldPlan.nativeSourceFreeze);verifyPin(oldPlan.nativeReview);
  const native=jsonPin(oldPlan.nativeSourceFreeze);for(const p of native.sources)verifyPin({path:join(ROOT,p.path),bytes:p.bytes,sha256:p.sha256});
  demand(r.approvedNativeProfile.sha256===native.sources.find((p:any)=>p.path==='scripts/benchmark-repair/skb-jpg-native-python.json')?.sha256,'jpg_D_native_profile_binding');
  if(r.mode==='real-provider')demand(r.balance&&r.requestedNewEnvelopeCny&&r.headroomCny==='30','jpg_D_explicit_cash_recipe');
  return loadDStorage(r);
}

/** One conservative reservation; legacy self-set floors are not counted twice. */
export function jpgDResourceRequirements(d:JpgDDescriptor,initial:boolean,solverActive:boolean,solverWritableBytes=0){
  demand(typeof initial==='boolean'&&typeof solverActive==='boolean'&&Number.isSafeInteger(solverWritableBytes)&&solverWritableBytes>=0&&solverWritableBytes<=256*1024**2&&d.solverUpperMaximumBytes===256*1024**2,'jpg_D_resource_state');
  return{C:d.CMinimumFreeBytes,D:d.DMinimumFreeBytes+(initial?d.storeMaximumAllocatedBytes:0),F:d.FMinimumFreeBytes+d.FPointerMaximumAllocatedBytes+d.dockerMetadataReserveBytes+d.FStopBufferBytes+(solverActive?d.solverUpperMaximumBytes-solverWritableBytes:0),solverRemainingFReservationBytes:solverActive?d.solverUpperMaximumBytes-solverWritableBytes:0,headroomCreditForVhdInternalSlack:0};
}
export function assertJpgDResourceObservation(d:JpgDDescriptor,free:Record<'C'|'D'|'F',number>,initial:boolean,solverActive:boolean,solverWritableBytes=0){
  const required=jpgDResourceRequirements(d,initial,solverActive,solverWritableBytes);
  demand(['C','D','F'].every(k=>Number.isSafeInteger(free[k as 'C'|'D'|'F'])&&free[k as 'C'|'D'|'F']>=required[k as 'C'|'D'|'F']),'jpg_D_physical_resource_guard');return{free,required,initial,solverActive};
}
