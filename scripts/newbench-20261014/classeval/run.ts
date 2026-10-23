import {createHash} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,renameSync,unlinkSync,openSync,closeSync,fsyncSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from '../runtime-snapshot/test/_lib.ts';
import {finalCandidate} from '../runtime-snapshot/app/src/objective/candidate.ts';
import {BENCHMARK_PROVIDER,benchmarkProviderKey,officialOpenRouterFault} from '../runtime-snapshot/scripts/repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../runtime-snapshot/scripts/repair-2026-10-10/full-f/shared/digitalocean-inference.ts';
import {requestTimeoutMs,canaryReady,retainedTaskAttempts} from './interface-policy.ts';
import {TaskSlots} from './task-slots.ts';
import {withProviderRoute} from './wire-provider.ts';
import {recoverSubmittedAtDeadline} from './native-checkpoint.ts';
import {assertExceptionRecovery,exceptionLimits} from './exception-policy.ts';

const SRC=import.meta.dir,ROOT=resolve(SRC,'../../..'),OUT=join(ROOT,'docs/newbench-20261014/classeval');
const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const cfg=read(join(SRC,'experiment.json')),catalog=read(join(SRC,'public-tasks.json'));
const OBJRUN_PROVIDER:any=cfg.objrunProvider??BENCHMARK_PROVIDER;
const OBJRUN_SOLVE_SECONDS=Number(cfg.objrunSolveSeconds??cfg.solveSeconds);
const CONCURRENCY=Number(cfg.concurrency??cfg.initialConcurrency);
const taskSlots=new TaskSlots(CONCURRENCY);
const hash=(x:string|Buffer)=>createHash('sha256').update(x).digest('hex');
function save(p:string,v:any){mkdirSync(dirname(p),{recursive:true});const tmp=p+'.'+process.pid+'.tmp';writeFileSync(tmp,JSON.stringify(v,null,2)+'\n');renameSync(tmp,p);}
function durable(p:string,v:any){mkdirSync(dirname(p),{recursive:true});const fd=openSync(p,'wx');try{writeFileSync(fd,JSON.stringify(v,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
function walk(d:string):string[]{return existsSync(d)?readdirSync(d,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(join(d,x.name)):[join(d,x.name)]):[];}
function alive(pid:number){try{process.kill(pid,0);return true;}catch{return false;}}
function pins(){const files=[...walk(SRC).filter(p=>/\.(ts|py|json|ps1)$/.test(p)&&!p.includes('source-pins.json')&&!p.includes('__pycache__')),...walk(join(SRC,'../runtime-snapshot/app/src')).filter(p=>p.endsWith('.ts')),join(SRC,'../runtime-snapshot/test/_lib.ts'),...walk(join(SRC,'../runtime-snapshot/scripts')).filter(p=>p.endsWith('.ts')),join(SRC,'../runtime-snapshot/app/bun.lock'),join(SRC,'../runtime-snapshot/app/package.json')];return [...new Set(files)].filter(existsSync).map(p=>({path:resolve(p),sha256:hash(readFileSync(p))}));}
const command=process.argv[2]??'run';mkdirSync(OUT,{recursive:true});
if(command==='pin'){save(join(OUT,'source-pins.json'),{atUtc:new Date().toISOString(),files:pins()});console.log('Pinned ClassEval sources');process.exit(0);}
function frozen(){const audit=read(join(SRC,'catalog-audit.json'));if(catalog.length!==100||hash(readFileSync(join(SRC,'public-tasks.json')))!==audit.publicCatalogSha256)throw Error('PublicCatalogChanged');for(const p of read(join(OUT,'source-pins.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('SourceChanged:'+p.path);if(cfg.model!==BENCHMARK_PROVIDER.model||cfg.provider!==BENCHMARK_PROVIDER.providerName||cfg.maxTokens!==16384||cfg.checks!==5||cfg.solveSeconds!==600||cfg.cyclesMaxUnits!==12||cfg.maxBranches!==4)throw Error('ExperimentProfileChanged');if(OBJRUN_SOLVE_SECONDS!==600){const amendment=read(join(OUT,'protocol-amendment.json'));if(OBJRUN_SOLVE_SECONDS!==1200||!amendment.approved||amendment.objrunSolveSeconds!==1200||amendment.additionalCanaryAttempts!==1||amendment.maxTaskAttemptsForClassEval0!==5)throw Error('UnapprovedObjRunSolveLimit');}if(cfg.exceptionRecovery)assertExceptionRecovery(cfg.exceptionRecovery,read(join(OUT,'exception-timeout-amendment.json')));}
const key=benchmarkProviderKey(ROOT);process.env.OPENROUTER_API_KEY=key;
function allowedTaskAttempts(arm:string,taskId:string){
 const exception=exceptionLimits(arm,taskId,cfg.exceptionRecovery);if(exception)return exception.maxTaskAttempts;
 const policyPath=join(OUT,'interface-recovery.json'),probePath=join(OUT,'tool-probe-latest.json');
 if(arm!=='objrun'||taskId!=='ClassEval_0'||!existsSync(policyPath)||!existsSync(probePath))return 2;
 const policy=read(policyPath),probe=read(probePath);
 if(![3,4,5].includes(policy.maxTaskAttempts)||policy.taskId!==taskId||!probe.healthy||probe.generationId!==policy.healthProbeGenerationId||probe.provider!==OBJRUN_PROVIDER.providerName||probe.model!==cfg.model)throw Error('InvalidBoundedInterfaceRecoveryPolicy');
 if(policy.maxTaskAttempts===5){const amendment=read(join(OUT,'protocol-amendment.json'));if(!amendment.approved||amendment.maxTaskAttemptsForClassEval0!==5||amendment.additionalCanaryAttempts!==1||OBJRUN_SOLVE_SECONDS!==1200||policy.objrunSolveSeconds!==1200)throw Error('InvalidBoundedTimeLimitRecoveryPolicy');}
 return policy.maxTaskAttempts;
}
const lock=join(OUT,'runner-lock.json');
if(existsSync(lock)){const prior=read(lock);if(alive(prior.pid))throw Error('RunnerAlreadyLive:'+prior.pid);renameSync(lock,lock+'.closed-'+Date.now());}
// Refuse to overlap a live engine left behind by an interrupted runner.
for(const p of walk(join(OUT,'tasks')).filter(p=>p.endsWith('engine-process.json'))){const prior=read(p);if(alive(prior.pid)&&!existsSync(join(dirname(p),'engine-stopped.json')))throw Error('PriorEngineStillLive:'+prior.pid);}
durable(lock,{pid:process.pid,atUtc:new Date().toISOString(),command:process.argv});
const originPath=join(OUT,'experiment-origin.json');if(!existsSync(originPath))durable(originPath,{atUtc:new Date().toISOString(),experiment:cfg,catalogSha256:hash(readFileSync(join(SRC,'public-tasks.json')))});
let stage='preflight',fatal:string|undefined,attention=false,stopped=false,active:any[]=[],grader='',graderPid:number|undefined;
const records=()=>walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);
const receipts=()=>walk(join(OUT,'calls')).filter(p=>p.endsWith('/receipt.json')||p.endsWith('\\receipt.json')).map(read);
function costs(){const rr=receipts(),unresolved=walk(join(OUT,'calls')).filter(p=>p.endsWith('dispatch.json')&&!existsSync(join(dirname(p),'receipt.json'))).map(read);return {modelCalls:rr.length+unresolved.length,actualCostUsd:rr.reduce((n,r)=>n+(r.actualCostUsd??0),0),unknownCostCount:rr.filter(r=>r.unknownCost).length+unresolved.length,unknownCostUpperBoundUsd:rr.filter(r=>r.unknownCost).reduce((n,r)=>n+r.upperBoundUsd,0)+unresolved.reduce((n,r)=>n+r.upperBoundUsd,0),unresolvedDispatchCount:unresolved.length,successfulModelResponses:rr.filter(r=>r.httpStatus===200&&!r.fault).length};}
function status(){const rr=records(),arms=Object.fromEntries(cfg.arms.map((arm:string)=>{const x=rr.filter(r=>r.arm===arm),valid=x.filter(r=>r.grade?.valid);return [arm,{total:100,completed:x.length,valid:valid.length,passed:valid.filter(r=>r.grade.passed).length,exceptions:x.filter(r=>!r.grade?.valid).length,passRateCompleted:valid.length?valid.filter(r=>r.grade.passed).length/valid.length:null}];}));save(join(OUT,'status.json'),{dataset:'classeval',stage,pid:process.pid,graderPid,grader,atUtc:new Date().toISOString(),startedAtUtc:read(originPath).atUtc,active,arms,...costs(),fatal,attention,protocol:'baseline single model attempt; objrun native machine with official-test feedback',sourceCommit:'90825141e640418ae6dc8257397345ee3ac36cbc',concurrency:CONCURRENCY,baselineProvider:cfg.provider,objrunProvider:OBJRUN_PROVIDER.providerName,objrunSolveSeconds:OBJRUN_SOLVE_SECONDS,exceptionRecovery:cfg.exceptionRecovery,providerFallbacks:false,perTaskDollarCap:null,monetaryStopPolicy:'Only actual account/API key availability; no task dollar cap'});}
function shouldStop(){if(existsSync(join(OUT,'stop-after-current-tasks.json')))stopped=true;return stopped;}
function updateRunning(){writeFileSync(join(OUT,'RUNNING.md'),`# ClassEval 2026-10-14\n\nStage: ${stage}. Runner PID: ${process.pid}. Grader PID: ${graderPid??'starting'}. Total shared task concurrency: ${CONCURRENCY}; grader concurrency: ${cfg.graderConcurrency??2}. User requested concurrency 8 on 2026-10-14.\n\nEntry: scripts/newbench-20261014/classeval/start.ps1 (resume safely with the same command).\nStatus: docs/newbench-20261014/classeval/status.json.\n\nBaseline: one successful model response per task, no test feedback before final grading. ObjRun: the frozen native machine, declare/tasks/submit/verify/finalCandidate, c5 / ${OBJRUN_SOLVE_SECONDS} seconds / 12 units / 4 branches. The original 600-second profile and all four prior ClassEval_0 attempts are retained; the user explicitly approved 1200 seconds for one additional canary and the remaining ObjRun tasks on 2026-10-14. ObjRun receives clipped official-test statistics; this is a test-feedback protocol and differs from standard single-attempt evaluation.\n\nModel: ${cfg.model}; OpenRouter baseline provider: ${cfg.provider}; ObjRun provider: ${OBJRUN_PROVIDER.providerName}; reasoning: enabled/high; temperature: 0; max_tokens: 16384; fallbacks: false. Official ClassEval v1.0.0 commit 90825141e640418ae6dc8257397345ee3ac36cbc; 100 fixed tasks per arm. Imports are supplied from import_statement. No tests or reference code are included in real model context.\n\nCanary: ClassEval_0 in each arm. A valid baseline canary permits baseline to continue independently; ObjRun continues after its canary has a valid grade and a native submitted final candidate. API failures are isolated to the affected arm. Valid canary results count toward the 100 and are not rerun.\n\nResults/candidates: results/ and tasks/. Raw key-free requests/responses and cost receipts: calls/. Scoring cache/logs: grader/. Account/key observations: observations/. Source pins: source-pins.json.\n\nContainers: existing pinned image, org.objrun.owner=newbench-20261014, 2 CPU / 2 GiB, non-root, no network, read-only root and private temporary directories. Only created containers are deleted. Model keys remain in local process environment.\n\nUser requirement (2026-10-14): no per-task dollar budget or spending cap. A task's accumulated cost never stops it, reduces its 16k output allowance, or truncates retries. Only account/API key availability can stop further spending; existing non-monetary limits and finite interface retries remain. No account/key limits are changed.\n\nFinite API retries and one task recovery are retained with all charges/unknown costs. ClassEval_0 has three retained failed DigitalOcean attempts. The user then explicitly authorized trying another supplier on 2026-10-14; a successful Fireworks tool probe permitted the fourth native canary, which reached the 600-second solve deadline without submit. The user then explicitly approved a 1200-second ObjRun solve limit and one additional canary, for a strict maximum of five retained ClassEval_0 attempts in interface-recovery.json and protocol-amendment.json. ObjRun is pinned to Fireworks with no automatic fallback; baseline remains DigitalOcean and its 100 valid results are retained. This provider difference must be reported in any comparison. Additional attempts are not unlimited. All retries and request timeouts in an ObjRun attempt are bounded by that native task's ${OBJRUN_SOLVE_SECONDS}-second solve deadline. Valid results never rerun; recovered candidates are regraded without generation. Exceptions do not count as wrong answers. A stop-after-current-tasks.json file requests a checkpoint. Insufficient credits stop further dispatch; no top-up, key-limit change, provider switch, or duplicate automation is performed.\n\n${cfg.exceptionRecovery?'Exception-only timeout amendment: '+JSON.stringify(cfg.exceptionRecovery)+'. The user authorized 2400 seconds and one additional attempt only for the listed invalid tasks. Every other task retains its existing budget; all valid results are reused. See exception-timeout-amendment.json.\n\n':''}${fatal?'Attention: '+fatal+'\n':''}`, 'utf8');}

let balance:any;
async function observation(){
 const dir=join(OUT,'observations',String(Date.now()));mkdirSync(dir,{recursive:true});
 const get=async(url:string)=>{for(let n=0;n<3;n++){try{const r=await fetch(url,{headers:{authorization:'Bearer '+key},proxy:cfg.localProxy,signal:AbortSignal.timeout(30000)} as any);const v:any=await r.json();if(!r.ok)throw Error('ObservationHttp:'+r.status);return v;}catch(e){if(n===2)throw e;await Bun.sleep(500*(n+1));}}};
 const credit:any=await get(BENCHMARK_PROVIDER.baseURL+'/credits'),k:any=await get(BENCHMARK_PROVIDER.baseURL+'/key');
 if(!Number.isFinite(credit.data?.total_credits)||!Number.isFinite(credit.data?.total_usage))throw Error('InvalidCreditObservation');
 const accountRemainingUsd=credit.data.total_credits-credit.data.total_usage;
 const keyRemainingUsd=k.data?.limit_remaining??(typeof k.data?.limit==='number'?k.data.limit-(k.data.usage??0):null);
 balance={atUtc:new Date().toISOString(),accountRemainingUsd,keyRemainingUsd,remainingUsd:Math.min(accountRemainingUsd,keyRemainingUsd??Infinity),rateLimit:k.data?.rate_limit??null,readOnly:true};
 save(join(dir,'balance.json'),balance);save(join(OUT,'balance-latest.json'),balance);
 if(!Number.isFinite(balance.remainingUsd)||balance.remainingUsd<0)throw Error('InvalidAvailableBalance');
 if(!existsSync(join(OUT,'prices.json'))){const data:any=await get(BENCHMARK_PROVIDER.baseURL+'/models/'+cfg.model+'/endpoints');const endpoint=data.data?.endpoints?.find((e:any)=>e.provider_name===cfg.provider&&e.tag===cfg.providerSlug);if(!endpoint)throw Error('PinnedProviderEndpointUnavailable');save(join(dir,'endpoints.json'),data);const prices=[endpoint.pricing,...(endpoint.pricing.overrides??[])],rates={input:Math.max(...prices.map((p:any)=>Number(p.prompt??endpoint.pricing.prompt)))*1e6,output:Math.max(...prices.map((p:any)=>Number(p.completion??endpoint.pricing.completion)))*1e6};if(!Number.isFinite(rates.input)||!Number.isFinite(rates.output)||rates.input>0.3+1e-12||rates.output>1.2+1e-12)throw Error('ProviderTariffExceedsPinnedCeiling');save(join(OUT,'prices.json'),{atUtc:new Date().toISOString(),model:cfg.model,provider:cfg.provider,rates,source:'https://openrouter.ai/api/v1/models/'+cfg.model+'/endpoints'});}
 return balance;
}
function estimate(){const r=records();const byArm=Object.fromEntries(cfg.arms.map((arm:string)=>{const x=r.filter(v=>v.arm===arm&&v.grade?.valid),pending=100-x.length;const mean=x.length?x.reduce((n,v)=>n+v.actualCostUsd,0)/x.length:null;return [arm,{valid:x.length,pending,meanObservedUsd:mean,estimatedRemainingUsd:mean===null?null:pending*mean*1.5}];}));const values=Object.values(byArm) as any[];save(join(OUT,'cost-estimate.json'),{atUtc:new Date().toISOString(),byArm,estimatedRemainingUsd:values.every(x=>x.estimatedRemainingUsd!==null)?values.reduce((n,x)=>n+x.estimatedRemainingUsd,0):null,safetyMultiplier:1.5,balance,unknownCosts:costs().unknownCostUpperBoundUsd,estimateOnly:true});return byArm;}
let reservedUsd=0,spentSinceObservation=0;
async function model(dir:string,body:any,deadline?:number,provider:any=BENCHMARK_PROVIDER){
 const wire=withProviderRoute(benchmarkProviderRequest({...body,model:cfg.model,stream:false,temperature:0,reasoning_effort:'high',max_tokens:16384},BENCHMARK_INFERENCE,BENCHMARK_PROVIDER),provider);
 const closeSchema=(v:any):any=>{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(closeSchema);const r=Object.fromEntries(Object.entries(v).map(([k,x])=>[k,closeSchema(x)]));if(r.type==='object')r.additionalProperties=false;return r;};
 if(wire.tools)wire.tools=wire.tools.map((t:any)=>({...t,function:{...t.function,parameters:closeSchema(t.function.parameters)}}));
 const rawReq=JSON.stringify(wire),upperBoundUsd=(Buffer.byteLength(rawReq)*provider.peakRates.input+16384*provider.peakRates.output)/1e6;
 for(let n=0;n<3;n++){
  const d=join(dir,'attempt-'+n),receiptPath=join(d,'receipt.json');let receipt:any,raw:string;
  if(existsSync(receiptPath)){receipt=read(receiptPath);if(receipt.requestSha256!==hash(rawReq))throw Error('SavedRequestMismatch');raw=existsSync(join(d,'response.json'))?readFileSync(join(d,'response.json'),'utf8'):'';}
  else{
   if(existsSync(join(d,'dispatch.json')))throw Error('UnresolvedPriorDispatch:'+d);
   frozen();if(stopped)throw Error('StoppedBeforeDispatch');
   const timeoutMs=requestTimeoutMs(deadline,Date.now());
   if(balance.remainingUsd-spentSinceObservation-reservedUsd<upperBoundUsd+0.01){stopped=true;fatal='InsufficientBalance';throw Error(fatal);}
   reservedUsd+=upperBoundUsd;durable(join(d,'request.json'),wire);durable(join(d,'dispatch.json'),{atUtc:new Date().toISOString(),pid:process.pid,requestSha256:hash(rawReq),upperBoundUsd});
   const begin=Date.now();let status=0,v:any,transportError:string|undefined;raw='';
   try{const response=await fetch(BENCHMARK_PROVIDER.endpoint,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+key,'X-OpenRouter-Title':'ObjRun ClassEval 20261014'},body:rawReq,signal:AbortSignal.timeout(timeoutMs),proxy:cfg.localProxy} as any);status=response.status;raw=await response.text();writeFileSync(join(d,'response.json'),raw,{flag:'wx'});try{v=JSON.parse(raw);}catch{v={};}}catch(e){transportError=String(e);v={};}
   const actualCostUsd=typeof v?.usage?.cost==='number'&&Number.isFinite(v.usage.cost)&&v.usage.cost>=0?v.usage.cost:null;
   const explicitlyRejected=status!==200&&!v.id&&!v.usage&&[400,401,402,403,404,429].includes(status);
   const fault=transportError??v.error?.message??(status===200?officialOpenRouterFault(v,provider.providerName):'ProviderHttp:'+status);
   receipt={atUtc:new Date().toISOString(),requestSha256:hash(rawReq),responseSha256:raw?hash(raw):null,httpStatus:status,generationId:v.id??null,model:v.model??null,provider:v.provider??null,usage:v.usage??null,actualCostUsd:explicitlyRejected?0:actualCostUsd,upperBoundUsd:explicitlyRejected?0:upperBoundUsd,unknownCost:!explicitlyRejected&&actualCostUsd===null,fault,seconds:(Date.now()-begin)/1000,requestedProviderName:provider.providerName,requestedProviderSlug:provider.providerSlug,officialCatalogQuantization:provider.quantization??'unknown'};
   durable(receiptPath,receipt);reservedUsd-=upperBoundUsd;spentSinceObservation+=receipt.actualCostUsd??receipt.upperBoundUsd;
   console.log(JSON.stringify({event:'model_receipt',atUtc:receipt.atUtc,generationId:receipt.generationId,status,provider:receipt.provider,cost:receipt.actualCostUsd,fault}));statusUpdate();
  }
  if(receipt.httpStatus===402){stopped=true;fatal='ProviderInsufficientCredits';throw Error(fatal);}
  const accepted=!receipt.fault||receipt.fault==='MissingOrInvalidOpenRouterUsdCost';
  if(receipt.httpStatus===200&&accepted&&JSON.parse(raw).choices?.length)return {raw,status:200,receipt};
  const retryable=receipt.httpStatus===0||receipt.httpStatus===429||receipt.httpStatus>=500||/timeout|timed out|temporar|overload/i.test(receipt.fault??'');
  if(!retryable||n===2)throw Error('ProviderFault:'+receipt.fault);
  await Bun.sleep(1000*(n+1));
 }
 throw Error('FiniteApiRetriesExhausted');
}
const statusUpdate=()=>status();
async function grade(tid:string,answer:string){for(let n=0;n<3;n++){try{const r=await fetch(grader+'/grade',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({task_id:tid,code:answer}),signal:AbortSignal.timeout(180000)});const v:any=await r.json();if(v.valid||n===2)return v;}catch(e){if(n===2)return {valid:false,passed:false,errorType:'GraderTransport',diagnostic:String(e)};}await Bun.sleep(1000*(n+1));}}
async function startGrader(){
 mkdirSync(join(OUT,'grader'),{recursive:true});
 const prior=existsSync(join(OUT,'grader/process.json'))?read(join(OUT,'grader/process.json')):undefined;
 const port=prior?.base?new URL(prior.base).port:'0';
 const proc=spawn('python',['-u',join(SRC,'grader_service.py'),'--port',port,'--output',join(OUT,'grader'),'--runner-pid',String(process.pid)],{cwd:ROOT,stdio:['ignore','pipe','pipe'],windowsHide:true});
 let log='';proc.stderr.on('data',d=>{log+=d;writeFileSync(join(OUT,'grader/stderr.log'),log);});
 const ready:any=await new Promise((accept,reject)=>{let buf='';const timer=setTimeout(()=>reject(Error('GraderStartupTimeout:'+log)),30000);proc.stdout.on('data',d=>{buf+=d;writeFileSync(join(OUT,'grader/stdout.log'),buf);if(buf.includes('\n')){try{const v=JSON.parse(buf.split('\n')[0]);clearTimeout(timer);accept(v);}catch(e){reject(e);}}});proc.once('exit',code=>{clearTimeout(timer);reject(Error('GraderExit:'+code+':'+log));});});
 grader='http://127.0.0.1:'+ready.port;graderPid=proc.pid;save(join(OUT,'grader/process.json'),{pid:graderPid,runnerPid:process.pid,base:grader,atUtc:new Date().toISOString()});
 return async()=>{if(proc.exitCode===null&&proc.signalCode===null){await new Promise<void>(accept=>{proc.once('exit',()=>accept());proc.kill();});}};
}
async function native(task:any,dir:string,callRoot:string,mockCode?:string){
 const nativeSolveSeconds=exceptionLimits('objrun',task.officialId,cfg.exceptionRecovery)?.solveSeconds??OBJRUN_SOLVE_SECONDS;
 const engineDir=join(dir,'engine');mkdirSync(engineDir,{recursive:true});let engine:Machine|undefined,interfaceError:string|undefined,pending=0,counter=0;
 let deadline:number|undefined;
 const events:any[]=[];
 const proxy=createServer(async(req,res)=>{pending++;try{
  const chunks:Buffer[]=[];for await(const chunk of req)chunks.push(Buffer.from(chunk));const body=JSON.parse(Buffer.concat(chunks).toString());
  const invoke=async(request:any,protocolAttempt:number)=>{
   const digest=hash(JSON.stringify(request));let r:any;
   if(mockCode!==undefined){const handIn=request.tools?.length===1&&request.tools[0].function.name==='submit';const tool=handIn||counter++>0?'submit':'verify';r={status:200,receipt:{mock:true},raw:JSON.stringify({id:'control-'+Date.now(),object:'chat.completion',choices:[{index:0,finish_reason:'tool_calls',message:{role:'assistant',content:null,tool_calls:[{id:'control-call-'+Date.now(),type:'function',function:{name:tool,arguments:JSON.stringify({answer:mockCode})}}]}}],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0}})};}
   else r=await model(join(callRoot,digest),request,deadline,OBJRUN_PROVIDER);
   events.push({atUtc:new Date().toISOString(),protocolAttempt,requestSha256:digest,generationId:r.receipt.generationId??null,mock:mockCode!==undefined});save(join(dir,'submit-response-attempts.json'),events);return r;
  };
  let r=await invoke(body,0);const handIn=body.tools?.length===1&&body.tools[0]?.function?.name==='submit';
  if(mockCode===undefined&&handIn&&r.status===200){const v=JSON.parse(r.raw),choice=v.choices?.[0],calls=choice?.message?.tool_calls??[];if(choice?.finish_reason!=='length'&&!(calls.length===1&&calls[0]?.function?.name==='submit'))r=await invoke({...body,messages:[...(body.messages??[]),{role:'user',content:'Your preceding response did not invoke submit and was not handed in. Invoke the available submit tool exactly once with the complete Python code in its answer argument. Earlier verify or plain text does not complete this hand-in.'}]},1);}
  res.writeHead(r.status,{'content-type':'application/json'});res.end(r.raw);
 }catch(e){interfaceError=String(e);res.writeHead(502,{'content-type':'application/json'});res.end(JSON.stringify({error:{message:String(e)}}));}finally{pending--;}});
 proxy.requestTimeout=0;proxy.timeout=0;await new Promise<void>(accept=>proxy.listen(0,'127.0.0.1',()=>accept()));const port=(proxy.address() as any).port;
 const id='classeval-20261014/'+(mockCode!==undefined?'control':'objrun')+'/'+task.officialId;
 try{
  engine=await machine({...BENCHMARK_INFERENCE,retryTimes:0,continueTimes:3},{directory:engineDir,keep:true});save(join(dir,'engine-process.json'),{pid:engine.pid,base:engine.base,runnerPid:process.pid,atUtc:new Date().toISOString()});
  const nodes=[{name:'parsed',domain:'bool',moment:'done',handle:grader+'/parsed'},{name:'correct',domain:'bool',moment:'done',handle:grader+'/correct'}];
  await engine.api('POST','/declare',{handles:nodes.map(n=>({name:n.handle,expectMs:180000})),places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',cfg.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
  await engine.api('POST','/exec',{sql:"update api set base_url=:endpoint,retry_on='[]' where key_env=:key and model=:model",params:{endpoint:'http://127.0.0.1:'+port+'/v1',key:'OPENROUTER_API_KEY',model:cfg.model}});
  const exists:any=await engine.api('POST','/query',{sql:'select * from task where id=:id',params:{id}});
  if(mockCode===undefined)deadline=exists.rows.length?Number(exists.rows[0].created_at)+Number(exists.rows[0].solve_seconds)*1000:Date.now()+nativeSolveSeconds*1000;
  if(!exists.rows.length)await engine.api('POST','/tasks',{id,run:'classeval-20261014',mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt+'\nUse submit to hand in your complete Python implementation. verify returns clipped official-test status, error types and test-group statistics. No filesystem or search tools are available.',objective:{nodes,edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'},readable:false,solveSeconds:nativeSolveSeconds,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
  const begin=Date.now();let t:any,why:any;
  while(Date.now()-begin<nativeSolveSeconds*1000+660000){
   if(interfaceError)throw Error(interfaceError);
   t=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/status');why=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/why');
   if(interfaceError)throw Error(interfaceError);
   if(pending===0&&(why.problems??[]).some((p:any)=>/kernel threw while advancing/i.test(String(p))&&/timed out|fetch failed|closed/i.test(String(p)))){save(join(dir,'native-interface-evidence.json'),{status:t,why});throw Error('NativeInterfaceTimeout');}
   if(JSON.stringify(why.problems).includes('The required submit tool was not called exactly once')){save(join(dir,'native-interface-evidence.json'),{status:t,why});break;}
   if(['done','failed'].includes(t.state)&&t.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(t.result).outcome))break;
   await Bun.sleep(1000);
  }
  const trace:any=await engine.api('POST','/query',{sql:'select * from agent_bot_msg order by instance,unit,seq limit 100000'});save(join(dir,'trace.json'),trace.rows);
  const state:any=await engine.api('POST','/query',{sql:'select * from task where id=:id',params:{id}});save(join(dir,'native-task.json'),state.rows[0]);
  const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});let candidate:any;
  try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const q=db.prepare(sql);try{return q.all(...params);}finally{q.finalize();}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);}finally{db.close();}
  if(!t?.result&&!candidate&&!JSON.stringify(why?.problems).includes('The required submit tool'))throw Error('NativeDeadlineWithoutFinalization');
  const nativeVerdict=t?.result?JSON.parse(t.result):null;
  if(nativeVerdict?.valid===false||nativeVerdict?.outcome==='grader_error')throw Error('NativeGraderEnvironmentError');
  return {answer:candidate?.body??'',candidateHow:candidate?.how??'none',engineState:t.state,engineVerdict:nativeVerdict,modelProtocolFailure:!candidate,enginePid:engine.pid,solveSeconds:nativeSolveSeconds};
 }catch(e){
  // A canceled later request must not erase an earlier native submit within the solve deadline.
  const {checkpoint,...candidate}=recoverSubmittedAtDeadline(engineDir,id,e);
  save(join(dir,'trace.json'),checkpoint.trace);save(join(dir,'native-task.json'),checkpoint.state);
  save(join(dir,'native-interruption.json'),{atUtc:new Date().toISOString(),error:String(e),recoveredFromNativeCheckpoint:true,candidateHow:candidate.candidateHow});
  return {...candidate,enginePid:engine?.pid};
 }finally{
  await engine?.stop();if(engine)save(join(dir,'engine-stopped.json'),{pid:engine.pid,atUtc:new Date().toISOString()});
  // Outstanding calls settle into their durable receipts before the proxy closes.
  const waitBegin=Date.now();while(pending>0&&Date.now()-waitBegin<605000)await Bun.sleep(100);
  await new Promise<void>(accept=>proxy.close(()=>accept()));
 }
}
async function controls(){
 const path=join(OUT,'controls.json');if(existsSync(path)&&read(path).allPassed)return;
 const rows=read(join(SRC,'upstream/data/ClassEval_data.json'));
 const rr:any[]=[];
 for(const index of [0,45,92]){const row=rows[index],reference=await grade(row.task_id,row.solution_code),wrong=await grade(row.task_id,row.skeleton);rr.push({taskId:row.task_id,reference,wrong});if(!reference.valid||!reference.passed||!wrong.valid||wrong.passed)throw Error('ScoringControlFailed:'+row.task_id);}
 const row=rows[0],control=await native(catalog[0],join(OUT,'controls/native'),join(OUT,'controls/calls'),row.solution_code);
 const trace=read(join(OUT,'controls/native/trace.json')),called=(name:string)=>trace.some((r:any)=>r.kind==='call'&&JSON.parse(r.body).calls?.some((c:any)=>c.name===name));
 const finalGrade=await grade(row.task_id,control.answer),allPassed=control.candidateHow==='submitted'&&finalGrade.valid&&finalGrade.passed&&called('verify')&&called('submit');
 save(path,{atUtc:new Date().toISOString(),allPassed,scoring:rr,native:{candidateHow:control.candidateHow,engineState:control.engineState,engineVerdict:control.engineVerdict,finalGrade,verifyCalled:called('verify'),submitCalled:called('submit'),modelCalls:0}});
 if(!allPassed)throw Error('NativeSubmitOrFinalCandidateControlFailed');
}
async function taskRun(task:any,arm:string){
 const p=join(OUT,'results',arm,task.officialId+'.json');if(existsSync(p)&&read(p).grade?.valid)return;
 return taskSlots.run(()=>taskRunInside(task,arm));
}
async function taskRunInside(task:any,arm:string){
 const path=join(OUT,'results',arm,task.officialId+'.json');if(existsSync(path)&&read(path).grade?.valid)return;
 const began=Date.now(),dir=join(OUT,'tasks',arm,task.officialId);mkdirSync(dir,{recursive:true});
 active.push({arm,taskId:task.officialId,atUtc:new Date().toISOString()});status();
 const previous=existsSync(path)?read(path):undefined;
 const attempts=retainedTaskAttempts(previous);
 const maxTaskAttempts=allowedTaskAttempts(arm,task.officialId);
 if(previous)durable(join(OUT,'recovery/result-history',arm+'-'+task.officialId+'-'+Date.now()+'.json'),previous);
 let result:any={taskId:task.officialId,arm,promptSha256:task.promptSha256,taskAttempts:attempts,maxTaskAttempts},lastError:any=previous?.error;
 try{
  for(let attempt=0;attempt<maxTaskAttempts;attempt++){
   const ownDir=join(dir,'attempt-'+attempt),candidatePath=join(ownDir,'candidate.json');
   if(attempt<attempts&&!existsSync(candidatePath))continue;
   try{
    let candidate:any;
    if(existsSync(candidatePath))candidate=read(candidatePath);
    else if(arm==='baseline'){const r=await model(join(OUT,'calls',arm,task.officialId,'single'),{model:cfg.model,messages:[{role:'user',content:task.prompt}]});const v=JSON.parse(r.raw);candidate={answer:v.choices[0].message.content??'',candidateHow:'single_model_response',finishReason:v.choices[0].finish_reason};save(candidatePath,candidate);}
    else{candidate=await native(task,ownDir,join(OUT,'calls',arm,task.officialId,'task-attempt-'+attempt));save(candidatePath,candidate);}
    result={...result,...candidate,taskAttempts:attempt+1};result.grade=candidate.modelProtocolFailure?{valid:true,passed:false,errorType:'ModelSubmissionProtocolFailure'}:await grade(task.officialId,candidate.answer);
    if(result.grade.valid)break;
    lastError=Error(result.grade.errorType);if(attempt===maxTaskAttempts-1)break;
   }catch(e){lastError=e;result={...result,taskAttempts:attempt+1};save(join(ownDir,'error.json'),{atUtc:new Date().toISOString(),error:String(e)});if(/ProviderFault|Unresolved|Insufficient|SourceChanged|SavedRequestMismatch/.test(String(e))||stopped)break;}
  }
  if(!result.grade)result.grade={valid:false,passed:false,errorType:/Provider|Dispatch/.test(String(lastError))?'ProviderError':'RunnerEnvironmentError'};
  if(!result.grade.valid)result.error=String(lastError??'FiniteTaskRecoveryExhausted');
 }finally{
  const own=walk(join(OUT,'calls',arm,task.officialId)).filter(p=>p.endsWith('receipt.json')).map(read);
  result={...result,atUtc:new Date().toISOString(),seconds:(Date.now()-began)/1000,actualCostUsd:own.reduce((n,r)=>n+(r.actualCostUsd??0),0),modelCalls:own.length,unknownCostCount:own.filter(r=>r.unknownCost).length};
  save(path,result);active=active.filter(x=>x.arm!==arm||x.taskId!==task.officialId);status();console.log(JSON.stringify({event:'task_completed',taskId:task.officialId,arm,valid:result.grade?.valid,passed:result.grade?.passed,seconds:result.seconds,cost:result.actualCostUsd,error:result.error}));
 }
}
async function runBatch(jobs:any[],concurrency=CONCURRENCY){await observation();spentSinceObservation=0;estimate();let index=0;await Promise.all(Array.from({length:concurrency},async()=>{while(index<jobs.length&&!shouldStop()){const job=jobs[index++];await taskRun(job.task,job.arm);}}));estimate();}
async function main(){
 frozen();await observation();status();updateRunning();const stopGrader=await startGrader();const timer=setInterval(()=>status(),15000);
 try{
  stage='scoring_and_native_controls';status();updateRunning();await controls();
  stage='baseline_full_objrun_canary';status();updateRunning();
  await Promise.all(cfg.arms.map(async(arm:string)=>{
   await runBatch([{task:catalog[0],arm}],1);
   const path=join(OUT,'results',arm,catalog[0].officialId+'.json'),first=read(path);
   if(!canaryReady(arm,[first])){attention=true;fatal=fatal??'CanaryInvalidOrNoNativeFinalSubmission:'+arm;save(join(OUT,'canary-'+arm+'.json'),{atUtc:new Date().toISOString(),passed:false,record:first,boundedRecoveryExhausted:first.taskAttempts>=allowedTaskAttempts(arm,first.taskId)});stage='running_with_interface_exception';status();updateRunning();return;}
   save(join(OUT,'canary-'+arm+'.json'),{atUtc:new Date().toISOString(),passed:true,taskId:first.taskId,arm,valid:first.grade.valid,candidateHow:first.candidateHow,cost:first.actualCostUsd,reusedInFull:true});
   const jobs=catalog.map((task:any)=>({task,arm})).filter((j:any)=>{const p=join(OUT,'results',arm,j.task.officialId+'.json');return !existsSync(p)||!read(p).grade?.valid;});
   for(let i=0;i<jobs.length&&!shouldStop();i+=CONCURRENCY*2)await runBatch(jobs.slice(i,i+CONCURRENCY*2),CONCURRENCY);
  }));
 }finally{
  clearInterval(timer);await stopGrader();const rr=records();stage=attention||stopped?'needs_attention':rr.length===200&&rr.every(r=>r.grade?.valid)?'complete':rr.length===200?'complete_with_exceptions':'needs_attention';status();updateRunning();estimate();
 }
}
main().catch(e=>{fatal=String(e);stage='needs_attention';status();updateRunning();console.error(fatal);process.exitCode=1;}).finally(()=>{if(existsSync(lock))unlinkSync(lock);});
