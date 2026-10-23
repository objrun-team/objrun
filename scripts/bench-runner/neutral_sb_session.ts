/** No provider request or Bench content: exercise the shared single-task session. */
import {requireSingleTaskSkillsBenchReadiness} from './skillsbench-single-task-readiness.ts';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';import {join,resolve} from 'node:path';
import {pin,verifyPin,demand} from './manifest.ts';import {openSkillsBenchSingleTaskSession} from './skillsbench-single-task-session.ts';
import {runSkillsBenchPythonChild} from './skillsbench-python-child.ts';import {verifyAdoptedActivation} from '../repair-2026-10-10/full-f/novaeve_formal_v1/broker/adopted-consumer-price-renewal.ts';
const [planPath,expectedSha,output]=process.argv.slice(2);demand(pin(planPath).sha256===expectedSha,'neutral_session_exact_plan');
const p=JSON.parse(readFileSync(planPath,'utf8')).plan;demand(p.noBenchContent===true&&p.modelCalls===0&&p.gradeCalls===0&&p.referenceCalls===0,'neutral_session_scope');
const out=resolve(output),deadline=Number(process.env.NOVAEVE_INFRASTRUCTURE_DEADLINE_MS);
demand(deadline>Date.now()&&deadline<=Date.now()+600000,'neutral_session_original_parent_deadline');mkdirSync(out,{recursive:false});
for(const q of p.sourcePins)verifyPin(q);
let missingQualificationRejected=false;try{requireSingleTaskSkillsBenchReadiness({taskId:'spring-boot-jakarta-migration'},{taskId:'spring-boot-jakarta-migration',adapter:'group02-adapter3-v1'},p.singleTaskStand.standEntryPin)}catch(error){missingQualificationRejected=String(error).includes('single_task_original_qualification_missing')}demand(missingQualificationRejected,'neutral_must_not_promote_missing_original_qualification');
const current=await verifyAdoptedActivation(p.activationPin.path),row={taskId:'spring-boot-jakarta-migration',arm:'F',route:p.neutralRunId+'/skillsbench/F/0/neutral-no-provider'};
const config={...p.neutralStandConfig,output:join(out,'empty-original-stand'),runId:p.neutralRunId,resourceOwnerPid:Number(process.env.NOVAEVE_RESOURCE_LEASE_PID),schedule:[],taskReadiness:{}};
const session=await openSkillsBenchSingleTaskSession({root:p.root,output:out,taskId:row.taskId,runId:p.neutralRunId,schedule:[row],sourcePins:p.sourcePins,connection:current.connection,binding:p.singleTaskStand,config,deadline,freshMaximumNewSpendUsd:async()=>{throw Error('neutral_provider_forward_forbidden')}});
let actor:any,error:any,closure:any;
try{
 actor=await runSkillsBenchPythonChild(p.singleTaskStand,p.neutralActorPin,['--plan',planPath,'--output',join(out,'actor')],p.root,Math.max(1,deadline-Date.now()));
 demand(actor.closeObserved&&actor.exitCode===0,'neutral_session_actor_close');
 const result=JSON.parse(readFileSync(join(out,'actor/result.json'),'utf8'));demand(result.complete&&result.actorClosed&&result.currentActorStatus===404,'neutral_session_actual_actor_closure');
}catch(e){error=String(e)}finally{try{closure=await session.close()}catch(e){error=String(error??'')+' '+String(e)}}
const state=session.fees.state();demand(state.provider.activeHandlers===0&&state.provider.journal.acceptedRequestCount===0&&state.cash.pendingCount===0&&state.cash.newUnknownCount===0&&state.cash.billedUsd===0,'neutral_session_zero_provider_cash_lifecycle');
writeFileSync(join(out,'result.json'),JSON.stringify({complete:!error,actor,closure,missingQualificationRejected,feeState:state,error:error??null,modelCalls:0,gradeCalls:0,formalReady:false},null,2)+'\n',{flag:'wx'});
demand(!error,'neutral_session_failed:'+error);console.log(JSON.stringify({complete:true,output:out}));
