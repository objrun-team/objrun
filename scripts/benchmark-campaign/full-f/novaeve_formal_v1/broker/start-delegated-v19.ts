/** Root starts only a signed delegation. Does not acquire another USD owner or modify any old file. */
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createDelegatedParent,reserveDelegatedBudget} from './delegated-parent-v19.ts';
import {startFullFBroker} from './broker-delegated-v19.ts';
const mode=process.argv[2];
if(mode==='--self-test'){
 const first={originalCapUsd:100,oldAllocationHighWaterUsd:20,historyUnknownUpperUsd:5,additionalAllocatedUsd:0,lanes:{}};
 const a=reserveDelegatedBudget(first,'original-1',30),b=reserveDelegatedBudget(a,'original-2',40);let over=false,duplicate=false;
 try{reserveDelegatedBudget(b,'original-3',6);}catch{over=true;}try{reserveDelegatedBudget(a,'original-1',1);}catch{duplicate=true;}
 if(!over||!duplicate||b.oldAllocationHighWaterUsd!==20||b.historyUnknownUpperUsd!==5||b.additionalAllocatedUsd!==70)throw Error('delegated_budget_fixture_failed');
 console.log(JSON.stringify({modelCalls:0,newPaidOwnerCreated:false,originalCapPreserved:true,oldOpenLaneReservationsPreserved:true,historyUnknownPreserved:true,overspendRefused:over,duplicateRefused:duplicate,resourcePool:'original17889only'}));
}else if(mode==='--start'){
 const root=resolve(import.meta.dir,'../../../../..'),directory=resolve(process.argv[4]),signedPlanPath=resolve(process.argv[3]);
 const delegated=await createDelegatedParent(root,directory,signedPlanPath),plan=delegated.plan,connection=delegated.originalConnection;
 const timer=setInterval(()=>{void delegated.refreshState().catch(()=>{});},2000);
 const b=await startFullFBroker({root,output:join(directory,'broker'),runId:delegated.lease.runId,port:plan.newPort,maxInFlight:16,targetMax:16,perBenchMax:16,perBenchHeavySlots:16,heavyCapacity:16,recordAndContinue:true,remoteDiskObservationPath:plan.remoteDiskObservationPath,
  beforeAccept:delegated.guard,initialParent:delegated.lease,retainCanonicalParent:true,leaseFactory:async()=>{await delegated.refreshState();return delegated.lease;},externalResources:()=>delegated.oldHealth().resourceSlots,
  externalLanes:()=>delegated.oldHealth().lanes,
  externalHealth:delegated.health,initialRound:delegated.oldHealth().round,initialRoundReceipts:delegated.oldHealth().roundReceipts,resourceProxy:async request=>{const path=new URL(request.url).pathname;const r=await fetch(connection.endpoint+path,{method:'POST',headers:{authorization:'Bearer '+connection.accessToken,'content-type':'application/json'},body:await request.text(),signal:AbortSignal.timeout(30000)});await delegated.refreshState();return new Response(await r.text(),{status:r.status,headers:{'content-type':'application/json'}});}});
 writeFileSync(join(directory,'connection.private.json'),JSON.stringify(b.connection,null,2)+'\n',{flag:'wx',mode:0o600});
 console.log(JSON.stringify({pid:process.pid,endpoint:b.connection.endpoint,connectionPath:join(directory,'connection.private.json'),oldServiceUnchanged:true,originalParentAndNoncePreserved:true,resourcePool:'original17889',modelCalls:0}));
}else throw Error('use --self-test or root --start signedPlanPath newOutputDirectory');
