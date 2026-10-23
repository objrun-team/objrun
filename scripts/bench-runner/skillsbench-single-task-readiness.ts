/** Per-task original qualification joins; never promotes a neutral native proof. */
import {readFileSync} from 'node:fs';import {resolve} from 'node:path';import {verifyPin,demand} from './manifest.ts';
const read=(p:any)=>{verifyPin(p);return JSON.parse(readFileSync(p.path,'utf8'))};
export function requireSingleTaskSkillsBenchReadiness(row:any,proof:any,standEntryPin:any){
 demand(row?.taskId&&proof?.taskId===row.taskId,'single_task_readiness_identity');
 demand(['group02-adapter2-v1','group02-adapter3-v1'].includes(proof.adapter),'single_task_supported_original_adapter');
 demand(proof.builtImagesPin&&proof.controlPin&&proof.workerStandProofPin,'single_task_original_qualification_missing');
 const built=read(proof.builtImagesPin),controls=read(proof.controlPin),http=read(proof.workerStandProofPin);
 demand(built.taskId===row.taskId&&controls.taskId===row.taskId,'single_task_qualification_task_join');
 demand(controls.controlsPassed===true&&controls.ownedContainersRemaining===0&&JSON.stringify(controls.decisions??controls.cases?.map((x:any)=>x.reward))==='[0,1,0]','single_task_original_controls_required');
 demand(JSON.stringify(controls.builtImagesPin)===JSON.stringify(proof.builtImagesPin),'single_task_controls_build_join');
 for(const name of ['collectionPin','emptyPin','oraclePin','wrongPin'])verifyPin(controls[name]);
 const collection=read(controls.collectionPin);demand(collection.complete===true&&collection.mode==='collect'&&Array.isArray(collection.nodeIds)&&collection.nodeIds.length>0,'single_task_original_full_collection_required');
 demand(http.actualSixHttpRoutesQualified===true&&http.modelCalls===0&&http.newPaidRequests===0&&!http.error,'single_task_real_six_http_qualification_required');
 demand(http.closed?.ownedContainersRemaining===0&&http.workerStandChildExit===0,'single_task_http_custody_closure_required');
 verifyPin(proof.qualificationRuntimePin);verifyPin(http.runtimePin);demand(JSON.stringify(http.runtimePin)===JSON.stringify(proof.qualificationRuntimePin),'single_task_actual_qualification_runtime_join');
 verifyPin(proof.workerConfigPin);const config=read(proof.workerConfigPin);demand(JSON.stringify(config.builtImagesPin)===JSON.stringify(proof.builtImagesPin)&&JSON.stringify(config.controlPin)===JSON.stringify(proof.controlPin),'single_task_http_build_control_join');
 verifyPin(standEntryPin);verifyPin(proof.actualStandEntryPin);
 demand(resolve(standEntryPin.path)===resolve(proof.actualStandEntryPin.path)&&standEntryPin.sha256===proof.actualStandEntryPin.sha256,'single_task_qualified_stand_entry_join');
 demand(proof.neutralOnly!==true&&proof.formalReady!==false,'single_task_neutral_is_not_qualification');
 return{taskId:row.taskId,built,controls,http,proof};
}
