/** One SB task: caller's lease, original shared admission/cash and original stand. */
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';import {join,relative,isAbsolute} from 'node:path';
import {demand,pin} from './manifest.ts';
import {acquireOwnedFullFAdmissionV76} from '../benchmark-campaign/full-f/novaeve_formal_v1/broker/shared-admission-owned-price-renewal.ts';
import {createSingleTaskFeeQueue} from './skillsbench-single-task-fee.ts';
import {startSingleTaskSkillsBenchStand} from './skillsbench-single-task-stand.ts';
import {processIdentity} from './runtime.ts';
export async function openSkillsBenchSingleTaskSession(input:any){
 demand(input.taskId&&input.schedule.length===1&&input.schedule[0].taskId===input.taskId,'single_task_only');
 demand(Number.isFinite(input.deadline)&&input.deadline>Date.now(),'single_task_absolute_deadline');
 const owner=Number(process.env.NOVAEVE_RESOURCE_LEASE_PID);
 demand(owner>0&&input.config.resourceOwnerPid===owner&&process.env.NOVAEVE_RESOURCE_BENCH==='skillsbench','single_task_actual_owned_sb_parent');
 const actualLeaseIncarnation=processIdentity(owner).incarnation;
 const requireOwnedResource=()=>{const h=JSON.parse(readFileSync(input.connection.healthPath,'utf8')),r=h.resourceSlots?.find((x:any)=>x.kind==='heavy-container'&&x.slug==='skillsbench'&&x.pid===owner),age=Date.now()-Date.parse(h.atUtc);
  demand(age>=0&&age<=30000&&h.healthy===true&&h.pid===input.connection.pid&&h.runId===input.connection.runId&&h.targetMax===16&&h.adoption?.protocol==='novaeve-truthful-broker-price-renewal-v1'&&h.adoption.singleResourcePool===true&&h.adoption.exactOwnedLeaseLaneBinding===true&&r&&!r.adoptedOrphanHold&&!r.inheritedResourceHold&&r.token===process.env.NOVAEVE_RESOURCE_TOKEN&&r.ownerIncarnation===actualLeaseIncarnation&&processIdentity(owner).incarnation===actualLeaseIncarnation&&r.slots===1&&r.memoryMb>=Number(process.env.NOVAEVE_RESOURCE_MEMORY_MB)&&r.plannedGrowthBytes>=Number(process.env.NOVAEVE_RESOURCE_GROWTH_BYTES),'single_task_actual_sb_owned_forward_closed')};
 requireOwnedResource();mkdirSync(input.output,{recursive:true});
 const laneSourcePins=input.sourcePins.filter((p:any)=>{const r=relative(input.root,p.path);return r!==''&&!r.startsWith('..')&&!isAbsolute(r)});demand(laneSourcePins.length>0,'single_task_code_root_lane_sources');
 const admission=await acquireOwnedFullFAdmissionV76({root:input.root,output:input.output,runId:input.runId,slug:'skillsbench',sourcePins:laneSourcePins,connection:input.connection,
  ownedResource:{pid:owner,token:process.env.NOVAEVE_RESOURCE_TOKEN}});
 let fees:any,stand:any,closed=false,tokenBefore=process.env.TGENGIN_GRADER_TOKEN;
 const receipt=(name:string,v:any)=>{const path=join(input.output,name);writeFileSync(path,JSON.stringify(v,null,2)+'\n',{flag:'wx'});return pin(path)};
 try{
  fees=createSingleTaskFeeQueue({...input,admission,requireOwnedResource});
  stand=await startSingleTaskSkillsBenchStand({...input,output:join(input.output,'original-stand')});
  process.env.TGENGIN_GRADER_TOKEN=stand.token;
  await admission.registerOwnedProcess(receipt('stand-process.json',{protocol:'paid-owned-process-v2',pid:stand.pid,role:'skillsbench-single-task-stand',runId:input.runId,ownerNonce:admission.owned.ownerNonce,identity:stand.identity}));
 }catch(error){
  const proof:any={error:String(error),laneReleasePermitted:false,resourceReleasePermitted:false};
  if(stand)try{proof.stand=await stand.close()}catch(closeError){proof.standError=String(closeError)}
  if(fees)try{proof.cash=await fees.retainFailure(String(error))}catch(cashError){proof.cashError=String(cashError)}
  receipt('session-start-failure.json',proof);throw error;
 }
 return{admission,fees,stand,
  async registerProcess(pid:number,role:string){return admission.registerOwnedProcess(receipt('process-'+pid+'.json',{protocol:'paid-owned-process-v2',pid,role,runId:input.runId,ownerNonce:admission.owned.ownerNonce,identity:processIdentity(pid)}))},
  async close(){
   demand(!closed,'single_task_session_close_once');
   for(const row of input.schedule)fees.sealRoute(row.route);
   fees.proxy.stop('single_task_generation_closed');await fees.proxy.drain();
   const standClosure=await stand.close(),cashClosure=await fees.close();
   const laneClosure=await admission.finishLightweight(cashClosure);
   demand(laneClosure.closed===true,'single_task_exact_lane_not_closed');
   closed=true;if(tokenBefore===undefined)delete process.env.TGENGIN_GRADER_TOKEN;else process.env.TGENGIN_GRADER_TOKEN=tokenBefore;
   const cash=fees.state().cash;
   return{proofPin:receipt('session-close.json',{standClosure,cashClosure,laneClosure,cash,resourceReleasePermitted:true,resourceReleasedByCaller:false,actualModelRequests:fees.state().provider}),standClosure,cashClosure,laneClosure,cash,resourceReleasePermitted:true};
  }
 };
}
