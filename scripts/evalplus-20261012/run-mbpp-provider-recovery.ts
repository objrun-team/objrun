import {createHash} from 'node:crypto';
import {submitResponse} from './mbpp-submit-response.ts';
import {interfaceFailure} from './mbpp-interface-policy-v2.ts';
import {withDifferentProviders,providerRoute,endpointAllowed} from './mbpp-provider-recovery.ts';
import {nativeInterfaceTimedOut} from './mbpp-proxy-transport.ts';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,openSync,fsyncSync,closeSync,renameSync,unlinkSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from '../../test/_lib.ts';
import {finalCandidate} from '../../app/src/objective/candidate.ts';
import {BENCHMARK_PROVIDER,benchmarkProviderKey,officialOpenRouterFault,openRouterRateLimitRejection} from '../repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../repair-2026-10-10/full-f/shared/digitalocean-inference.ts';
const ROOT=resolve(import.meta.dir,'../..'),BASE=join(ROOT,'docs/evalplus-20261012');
const slug=process.argv[2],phase=process.argv[3]??'pilot';
if(slug!=='mbpp'||phase!=='full')throw Error('MBPP continuation is restricted to mbpp full');
if(!['mbpp','mbpp'].includes(slug)||!['pilot','full','status'].includes(phase))throw Error('run.ts mbpp|mbpp pilot|full|status');
const cfg=JSON.parse(readFileSync(join(BASE,slug,'config.json'),'utf8'));
const runMode='full';if(process.argv[4]!=='full')throw Error('Only the full-namespace interface recovery scope is allowed');
const recoveryScope=JSON.parse(readFileSync(join(BASE,'mbpp','interface-recovery-scope.json'),'utf8'));
const activePass=JSON.parse(readFileSync(join(BASE,'mbpp','objrun-adapter-v1/full/recovery/active-pass.json'),'utf8'));
const recoveryPass=JSON.parse(readFileSync(activePass.path,'utf8'));
if(recoveryPass.state!=='ready')throw Error('RecoveryPassNotPrepared');
const eligibleIds=new Set(recoveryPass.targets.map((r:any)=>r.officialId));
const providerConfig=JSON.parse(readFileSync(join(BASE,'mbpp','provider-recovery-config.json'),'utf8'));
if(recoveryPass.providerRecoveryVersion!==providerConfig.version)throw Error('ProviderRecoveryPassNotPrepared');
if(providerConfig.providers.some((e:any)=>!endpointAllowed(e)))throw Error('QuantizedProviderForbidden');
const OUT=join(BASE,'mbpp','objrun-adapter-v1',runMode);
mkdirSync(OUT,{recursive:true});
const hash=(s:string|Buffer)=>createHash('sha256').update(s).digest('hex');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
function continuationSources(){for(const manifest of ['objrun-adapter-v1-source-pins.json','interface-recovery-source-pins.json','provider-recovery-source-pins.json'])for(const p of read(join(BASE,'mbpp',manifest)).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('ContinuationSourceChanged:'+p.path);}
function retainedResults(){for(const p of read(join(BASE,'mbpp','diagnosis/interface-recovery-round2-valid-retention.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('ValidResultChanged:'+p.path);}
function frozenSources(){if(phase==='full'){for(const p of read(join(BASE,'source-pins.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('FrozenSourceChanged:'+p.path);continuationSources();retainedResults();}}
function save(p:string,v:any){mkdirSync(resolve(p,'..'),{recursive:true});const tmp=p+'.'+process.pid+'.tmp';writeFileSync(tmp,JSON.stringify(v,null,2)+'\n');renameSync(tmp,p);}
function durable(p:string,v:any){mkdirSync(resolve(p,'..'),{recursive:true});const fd=openSync(p,'wx');try{writeFileSync(fd,JSON.stringify(v,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
function walk(d:string):string[]{return existsSync(d)?readdirSync(d,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(join(d,x.name)):[join(d,x.name)]):[];}
function allRecords(){return walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);}
function receipts(){return walk(join(OUT,'calls')).filter(p=>p.endsWith('receipt.json')).map(read);}
const totals=()=>{const rr=receipts(),held=walk(join(OUT,'calls')).filter(p=>p.endsWith('dispatch-disposition.json')&&!existsSync(join(dirname(p),'receipt.json'))).map(read).filter(r=>r.state==='interrupted_no_response');return {modelCalls:walk(join(OUT,'calls')).filter(p=>p.endsWith('dispatch.json')).length,completedCalls:rr.filter(r=>r.dispatched).length,unresolvedDispatchCount:held.length,actualCostUsd:rr.reduce((n,r)=>n+(r.actualCostUsd??0),0),unknownCostCount:rr.filter(r=>r.unknownCost).length+held.length,unknownCostUpperBoundUsd:rr.filter(r=>r.unknownCost).reduce((n,r)=>n+(r.upperBoundUsd??0),0)+held.reduce((n,r)=>n+(r.upperBoundUsd??0),0)};};
if(phase==='status'){const prev=existsSync(join(OUT,'status.json'))?read(join(OUT,'status.json')):{};console.log(JSON.stringify({...prev,verifiedRecords:allRecords().length,...totals()}));process.exit(0);}
const catalogPath=join(BASE,slug,'public-tasks.json');
if(hash(readFileSync(catalogPath))!==cfg.publicCatalogSha256)throw Error('Frozen public catalog changed');
const catalog=read(catalogPath),tasks=catalog.filter((t:any)=>recoveryScope.taskIds.includes(t.officialId)&&eligibleIds.has(t.officialId));
if(tasks.length!==eligibleIds.size || tasks.some((t:any)=>!recoveryScope.taskIds.includes(t.officialId)||!providerConfig.taskIds.includes(t.officialId)))throw Error('RecoveryScopeMismatch');
const key=benchmarkProviderKey(ROOT),grader='http://127.0.0.1:'+cfg.graderPort;
const lock=join(OUT,'runner-lock.json');
if(existsSync(lock)){const previous=read(lock);try{process.kill(previous.pid,0);throw Error('RunnerAlreadyLive:'+previous.pid);}catch(e){if(String(e).includes('RunnerAlreadyLive'))throw e;}renameSync(lock,lock+'.closed-'+Date.now());}
durable(lock,{pid:process.pid,atUtc:new Date().toISOString(),command:process.argv,phase,dataset:slug});
let stopped=false,error:string|undefined,currentArm='objrun',active:any[]=[];
function stopRequested(){if(existsSync(join(OUT,'stop-after-current-tasks.json')))stopped=true;return stopped;}
function nativeRecoveryReady(short:string,prior:any){return false;}
const started=Date.now();
const origin=existsSync(join(OUT,'experiment-origin.json'))?read(join(OUT,'experiment-origin.json')).startedAtUtc:new Date(started).toISOString();
function status(stage='running'){
 const records=allRecords();const arms=Object.fromEntries(['objrun'].map(arm=>{const a=records.filter(r=>r.arm===arm);const valid=a.filter(r=>r.grade?.valid);return [arm,{completed:a.length,total:378,valid:valid.length,passed:valid.filter(r=>r.grade?.passed).length,passRateCompleted:valid.length?valid.filter(r=>r.grade?.passed).length/valid.length:null,exceptions:a.filter(r=>!r.grade?.valid).length}];}));
 save(join(OUT,'status.json'),{dataset:slug,phase,stage,pid:process.pid,atUtc:new Date().toISOString(),startedAtUtc:new Date(started).toISOString(),experimentStartedAtUtc:origin,elapsedSeconds:(Date.now()-Date.parse(origin))/1000,runnerElapsedSeconds:(Date.now()-started)/1000,currentArm,active,arms,...totals(),adapterVersion:'objrun-adapter-v1',adapterTransportRevision:2,interfaceRecoveryRevision:1,providerRecoveryVersion:providerConfig.version,providerPhaseRound:recoveryPass.providerPhaseRound,recoveryRound:activePass.round,recoveryTargetTotal:tasks.length,recoveryResolved:allRecords().filter(r=>eligibleIds.has(r.officialId)&&r.grade?.valid).length,runMode,error});
}
async function grade(tid:string,code:string,feedback=false){
 for(let n=0;n<3;n++){
   try{const res=await fetch(grader+'/grade',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({task_id:tid,code,feedback_only:feedback}),signal:AbortSignal.timeout(180000)});const v=await res.json();if(v.valid||n===2)return v;}catch(e){if(n===2)return {valid:false,passed:false,errorType:'GraderTransport',diagnostic:String(e)};}
   await Bun.sleep(1000*(n+1));
 }
}
async function model(dir:string,body:any,samplingMax?:number):Promise<{raw:string,status:number,receipt:any}>{
 const short=dir.replace(/\\/g,'/').match(/\/calls\/objrun\/(Mbpp-\d+)\//)?.[1];
 const tid=short?.replace('-','/');if(!tid||!providerConfig.taskIds.includes(tid))throw Error('TaskOutsideProviderScope');
 const primary=providerConfig.taskPrimaryProviders[tid];
 const endpoints=[...providerConfig.providers].sort((a:any,b:any)=>a.tag===primary?-1:b.tag===primary?1:0);
 const saved=join(dir,'receipt.json');
 if(existsSync(saved)&&existsSync(join(dir,'response.json'))){const r=read(saved);if(r.httpStatus===200&&(!r.fault||r.fault==='MissingOrInvalidOpenRouterUsdCost'))return modelOnce(dir,body,samplingMax,endpoints[0]);}
 return withDifferentProviders(dir,endpoints,(path,endpoint)=>modelOnce(path,body,samplingMax,endpoint),{receipt:path=>existsSync(join(path,'receipt.json'))?read(join(path,'receipt.json')):undefined,event:value=>save(join(dir,'provider-switch-'+Date.now()+'.json'),{...value,atUtc:new Date().toISOString(),authorizedBy:providerConfig.authorizedBy,recoveryRound:activePass.round}),wait:()=>Bun.sleep(1000)});
}
async function modelOnce(dir:string,body:any,samplingMax:number|undefined,endpoint:any):Promise<{raw:string,status:number,receipt:any}>{
 const rr=join(dir,'receipt.json'),responsePath=join(dir,'response.json');
 if(existsSync(rr)){const receipt=read(rr);if(existsSync(responsePath))return {raw:readFileSync(responsePath,'utf8'),status:receipt.httpStatus??502,receipt,cacheReplay:true} as any;throw Error('UncertainPriorRequest:'+dir);}
 if(existsSync(join(dir,'request.json')))throw Error('UncertainPriorDispatch:'+dir);
 const wire=benchmarkProviderRequest({...body,stream:false,temperature:0,seed:42,reasoning_effort:'high',max_tokens:16384},BENCHMARK_INFERENCE,BENCHMARK_PROVIDER);
 wire.provider=providerRoute(endpoint);
 const clean=(v:any):any=>{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(clean);const x:any=Object.fromEntries(Object.entries(v).map(([k,t])=>[k,clean(t)]));if(x.type==='object')x.additionalProperties=false;return x;};
 if(wire.tools)wire.tools=wire.tools.map((t:any)=>({...t,function:{...t.function,parameters:clean(t.function.parameters)}}));
 if(samplingMax!==undefined)wire.max_tokens=samplingMax;
 continuationSources();
 const rawReq=JSON.stringify(wire);durable(join(dir,'request.json'),wire);
 durable(join(dir,'dispatch.json'),{atUtc:new Date().toISOString(),pid:process.pid,requestSha256:hash(rawReq)});
 const begin=Date.now();let raw='',httpStatus=0,v:any;
 try{
   const response=await fetch(BENCHMARK_PROVIDER.endpoint,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+key,'X-OpenRouter-Title':'ObjRun EvalPlus'},body:rawReq,signal:AbortSignal.timeout(600000),proxy:cfg.httpProxy,keepalive:false} as any);
   httpStatus=response.status;raw=await response.text();durable(responsePath,JSON.parse(raw));v=JSON.parse(raw);
 }catch(e){v={transportError:String(e)};}
 const cost=typeof v.usage?.cost==='number'?v.usage.cost:null;
 const upperBoundUsd=cost??((v.usage?.prompt_tokens??Buffer.byteLength(rawReq))*wire.provider.max_price.prompt+(v.usage?.completion_tokens??wire.max_tokens)*wire.provider.max_price.completion)/1e6;
 const explicitRejected=openRouterRateLimitRejection(v,httpStatus,endpoint.provider_name);
 const receipt={atUtc:new Date().toISOString(),dispatched:true,httpStatus,generationId:v.id??null,model:v.model??null,provider:v.provider??null,usage:v.usage??null,actualCostUsd:explicitRejected?0:cost,upperBoundUsd:explicitRejected?0:upperBoundUsd,unknownCost:!explicitRejected&&cost===null,seconds:(Date.now()-begin)/1000,requestSha256:hash(rawReq),responseSha256:raw?hash(raw):null,fault:explicitRejected?'ExplicitRateLimit':v.error?.message??(httpStatus===200?officialOpenRouterFault(v,endpoint.provider_name):v.transportError??'ProviderError'),samplingMaxTokens:samplingMax??null,requestedProviderTag:endpoint.tag,officialCatalogPrecision:endpoint.quantization,providerRecoveryVersion:providerConfig.version};
 durable(rr,receipt);
 if(!raw)throw Error('ProviderTransportUnknown:'+dir);
 return {raw,status:httpStatus,receipt};
}
async function generated(task:any,dir:string,index=0,max?:number){
 const body={model:BENCHMARK_PROVIDER.model,messages:[{role:'user',content:task.prompt}]};
 for(let retry=0;retry<3;retry++){
   const r=await model(join(dir,'sample-'+index,'attempt-'+retry),body,max);
   if(r.receipt.fault==='ExplicitRateLimit'&&retry<2){await Bun.sleep(1000*(retry+1));continue;}
   if(r.status!==200||r.receipt.fault&&r.receipt.fault!=='MissingOrInvalidOpenRouterUsdCost')throw Error('ProviderFault:'+r.receipt.fault);
   const v=JSON.parse(r.raw);return {answer:v.choices?.[0]?.message?.content??'',receipt:r.receipt,finishReason:v.choices?.[0]?.finish_reason};
 }
 throw Error('FiniteRateRetriesExhausted');
}
async function objrun(task:any,dir:string){
 const engineDir=join(dir,'engine');mkdirSync(engineDir,{recursive:true});let taskInterfaceError:string|undefined,pendingProxyRequests=0;
 const protocolEvents:any[]=[];
 const proxy=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(req){pendingProxyRequests++;try{const body=await req.json();const r=await submitResponse(body,async(request,protocolAttempt)=>{const digest=hash(JSON.stringify(request));let result:any;for(let n=0;n<3;n++){result=await model(join(OUT,'calls','objrun',task.officialId.replace('/','-'),'schema-v3',digest,'attempt-'+n),request);if(result.receipt.fault==='ExplicitRateLimit'&&n<2){await Bun.sleep((n+1)*1000);continue;}break;}if(result.receipt.fault&&result.receipt.fault!=='MissingOrInvalidOpenRouterUsdCost')throw Error('ProviderFault:'+result.receipt.fault);protocolEvents.push({atUtc:new Date().toISOString(),protocolAttempt,requestHash:digest,generationId:result.receipt.generationId,cacheReplay:result.cacheReplay===true,recoveryRound:activePass.round,actualProvider:result.receipt.provider,requestedProviderTag:result.receipt.requestedProviderTag,providerRecoveryVersion:providerConfig.version});save(join(dir,'submit-response-attempts.json'),protocolEvents);return result;});return new Response(r.raw,{status:r.status,headers:{'content-type':'application/json'}});}catch(e){taskInterfaceError=String(e);return Response.json({error:{message:String(e)}},{status:502});}finally{pendingProxyRequests--;}}});
 let engine:Machine|undefined;
 const id='ep-mbpp-objrun-adapter-v1-'+runMode+'/objrun/'+task.officialId;
 try{
 engine=await machine({...BENCHMARK_INFERENCE,retryTimes:0,continueTimes:3},{directory:engineDir,keep:true});
 save(join(dir,'engine-process.json'),{pid:engine.pid,base:engine.base,runnerPid:process.pid,atUtc:new Date().toISOString()});
 const nodes=[{name:'parsed',domain:'bool',moment:'done',handle:grader+'/parsed'},{name:'correct',domain:'bool',moment:'done',handle:grader+'/correct'}];
 const objective={nodes,edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'};
 await engine.api('POST','/declare',{handles:nodes.map(n=>({name:n.handle,expectMs:180000})),places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
 await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
 await engine.api('POST','/exec',{sql:"update api set base_url=:endpoint,retry_on='[]' where key_env=:key and model=:model",params:{endpoint:`http://127.0.0.1:${proxy.port}/v1`,key:'OPENROUTER_API_KEY',model:BENCHMARK_PROVIDER.model}});
 const existing=await engine.api<any>('POST','/query',{sql:'select * from task where id=:id',params:{id}});
 if(!existing.rows.length)await engine.api('POST','/tasks',{id,run:'ep-'+slug+'-'+phase,mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt+'\nUse submit to hand in your completed code. verify gives public base test feedback. No filesystem or search tools are available.',objective,readable:false,solveSeconds:600,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
 const start=Date.now();let t:any;
 while(Date.now()-start<1260000){if(taskInterfaceError)throw Error(taskInterfaceError);t=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/status');const why=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/why');if(taskInterfaceError)throw Error(taskInterfaceError);if(nativeInterfaceTimedOut(why,pendingProxyRequests)){save(join(dir,'native-interface-evidence.json'),{atUtc:new Date().toISOString(),status:t,why,pendingProxyRequests,successfulResponsesRetained:true});const trace=await engine.api<any>('POST','/query',{sql:'select * from agent_bot_msg order by unit,seq'});save(join(dir,'trace.json'),trace.rows);throw Error('NativeInterfaceTimeout:'+task.officialId);}if(JSON.stringify(why.problems).includes('The required submit tool was not called exactly once')){const trace=await engine.api<any>('POST','/query',{sql:'select * from agent_bot_msg order by unit,seq'});save(join(dir,'trace.json'),trace.rows);return {answer:'',candidateHow:'none',engineState:'model_submission_protocol_failure',engineVerdict:{valid:true,pass:0,outcome:'model_submission_protocol_failure'},modelProtocolFailure:true,originalKernelEvidence:why};}if(['done','failed'].includes(t.state)&&t.result&& !['finalization_pending','finalization_error'].includes(JSON.parse(t.result).outcome))break;await Bun.sleep(1000);}
 if(!t?.result)throw Error('EngineTaskDeadline');
 const trace=await engine.api<any>('POST','/query',{sql:'select * from agent_bot_msg where instance like :prefix order by unit,seq',params:{prefix:id+'#%'}});save(join(dir,'trace.json'),trace.rows);
 const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});let candidate:any;
 try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const q=db.prepare(sql);try{return q.all(...params);}finally{q.finalize();}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);}finally{db.close();}
 return {answer:candidate?.body??'',candidateHow:candidate?.how??'none',engineState:t.state,engineVerdict:JSON.parse(t.result),enginePid:engine.pid};
 }finally{await engine?.stop();while(pendingProxyRequests>0)await Bun.sleep(100);await proxy.stop(false);}
}
async function taskRun(task:any,arm:string){
 frozenSources();
 const short=task.officialId.replace('/','-'),resultPath=join(OUT,'results',arm,short+'.json');
 let nativeRecoveryAttempts=0;
 if(!eligibleIds.has(task.officialId)||!recoveryScope.taskIds.includes(task.officialId))throw Error('TaskOutsideAuthorizedInterfaceScope');
 if(existsSync(resultPath)){
  const prior=read(resultPath);if(prior.grade?.valid)return;
  const planned=recoveryPass.targets.find((r:any)=>r.officialId===task.officialId);
  if(hash(readFileSync(resultPath))!==planned.resultSha256)throw Error('RecoveryResultChangedAfterPreparation:'+task.officialId);
  if(prior.answer!==undefined){const v=await grade(task.officialId,prior.answer);save(resultPath,{...prior,grade:v,regradedWithoutModelAtUtc:new Date().toISOString(),interfaceRecoveryRound:activePass.round});return;}
  if(!prior.interfaceFailure)throw Error('OnlyInterfaceFailuresMayRegenerate');
 }
 const dir=join(OUT,'tasks',arm,short);mkdirSync(dir,{recursive:true});const begin=Date.now();
 active.push({arm,taskId:task.officialId,startedAtUtc:new Date().toISOString()});status();
 let result:any={officialId:task.officialId,arm,purpose:phase==='pilot'?'Preparation pilot; excluded from full results':'Full fixed task list',promptSha256:task.promptSha256};
 try{
   const x=await objrun(task,dir);save(join(dir,'candidate.json'),x);result={...result,...x};result.grade=x.modelProtocolFailure?{valid:true,passed:false,errorType:'ModelSubmissionProtocolFailure',outcome:'no completed native submission; earlier verify or plain text not accepted'}:await grade(task.officialId,x.answer);
 }catch(e){result.error=String(e);result.grade={valid:false,passed:false,errorType:'GenerationOrRunnerError'};}
 if(interfaceFailure(result.error)){result.interfaceFailure=true;result.interfaceRetryExhausted=true;result.interfacePolicy='Task-local failure after finite retries; other tasks continue. Original dispatches and unknown costs retained.';}
 result.nativeInterfaceTimeout=/NativeInterfaceTimeout/.test(String(result.error??''));result.nativeRecoveryAttempts=nativeRecoveryAttempts;result.adapterTransportRevision=2;result.interfaceRecoveryRound=activePass.round;result.interfaceRecoveryAuthority=providerConfig.authorizedBy;result.providerRecoveryVersion=providerConfig.version;result.providerPhaseRound=recoveryPass.providerPhaseRound;result.primaryProvider=providerConfig.taskPrimaryProviders[task.officialId];
 const own=walk(join(OUT,'calls',arm,short)).filter(p=>p.endsWith('receipt.json')).map(read);
 const eventsPath=join(dir,'submit-response-attempts.json');result.protocolRepairCalls=existsSync(eventsPath)?read(eventsPath).filter((r:any)=>r.protocolAttempt===1).length:0;result.adapterVersion='objrun-adapter-v1';result.runMode=runMode;
 result={...result,completedAtUtc:new Date().toISOString(),seconds:(Date.now()-begin)/1000,modelCalls:own.filter(r=>r.dispatched).length,actualCostUsd:own.reduce((n,r)=>n+(r.actualCostUsd??0),0),unknownCostCount:own.filter(r=>r.unknownCost).length};
 save(resultPath,result);active=active.filter(x=>!(x.arm===arm&&x.taskId===task.officialId));console.log(JSON.stringify({task:task.officialId,arm,valid:result.grade?.valid,passed:result.grade?.passed,seconds:result.seconds,cost:result.actualCostUsd,error:result.error}));status();
 // Interface faults are retained in this task result and never stop unrelated tasks.
}
async function main(){
 frozenSources();
 retainedResults();
 const health=await (await fetch(grader+'/health')).json();if(health.dataset!==slug)throw Error('Wrong grader');
 if(!read(join(BASE,'controls.json')).allPassed)throw Error('Official grader controls not accepted');
 const timer=setInterval(()=>status(),15000);status();
 try{for(const arm of ['objrun']){currentArm=arm;let index=0;await Promise.all(Array.from({length:cfg.concurrency},async()=>{while(index<tasks.length&&!stopRequested())await taskRun(tasks[index++],arm);}));if(stopRequested())break;const recovery=tasks.filter((task:any)=>{const short=task.officialId.replace('/','-'),p=join(OUT,'results',arm,short+'.json');return existsSync(p)&&nativeRecoveryReady(short,read(p));});let recoverIndex=0;await Promise.all(Array.from({length:cfg.concurrency},async()=>{while(recoverIndex<recovery.length&&!stopRequested())await taskRun(recovery[recoverIndex++],arm);}));}}
 finally{clearInterval(timer);retainedResults();const exceptions=allRecords().filter(r=>!r.grade?.valid).length;status(stopped?'needs_attention':exceptions?'complete_with_exceptions':'complete');save(activePass.path,{...recoveryPass,state:stopped?'stopped':'finished',finishedAtUtc:new Date().toISOString(),resolved:allRecords().filter(r=>eligibleIds.has(r.officialId)&&r.grade?.valid).length,...totals()});if(existsSync(lock))unlinkSync(lock);}
}
main().catch(e=>{error=String(e);status('needs_attention');console.error(error);if(existsSync(lock))unlinkSync(lock);process.exitCode=1;});
