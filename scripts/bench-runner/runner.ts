import {mkdirSync,writeFileSync,existsSync,readFileSync,copyFileSync,constants} from 'node:fs';
import {join,resolve} from 'node:path';
import {STAGES,type TaskManifest,type StageName,type BenchAdapter,type AttemptContext,type StageResult,type Pin} from './types.ts';
import {loadManifest,pin,verifyPin,demand} from './manifest.ts';
import {DurableQueue} from './queue.ts';
import {assertAdmission,assertContinuation} from './admission.ts';
import {retainValidResult} from './retention.ts';
export interface RunOptions {manifestPath:string;admissionControlPath:string;checkOnly?:boolean;dryRun?:boolean;stage?:StageName;attemptId?:string}
function validateResult(r:StageResult){
 demand(r&&['complete','retryable','invalid','unknown','valid'].includes(r.status)&&typeof r.nativeClosed==='boolean'&&typeof r.financialClosed==='boolean'&&typeof r.candidateOrSubmissionPresent==='boolean','adapter_result_schema');
 demand(r.proofPins.length>0,'adapter_result_proof_required');for(const p of r.proofPins)verifyPin(p);
 if(r.status==='valid')demand(r.validResult&&typeof r.validResult.passed==='boolean'&&typeof r.validResult.outcome==='string','valid_requires_original_acceptance_proof');
}
function archiveResult(r:StageResult,runDir:string,context?:AttemptContext):StageResult {
 const directory=join(runDir,'archived-proofs');mkdirSync(directory,{recursive:true});const copies=[];
 const proofs=[...r.proofPins,...(r.validResult?[r.validResult.proofPin]:[]),...Object.values(r.completedStages??{}).flatMap(x=>x!.proofPins)];
 for(const p of proofs){verifyPin(p);const target=join(directory,p.sha256+'.artifact');if(!existsSync(target))copyFileSync(p.path,target,constants.COPYFILE_EXCL);const copy=pin(target);demand(copy.bytes===p.bytes&&copy.sha256===p.sha256,'archive_custody_mismatch');verifyPin(p);copies.push({original:p,archived:copy})}
 const receipt=join(runDir,'archived-result.json');writeFileSync(receipt,JSON.stringify({taskId:context?.taskId,bench:context?.bench,manifestPin:context?.manifestPin,result:r,copies},null,2)+'\n',{flag:'wx'});
 return {...r,proofPins:[...r.proofPins,...copies.map(p=>p.archived),pin(receipt)]};
}
export class Runner {
 constructor(readonly queue:DurableQueue,readonly getAdapter:(bench:TaskManifest['bench'])=>BenchAdapter){}
 check(path:string){const m=loadManifest(path);this.getAdapter(m.bench).validate(m);const key=this.queue.key(m.bench,m.taskId),t=this.queue.task(key);return{valid:true,taskKey:key,imported:!!t,permanentValid:!!t?.valid,quarantined:!!t?.quarantined,stages:STAGES.filter(s=>m.stages[s]).map(s=>({stage:s,queue:['prepare','qualify'].includes(s)?'preparation':'formal',effect:m.stages[s]!.effect,kind:m.stages[s]!.kind})),spawned:false,modelCalls:0}}
 nextStage(m:TaskManifest):StageName|undefined {const key=this.queue.key(m.bench,m.taskId),valid=!!this.queue.task(key)?.valid;return STAGES.find(s=>m.stages[s]&&this.queue.stage(key,s)?.state!=='complete'&&(!valid||['cleanup','reconcile','archive'].includes(s)))}
 private continuation(key:string,stage:StageName,spec?:TaskManifest['stages'][StageName]){if(!['grade','cleanup','reconcile','archive'].includes(stage))return false;if(stage==='grade')return !!this.queue.task(key)?.valid||['running','complete'].includes(this.queue.stage(key,'solve')?.state);return !!this.queue.task(key)?.valid||!!this.queue.stage(key,'solve')||spec?.kind==='reuse'||spec?.effect==='read-only'}
 private context(m:TaskManifest,path:string,admission:string,id:string,stage:StageName,runDir:string):AttemptContext{return{attemptId:id,taskId:m.taskId,bench:m.bench,stage,runDir,manifestPath:resolve(path),manifestPin:pin(path),admissionControlPath:resolve(admission),inventoryTask:this.queue.inventory(this.queue.key(m.bench,m.taskId))}}
 private retrySuccessor(m:TaskManifest,c:AttemptContext,r:StageResult){if(r.status!=='retryable')return;const policyPin=m.adapterConfig.retryPolicyPin as Pin|undefined;if(!policyPin)return{retryBlocked:'reviewed_retry_policy_required'};try{const {deriveRetryManifest}=require('./recovery.ts');const successor=deriveRetryManifest({manifestPath:c.manifestPath,context:c,result:r,policyPin});this.queue.event('retry-successor-awaiting-root-signature',this.queue.key(m.bench,m.taskId),c.attemptId,successor);return{retrySuccessor:successor}}catch(error){const reason=String(error);this.queue.event('retry-derivation-blocked',this.queue.key(m.bench,m.taskId),c.attemptId,{reason});return{retryBlocked:reason}}}
 private retention(m:TaskManifest,c:AttemptContext,r:StageResult){if(r.status!=='valid'||!r.nativeClosed||!r.financialClosed)return;try{return{retainedPin:retainValidResult(m,c,r)}}catch(error){const pending={reason:String(error),permanentValidNoRetry:true,manifestPin:c.manifestPin,proofPins:r.proofPins};this.queue.event('retention-sync-pending',this.queue.key(m.bench,m.taskId),c.attemptId,pending);return{retentionSyncPending:pending}}}
 async plan(o:RunOptions){
  const m=loadManifest(o.manifestPath);this.getAdapter(m.bench).validate(m);const key=this.queue.key(m.bench,m.taskId),stage=o.stage??this.nextStage(m);demand(stage,'no_unfinished_stage');demand(!this.queue.task(key)?.valid||['cleanup','reconcile','archive'].includes(stage),'valid_task_never_rerun');
  const existing=this.queue.planned(key,stage);const claim=existing?{id:existing.id,runDir:existing.run_dir}:this.queue.claim(key,stage,pin(o.manifestPath),id=>join(m.artifactRoot,m.bench,m.taskId,id,stage),true);
  if(existing)demand(JSON.parse(existing.manifest_pin).sha256===pin(o.manifestPath).sha256,'planned_manifest_changed');
  const context=this.context(m,o.manifestPath,o.admissionControlPath,claim.id,stage,claim.runDir);mkdirSync(context.runDir,{recursive:true});const cp=join(context.runDir,'planned-context.json');if(!existsSync(cp))writeFileSync(cp,JSON.stringify(context,null,2)+'\n',{flag:'wx'});
  let binding:any;if(m.adapterConfig.bindingSpec&&m.stages[stage]!.kind==='command'){const request=join(context.runDir,'binding-request.json');if(existsSync(request))binding={requestPin:pin(request),draftPin:pin(join(context.runDir,'root-entry.draft.json'))};else{const {prepareContextDraft}=await import('./bindings.ts');binding=prepareContextDraft(m,context)}}
  return{state:'planned',attemptId:claim.id,contextPin:pin(cp),binding,spawned:false,newNativeModelCalls:0};
 }
 async runOne(o:RunOptions){
  const m=loadManifest(o.manifestPath),adapter=this.getAdapter(m.bench);adapter.validate(m);if(o.checkOnly||o.dryRun)return this.check(o.manifestPath);if(m.adapterConfig.retryNotBeforeUtc)demand(Date.now()>=Date.parse(String(m.adapterConfig.retryNotBeforeUtc)),'retry_backoff_not_elapsed');
  const key=this.queue.key(m.bench,m.taskId),task=this.queue.task(key);demand(task,'inventory_import_required');demand(!task.quarantined&&m.history.stateKnown,'unknown_history_quarantined');
  const prepared=o.attemptId?this.queue.attempt(o.attemptId):null;if(o.attemptId)demand(prepared?.state==='planned'&&prepared.task_key===key&&JSON.parse(prepared.manifest_pin).sha256===pin(o.manifestPath).sha256,'exact_planned_attempt_required');
  const selectedStage:StageName|undefined=prepared?.stage??o.stage;
  if(task.valid&&selectedStage)demand(['cleanup','reconcile','archive'].includes(selectedStage),'valid_task_never_rerun');
  const inventory=this.queue.inventory(key);demand(!['inflight','quarantined'].includes(inventory.state),'inventory_not_admissible');
  demand((inventory.priorKnownUsd===undefined||m.original.priorKnownUsd>=inventory.priorKnownUsd)&&(inventory.priorUnknownUsd===undefined||m.original.priorUnknownUsd>=inventory.priorUnknownUsd),'inventory_cost_exposure_cannot_reset');
  const first=selectedStage??this.nextStage(m);if(!first)return{taskKey:key,state:task.valid?'valid-archived':'complete',results:[],spawned:false};
  if(this.continuation(key,first,m.stages[first]))assertContinuation(o.admissionControlPath,first);else{demand(!task.valid&&!m.history.validResultPins.length&&inventory.state!=='valid','valid_task_never_rerun');assertAdmission(o.admissionControlPath,key,first,inventory.state==='recoverable')}
  let originalRecoveryProofPin:Pin|undefined;
  if(!task.valid&&(m.history.originalResultRecoveryRequired||inventory.state==='recoverable')){
   demand(adapter.recover,'original_candidate_recovery_required');const c=this.context(m,o.manifestPath,o.admissionControlPath,'original-recovery','reconcile',join(m.artifactRoot,m.bench,m.taskId,'original-recovery-'+crypto.randomUUID()));const raw=await adapter.recover(m,c);validateResult(raw);const r=archiveResult(raw,c.runDir,c),retention=this.retention(m,c,r),state=this.queue.originalRecovery(key,r);originalRecoveryProofPin=pin(join(c.runDir,'archived-result.json'));if(state==='valid')return{taskKey:key,state:'retained-valid',result:r,spawned:false,...retention};
  }
  const results:any[]=[];
  for(const stage of STAGES){
   if(selectedStage&&stage!==selectedStage)continue;const spec=m.stages[stage];if(!spec)continue;
   const prior=this.queue.stage(key,stage);if(prior?.state==='complete'){const r=JSON.parse(prior.result);for(const p of r.proofPins)verifyPin(p);results.push({stage,reused:true,proofPins:r.proofPins});continue}
   if(this.queue.task(key).valid&&!['cleanup','reconcile','archive'].includes(stage))continue;
   if(this.continuation(key,stage,m.stages[stage]))assertContinuation(o.admissionControlPath,stage);else assertAdmission(o.admissionControlPath,key,stage,!!prior&&prior.state!=='planned');
   if(stage==='solve'){demand(!results.some(x=>x.result?.candidateOrSubmissionPresent),'candidate_requires_original_result_recovery');for(const before of ['prepare','qualify'] as StageName[])if(m.stages[before])demand(this.queue.stage(key,before)?.state==='complete','prerequisite_stage_not_complete')}
   if(m.adapterConfig.bindingSpec&&spec.kind==='command'&&!prepared){const planned=await this.plan({...o,stage});return{...planned,taskKey:key,state:'planned-awaiting-root-signature',results}}
   const claim=prepared?{id:prepared.id,runDir:prepared.run_dir}:this.queue.claim(key,stage,pin(o.manifestPath),id=>join(m.artifactRoot,m.bench,m.taskId,id,stage));mkdirSync(claim.runDir,{recursive:true});let context=this.context(m,o.manifestPath,o.admissionControlPath,claim.id,stage,claim.runDir);if(originalRecoveryProofPin)context.originalRecoveryProofPin=originalRecoveryProofPin;
   if(m.adapterConfig.bindingSpec&&spec.kind==='command'){const {loadPreparedContext}=await import('./bindings.ts');context=loadPreparedContext(m,context)}
   if(prepared)this.queue.activatePlanned(claim.id);writeFileSync(join(claim.runDir,'intent-context.json'),JSON.stringify(context,null,2)+'\n',{flag:'wx'});this.queue.started(claim.id);
   try{const raw=await adapter.execute(m,spec,context);validateResult(raw);const r=archiveResult(raw,claim.runDir,context),retention=this.retention(m,context,r),state=this.queue.finish(claim.id,r,spec);results.push({stage,attemptId:claim.id,state,result:r,...retention,...this.retrySuccessor(m,context,r)});if(state!=='complete')return{taskKey:key,state,results};}
   catch(error){this.queue.quarantine(claim.id,String(error));return{taskKey:key,state:'unknown',attemptId:claim.id,reason:String(error),results,noAutomaticRespawn:true}}
  }
  return{taskKey:key,state:this.queue.task(key).valid?'valid-archived':'complete',results};
 }
 async reconcile(attemptId:string,manifestPath:string,admissionControlPath:string){
  const a=this.queue.attempt(attemptId);demand(a?.state==='unknown','unknown_attempt_required');const m=loadManifest(manifestPath);demand(this.queue.key(m.bench,m.taskId)===a.task_key,'reconcile_identity');verifyPin(JSON.parse(a.manifest_pin));demand(pin(manifestPath).sha256===JSON.parse(a.manifest_pin).sha256,'reconcile_original_manifest');const adapter=this.getAdapter(m.bench);demand(adapter.recover,'adapter_cannot_prove_recovery');
  const c=this.context(m,manifestPath,admissionControlPath,attemptId,a.stage,a.run_dir);const raw=await adapter.recover(m,c);validateResult(raw);const archivedContext={...c,runDir:join(a.run_dir,'reconciliation-'+crypto.randomUUID())},result=archiveResult(raw,archivedContext.runDir,archivedContext),retention=this.retention(m,archivedContext,result);return{attemptId,state:this.queue.reconcile(attemptId,result),result,...retention,...this.retrySuccessor(m,c,result)};
 }
 enqueue(manifestPath:string,admissionPath:string){const m=loadManifest(manifestPath);this.getAdapter(m.bench).validate(m);const stage=this.nextStage(m);demand(stage,'no_unfinished_stage');const key=this.queue.key(m.bench,m.taskId);this.queue.enqueue(key,resolve(manifestPath),pin(manifestPath),resolve(admissionPath),['prepare','qualify'].includes(stage)?'preparation':'formal');return{taskKey:key,queued:true,stage,spawned:false}}
 async dispatch(options:{watch?:boolean;maxConcurrentStages?:number;preparationLimit?:number;pollMs?:number;signal?:AbortSignal}={}){
  const running=new Map<string,Promise<void>>();const errors:any[]=[];
  do{
   let launched=0;
   for(const job of this.queue.queuedJobs()){
    if(options.signal?.aborted)break;
    try{
     verifyPin(JSON.parse(job.manifest_pin));const m=loadManifest(job.manifest_path);demand(job.task_key===this.queue.key(m.bench,m.taskId),'queued_manifest_task_identity');const stage=this.nextStage(m);if(!stage){this.queue.finishJob(job.task_key,'closed',{complete:true});continue}
     if(this.continuation(job.task_key,stage,m.stages[stage]))assertContinuation(job.admission_path,stage);else assertAdmission(job.admission_path,job.task_key,stage,!!this.queue.stage(job.task_key,stage)&&!this.queue.planned(job.task_key,stage));
     const planned=this.queue.planned(job.task_key,stage);
     if(m.adapterConfig.bindingSpec&&m.stages[stage]!.kind==='command'){if(!planned){await this.plan({manifestPath:job.manifest_path,admissionControlPath:job.admission_path,stage});this.queue.finishJob(job.task_key,'blocked',{reason:'awaiting_root_signature'});continue}const {loadPreparedContext}=await import('./bindings.ts');loadPreparedContext(m,this.context(m,job.manifest_path,job.admission_path,planned.id,stage,planned.run_dir))}
     this.queue.claimJob(job.task_key,options.maxConcurrentStages??16,options.preparationLimit??4);
     launched++;
     const work=(async()=>{try{const result:any=await this.runOne({manifestPath:job.manifest_path,admissionControlPath:job.admission_path,stage,attemptId:planned?.id});const next=this.nextStage(m),blocked=['unknown','retryable','planned-awaiting-root-signature'].includes(result.state);this.queue.finishJob(job.task_key,blocked?'blocked':next?'queued':'closed',result,next?(['prepare','qualify'].includes(next)?'preparation':'formal'):undefined)}catch(error){this.queue.finishJob(job.task_key,'blocked',{reason:String(error),noAutomaticRetry:true})}finally{running.delete(job.task_key)}})();running.set(job.task_key,work);
    }catch(error){errors.push({taskKey:job.task_key,error:String(error)});if(errors.length>64)errors.shift();if(!/admission_closed|not_allowed|priority|preparation_limit|dispatcher_stage_limit/.test(String(error)))this.queue.finishJob(job.task_key,'blocked',{reason:String(error)})}
   }
   if(!options.watch){await Promise.all(running.values());if(launched>0&&this.queue.queuedJobs().length>0)continue;return{dispatchCompleted:true,errors,status:this.queue.status()}}
   if(!options.signal?.aborted)await new Promise(r=>setTimeout(r,Math.min(1000,Math.max(10,options.pollMs??250))));
  }while(!options.signal?.aborted);
  await Promise.all(running.values());return{stoppedIntake:true,existingStagesNaturallyFinished:true,errors,status:this.queue.status()};
 }
}
