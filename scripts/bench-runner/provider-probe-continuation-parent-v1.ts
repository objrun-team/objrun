/** Typed infrastructure scope; reuses the original pool and explicit child observer. */
import{readFileSync,writeFileSync,mkdirSync}from'node:fs';import{join,resolve}from'node:path';
import{installUnlimitedFinancialLoader}from'./provider-probe-continuation-loader-v1.ts';
const [configPath,scopePath]=process.argv.slice(2),config=installUnlimitedFinancialLoader(configPath);
const{actualPin,jsonPin,demand,verifyPin}=await import('../benchmark-repair/paid-resource-proof-v2.ts');
const{verifyProviderProbeScope}=await import('./provider-probe-continuation-policy-v1.ts');
const{verifyAdoptedActivation}=await import('./unlimited-readonly-guard-retry.ts');
const{ownedOperationResource}=await import('./owned-operation-resource.ts');
const{observedSpawn,configureObservedSpawn}=await import('./observed-spawn.ts');
const{processIdentity}=await import('./runtime.ts');
const scopePin=actualPin(scopePath),scope=jsonPin(scopePin).scope;
verifyProviderProbeScope(scopePin,{providerSlug:scope.providerSlug,slug:'terminal-bench',runId:scope.runId,output:scope.output,sourcePins:[scopePin]});
for(const p of[scope.activationPin,scope.sourceConfigPin,scope.parentEntryPin,scope.childEntryPin])verifyPin(p);
demand(actualPin(import.meta.path).sha256===scope.parentEntryPin.sha256&&actualPin(configPath).sha256===scope.sourceConfigPin.sha256,'provider_probe_exact_parent_and_loader');
demand(['zero-request-acceptance','real-model-probe'].includes(scope.probeStage)&&scope.resource?.bench==='terminal-bench'&&scope.resource.cpu===1&&scope.resource.memoryMb===2048&&scope.resource.slots===1&&scope.resource.growthBytes===10737418240&&scope.coordinationCeilingSeconds===(scope.maximumModelRequests===0?600:1300),'provider_probe_explicit_infrastructure_resource');
const current=await verifyAdoptedActivation(scope.activationPin.path);
demand(current.health.providerProbeCapability==='signed-fireworks-two-request-only-v1','current_single_broker_not_probe_capable');
const out=resolve(scope.output),parentOut=out+'-parent';mkdirSync(parentOut,{recursive:false});
const save=(n:string,v:any)=>{writeFileSync(join(parentOut,n),JSON.stringify(v,null,2)+'\n',{flag:'wx',mode:0o600});return actualPin(join(parentOut,n))};
save('intent.json',{protocol:'bench-signed-provider-probe-parent-intent-v1',scopePin,pid:process.pid,identity:processIdentity(process.pid),sourceConfigPin:actualPin(configPath),nonBenchmark:true});
configureObservedSpawn(join(parentOut,'process'),[...config.sourcePins,scopePin]);
const lease=await ownedOperationResource(current.connection,{planPin:scopePin,resource:scope.resource});save('lease-acquire.private.json',{...lease,release:undefined});
const child=observedSpawn(process.execPath,[join(import.meta.dir,'provider-probe-continuation-loader-v1.ts'),configPath,scope.childEntryPin.path,configPath,scopePath],{cwd:scope.root,env:{...process.env},windowsHide:true,stdio:['ignore','pipe','pipe']});
const streams=await import('node:fs'),stdout=streams.createWriteStream(join(parentOut,'child.stdout'),{flags:'wx'}),stderr=streams.createWriteStream(join(parentOut,'child.stderr'),{flags:'wx'});child.stdout?.pipe(stdout);child.stderr?.pipe(stderr);
let timedOut=false,timer:any;const closed=new Promise<{code:number|null,signal:string|null}>((ok,no)=>{child.once('error',no);child.once('close',(code,signal)=>ok({code,signal}))});
let exit:any;try{exit=await Promise.race([closed,new Promise((_,reject)=>{timer=setTimeout(()=>{timedOut=true;reject(Error('provider_probe_coordination_deadline'))},scope.coordinationCeilingSeconds*1000)})])}catch(error){save('hold-retained.json',{pid:process.pid,ownerIncarnation:lease.ownerIncarnation,childPid:child.pid,childCloseProven:false,timedOut,error:String(error),resourceReleased:false});throw error}finally{clearTimeout(timer)}
await Promise.all([stdout,stderr].map(s=>new Promise<void>((ok,no)=>{if(s.closed)return ok();s.once('close',()=>ok());s.once('error',no)})));
save('child-close.json',{...exit,closeObserved:true,pid:child.pid,stdoutPin:actualPin(join(parentOut,'child.stdout')),stderrPin:actualPin(join(parentOut,'child.stderr')),timedOut});
let result:any;try{result=jsonPin(actualPin(join(out,'provider-probe-result.json')))}catch{}
demand(result?.laneClosure?.closed===true&&result.actualBenchTasks===0&&result.referenceCalls===0&&result.gradeCalls===0&&result.knownUnknownFeesRetained===true,'provider_probe_cash_lane_closure_unproven_hold_retained');
await lease.release();save('lease-release.json',{pid:process.pid,ownerIncarnation:lease.ownerIncarnation,released:true,resourceReleasedAfterActualChildClose:true});
const fresh=await verifyAdoptedActivation(scope.activationPin.path);demand(!fresh.health.resourceSlots.some((r:any)=>r.pid===process.pid&&r.ownerIncarnation===lease.ownerIncarnation),'provider_probe_resource_fresh_absence');
save('result.json',{protocol:'bench-original-shared-provider-probe-parent-result-v1',scopePin,accepted:result.accepted===true&&exit.code===0,probeStage:scope.probeStage,supplierLivenessProven:result.accepted===true&&scope.maximumModelRequests>0,childClosed:true,resourceReleased:true,resourceFreshAbsent:true,originalCashResultPin:actualPin(join(out,'provider-probe-result.json')),actualModelRequestLimit:scope.maximumModelRequests,nonBenchmark:true});
demand(result.accepted===true&&exit.code===0,'real_provider_probe_not_accepted');console.log(JSON.stringify({accepted:true,resourceReleased:true,nonBenchmark:true}));
