/** Source-bound ACC gate; cold tests alone cannot certify runtime readiness. */
import {jsonPin,verifyPin,demand,hash} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
export function validateAccReadiness(row:any,proof:any){
 demand(row.taskId==='adaptive-cruise-control'&&proof.adapter==='acc-independent-v1','exact_acc_adapter_scope');
 for(const p of proof.packageSourcePins.concat([proof.runtimeCorePin,proof.snapshotAdapterPin,proof.bundlePin,proof.preparedImageResultPin,proof.builtImagesPin,proof.controlPin,proof.runtimeAcceptancePin,proof.standAcceptancePin,proof.privateImageInspectPin]))verifyPin(p);
 const prepared=jsonPin(proof.preparedImageResultPin),built=jsonPin(proof.builtImagesPin),cold=jsonPin(proof.controlPin),runtime=jsonPin(proof.runtimeAcceptancePin),stand=jsonPin(proof.standAcceptancePin);
 demand(hash(JSON.stringify(row.originalResources))===hash(JSON.stringify(prepared.originalResources)),'original_acc_resources_unchanged');
 demand(hash(JSON.stringify(prepared.builtImagesPin))===hash(JSON.stringify(proof.builtImagesPin))&&prepared.actualCollection.taskId===row.taskId,'actual_acc_build_join');
 const collection=prepared.actualCollection;
 demand(collection.mode==='collect'&&collection.complete&&collection.pytestExitCode===0&&collection.nodeIds.length===12,'actual_acc_full12_collection');
 demand(cold.protocol==='skillsbench-acc-real-independent-cold-controls-v1'&&cold.controlsPassed&&cold.ownedContainersRemaining===0&&JSON.stringify(cold.cases.map((x:any)=>x.reward))==='[0,1,0]','actual_acc_cold_required');
 demand(hash(JSON.stringify(cold.preparedImageResultPin))===hash(JSON.stringify(proof.preparedImageResultPin))&&hash(JSON.stringify(cold.bundlePin))===hash(JSON.stringify(proof.bundlePin)),'acc_cold_source_join');
 for(const item of cold.cases){verifyPin(item.resultPin);verifyPin(item.preamblePin);const grade=jsonPin(item.resultPin);demand(grade.complete&&JSON.stringify(grade.nodeIds)===JSON.stringify(collection.nodeIds)&&grade.candidateSnapshotUsed===false&&grade.candidateExecutablesUsed===false,'acc_cold_full_private_grades');}
 demand(runtime.protocol==='skillsbench-acc-real-stopped-snapshot-refresh-control-v1'&&runtime.verified&&runtime.ownedContainersRemaining===0&&runtime.modelCalls===0&&runtime.candidateSnapshotUsedForTrustedGrader===false&&JSON.stringify(runtime.steps.map((s:any)=>s.reward))==='[0,1,0]','acc_actual_snapshot_refresh_required');
 for(const item of runtime.steps){verifyPin(item.gradePin);verifyPin(item.evaluationPin);const grade=jsonPin(item.gradePin);demand(grade.complete&&JSON.stringify(grade.nodeIds)===JSON.stringify(collection.nodeIds)&&grade.candidateSnapshotUsed===false&&grade.candidateExecutablesUsed===false,'acc_snapshot_full_private_grades');}
 demand(jsonPin(proof.privateImageInspectPin)[0].Id===proof.privateImageId&&proof.privateImageId!==built.candidateImageId,'acc_private_image_independent');
 demand(stand.protocol==='skillsbench-acc-real-stand-refresh-controls-v1'&&stand.verified&&stand.modelCalls===0&&stand.ownedContainersRemaining===0&&stand.skillsReadVerified&&stand.skillsHelperExecuted&&JSON.stringify(stand.steps.map((s:any)=>s.reward))==='[0,1,0]','acc_actual_stand_and_skills_required');
 for(const p of stand.sourcePins)verifyPin(p);
 for(const step of stand.steps){verifyPin(step.gradeOwnerPin);const grade=jsonPin(step.gradeOwnerPin);demand(grade.result.complete&&JSON.stringify(grade.result.nodeIds)===JSON.stringify(collection.nodeIds)&&grade.result.candidateSnapshotUsed===false&&grade.result.candidateExecutablesUsed===false,'acc_actual_stand_full_grades');}
 demand(new Set(stand.steps.map((s:any)=>s.gradeOwnerPin.path)).size===3&&stand.latestPassedReceiptMatchesLastVerify===true,'acc_latest_scoring_required');
 return proof.packageSourcePins.concat([proof.runtimeCorePin,proof.snapshotAdapterPin,proof.bundlePin]);
}
