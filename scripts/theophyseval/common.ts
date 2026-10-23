import {createHash} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,appendFileSync,renameSync,openSync,closeSync,fsyncSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {decodeProviderResponse} from './transport.ts';
import {controlRead} from './control_read.ts';
import {Semaphore} from './scheduling.ts';
export const HERE=import.meta.dir, ROOT=resolve(HERE,'..'), OUT=join(ROOT,'outputs',process.env.TPE_RUN??'theophyseval-pilot-20261016-v3');
export const read=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
export const cfg=read(process.env.TPE_CONFIG??join(HERE,'experiment.json'));
export const hash=(s:string|Buffer)=>createHash('sha256').update(s).digest('hex');
export function save(p:string,v:any){mkdirSync(dirname(p),{recursive:true});const t=p+'.'+process.pid+'.tmp';writeFileSync(t,JSON.stringify(v,null,2)+'\n');renameSync(t,p);}
export function durable(p:string,v:any){mkdirSync(dirname(p),{recursive:true});const fd=openSync(p,'wx');try{writeFileSync(fd,JSON.stringify(v,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
export const walk=(p:string):string[]=>existsSync(p)?readdirSync(p,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(join(p,x.name)):[join(p,x.name).replaceAll('\\','/')]):[];
export function accounting(p=join(OUT,'calls')){
 const files=walk(p),receipts=files.filter(p=>p.endsWith('/receipt.json')).map(read);
 const unsettled=files.filter(p=>p.endsWith('/dispatch.json')&&!existsSync(join(dirname(p),'receipt.json'))).map(read);
 return {modelCalls:receipts.length+unsettled.length,actualCostUsd:receipts.reduce((s,r)=>s+(r.actualCostUsd??0),0),
 unknownCostCount:receipts.filter(r=>r.unknownCost).length+unsettled.length,
 unknownCostUpperBoundUsd:receipts.filter(r=>r.unknownCost).reduce((s,r)=>s+r.upperBoundUsd,0)+unsettled.reduce((s,r)=>s+r.reserveUsd,0),
 budgetSpentUsd:receipts.reduce((s,r)=>s+(r.actualCostUsd??r.upperBoundUsd),0)+unsettled.reduce((s,r)=>s+r.reserveUsd,0)};
}
export class BudgetStop extends Error{}
let held=0;
const groupHeld=new Map<string,number>();
let remaining=Infinity,lastBalance=0,balancePending:Promise<void>|undefined;
export async function balance(force=false,deadline=Date.now()+65000){
 if(!force&&Date.now()-lastBalance<30000)return;
 if(balancePending)return balancePending;
 balancePending=(async()=>{
  const details:any={atUtc:new Date().toISOString()};
  for(const name of ['credits','key']){
   const attempts:any[]=[],log=join(OUT,'control-plane',Date.now()+'-'+name+'.json');
   const r=await controlRead('https://openrouter.ai/api/v1/'+name,{headers:{authorization:'Bearer '+process.env.OPENROUTER_API_KEY},proxy:cfg.proxy??undefined}, {deadline,onAttempt:entry=>{attempts.push(entry);save(log,{endpoint:name,attempts});}});
   details[name]=r.data;
  }
  const a=details.credits,k=details.key;
  remaining=Math.min(a.total_credits-a.total_usage,k.limit_remaining??Infinity,k.effective_budget?.remaining_usd??Infinity,...(k.budgets??[]).map((b:any)=>b.remaining_usd??Infinity));
  if(!Number.isFinite(remaining)||remaining<0)throw Error('InvalidBalance');
  save(join(OUT,'balance-latest.json'),{atUtc:details.atUtc,remainingUsd:remaining,keyLimit:k.limit,keyRemaining:k.limit_remaining,reportedRateLimit:k.rate_limit??null});lastBalance=Date.now();
 })();try{await balancePending;}finally{balancePending=undefined;}
}
export async function observe(){
 await balance(true);
 const attempts:any[]=[];
 const data:any=await controlRead('https://openrouter.ai/api/v1/models/'+cfg.model+'/endpoints',{proxy:cfg.proxy??undefined},{onAttempt:entry=>{attempts.push(entry);save(join(OUT,'control-plane/provider-endpoints.json'),{attempts});}});
 const e=data.data?.endpoints?.find((e:any)=>e.provider_name==='DigitalOcean'&&e.tag==='digitalocean');
 if(!e)throw Error('PinnedProviderUnavailable');
 const prices=[e.pricing,...(e.pricing.overrides??[])];
 const input=Math.max(...prices.map((p:any)=>Number(p.prompt??e.pricing.prompt)))*1e6;
 const output=Math.max(...prices.map((p:any)=>Number(p.completion??e.pricing.completion)))*1e6;
 if(!Number.isFinite(input)||!Number.isFinite(output)||input>0.3+1e-12||output>1.2+1e-12)throw Error('ProviderTariffChanged');
 save(join(OUT,'prices.json'),{atUtc:new Date().toISOString(),inputUsdPerMillion:input,outputUsdPerMillion:output,officialResponse:data});
}
function strict(v:any):any{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(strict);const x:any=Object.fromEntries(Object.entries(v).map(([k,a])=>[k,strict(a)]));if(x.type==='object')x.additionalProperties=false;return x;}
export function wireBody(body:any){
 const wire:any={...body,model:cfg.model,stream:false,temperature:0,max_tokens:16384,
 provider:{only:['digitalocean'],allow_fallbacks:false,max_price:{prompt:0.3,completion:1.2}},reasoning:{enabled:true,effort:'high',exclude:false}};
 for(const k of ['seed','thinking','reasoning_effort','max_completion_tokens'])delete wire[k];
 if(body.tool_choice?.type==='function'){
  wire.tools=(body.tools??[]).filter((t:any)=>t.function?.name===body.tool_choice.function.name);wire.tool_choice='auto';
 }
 if(wire.tools)wire.tools=wire.tools.map((t:any)=>({...t,function:{...t.function,parameters:strict(t.function.parameters)}}));
 return wire;
}
export const reserveUsd=(wire:any)=>Buffer.byteLength(JSON.stringify(wire))*0.3/1e6+16384*1.2/1e6;
export const exceedsCap=(spent:number,reserve:number,cap:number|null|undefined)=>cap!=null&&spent+reserve>cap;
const slots=new Semaphore(cfg.modelConcurrency??32,()=>save(join(OUT,'model-concurrency.json'),{atUtc:new Date().toISOString(),cap:slots.limit,active:slots.active,peak:slots.peak,queued:slots.queue.length}));
export const requestConcurrency=()=>({cap:slots.limit,active:slots.active,peak:slots.peak,queued:slots.queue.length});
export async function model(dir:string,body:any,groupCalls:string,deadline:number):Promise<any>{
 const release=await slots.acquire(deadline);
 try{return await modelAttemptChain(dir,body,groupCalls,deadline);}finally{release();}
}
async function modelAttemptChain(dir:string,body:any,groupCalls:string,deadline:number):Promise<any>{
 const wire=wireBody(body),raw=JSON.stringify(wire),reserve=reserveUsd(wire);
 for(let attempt=0;attempt<3;attempt++){
  const d=join(dir,'attempt-'+attempt),rp=join(d,'receipt.json');
  if(existsSync(rp))throw Error('CompletedCallMustBeRecoveredWithoutRedispatch');
  if(existsSync(join(d,'dispatch.json')))throw Error('UnresolvedDispatch');
  if(Date.now()>=deadline)throw new BudgetStop('SolveTimeBudget');
  await balance(false,deadline);
  if(exceedsCap(accounting().budgetSpentUsd,reserve,cfg.pilotBudgetUsd))throw new BudgetStop('PilotDollarBudget');
  if(exceedsCap(accounting(groupCalls).budgetSpentUsd,reserve,cfg.perQuestionDollarCap))throw new BudgetStop('GroupQuestionDollarBudget');
  if(remaining-held<reserve)throw new BudgetStop('AccountOrKeyBalance');
  held+=reserve;groupHeld.set(groupCalls,(groupHeld.get(groupCalls)??0)+reserve);
  durable(join(d,'request.json'),wire);durable(join(d,'dispatch.json'),{atUtc:new Date().toISOString(),pid:process.pid,requestSha256:hash(raw),reserveUsd:reserve});
  const start=Date.now();let response:any={},status=0,transportError:string|undefined,headerGenerationId:string|null=null;
  try{
   const r=await fetch('https://openrouter.ai/api/v1/chat/completions',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+process.env.OPENROUTER_API_KEY,'X-OpenRouter-Title':'ObjRun TheoPhysEval 20261016'},body:raw,proxy:cfg.proxy??undefined,timeout:false,signal:AbortSignal.timeout(Math.max(1,deadline-Date.now()))} as any);
   status=r.status;
   headerGenerationId=r.headers.get('x-generation-id');
   durable(join(d,'response-headers.json'),{status:r.status,generationId:r.headers.get('x-generation-id'),contentType:r.headers.get('content-type'),date:r.headers.get('date')});
   const rawPath=join(d,'response.raw.txt');writeFileSync(rawPath,'');
   const reader=r.body?.getReader();let bodyError:string|undefined;
   try{if(reader)while(true){const chunk=await reader.read();if(chunk.done)break;appendFileSync(rawPath,chunk.value);}}catch(e){bodyError=String(e);}finally{reader?.releaseLock();}
   try{response=decodeProviderResponse(readFileSync(rawPath,'utf8'));durable(join(d,'response.json'),response);}catch(e){transportError=String(e)+(bodyError?':'+bodyError:'');}
  }catch(e){transportError=String(e);}
  const reject=[400,401,402,403,404,429].includes(status)&&!response.id&&!response.usage;
  const usd=typeof response.usage?.cost==='number'&&Number.isFinite(response.usage.cost)&&response.usage.cost>=0?response.usage.cost:null;
  const fault=transportError??response.error?.message??(status!==200?'ProviderHTTP'+status:response.provider!=='DigitalOcean'?'UnexpectedProvider':![cfg.model,cfg.canonicalModel].includes(response.model)?'UnexpectedModel':!response.id?'MissingGenerationId':undefined);
  const receipt={atUtc:new Date().toISOString(),httpStatus:status,generationId:response.id??headerGenerationId,provider:response.provider??null,model:response.model??null,
   usage:response.usage??null,actualCostUsd:reject?0:usd,unknownCost:!reject&&usd===null,upperBoundUsd:reject?0:usd??reserve,
   requestSha256:hash(raw),seconds:(Date.now()-start)/1000,finishReason:response.choices?.[0]?.finish_reason??null,fault:fault??null};
  durable(rp,receipt);held-=reserve;groupHeld.set(groupCalls,(groupHeld.get(groupCalls)??reserve)-reserve);remaining-=receipt.actualCostUsd??receipt.upperBoundUsd;
  if(status===200&&!fault)return {raw:JSON.stringify(response),answer:response.choices?.[0]?.message?.content??'',receipt};
  if([401,402,403].includes(status)||/UnexpectedProvider|UnexpectedModel|MissingGenerationId/.test(fault??''))throw Error('PinnedProviderFault:'+fault);
  const retry=status===429||status>=500||status===0||(status===200&&/IncompleteProviderResponse:WhitespaceOnly/.test(fault??''));
  if(Date.now()>=deadline)throw Error('ProviderFault:'+fault);
  if(!retry||attempt===2)throw Error('ProviderFault:'+fault);
  await Bun.sleep(1000*(attempt+1));
 }
 throw Error('FiniteRetryChainExhausted');
}
