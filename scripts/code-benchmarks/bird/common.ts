import {createHash} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,renameSync,openSync,closeSync,fsyncSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {BENCHMARK_PROVIDER,benchmarkProviderKey,officialOpenRouterFault,openRouterRateLimitRejection} from '../runtime-snapshot/scripts/repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
export {BENCHMARK_PROVIDER};
export const ROOT=resolve(import.meta.dir,'../../..'), HERE=import.meta.dir;
export const read=(p:string)=>JSON.parse(readFileSync(p,'utf8').replace(/^\uFEFF/,''));
export const cfg=read(join(HERE,'experiment.json'));
export const OUT=join(ROOT,'docs/newbench-20261014/bird');
export const hash=(s:string|Buffer)=>createHash('sha256').update(s).digest('hex');
export function save(p:string,v:any){mkdirSync(dirname(p),{recursive:true});const tmp=p+'.'+process.pid+'.tmp';writeFileSync(tmp,JSON.stringify(v,null,2)+'\n');renameSync(tmp,p);}
export function durable(p:string,v:any){mkdirSync(dirname(p),{recursive:true});const fd=openSync(p,'wx');try{writeFileSync(fd,JSON.stringify(v,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
export function walk(p:string):string[]{return existsSync(p)?readdirSync(p,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(join(p,x.name)):[join(p,x.name)]):[];}
export const receipts=(p:string)=>walk(p).filter(x=>x.endsWith('receipt.json')).map(read);
export const cost=(p:string)=>receipts(p).reduce((n,r)=>n+(r.actualCostUsd??0),0);
export const budgetSpent=(p:string)=>receipts(p).reduce((n,r)=>n+(r.actualCostUsd??r.upperBoundUsd??0),0);
// Read only the authorized root .env, then pass the key in the engine environment.
delete process.env.OPENROUTER_API_KEY;
const key=benchmarkProviderKey(ROOT);
process.env.OPENROUTER_API_KEY=key;
let balanceAt=0, remaining=0, reserved=0, balancePending:Promise<any>|undefined;
export async function balance(force=false){
 if(!force&&Date.now()-balanceAt<30000)return remaining;
 if(balancePending)return balancePending;
 balancePending=(async()=>{
  const observations:any={atUtc:new Date().toISOString(),readOnly:true};
  for(const name of ['credits','key']){
   let last:any;
   for(let i=0;i<3;i++){try{const r=await fetch('https://openrouter.ai/api/v1/'+name,{headers:{authorization:'Bearer '+key},proxy:cfg.localProxy,signal:AbortSignal.timeout(30000)} as any);const v:any=await r.json();if(!r.ok)throw Error('BalanceHTTP'+r.status);last=v.data;break;}catch(e){if(i===2)throw e;await Bun.sleep(500*(i+1));}}
   observations[name]=last;
  }
  const a=observations.credits,k=observations.key;
  const account=a.total_credits-a.total_usage;
  const keyRemaining=Math.min(k.limit_remaining??(k.limit==null?Infinity:k.limit-k.usage),k.effective_budget?.remaining_usd??Infinity,...(k.budgets??[]).map((b:any)=>b.remaining_usd??Infinity));
  if(!Number.isFinite(account)||account<0||typeof keyRemaining!=='number'||Number.isNaN(keyRemaining))throw Error('InvalidBalanceObservation');
  remaining=Math.min(account,keyRemaining);balanceAt=Date.now();
  observations.key={limit:k.limit,limit_remaining:k.limit_remaining,limit_reset:k.limit_reset,usage:k.usage,effective_budget:k.effective_budget,budgets:k.budgets};
  observations.remainingUsd=remaining;observations.accountRemainingUsd=account;observations.keyRemainingUsd=Number.isFinite(keyRemaining)?keyRemaining:null;
  save(join(OUT,'balance-latest.json'),observations);save(join(OUT,'balance-history',Date.now()+'.json'),observations);
  return remaining;
 })();try{return await balancePending;}finally{balancePending=undefined;}
}
function strictSchema(v:any):any{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(strictSchema);const x:any=Object.fromEntries(Object.entries(v).map(([k,a])=>[k,strictSchema(a)]));if(x.type==='object')x.additionalProperties=false;return x;}
export function wireBody(body:any,maxTokens=cfg.maxTokens){
 const wire={...body,model:cfg.model,stream:false,temperature:cfg.temperature,max_tokens:maxTokens,provider:{...BENCHMARK_PROVIDER.routing},reasoning:{enabled:true,effort:'high',exclude:false}};
 delete wire.seed;delete wire.thinking;delete wire.reasoning_effort;delete wire.max_completion_tokens;
 const forced=body.tool_choice?.type==='function';
 if(forced){wire.tools=(body.tools??[]).filter((t:any)=>t.function?.name===body.tool_choice.function.name);wire.tool_choice='auto';}
 if(wire.tools)wire.tools=wire.tools.map((t:any)=>({...t,function:{...t.function,parameters:strictSchema(t.function.parameters)}}));
 return wire;
}
export class BudgetStop extends Error{}
export function reserveUsd(body:any,max:number){return Buffer.byteLength(JSON.stringify(wireBody(body,max)))*0.3/1e6+max*1.2/1e6;}
export function fittingTokens(messages:any[],remaining:number){const body={messages},input=reserveUsd(body,cfg.maxTokens)-cfg.maxTokens*1.2/1e6;return Math.min(cfg.maxTokens,Math.floor((remaining-input)*1e6/1.2));}
export async function model(dir:string,body:any,maxTokens=cfg.maxTokens):Promise<any>{
 const wire=wireBody(body,maxTokens),rawReq=JSON.stringify(wire),reserve=reserveUsd(body,maxTokens);
 for(let attempt=0;attempt<3;attempt++){
  const d=join(dir,'attempt-'+attempt),rp=join(d,'receipt.json');
  let receipt:any,raw='';
  if(existsSync(rp)){receipt=read(rp);if(existsSync(join(d,'response.json')))raw=readFileSync(join(d,'response.json'),'utf8');}
  else{
   if(existsSync(join(d,'dispatch.json'))){save(join(d,'unresolved-dispatch.json'),{unknownCost:true,upperBoundUsd:reserve,reason:'Interrupted without durable response; not automatically redispatched'});throw Error('UnresolvedDispatch:'+d);}
   await balance();if(remaining-reserved<reserve)throw new BudgetStop('InsufficientAccountOrKeyBalance');reserved+=reserve;
   durable(join(d,'request.json'),wire);durable(join(d,'dispatch.json'),{atUtc:new Date().toISOString(),pid:process.pid,requestSha256:hash(rawReq),reservedUpperBoundUsd:reserve});
   const begin=Date.now();let status=0,v:any={},transportError:string|undefined;
   try{const r=await fetch(BENCHMARK_PROVIDER.endpoint,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+key,'X-OpenRouter-Title':'ObjRun BIRD 20251106'},body:rawReq,proxy:cfg.localProxy,signal:AbortSignal.timeout(600000)} as any);status=r.status;raw=await r.text();writeFileSync(join(d,'response.raw.txt'),raw);try{v=JSON.parse(raw);durable(join(d,'response.json'),v);}catch{transportError='NonJSONProviderResponse';}}
   catch(e){transportError=String(e);}
   const usd=typeof v.usage?.cost==='number'&&Number.isFinite(v.usage.cost)?v.usage.cost:null;
   const explicitRejection=[400,401,402,403,404,429].includes(status)&&!v.id&&!v.usage;
   const rate=openRouterRateLimitRejection(v,status,BENCHMARK_PROVIDER.providerName);
   receipt={atUtc:new Date().toISOString(),httpStatus:status,generationId:v.id??null,provider:v.provider??null,model:v.model??null,usage:v.usage??null,actualCostUsd:explicitRejection?0:usd,unknownCost:!explicitRejection&&usd===null,upperBoundUsd:explicitRejection?0:usd??reserve,requestSha256:hash(rawReq),seconds:(Date.now()-begin)/1000,finishReason:v.choices?.[0]?.finish_reason,maxTokens,fault:transportError??v.error?.message??(status===200?officialOpenRouterFault(v):'ProviderHTTP'+status),explicitRateLimit:rate};
   durable(rp,receipt);reserved-=reserve;remaining-=receipt.actualCostUsd??receipt.upperBoundUsd;
   if(status===402)throw new BudgetStop('ProviderInsufficientCredits');
  }
  if(receipt.httpStatus===200&&(!receipt.fault||receipt.fault==='MissingOrInvalidOpenRouterUsdCost')&&raw){return {raw,status:200,receipt,message:JSON.parse(raw).choices?.[0]?.message,answer:JSON.parse(raw).choices?.[0]?.message?.content??''};}
  const transient=receipt.httpStatus===0||receipt.httpStatus===429||receipt.httpStatus>=500||/timeout|temporarily|overload|fetch|socket|closed/i.test(receipt.fault??'');
  if(!transient||attempt===2)throw Error('ProviderFault:'+receipt.fault);
  await Bun.sleep((attempt+1)*1000);
 }
 throw Error('FiniteRetriesExhausted');
}
const gold=read(join(HERE,'dev_20251106.json')),dbs=read(join(HERE,'database-manifest.json'));
const worker=readFileSync(join(HERE,'sql-worker.py'),'utf8');
export function extractSQL(s:string){const m=s.match(/```(?:sqlite|sql)?\s*\n([\s\S]*?)```/i);return (m?m[1]:s).trim();}
async function docker(path:string,data?:any,method?:string,timeout=30000){const r=await fetch(cfg.dockerEndpoint+path,{method:method??(data===undefined?'GET':'POST'),headers:{'content-type':'application/json'},...(data===undefined?{}:{body:JSON.stringify(data)}),signal:AbortSignal.timeout(timeout)});const raw=await r.text();if(!r.ok)throw Error('DockerHTTP'+r.status+':'+raw.slice(0,400));return raw?JSON.parse(raw):null;}
export async function grade(task:any,answer:string,dir:string,override?:string){
 const sql=extractSQL(answer),cache=join(dir,'grades',hash(JSON.stringify([task.question_id,sql,override??null]))+'.json');
 if(existsSync(cache)&&read(cache).valid)return read(cache);
 let last:any;
 for(let attempt=0;attempt<3;attempt++){
  let cid:string|undefined;
  try{
   const req={sql,gold:override??gold.find((r:any)=>r.question_id===task.question_id).SQL,timeout:30};
   const create={Image:'sha256:541096ae9b05d3b850341b78790e2ed31e94d5aa0ea086933c6ff0c09ffa2e63',Cmd:['python','-c',worker,JSON.stringify(req)],User:'65534:65534',Labels:{'org.objrun.owner':'newbench-20261014','org.objrun.benchmark':'bird','org.objrun.task':task.officialId},HostConfig:{NetworkMode:'none',ReadonlyRootfs:true,CapDrop:['ALL'],SecurityOpt:['no-new-privileges'],PidsLimit:64,Memory:2147483648,NanoCpus:2000000000,Binds:[dbs[task.db_id]+':/db.sqlite:ro'],Tmpfs:{'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},LogConfig:{Type:'json-file',Config:{'max-size':'1m','max-file':'1'}}}};
   cid=(await docker('/containers/create?name=objrun-bird-'+crypto.randomUUID().slice(0,12),create)).Id;
   await docker('/containers/'+cid+'/start',{});const wait=await docker('/containers/'+cid+'/wait',{},'POST',85000);
   const r=await fetch(cfg.dockerEndpoint+'/containers/'+cid+'/logs?stdout=1&stderr=1',{signal:AbortSignal.timeout(20000)});const b=Buffer.from(await r.arrayBuffer());let s='';for(let i=0;i+8<=b.length;){const n=b.readUInt32BE(i+4);s+=b.subarray(i+8,i+8+n).toString();i+=8+n;}
   last=wait.StatusCode===0?JSON.parse(s.trim().split('\n').at(-1)!):{valid:false,passed:false,errorType:'GraderContainerExit',exitCode:wait.StatusCode};
   last={...last,containerId:cid,atUtc:new Date().toISOString(),candidateSha256:hash(sql),comparison:'set(predicted_rows) == set(gold_rows)',goldVersion:'dev_20251106',attempt};
  }catch(e){last={valid:false,passed:false,errorType:'GraderEnvironment',diagnostic:String(e),atUtc:new Date().toISOString(),attempt};}
  finally{if(cid)try{await docker('/containers/'+cid+'?force=1',undefined,'DELETE');}catch(e){save(join(dir,'cleanup-errors',Date.now()+'.json'),{containerId:cid,error:String(e)});}}
  save(cache+'.attempt-'+attempt+'.json',last);if(last.valid)break;await Bun.sleep(500*(attempt+1));
 }
 save(cache,last);return last;
}
export function fullFeedback(g:any){return g.passed?'passed':g.errorType==='ResultMismatch'?'failed: result mismatch':`failed: ${g.errorType}${g.message?': '+g.message:''}`;}
export function binaryFeedback(g:any){return g.passed?'passed':'failed';}
