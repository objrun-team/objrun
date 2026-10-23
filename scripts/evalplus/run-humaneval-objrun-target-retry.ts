import {createHash} from 'node:crypto';
import {acceptAttempt,targetReached,canSchedule} from './humaneval-target-retry-policy.ts';
import {fireworksRequest,fireworksFault} from './humaneval-fireworks-route.ts';
import {submitResponse} from './humaneval-submit-response.ts';
import {withOneInterfaceRetry,interfaceFailure,transientInterfaceReceipt} from './humaneval-interface-policy-v2.ts';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,openSync,fsyncSync,closeSync,renameSync,unlinkSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from '../../test/_lib.ts';
import {finalCandidate} from '../../app/src/objective/candidate.ts';
import {BENCHMARK_PROVIDER,benchmarkProviderKey,officialOpenRouterFault,openRouterRateLimitRejection} from '../benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../benchmark-campaign/full-f/shared/digitalocean-inference.ts';
const ROOT=resolve(import.meta.dir,'../..'),BASE=join(ROOT,'docs/evalplus-20261012');
const slug=process.argv[2],phase=process.argv[3]??'pilot';
if(slug!=='humaneval'||phase!=='full')throw Error('HumanEval continuation is restricted to humaneval full');
if(!['humaneval','mbpp'].includes(slug)||!['pilot','full','status'].includes(phase))throw Error('run.ts humaneval|mbpp pilot|full|status');
const cfg=JSON.parse(readFileSync(join(BASE,slug,'config.json'),'utf8'));
const runMode=process.argv[4];if(!/^round-\d{4}$/.test(runMode))throw Error('Expected bounded retry round');
const retryCfg=JSON.parse(readFileSync(join(BASE,'humaneval','objrun-retry-to-target-v1-config.json'),'utf8'));
const round=Number(runMode.slice(6));if(round<1||round>retryCfg.maxRounds)throw Error('RoundLimit');
const BATCH=join(BASE,'humaneval','objrun-retry-to-target-v1'),OUT=join(BATCH,'rounds',runMode);
mkdirSync(OUT,{recursive:true});
const hash=(s:string|Buffer)=>createHash('sha256').update(s).digest('hex');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
function continuationSources(){for(const manifest of ['objrun-adapter-v1-source-pins.json','objrun-fireworks-v1-source-pins.json','objrun-retry-to-target-v1-source-pins.json'])for(const p of read(join(BASE,'humaneval',manifest)).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('ContinuationSourceChanged:'+p.path);}
function frozenSources(){if(phase==='full'){for(const p of read(join(BASE,'source-pins.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('FrozenSourceChanged:'+p.path);continuationSources();}}
function save(p:string,v:any){mkdirSync(resolve(p,'..'),{recursive:true});const tmp=p+'.'+process.pid+'.tmp';writeFileSync(tmp,JSON.stringify(v,null,2)+'\n');renameSync(tmp,p);}
function durable(p:string,v:any){mkdirSync(resolve(p,'..'),{recursive:true});const fd=openSync(p,'wx');try{writeFileSync(fd,JSON.stringify(v,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
function walk(d:string):string[]{return existsSync(d)?readdirSync(d,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(join(d,x.name)):[join(d,x.name)]):[];}
function allRecords(){return walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);}
function receipts(){return walk(join(OUT,'calls')).filter(p=>p.endsWith('receipt.json')).map(read);}
const totals=()=>{const rr=receipts();return {modelCalls:walk(join(OUT,'calls')).filter(p=>p.endsWith('dispatch.json')).length,completedCalls:rr.filter(r=>r.dispatched).length,actualCostUsd:rr.reduce((n,r)=>n+(r.actualCostUsd??0),0),unknownCostCount:rr.filter(r=>r.unknownCost).length,unknownCostUpperBoundUsd:rr.filter(r=>r.unknownCost).reduce((n,r)=>n+(r.upperBoundUsd??0),0)};};
if(phase==='status'){const prev=existsSync(join(OUT,'status.json'))?read(join(OUT,'status.json')):{};console.log(JSON.stringify({...prev,verifiedRecords:allRecords().length,...totals()}));process.exit(0);}
const catalogPath=join(BASE,slug,'public-tasks.json');
if(hash(readFileSync(catalogPath))!==cfg.publicCatalogSha256)throw Error('Frozen public catalog changed');
const catalog=read(catalogPath),selected=read(join(OUT,'selected-task-ids.json'));
if(selected.some((id:string)=>!retryCfg.initialFailedIds.includes(id)))throw Error('Only initial failures may be retried');
const tasks=selected.map((id:string)=>{const task=catalog.find((t:any)=>t.officialId===id);if(!task)throw Error('Missing public task:'+id);return task;});
function providerFor(dir:string){const short=dir.slice(join(OUT,'calls','objrun').length+1).split(/[\\/]/)[0];const provider=retryCfg.providers[short.replace('-','/')];if(!['DigitalOcean','Fireworks'].includes(provider))throw Error('Unknown retry provider:'+short);return provider;}
const key=benchmarkProviderKey(ROOT),grader='http://127.0.0.1:'+cfg.graderPort;
const lock=join(OUT,'runner-lock.json');
if(existsSync(lock)){const previous=read(lock);try{process.kill(previous.pid,0);throw Error('RunnerAlreadyLive:'+previous.pid);}catch(e){if(String(e).includes('RunnerAlreadyLive'))throw e;}renameSync(lock,lock+'.closed-'+Date.now());}
durable(lock,{pid:process.pid,atUtc:new Date().toISOString(),command:process.argv,phase,dataset:slug});
let stopped=false,error:string|undefined,currentArm='baseline',active:any[]=[];
const started=Date.now();
function status(stage='running'){
 const records=allRecords();const arms=Object.fromEntries(['baseline','objrun','independent'].map(arm=>{const a=records.filter(r=>r.arm===arm);const valid=a.filter(r=>r.grade?.valid);return [arm,{completed:a.length,total:tasks.length,valid:valid.length,passed:valid.filter(r=>r.grade?.passed).length,passRateCompleted:valid.length?valid.filter(r=>r.grade?.passed).length/valid.length:null,exceptions:a.filter(r=>!r.grade?.valid).length}];}));
 save(join(OUT,'status.json'),{dataset:slug,phase,stage,pid:process.pid,atUtc:new Date().toISOString(),startedAtUtc:new Date(started).toISOString(),elapsedSeconds:(Date.now()-started)/1000,currentArm,active,arms,...totals(),adapterVersion:'objrun-retry-to-target-v1',runMode,error});
}
async function grade(tid:string,code:string,feedback=false){
 for(let n=0;n<3;n++){
   try{const res=await fetch(grader+'/grade',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({task_id:tid,code,feedback_only:feedback}),signal:AbortSignal.timeout(180000)});const v=await res.json();if(v.valid||n===2)return v;}catch(e){if(n===2)return {valid:false,passed:false,errorType:'GraderTransport',diagnostic:String(e)};}
   await Bun.sleep(1000*(n+1));
 }
}
async function model(dir:string,body:any,samplingMax?:number):Promise<{raw:string,status:number,receipt:any}>{
 return withOneInterfaceRetry(dir,path=>modelOnce(path,body,samplingMax),{receipt:path=>existsSync(join(path,'receipt.json'))?read(join(path,'receipt.json')):undefined,event:value=>save(join(dir,'interface-retry-policy.json'),{...value,atUtc:new Date().toISOString(),authorizedBy:'User: 可以重试接口异常的题，其他题目也继续跑，接口异常不要阻塞整个Bench的进度。',oldFailureAndUnknownCostsRetained:true}),wait:()=>Bun.sleep(1000)});
}
async function modelOnce(dir:string,body:any,samplingMax?:number):Promise<{raw:string,status:number,receipt:any}>{
 const rr=join(dir,'receipt.json'),responsePath=join(dir,'response.json');
 if(existsSync(rr)){const receipt=read(rr);if(existsSync(responsePath))return {raw:readFileSync(responsePath,'utf8'),status:receipt.httpStatus??502,receipt};throw Error('UncertainPriorRequest:'+dir);}
 if(existsSync(join(dir,'request.json')))throw Error('UncertainPriorDispatch:'+dir);
 const provider=providerFor(dir),request={...body,stream:false,temperature:0,seed:42,reasoning_effort:'high',max_tokens:16384};
 const wire=provider==='Fireworks'?fireworksRequest(request):benchmarkProviderRequest(request,BENCHMARK_INFERENCE,BENCHMARK_PROVIDER);
 const clean=(v:any):any=>{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(clean);const x:any=Object.fromEntries(Object.entries(v).map(([k,t])=>[k,clean(t)]));if(x.type==='object')x.additionalProperties=false;return x;};
 if(wire.tools)wire.tools=wire.tools.map((t:any)=>({...t,function:{...t.function,parameters:clean(t.function.parameters)}}));
 if(samplingMax!==undefined)wire.max_tokens=samplingMax;
 continuationSources();
 const rawReq=JSON.stringify(wire);durable(join(dir,'request.json'),wire);
 durable(join(dir,'dispatch.json'),{atUtc:new Date().toISOString(),pid:process.pid,requestSha256:hash(rawReq)});
 const begin=Date.now();let raw='',httpStatus=0,v:any;
 try{
   const response=await fetch(BENCHMARK_PROVIDER.endpoint,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+key,'X-OpenRouter-Title':'ObjRun EvalPlus'},body:rawReq,signal:AbortSignal.timeout(600000),proxy:cfg.httpProxy} as any);
   httpStatus=response.status;raw=await response.text();durable(responsePath,JSON.parse(raw));v=JSON.parse(raw);
 }catch(e){v={transportError:String(e)};}
 const cost=typeof v.usage?.cost==='number'?v.usage.cost:null;
 const upperBoundUsd=cost??((v.usage?.prompt_tokens??Buffer.byteLength(rawReq))*0.3+(v.usage?.completion_tokens??wire.max_tokens)*1.2)/1e6;
 const explicitRejected=openRouterRateLimitRejection(v,httpStatus,provider);
 const receipt={atUtc:new Date().toISOString(),dispatched:true,httpStatus,generationId:v.id??null,model:v.model??null,provider:v.provider??null,usage:v.usage??null,actualCostUsd:explicitRejected?0:cost,upperBoundUsd:explicitRejected?0:upperBoundUsd,unknownCost:!explicitRejected&&cost===null,seconds:(Date.now()-begin)/1000,requestSha256:hash(rawReq),responseSha256:raw?hash(raw):null,fault:explicitRejected?'ExplicitRateLimit':v.error?.message??(httpStatus===200?officialOpenRouterFault(v,provider):v.transportError??'ProviderError'),samplingMaxTokens:samplingMax??null};
 durable(rr,receipt);
 if(!raw)throw Error('ProviderTransportUnknown:'+dir);
 return {raw,status:httpStatus,receipt};
}
async function objrun(task:any,dir:string){
 const engineDir=join(dir,'engine');mkdirSync(engineDir,{recursive:true});let taskInterfaceError:string|undefined;
 const protocolEvents:any[]=[];
 const proxy=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(req){try{const body=await req.json();const r=await submitResponse(body,async(request,protocolAttempt)=>{const digest=hash(JSON.stringify(request));let result:any;for(let n=0;n<3;n++){result=await model(join(OUT,'calls','objrun',task.officialId.replace('/','-'),'schema-v3',digest,'attempt-'+n),request);if(result.receipt.fault==='ExplicitRateLimit'&&n<2){await Bun.sleep((n+1)*1000);continue;}break;}if(result.receipt.fault&&result.receipt.fault!=='MissingOrInvalidOpenRouterUsdCost')throw Error('ProviderFault:'+result.receipt.fault);protocolEvents.push({atUtc:new Date().toISOString(),protocolAttempt,requestHash:digest,generationId:result.receipt.generationId});save(join(dir,'submit-response-attempts.json'),protocolEvents);return result;});return new Response(r.raw,{status:r.status,headers:{'content-type':'application/json'}});}catch(e){taskInterfaceError=String(e);return Response.json({error:{message:String(e)}},{status:502});}}});
 let engine:Machine|undefined;
 const id='ep-humaneval-objrun-retry-to-target-v1-'+runMode+'/objrun/'+task.officialId;
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
 while(Date.now()-start<1260000){if(taskInterfaceError)throw Error(taskInterfaceError);t=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/status');const why=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/why');if(JSON.stringify(why.problems).includes('The required submit tool was not called exactly once')){const trace=await engine.api<any>('POST','/query',{sql:'select * from agent_bot_msg order by unit,seq'});save(join(dir,'trace.json'),trace.rows);return {answer:'',candidateHow:'none',engineState:'model_submission_protocol_failure',engineVerdict:{valid:true,pass:0,outcome:'model_submission_protocol_failure'},modelProtocolFailure:true,originalKernelEvidence:why};}if(['done','failed'].includes(t.state)&&t.result&& !['finalization_pending','finalization_error'].includes(JSON.parse(t.result).outcome))break;await Bun.sleep(1000);}
 if(!t?.result)throw Error('EngineTaskDeadline');
 const trace=await engine.api<any>('POST','/query',{sql:'select * from agent_bot_msg where instance like :prefix order by unit,seq',params:{prefix:id+'#%'}});save(join(dir,'trace.json'),trace.rows);
 const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});let candidate:any;
 try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const q=db.prepare(sql);try{return q.all(...params);}finally{q.finalize();}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);}finally{db.close();}
 return {answer:candidate?.body??'',candidateHow:candidate?.how??'none',engineState:t.state,engineVerdict:JSON.parse(t.result),enginePid:engine.pid};
 }finally{await engine?.stop();await proxy.stop(false);}
}
async function taskRun(task:any,arm:string){
 frozenSources();
 const short=task.officialId.replace('/','-'),resultPath=join(OUT,'results',arm,short+'.json');
 if(existsSync(resultPath)){const prior=read(resultPath);if(prior.grade?.valid||prior.interfaceRetryExhausted)return;if(prior.answer!==undefined){prior.grade=await grade(task.officialId,prior.answer);save(resultPath,prior);const state=acceptAttempt(read(join(BATCH,'effective-state.json')),prior,resultPath,round);save(join(BATCH,'effective-state.json'),state);return;}throw Error('Interrupted task requires evidence reconciliation:'+task.officialId);}
 const state=read(join(BATCH,'effective-state.json'));if(state.cases[task.officialId].passed||targetReached(state))return;
 const dir=join(OUT,'tasks',arm,short);mkdirSync(dir,{recursive:true});const begin=Date.now();
 active.push({arm,taskId:task.officialId,startedAtUtc:new Date().toISOString()});status();
 let result:any={officialId:task.officialId,arm,purpose:'User-authorized fresh ObjRun retry; separate cumulative metric',round,providerExpected:retryCfg.providers[task.officialId],promptSha256:task.promptSha256};
 try{const x=await objrun(task,dir);save(join(dir,'candidate.json'),x);result={...result,...x};result.grade=x.modelProtocolFailure?{valid:true,passed:false,errorType:'ModelSubmissionProtocolFailure'}:await grade(task.officialId,x.answer);}
 catch(e){result.error=String(e);result.grade={valid:false,passed:false,errorType:'GenerationOrRunnerError'};}
 if(interfaceFailure(result.error)){result.interfaceFailure=true;result.interfaceRetryExhausted=true;}
 const own=walk(join(OUT,'calls',arm,short)).filter(p=>p.endsWith('receipt.json')).map(read);
 const eventsPath=join(dir,'submit-response-attempts.json');result.protocolRepairCalls=existsSync(eventsPath)?read(eventsPath).filter((r:any)=>r.protocolAttempt===1).length:0;
 result={...result,completedAtUtc:new Date().toISOString(),seconds:(Date.now()-begin)/1000,modelCalls:own.length,actualCostUsd:own.reduce((n,r)=>n+(r.actualCostUsd??0),0),unknownCostCount:own.filter(r=>r.unknownCost).length};
 save(resultPath,result);const updated=acceptAttempt(read(join(BATCH,'effective-state.json')),result,resultPath,round);save(join(BATCH,'effective-state.json'),updated);
 active=active.filter(x=>x.taskId!==task.officialId);console.log(JSON.stringify({task:task.officialId,round,valid:result.grade?.valid,passed:result.grade?.passed,cumulativePassed:updated.passed,accuracy:updated.accuracy,seconds:result.seconds,error:result.error}));status();
}
async function main(){
 frozenSources();const health=await(await fetch(grader+'/health')).json();if(health.dataset!==slug)throw Error('Wrong grader');if(!read(join(BASE,'controls.json')).allPassed)throw Error('Controls failed');
 const timer=setInterval(()=>status(),15000);status();
 try{currentArm='objrun';let index=0;await Promise.all(Array.from({length:2},async()=>{while(index<tasks.length&&!targetReached(read(join(BATCH,'effective-state.json')))){if(!canSchedule(read(join(BATCH,'effective-state.json')),active.length)){await Bun.sleep(250);continue;}await taskRun(tasks[index++],'objrun');}}));}
 finally{clearInterval(timer);status('complete');if(existsSync(lock))unlinkSync(lock);}
}
main().catch(e=>{error=String(e);status('needs_attention');console.error(error);if(existsSync(lock))unlinkSync(lock);process.exitCode=1;});
