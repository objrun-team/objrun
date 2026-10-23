/** Root-signed zero-model acceptance of the existing production Python ownership boundary. */
import{readFileSync,writeFileSync,mkdirSync,openSync,closeSync}from'node:fs';
import{join,resolve}from'node:path';import{verify}from'node:crypto';
import{pin,verifyPin,demand}from'./manifest.ts';import{processIdentity,executeCommand}from'./runtime.ts';
import{resource}from'./original-owned-resource-price-renewal.ts';
import{verifyAdoptedActivation}from'../repair-2026-10-10/full-f/novaeve_formal_v1/broker/adopted-consumer-price-renewal.ts';
const acceptanceStarted=performance.now();
const[path,hash,output]=process.argv.slice(2),out=resolve(output);
demand(pin(path).sha256===hash,'exact_signed_acceptance_required');const envelope=JSON.parse(readFileSync(path,'utf8')),p=envelope.plan;
demand(envelope.protocol==='bench-root-signed-infrastructure-acceptance-v1'&&p.authorityPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98','original_root_infrastructure_authority');verifyPin(p.authorityPin);
demand(verify(null,Buffer.from(JSON.stringify(p)),readFileSync(p.authorityPin.path),Buffer.from(envelope.signature,'base64')),'infrastructure_signature');
demand(p.protocol==='bench-zero-model-infrastructure-acceptance-plan-v1'&&p.noBenchContent===true&&p.modelCalls===0&&p.gradeCalls===0&&p.referenceCalls===0&&p.resource.memoryMb===2048&&p.resource.growthBytes===10737418240&&p.resource.slots===1&&p.imageLoadTimeoutSeconds===600&&p.nodeCopyTimeoutSeconds===240&&Date.parse(p.expiresAtUtc)>Date.now()&&out===resolve(p.output),'infrastructure_exact_scope');
demand(resolve(p.nativeOutput)===join(out,'native'),'native_output_exact_child');
demand(p.overallTimeoutSeconds===600,'original_total_preparation_deadline');
for(const q of[p.producerPin,p.activationPin,p.pythonExecutablePin,p.bootstrapPin,p.mappingPin,p.entryPin,p.baseInspectPin,p.nodePin,p.sshExecutablePin,...p.libraryPins,...p.sourcePins])verifyPin(q);
demand(pin(import.meta.path).sha256===p.producerPin.sha256,'actual_infrastructure_producer');
if(p.formalParent&&process.env.BENCH_ATTEMPT_ID!==p.formalParent.attemptId){
 verifyPin(p.formalParent.manifestPin);const m=JSON.parse(readFileSync(p.formalParent.manifestPin.path,'utf8'));
 const argv=[process.execPath,import.meta.path,path,hash,out],runDir=p.formalParent.parentRunDir;mkdirSync(runDir,{recursive:true});const entry=join(runDir,'root-verified-argv.json');writeFileSync(entry,JSON.stringify({entry:{argv},rootSignedPlanPin:pin(path)}),{flag:'wx'});
 const context:any={attemptId:p.formalParent.attemptId,taskId:m.taskId,bench:m.bench,stage:'qualify',runDir,manifestPath:p.formalParent.manifestPin.path,manifestPin:p.formalParent.manifestPin,bindings:{ENTRY_ENVELOPE:entry}};
 const result=await executeCommand(m,{command:argv,timeoutSeconds:600,effect:'native',resourceMode:'owned'} as any,context);writeFileSync(join(runDir,'result.json'),JSON.stringify(result,null,2));demand(result.exitCode===0&&result.closeObserved&&!result.timedOut,'actual_formal_execute_command_failed');console.log(JSON.stringify({complete:true,formalParentResult:runDir}));process.exit(0);
}
const save=(n:string,v:any)=>writeFileSync(join(out,n),JSON.stringify(v,null,2)+'\n',{flag:'wx'});
mkdirSync(out,{recursive:false});save('intent.json',{planPin:pin(path),owner:{pid:process.pid,...processIdentity(process.pid)},modelCalls:0});
const current=await verifyAdoptedActivation(p.activationPin.path),a=JSON.parse(readFileSync(p.activationPin.path,'utf8'));
const lease=await resource(current.connection,{planPin:pin(path),originalPeakMemoryMb:2048,originalPlannedGrowthBytes:10737418240});
save('lease-acquire.private.json',{pid:process.pid,...lease,release:undefined});
const argv=[p.pythonExecutablePin.path,'-B',p.bootstrapPin.path,'--config',p.mappingPin.path,'--original-script',p.entryPin.path,'--',path,p.nativeOutput];
const stdout=openSync(join(out,'stdout.log'),'wx'),stderr=openSync(join(out,'stderr.log'),'wx');let child:any,exitCode:any,error:any,closeObserved=false,timedOut=false,timer:any;
try{if(p.formalParent){
 process.env.DOCKER_HOST=a.dockerHost;process.env.NOVAEVE_ACTIVATION_PATH=p.activationPin.path;process.env.NOVAEVE_BROKER_CONTROL_PATH=a.brokerControlPath;process.env.NOVAEVE_RESOURCE_PARENT_PID=String(process.pid);process.env.NOVAEVE_RESOURCE_BENCH='terminal-bench';process.env.NOVAEVE_RESOURCE_SLOTS='1';process.env.NOVAEVE_ROOT_ONLY_DISPATCH='1';
 const driver=await import('./formal_parent_stand.ts');await driver.formalNeutralStand(p,path,out);exitCode=0;closeObserved=true;
}else{child=Bun.spawn(argv,{stdin:'ignore',stdout,stderr,env:{...process.env,DOCKER_HOST:a.dockerHost,NOVAEVE_ACTIVATION_PATH:p.activationPin.path}});save('process.json',{argv,pid:child.pid,...processIdentity(child.pid),startedAtUtc:new Date().toISOString()});timer=setTimeout(()=>{timedOut=true;save('overall-deadline-fired.json',{seconds:600,pid:child.pid,descendantClosureProven:false,resourceReleased:false,atUtc:new Date().toISOString()});child.kill('SIGTERM')},Math.max(1,600000-(performance.now()-acceptanceStarted)));exitCode=await child.exited;closeObserved=true}}catch(e){error=String(e)}finally{clearTimeout(timer);closeSync(stdout);closeSync(stderr);save('process-close.json',{exitCode:exitCode??null,error:error??null,closeObserved,timedOut,elapsedSeconds:(performance.now()-acceptanceStarted)/1000,finishedAtUtc:new Date().toISOString(),stdoutPin:pin(join(out,'stdout.log')),stderrPin:pin(join(out,'stderr.log'))})}
const nativeResult=join(p.nativeOutput,'result.json');let native:any;try{native=JSON.parse(readFileSync(nativeResult,'utf8'))}catch{}
if(!timedOut&&closeObserved&&native?.actorClosed){await lease.release();save('lease-release.json',{pid:process.pid,ownerIncarnation:lease.ownerIncarnation,released:true})}else{save('hold-retained.json',{pid:process.pid,reason:timedOut?'overall600s_deadline_descendant_closure_unknown':'native closure not proven',resourceReleased:false});throw Error('native_acceptance_custody_hold')}
const final=await verifyAdoptedActivation(p.activationPin.path);demand(!final.health.resourceSlots.some((r:any)=>r.pid===process.pid&&r.ownerIncarnation===lease.ownerIncarnation),'acceptance_lease_absence');
save('result.json',{complete:exitCode===0&&native.complete,modelCalls:0,gradeCalls:0,referenceCalls:0,nativeResultPin:pin(nativeResult),resourceReleased:true,actualSubprocessClosed:true});demand(exitCode===0&&native.complete,'actual_infrastructure_acceptance_failed');console.log(JSON.stringify({complete:true,output:out,resourceReleased:true}));
