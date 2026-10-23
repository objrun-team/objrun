/** Grade validity is read from the actual task acceptance, never exit/DB state. */
import {existsSync,readdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {actualPin,jsonPin,verifyPin} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {base} from './review-authority-v4.ts';
export function retainedValidForTask(taskId:string){const directory=join(base,'valid-completions');if(!existsSync(directory))return null;for(const name of readdirSync(directory).filter(n=>n.endsWith('.json'))){const pin=actualPin(join(directory,name)),proof=jsonPin(pin);if(proof.taskId!==taskId||proof.valid!==true||proof.rerunForbidden!==true)continue;for(const field of ['summaryPin','taskPin','proofPin'])if(proof[field])verifyPin(proof[field]);return {pin,proof};}return null;}
export function inspectActualGrade(output:string,taskId:string){
 const processPin=actualPin(join(output,'process.json')),processInfo=jsonPin(processPin),summaryPin=actualPin(join(output,'summary.json')),summary=jsonPin(summaryPin);
 if(!(processInfo.taskId===taskId||(processInfo.executingTaskIds?.length===1&&processInfo.executingTaskIds[0]===taskId)))throw Error('actual_grade_worker_task_join');
 const tasks=readdirSync(output).filter(n=>/^task-\d+\.json$/.test(n)).map(n=>{const pin=actualPin(join(output,n)),task=jsonPin(pin);if(task.officialId!==taskId||task.runId!==processInfo.runId)throw Error('actual_grade_task_run_join');return {pin,task};});
 if(summary.recordedTaskRuns!==tasks.length)throw Error('actual_grade_record_count_mismatch');
 let disposition:string;
 const retained=retainedValidForTask(taskId);if(retained?.proof.runId===processInfo.runId){const root=retained.proof;if(root.protocol==='novaeve-root-retained-recovered-native-grade-v1'){if(root.rootReviewed!==true||!root.proofPin)throw Error('root_reviewed_cached_receipt_retention_required');const recovered=jsonPin(root.proofPin);if(recovered.taskId!==taskId||recovered.oldRunId!==processInfo.runId||recovered.modelCalls!==0||recovered.newGradingInvocations!==0||recovered.originalRunUnchanged!==true||recovered.derivedAcceptance?.valid!==true||recovered.derivedAcceptance?.passed!==root.passed)throw Error('recovered_original_grade_receipt_identity');verifyPin(recovered.gradePin);}disposition='valid_including_wrong_rerun_forbidden';}
 else if(tasks.some(t=>t.task.acceptance?.valid===true)){if(tasks.some(t=>t.task.acceptance?.valid===true&&t.task.generationValid!==true))throw Error('valid_acceptance_generation_inconsistent');disposition='valid_including_wrong_rerun_forbidden';}
 else if(tasks.length&&tasks.every(t=>t.task.acceptance?.valid===false&&t.task.acceptance?.outcome==='grader_error'))disposition='invalid_grade_waiting_reviewed_changed_setup';
 else if(!tasks.length&&summary.fatal)disposition='startup_or_transport_failure_requires_exact_closure';
 else disposition='unclassified_grade_requires_specific_audit';
 return {protocol:'novaeve-actual-task-grade-disposition-v8',taskId,runId:processInfo.runId,processPin,summaryPin,retainedProofPin:retained?.pin??null,cachedOriginalGradeRecoveryApplied:retained?.proof.protocol==='novaeve-root-retained-recovered-native-grade-v1'&&retained.proof.runId===processInfo.runId,taskPins:tasks.map(t=>t.pin),disposition,rerunForbidden:disposition==='valid_including_wrong_rerun_forbidden',acceptances:tasks.map(t=>({officialId:t.task.officialId,taskId:t.task.taskId,generationValid:t.task.generationValid,valid:t.task.acceptance?.valid,passed:t.task.acceptance?.passed,outcome:t.task.acceptance?.outcome,why:t.task.acceptance?.why})),modelCalls:0};
}
if(import.meta.main){const proof=inspectActualGrade(process.argv[2],process.argv[3]);if(process.argv[4])writeFileSync(process.argv[4],JSON.stringify(proof,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(proof));}
