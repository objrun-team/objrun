import {sampleUpToFive} from './humaneval-five-samples.ts';
import {createHash} from 'node:crypto';
import {withOneInterfaceRetry} from './humaneval-interface-policy-v2.ts';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,openSync,fsyncSync,closeSync,renameSync,unlinkSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {BENCHMARK_PROVIDER,benchmarkProviderKey,officialOpenRouterFault,openRouterRateLimitRejection} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts';
const ROOT=resolve(import.meta.dir,'../../..'),BASE=join(ROOT,'docs/evalplus-20261012');
const slug=process.argv[2],phase=process.argv[3]??'pilot';
if(slug!=='humaneval'||phase!=='full')throw Error('HumanEval continuation is restricted to humaneval full');
if(!['humaneval','mbpp'].includes(slug)||!['pilot','full','status'].includes(phase))throw Error('run.ts humaneval|mbpp pilot|full|status');
const cfg=JSON.parse(readFileSync(join(BASE,slug,'config.json'),'utf8'));
const OUT=join(BASE,slug,phase==='status'?(process.argv[4]??'full'):phase);
mkdirSync(OUT,{recursive:true});
const hash=(s:string|Buffer)=>createHash('sha256').update(s).digest('hex');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
function continuationSources(){for(const p of read(join(BASE,'humaneval','independent-fixed5-source-pins.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('ContinuationSourceChanged:'+p.path);}
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
const catalog=read(catalogPath),tasks=phase==='pilot'?catalog.slice(0,10):catalog;
const key=benchmarkProviderKey(ROOT),grader='http://127.0.0.1:'+cfg.graderPort;
const samplingCfg=read(join(BASE,'humaneval','independent-fixed5-config.json'));
if(samplingCfg.maxAttempts!==5||samplingCfg.maxTokens!==16384||!samplingCfg.stopAfterCorrect)throw Error('Wrong fixed-five sampling configuration');
const baselineWire=read(join(OUT,'calls','baseline','HumanEval-0','sample-0','attempt-0','request.json'));
const sorted=(v:any):any=>Array.isArray(v)?v.map(sorted):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sorted(v[k])])):v;
function generationOptions(v:any){const {messages,...other}=v;return JSON.stringify(sorted(other));}
const lock=join(OUT,'runner-lock.json');
if(existsSync(lock)){const previous=read(lock);try{process.kill(previous.pid,0);throw Error('RunnerAlreadyLive:'+previous.pid);}catch(e){if(String(e).includes('RunnerAlreadyLive'))throw e;}renameSync(lock,lock+'.closed-'+Date.now());}
durable(lock,{pid:process.pid,atUtc:new Date().toISOString(),command:process.argv,phase,dataset:slug});
let stopped=false,error:string|undefined,currentArm='independent',active:any[]=[];
const started=Date.now();
function status(stage='running'){
 const records=allRecords();const arms=Object.fromEntries(['baseline','objrun','independent'].map(arm=>{const a=records.filter(r=>r.arm===arm);const valid=a.filter(r=>r.grade?.valid);return [arm,{completed:a.length,total:tasks.length,valid:valid.length,passed:valid.filter(r=>r.grade?.passed).length,passRateCompleted:valid.length?valid.filter(r=>r.grade?.passed).length/valid.length:null,exceptions:a.filter(r=>!r.grade?.valid).length}];}));
 save(join(OUT,'status.json'),{dataset:slug,phase,stage,pid:process.pid,atUtc:new Date().toISOString(),startedAtUtc:new Date(started).toISOString(),elapsedSeconds:(Date.now()-started)/1000,currentArm,active,arms,...totals(),samplingVersion:'fixed5-v1',maxAttempts:5,maxTokens:16384,stopAfterCorrect:true,error});
}
async function grade(tid:string,code:string,feedback=false){
 for(let n=0;n<3;n++){
   try{const res=await fetch(grader+'/grade',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({task_id:tid,code,feedback_only:feedback}),signal:AbortSignal.timeout(180000)});const v=await res.json();if(v.valid||n===2)return v;}catch(e){if(n===2)return {valid:false,passed:false,errorType:'GraderTransport',diagnostic:String(e)};}
   await Bun.sleep(1000*(n+1));
 }
}
async function model(dir:string,body:any,samplingMax?:number):Promise<{raw:string,status:number,receipt:any}>{
 // Original approval retained verbatim: retry interface failures, continue other tasks, and do not let interface errors block the entire benchmark.
 return withOneInterfaceRetry(dir,path=>modelOnce(path,body,samplingMax),{receipt:path=>existsSync(join(path,'receipt.json'))?read(join(path,'receipt.json')):undefined,event:value=>save(join(dir,'interface-retry-policy.json'),{...value,atUtc:new Date().toISOString(),authorizedBy:'User: 可以重试接口异常的题，其他题目也继续跑，接口异常不要阻塞整个Bench的进度。',oldFailureAndUnknownCostsRetained:true}),wait:()=>Bun.sleep(1000)});
}
async function modelOnce(dir:string,body:any,samplingMax?:number):Promise<{raw:string,status:number,receipt:any}>{
 const rr=join(dir,'receipt.json'),responsePath=join(dir,'response.json');
 if(existsSync(rr)){const receipt=read(rr);if(existsSync(responsePath))return {raw:readFileSync(responsePath,'utf8'),status:receipt.httpStatus??502,receipt};throw Error('UncertainPriorRequest:'+dir);}
 if(existsSync(join(dir,'request.json')))throw Error('UncertainPriorDispatch:'+dir);
 const wire=benchmarkProviderRequest({...body,stream:false,temperature:0,seed:42,reasoning_effort:'high',max_tokens:16384},BENCHMARK_INFERENCE,BENCHMARK_PROVIDER);
 const clean=(v:any):any=>{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(clean);const x:any=Object.fromEntries(Object.entries(v).map(([k,t])=>[k,clean(t)]));if(x.type==='object')x.additionalProperties=false;return x;};
 if(wire.tools)wire.tools=wire.tools.map((t:any)=>({...t,function:{...t.function,parameters:clean(t.function.parameters)}}));
 if(samplingMax!==undefined&&samplingMax!==16384)throw Error('Token ceiling must equal baseline');
 if(generationOptions(wire)!==generationOptions(baselineWire))throw Error('Generation settings differ from baseline');
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
 const explicitRejected=openRouterRateLimitRejection(v,httpStatus,BENCHMARK_PROVIDER.providerName);
 const receipt={atUtc:new Date().toISOString(),dispatched:true,httpStatus,generationId:v.id??null,model:v.model??null,provider:v.provider??null,usage:v.usage??null,actualCostUsd:explicitRejected?0:cost,upperBoundUsd:explicitRejected?0:upperBoundUsd,unknownCost:!explicitRejected&&cost===null,seconds:(Date.now()-begin)/1000,requestSha256:hash(rawReq),responseSha256:raw?hash(raw):null,fault:explicitRejected?'ExplicitRateLimit':v.error?.message??(httpStatus===200?officialOpenRouterFault(v):v.transportError??'ProviderError'),samplingMaxTokens:samplingMax??null};
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

async function taskRun(task:any){
 frozenSources();
 const arm='independent',short=task.officialId.replace('/','-'),resultPath=join(OUT,'results',arm,short+'.json');
 if(existsSync(resultPath)&&read(resultPath).grade?.valid)return;
 const dir=join(OUT,'tasks',arm,short);mkdirSync(dir,{recursive:true});const begin=Date.now();
 active.push({arm,taskId:task.officialId,startedAtUtc:new Date().toISOString()});status();
 const samplePath=join(dir,'samples.json');const prior=existsSync(samplePath)?read(samplePath):[];
 for(const sample of prior){if(sample.answer!==undefined&&!sample.grade?.valid)sample.grade=await grade(task.officialId,sample.answer);}
 const samples=await sampleUpToFive({prior,generate:index=>generated(task,join(OUT,'calls',arm,short),index),grade:answer=>grade(task.officialId,answer),persist:rows=>save(samplePath,rows)});
 save(samplePath,samples);
 const passed=samples.some(x=>x.grade?.valid&&x.grade?.passed);
 const valid=passed||(samples.length===5&&samples.every(x=>x.grade?.valid));
 const own=walk(join(OUT,'calls',arm,short)).filter(p=>p.endsWith('receipt.json')).map(read);
 const result={officialId:task.officialId,arm,purpose:'Fixed task list; new independent up-to-five experiment',samplingVersion:'fixed5-v1',promptSha256:task.promptSha256,attemptCount:samples.length,sampleCount:samples.filter(x=>x.answer!==undefined).length,maxAttempts:5,maxTokens:16384,stopAfterCorrect:true,matchProtocol:'Fresh public prompt each time; generation options exactly equal baseline; up to five attempts; independent official base+plus scoring after each attempt; stop on first correct solution; no answers or feedback in model messages; no paired-cost or reduced-token cap.',grade:{valid,passed,lastCandidatePassed:!!(samples.at(-1)?.grade?.valid&&samples.at(-1)?.grade?.passed),firstCandidatePassed:!!(samples[0]?.grade?.valid&&samples[0]?.grade?.passed),...(valid?{}:{errorType:'IndependentAttemptException'})},completedAtUtc:new Date().toISOString(),seconds:(Date.now()-begin)/1000,modelCalls:own.filter(r=>r.dispatched).length,actualCostUsd:own.reduce((n,r)=>n+(r.actualCostUsd??0),0),unknownCostCount:own.filter(r=>r.unknownCost).length};
 save(resultPath,result);active=active.filter(x=>x.taskId!==task.officialId);
 console.log(JSON.stringify({task:task.officialId,arm,valid,passed,attempts:result.attemptCount,maxTokens:16384,seconds:result.seconds,cost:result.actualCostUsd}));status();
}
async function main(){
 frozenSources();
 const health=await(await fetch(grader+'/health')).json();if(health.dataset!=='humaneval')throw Error('Wrong grader');
 if(!read(join(BASE,'controls.json')).allPassed)throw Error('Official grader controls not accepted');
 const timer=setInterval(()=>status(),15000);status();let index=0;
 try{await Promise.all(Array.from({length:cfg.concurrency},async()=>{while(index<tasks.length)await taskRun(tasks[index++]);}));}
 finally{clearInterval(timer);status('independent_complete_needs_objrun_diagnosis');if(existsSync(lock))unlinkSync(lock);}
}
main().catch(e=>{error=String(e);status('needs_attention');console.error(error);if(existsSync(lock))unlinkSync(lock);process.exitCode=1;});
