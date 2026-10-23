import {readFileSync} from 'node:fs';import {resolve,join} from 'node:path';
import {createAdoptedParent,immutable} from './adopted-parent-v46.ts';import {verifyAdoptionEnvelope} from './sign-adoption-v46.ts';import {preflightAdoption} from './preflight-adoption-v46.ts';import {startFullFBroker} from './broker-adoption-v46.ts';
const root=resolve(import.meta.dir,'../../../../..'),mode=process.argv[2],path=resolve(process.argv[3]);
if(mode==='--preflight-unsigned'){console.log(JSON.stringify(await preflightAdoption(JSON.parse(readFileSync(path,'utf8')))));}
else if(mode==='--start'){
 const plan=verifyAdoptionEnvelope(JSON.parse(readFileSync(path,'utf8')));await preflightAdoption(plan);
 const directory=resolve(process.argv[4]);if(directory!==resolve(plan.outputDirectory))throw Error('signed_output_directory_required');
 const a=await createAdoptedParent(root,directory,path);const health=()=>{try{a.guard();return {healthy:true};}catch(e){return {healthy:false,stopReason:String(e)};}};
 const b=await startFullFBroker({root,output:join(directory,'broker'),runId:a.lease.runId,port:17895,aliasPorts:[17889],maxInFlight:16,targetMax:16,perBenchMax:16,heavyCapacity:16,perBenchHeavySlots:16,recordAndContinue:true,remoteDiskObservationPath:plan.remoteDiskObservationPath,initialParent:a.lease,retainCanonicalParent:true,leaseFactory:async()=>a.lease,beforeAccept:a.guard,externalHealth:health,initialResources:a.initialResources,externalLanes:()=>a.inheritedLanes,adoptionMetadata:a.metadata,adoptionResourceRelease:a.releaseResource,initialRound:5});
 immutable(join(directory,'connection.private.json'),{...b.connection,adoption:a.metadata()});console.log(JSON.stringify({pid:process.pid,endpoint:b.connection.endpoint,aliasEndpoints:b.aliasEndpoints,connectionPath:join(directory,'connection.private.json'),modelCalls:0,originalBudgetReset:false}));
}else throw Error('root --preflight-unsigned plan OR --start signedPlan exactDirectory');
