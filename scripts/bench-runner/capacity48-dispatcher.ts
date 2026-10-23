/** Controlled successor entry: original Runner and same atomic queue, signed48/prep4. */
import {readFileSync} from 'node:fs';import {resolve} from 'node:path';import {verify,createHash} from 'node:crypto';
import {installUnlimitedFinancialLoader} from './capacity48-loader.ts';
function need(v:unknown,w:string):asserts v{if(!v)throw Error(w)}
export function signedCapacityQueueClass(Base:any,policyPin:any,policy:any){
 return class SignedCapacityQueue extends Base{
  claimJob(taskKey:string,maximum=policy.maximumActualSolvers,preparation=policy.maximumPreparation,explicitPolicy=policyPin){
   need(maximum===policy.maximumActualSolvers&&preparation===policy.maximumPreparation,'dispatcher_exact_signed_48_4');
   need(JSON.stringify(explicitPolicy)===JSON.stringify(policyPin),'dispatcher_same_signed_capacity_policy');
   return super.claimJob(taskKey,maximum,preparation,policyPin);
  }
 };
}
export async function main(args=process.argv.slice(2)){
 const [configPath,planPath]=args,c=installUnlimitedFinancialLoader(configPath);
 const {verifyPin}=await import('./manifest.ts'),{verifyRuntimeCapacityPolicy}=await import('./runtime-capacity-policy.ts'),{processIdentity}=await import('./runtime.ts');
 const e=JSON.parse(readFileSync(planPath,'utf8')),p=e.plan;verifyPin(e.authorityPublicPin);need(e.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(p)),readFileSync(e.authorityPublicPin.path),Buffer.from(e.signature,'base64')),'signed_capacity_watch_handoff_plan');
 need(e.protocol==='bench-signed-capacity48-watch-handoff-v1'&&p.protocol==='bench-capacity48-watch-handoff-v1'&&p.previousWatchPid===31420&&p.previousWatchIncarnation==='134365352685902692','exact_original_capacity_watch');
 const policy=verifyRuntimeCapacityPolicy(p.capacityPolicyPin);need(JSON.stringify(p.capacityPolicyPin)===JSON.stringify(c.capacityPolicyPin),'dispatcher_loader_same_capacity_policy');
 verifyPin(p.oldWatchClosedProofPin);verifyPin(p.originalQueueSnapshotPin);verifyPin(p.newBrokerActivationPin);
 const closed=JSON.parse(readFileSync(p.oldWatchClosedProofPin.path,'utf8'));need(closed.originalWatchPid===p.previousWatchPid&&closed.originalWatchIncarnation===p.previousWatchIncarnation&&closed.originalProcessWaitedExited===true&&closed.activeTasksAtHandoff===0,'exact_naturally_drained_original_watch_closed');
 need(resolve(p.databasePath)===resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner/queue.sqlite'),'same_original_dispatch_queue');
 const {verifyAdoptedActivation}=await import('./unlimited-readonly-guard-retry.ts');const actual=await verifyAdoptedActivation(p.newBrokerActivationPin.path);need(actual.health.targetMax===48&&actual.health.maxInFlight===48&&actual.health.activeRequests===0&&actual.health.queuedRequests===0,'new_capacity_broker_actual_ready');
 const {DurableQueue}=await import('./queue.ts'),{Runner}=await import('./runner.ts'),{getAdapter}=await import('./adapters/index.ts');const Queue=signedCapacityQueueClass(DurableQueue,p.capacityPolicyPin,policy),q=new Queue(p.databasePath),abort=new AbortController();
 try{need(!q.status().jobs.some((j:any)=>j.state==='running'),'no_active_jobs_at_dispatcher_handoff');process.once('SIGINT',()=>abort.abort());process.once('SIGTERM',()=>abort.abort());console.log(JSON.stringify({protocol:'bench-capacity48-actual-watch-start-v1',pid:process.pid,incarnation:processIdentity(process.pid).incarnation,queue:p.databasePath,capacityPolicyPin:p.capacityPolicyPin,maxConcurrentStages:48,preparationLimit:4}));return await new Runner(q,getAdapter).dispatch({watch:true,maxConcurrentStages:48,preparationLimit:4,signal:abort.signal});}finally{q.close()}
}
if(import.meta.main)main().catch(e=>{console.error(JSON.stringify({error:String(e),newAdmissionsFailClosed:true}));process.exitCode=1});
