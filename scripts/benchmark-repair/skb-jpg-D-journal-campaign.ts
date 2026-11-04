import { randomBytes, timingSafeEqual } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, statfsSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { Database } from 'bun:sqlite';
import { createCampaignJournal, inspectCampaignJournal } from './campaign-journal.ts';
import { ScientificJournalProxy, captureProviderResponse, type TaskReceipt } from './scientific-journal-proxy.ts';
import { createCnyCashShadow, verifyCashClosure, type CashTicket } from './cny-cash-shadow-v2.ts';
import { actualPin, demand, fileHash, hash, inside, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { durableJpgJson, acquireJpgPaidResource, verifyJpgCertificate, JPG_REGISTRY, validateDStoreInitialization, saveJpgDDiscovery } from './jpg-D-paid-resource-admission-v1.ts';
import { JPG_FAMILY, JPG_FROZEN, JPG_IMAGE, jpgSourceFiles, loadJpgGates, validateJpgRecipe, loadDStorage, assertJpgDResourceObservation, assertJpgFoundationColdOnly, TASK_ID, SECONDS, VERIFY_SECONDS, CHECKS, ARTIFACT, type JpgRecipe, type JpgDStorage } from './jpg-D-journal-contract.ts';
import { OFFICIAL_HASHES, artifactVerdict, jpgGeneration, jpgObjective, mockCall } from './skb-jpg-contract.ts';
import { loadNativePython, spawnNativePython, localhostPortClosed, NATIVE_PROFILE_PATH } from './skb-jpg-native-python.ts';
import { launchJpgDNativeService as launchNativeJpgService } from './jpg-D-native-service-v1.ts';
import { jpgDNativeEnvironment, type JpgDDescriptor } from './jpg-d-storage-profile.ts';
import { ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY, type FinancialInterruptedBoundary } from './financial-interruption-closure-v1.ts';
import { auditJpgEvidence } from './skb-jpg-audit.ts';
import { tbEngine } from './tb-engine.ts';
import { tbToolGateway } from './tb-tool-gateway.ts';
import { SIX_TOOLS } from './tb-nginx-contract.ts';
import { finalCandidate } from '../../app/src/objective/candidate.ts';
import { graderFetch } from '../../app/src/engine/registry.ts';

const ROOT=resolve(import.meta.dir,'../..'), CROOT='C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6';
const AUDITOR=join(import.meta.dir,'audit-jpg-D-journal-campaign.py'), PLAN=join(ROOT,'.local-evidence/repository/test/fixtures/repair/jpg-journal-paid-readiness-plan.json');
let nativeDEnvironment:NodeJS.ProcessEnv|undefined,activeDescriptor:JpgDDescriptor|undefined;
type Engine=Awaited<ReturnType<typeof tbEngine>>;
/** Native, bounded direct child. stdout is discarded to keep host credentials out of logs. */
export async function jpgNativeOperation(argv:string[],timeoutMs:number){
  const child=spawnNativePython([AUDITOR,...argv],{env:nativeDEnvironment,stdio:['ignore','ignore','pipe']});demand(child.pid,'jpg_native_child_pid');
  let stderrBytes=0,exit:number|null=null,closed=false,timedOut=false;const stderr:Buffer[]=[];
  child.stderr?.on('data',chunk=>{stderrBytes+=chunk.length;if(stderrBytes<=16384)stderr.push(Buffer.from(chunk));});
  await new Promise<void>((ok,bad)=>{
    const timers:ReturnType<typeof setTimeout>[]=[];let settled=false;
    const finish=(error?:Error)=>{if(settled)return;settled=true;timers.forEach(clearTimeout);error?bad(error):ok();};
    timers.push(setTimeout(()=>{timedOut=true;child.kill('SIGTERM');timers.push(setTimeout(()=>{if(!closed)child.kill('SIGKILL');timers.push(setTimeout(()=>finish(new Error('JPG native operation did not close')),2000));},1500));},timeoutMs));
    child.once('error',()=>finish(new Error('JPG native operation failed to launch')));child.once('exit',code=>{exit=code;});
    child.once('close',()=>{closed=true;finish(exit===0&&!timedOut&&stderrBytes<=16384?undefined:new Error('JPG native operation failed; typed evidence retained'));});
  });return{pid:child.pid,exit,closed,timedOut,stderrSha256:hash(Buffer.concat(stderr)),stderrBytes};
}
function resourceGuard(start:boolean,store?:string){
  demand(activeDescriptor,'jpg_D_active_descriptor');const f=statfsSync(ROOT),c=statfsSync(CROOT),d=statfsSync('D:/');
  const observation=assertJpgDResourceObservation(activeDescriptor,{F:f.bavail*f.bsize,C:c.bavail*c.bsize,D:d.bavail*d.bsize},false,true,0);
  let envelope:number|undefined;
  if(store){
    demand(resolve(store)===resolve(activeDescriptor.storePhysical),'jpg_D_store_reserve_scope');
    const unit=d.bsize;demand(Number.isSafeInteger(unit)&&unit>=4096&&unit<=65536,'jpg_D_allocation_unit_unknown');
    const measure=(path:string):number=>{let total=unit;for(const name of readdirSync(path)){const p=join(path,name),s=lstatSync(p);demand(!s.isSymbolicLink()&&realpathSync(p).toLowerCase()===resolve(p).toLowerCase(),'jpg_D_owned_envelope_reparse');if(s.isDirectory())total+=measure(p);else{demand(s.isFile()&&s.nlink===1,'jpg_D_owned_envelope_nonregular');total+=Math.max(unit,Math.ceil(s.size/unit)*unit);}}return total;};
    envelope=measure(store);demand(envelope+72*1024**2<=activeDescriptor.storeMaximumAllocatedBytes,'jpg_D_owned_store_reservation_guard');
  }
  return{...observation,startPhase:start,storeMaximumAllocatedBytes:activeDescriptor.storeMaximumAllocatedBytes,allocatedStoreEnvelopeBytes:envelope,oneProviderCaptureAndClosureReserveBytes:72*1024**2,solverWritableMeasurement:'Bridge independently measures actual frozen256MiB boundary; proxy conservatively reserves all256MiB',kernelQuotaCertified:false};
}
function sourceGuard(recipe:JpgRecipe){for(const p of recipe.sourcePins)verifyPin(p);for(const row of recipe.artifacts)verifyPin(row.pin);for(const p of Object.values(recipe.gates))verifyPin(p);verifyPin(recipe.publicDependencyArchive);}
const ownedFlushRoots=new Set<string>();
function ordinaryOwnedFlushPath(path:string,root:string){
  const owner=resolve(root),full=resolve(path);demand(ownedFlushRoots.has(owner)&&inside(owner,full),'jpg_flush_not_self_owned');
  let current=full;while(true){const s=lstatSync(current);demand(!s.isSymbolicLink()&&realpathSync(current).toLowerCase()===current.toLowerCase(),'jpg_flush_reparse');if(current===owner)break;current=dirname(current);demand(inside(owner,current),'jpg_flush_root_escape');}return full;
}
function flushExisting(path:string,owner:string){
  const full=ordinaryOwnedFlushPath(path,owner);demand(lstatSync(full).isFile(),'jpg_flush_regular_file');const before=actualPin(full);
  const fd=openSync(full,'r+');try{ordinaryOwnedFlushPath(full,owner);fsyncSync(fd);}finally{closeSync(fd);}
  const after=actualPin(full);demand(before.bytes===after.bytes&&before.sha256===after.sha256,'jpg_flush_content_changed');return after;
}
function flushTree(path:string,owner:string):Pin[]{ordinaryOwnedFlushPath(path,owner);return readdirSync(path,{withFileTypes:true}).flatMap(item=>{
  const full=ordinaryOwnedFlushPath(join(path,item.name),owner);return item.isDirectory()?flushTree(full,owner):item.isFile()&&item.name!=='config.yaml'?[flushExisting(full,owner)]:[];
});}
/** A new F-only fixture scope is the sole public test entry; it cannot register an existing/source/cache root. */
export function createJpgOwnedFlushFixture(){const root=join(ROOT,'.scratch/jpg-fsync-owned-controls',randomBytes(16).toString('hex'));mkdirSync(root,{recursive:true});ownedFlushRoots.add(resolve(root));return{root,flush:(path:string)=>flushExisting(path,root),close:()=>ownedFlushRoots.delete(resolve(root))};}
function sqlAll(db:Database,sql:string,params:unknown[]=[]):any[]{const statement=db.query(sql);try{return statement.all(...params as any[]);}finally{statement.finalize();}}
export function stoppedJpgSnapshot(databasePath:string,id:string){
  const db=new Database(databasePath,{readonly:true});try{
    const adapter={all:(sql:string,params?:unknown[])=>sqlAll(db,sql,params),run(){throw new Error('readonly');},exec(){throw new Error('readonly');},close(){}};
    return{candidate:finalCandidate(adapter as never,id),trace:sqlAll(db,'select * from agent_bot_msg where instance like ? order by unit,seq',[id+'#%']),units:sqlAll(db,'select * from agent_bot_ctx where instance like ? order by unit',[id+'#%'])};
  }finally{db.close();}
}
function allowedStore(recipe:JpgRecipe){
  const d=loadDStorage(recipe);demand(resolve(recipe.store)===resolve(d.storePhysical),'jpg_D_authorized_physical_store');
  let p=dirname(recipe.store);while(!existsSync(p))p=dirname(p);
  while(true){demand(lstatSync(p).isDirectory()&&!lstatSync(p).isSymbolicLink()&&realpathSync(p).toLowerCase()===resolve(p).toLowerCase(),'jpg_D_store_ancestor_reparse');const next=dirname(p);if(next===p)break;p=next;}
  return d;
}

/** Pure preparation: no model, Docker, service, lock or candidate is opened. */
export function prepareJpgJournal(input:{providerKind:'local-mock'|'real-provider';DStorage:JpgDStorage;capUsd:number;priorUsd:number;prices:Pin;balance?:Pin;envelopeCny?:string;coldMockCertificate?:Pin;financialBoundary?:FinancialInterruptedBoundary}){
  assertJpgFoundationColdOnly(input.providerKind);
  const d=JSON.parse(readFileSync(verifyPin(input.DStorage.descriptorPin),'utf8')) as JpgDDescriptor;
  const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-'),output=d.directories.taskmeta!,store=d.storePhysical;
  const prepared=join(ROOT,'docs/repair-2026-10-08/jpg-D-journal-preparations',runId),taskRoot=join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks');
  const catalog=readdirSync(taskRoot,{withFileTypes:true}).filter(row=>row.isDirectory()&&existsSync(join(taskRoot,row.name,'task.md'))).map(row=>({id:row.name,publicTaskSha256:fileHash(join(taskRoot,row.name,'task.md'))})).sort((a,b)=>a.id.localeCompare(b.id));
  demand(catalog.length===87&&catalog.some(row=>row.id===TASK_ID),'jpg_source_catalog_count');
  const image=join(ROOT,'.local-evidence/repository/test/fixtures/repair/software-jpg-build-copy-verified-v2/image-manifest.json'),build=join(dirname(image),'build-proof.json'),b=jsonPin(actualPin(build));
  const gates={controls:actualPin(join(ROOT,'.local-evidence/repository/test/fixtures/repair/software-jpg-controls-copy-verified-v3/report.json')),image:actualPin(image),build:actualPin(build),profile:actualPin(b.dependencyProfilePath)};loadJpgGates(ROOT,gates);
  const runtime=join(ROOT,'examples/benchmark/terminal-bench/.runtime'),artifacts:{name:string;pin:Pin}[]=[];
  for(const name of readdirSync(runtime))if(lstatSync(join(runtime,name)).isFile())artifacts.push({name:'runtime/'+name,pin:actualPin(join(runtime,name))});
  const profile=jsonPin(gates.profile);for(const row of profile.assets)artifacts.push({name:'grader-dependencies/'+row.path,pin:actualPin(resolve(dirname(gates.profile.path),row.path))});
  for(const name of Object.keys(OFFICIAL_HASHES))artifacts.push({name:'official/'+name,pin:actualPin(join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',TASK_ID,name))});
  artifacts.push({name:'official/source-metadata.json',pin:actualPin(join(ROOT,'.phase1-data/skillsbench/source.json'))});
  artifacts.push({name:'official/task-catalog.json',pin:durableJpgJson(join(prepared,'task-catalog.json'),{protocol:'jpg-source-catalog-v1',sourceTaskCount:87,supportedTaskIds:[TASK_ID],unsupportedTaskCount:86,source:actualPin(join(ROOT,'.phase1-data/skillsbench/source.json')),catalog})});
  for(const [name,p] of Object.entries(gates))artifacts.push({name:'gates/'+name+'.json',pin:p});
  const base=process.env.OBJRUN_SKB_ARCHIVE_BASE??join(CROOT,'experiment-stores/skb-jpg-2026-10-08T10-44-53-897Z/frozen-source.zip');
  for(const name of ['descriptorPin','ramPlanPin','profileReviewPin','namespaceProofPin']as const){const pin=input.DStorage[name];if(pin)artifacts.push({name:'storage/'+name+'.json',pin});}
  const r:JpgRecipe={protocol:'jpg-D-journal-recipe-v1',family:JPG_FAMILY,runId,createdAtUtc:new Date().toISOString(),mode:input.providerKind,output,store,prices:input.prices,balance:input.balance,DStorage:input.DStorage,financialBoundary:input.financialBoundary??ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY,
    deferredFault:actualPin(join(ROOT,'.local-evidence/repository/test/fixtures/repair/scientific-campaign-deferred-fault.json')),originalPidClosure:actualPin(join(ROOT,'.local-evidence/repository/test/fixtures/repair/science1220-oom-original-process-closure.json')),
    requestedNewEnvelopeCny:input.envelopeCny,headroomCny:'30',capUsd:input.capUsd,priorCampaignCostUpperBoundUsd:input.priorUsd,sourcePins:jpgSourceFiles(ROOT),artifacts,gates,publicDependencyArchive:actualPin(base),approvedNativeProfile:actualPin(NATIVE_PROFILE_PATH),readinessPlan:actualPin(PLAN),coldMockCertificate:input.coldMockCertificate,
    hostRuntime:{bun:actualPin(process.execPath),bunVersion:Bun.version,python:actualPin(loadNativePython().executable),distributionArchived:false},formalPaidReady:false,sourceTaskCount:87,supportedTaskIds:[TASK_ID],unsupportedTaskCount:86,taskSeconds:1800,verifierSeconds:600,checks:6};
  validateJpgRecipe(r);allowedStore(r);loadNativePython();durableJpgJson(join(prepared,'recipe.json'),r);
  durableJpgJson(join(prepared,'preparation.json'),{protocol:'jpg-D-journal-preparation-v1',family:JPG_FAMILY,purpose:'one-task-engineering-cold-foundation',minimumTrialDistinctTasks:10,benchmarkTrialRequirementMet:false,runId,recipePin:actualPin(join(prepared,'recipe.json')),modelCalls:0,providerForwarded:0,DockerOperations:0,locksAcquired:0,DWrites:0,formalPaidReady:false,readyTaskIds:[],entryPin:actualPin(import.meta.path)});
  return{recipePath:join(prepared,'recipe.json'),runId,formalPaidReady:false,modelCalls:0,DockerOperations:0};
}

/** U/F are independent cold containers; one proxy/journal and one owned stand. */
export async function runJpgJournal(recipePin:Pin,mode:'docker-mock'|'run'){
  assertJpgFoundationColdOnly(mode);
  const recipe=jsonPin(recipePin) as JpgRecipe;validateJpgRecipe(recipe);demand(mode==='run'?recipe.mode==='real-provider':recipe.mode==='local-mock','jpg_mode_mismatch');
  activeDescriptor=allowedStore(recipe);nativeDEnvironment=jpgDNativeEnvironment(activeDescriptor,process.env);
  demand(Object.entries(activeDescriptor.nativeEnvironment).every(([k,v])=>process.env[k]===v),'jpg_D_parent_environment_must_precede_Bun_start');
  demand(recipe.DStorage.namespaceProofPin,'jpg_D_actual_namespace_proof_required');
  loadJpgGates(ROOT,recipe.gates);loadNativePython();validateDStoreInitialization(recipe);resourceGuard(true);
  if(mode==='run'){demand(recipe.coldMockCertificate,'jpg_current_cold_mock_required');const c=verifyJpgCertificate(recipe.coldMockCertificate!,jsonPin(recipe.coldMockCertificate!).runId,'local-mock');demand(same(c.source.pins,recipe.sourcePins),'jpg_mock_executed_source_changed');}
  const admission=mode==='run'?await acquireJpgPaidResource(recipe):undefined;
  const output=recipe.output,store=recipe.store,runId=recipe.runId,privateConfigs:string[]=[],secrets:string[]=[],registrationPins:Pin[]=[],engines:Engine[]=[],ports:number[]=[],captures:any[]=[],records:any[]=[],faults:{stage:string;error:string}[]=[],steps=new Map<string,number>(),containerIds=new Set<string>();
  let journal:ReturnType<typeof createCampaignJournal>|undefined,cash:ReturnType<typeof createCnyCashShadow>|undefined,proxy:ScientificJournalProxy|undefined,server:ReturnType<typeof Bun.serve>|undefined,gateway:ReturnType<typeof tbToolGateway>|undefined,bridge:ReturnType<typeof launchNativeJpgService>|undefined,currentEngine:Engine|undefined,currentPlace:string|undefined,allGenerationClosedAt=0,cashPin:Pin|undefined;
  const closedRoutes=new Set<string>(),tickets=new Map<number,CashTicket>(),token=randomBytes(32).toString('hex'),proxyToken=randomBytes(32).toString('hex');secrets.push(token,proxyToken);
  const safeError=(e:unknown)=>e instanceof Error?e.name:'JpgOperationFailure',save=(name:string,v:unknown,replace=false)=>durableJpgJson(join(output,name),v,replace);
  const register=(pid:number,role:string)=>{const p=save('process-'+role+'.json',{protocol:'paid-owned-process-v2',family:JPG_FAMILY,runId,ownerNonce:admission?.owned.ownerNonce??null,pid,role});registrationPins.push(p);admission?.registerOwnedProcess(p);};
  const attempt=async(stage:string,job:()=>unknown|Promise<unknown>)=>{try{return await job();}catch(e){faults.push({stage,error:safeError(e)});proxy?.stop(stage);cash?.poison(stage);return undefined;}};
  const request=async(path:string,body:any)=>{const r=await graderFetch(stand+path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(930000)});const v=await r.json();demand(r.ok,'jpg_authenticated_operation_failed');return v as any;};
  let stand='';const envRestore={token:process.env.TGENGIN_GRADER_TOKEN,origins:process.env.TGENGIN_GRADER_ORIGINS,key:process.env.OBJRUN_JPG_JOURNAL_PROXY_KEY};
  try{
    demand(realpathSync(store).toLowerCase()===resolve(store).toLowerCase(),'jpg_store_physical_changed');save('recipe.json',recipe);
    demand(realpathSync(output).toLowerCase()===resolve(output).toLowerCase(),'jpg_output_physical_changed');ownedFlushRoots.add(resolve(store));ownedFlushRoots.add(resolve(output));
    await jpgNativeOperation(['--verify-store','--recipe',join(output,'recipe.json'),'--output',join(activeDescriptor!.directories.audit!,'initial-store-before-generation.json')],15000);
    if(!admission){save('jpg-paid-resource-run.json',{protocol:JPG_REGISTRY,family:JPG_FAMILY,runId,providerKind:'local-mock',released:false,certificationPin:null,productionLockAcquired:false});saveJpgDDiscovery(recipe,actualPin(join(output,'jpg-paid-resource-run.json')));}
    save('manifest.json',{protocol:'jpg-journal-manifest-v1',storageVariant:'jpg-D-journal-v1',family:JPG_FAMILY,purpose:'one-task-engineering-cold-foundation',minimumTrialDistinctTasks:10,benchmarkTrialRequirementMet:false,campaign:runId,createdAt:new Date().toISOString(),sourceTaskCount:87,supportedTaskIds:[TASK_ID],unsupportedTaskCount:86,benchmarks:['skillsbench'],selectedTaskIds:[TASK_ID],arms:['U','F'],concurrency:1,taskSeconds:SECONDS,verifierSeconds:VERIFY_SECONDS,checks:CHECKS,reuse:'never',model:'deepseek-flash',temperature:0,seed:42,reasoningEffort:'none',maxTokens:8192,providerKind:recipe.mode,statusEndpoint:'/tasks/:id/status',hostRuntime:recipe.hostRuntime,storage:{logical:store,physical:realpathSync(store),descriptorPin:recipe.DStorage.descriptorPin,stages:activeDescriptor!.stageMapping,captureProducer:'Derived stand captures only the fixed regular workbook into descriptor.captures',newPrivateSharedRamBytes:512*1024**2,solverWritableMaximumBytes:256*1024**2},operationalLimits:resourceGuard(true),feedbackScope:'F only; CHECKS=6 limits explicit model verify. Automatic physical feedback and independent final grading are separate.',mockOnly:mode==='docker-mock',formalScoreCertified:false,recipePin});
    await jpgNativeOperation(['--verify-namespace','--recipe',join(output,'recipe.json'),'--output',join(activeDescriptor!.directories.audit!,'namespace-before-generation.json')],60000);
    await jpgNativeOperation(['--freeze','--recipe',join(output,'recipe.json'),'--output',output,'--store',activeDescriptor!.directories.source!],120000);sourceGuard(recipe);
    const journalDirectory=activeDescriptor!.directories.journal!;journal=createCampaignJournal({directory:journalDirectory,campaign:runId,capUsd:recipe.capUsd,priorCampaignCostUpperBoundUsd:recipe.priorCampaignCostUpperBoundUsd,outputDirectory:output});
    cash=createCnyCashShadow({directory:activeDescriptor!.directories.cash!,runId,providerKind:recipe.mode,admission,prices:recipe.prices,journal:{directory:journalDirectory,configPin:actualPin(join(journalDirectory,'journal-config.json')),sourcePin:{path:join(import.meta.dir,'campaign-journal.ts'),sha256:JPG_FROZEN['campaign-journal.ts']}}});
    const routes=new Set(['U','F'].map(arm=>runId+'/skillsbench/'+arm+'/0/'+TASK_ID));
    proxy=new ScientificJournalProxy(journal,{routes,failureDirectory:join(activeDescriptor!.directories.raw!,'failure-receipts'),beforeAdmission:()=>{demand(!cash!.snapshot().poisoned,'jpg_cash_stopped');resourceGuard(false,store);sourceGuard(recipe);admission?.validateForwardSource();},
      beforeForward:(a,prefix,raw,route)=>{const funding=cash!.beforeForward({id:runId+'/'+a.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(a.requestFile),journal:{admitted:a,startPrefix:prefix}});tickets.set(a.requestSeq,funding.ticket);demand(funding.admitted,'jpg_cash_denied');},
      afterDurableFinish:r=>{const ticket=tickets.get(r.requestSeq);if(ticket)cash!.finish(ticket,{kind:'journal-finish',journalRef:{...r.journalRef,callId:String(r.requestSeq)}});},
      afterFailedJournalCapture:(a,_f,e:any)=>{if(!a)return;const ticket=tickets.get(a.requestSeq);if(!ticket)return;if(e.journalRef)cash!.finish(ticket,{kind:'journal-finish',journalRef:{...e.journalRef,callId:String(a.requestSeq)}});else cash!.finish(ticket,{kind:'failed-capture',requestSeq:a.requestSeq,evidence:{files:e.files,responsePin:e.files.find((p:Pin)=>p.path.endsWith('response.json.gz')),rawResponseSha256:e.rawResponseSha256,usage:e.usage,httpStatus:e.httpStatus,providerAttempted:e.providerAttempted,originalPrefix:e.journalSnapshot.durablePrefix,reason:e.error}});},
      transport:async raw=>{if(mode==='run'){demand(process.env.DEEPSEEK_API_KEY,'jpg_real_provider_credential');return captureProviderResponse(await fetch('https://api.deepseek.com/chat/completions',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+process.env.DEEPSEEK_API_KEY},body:raw,signal:AbortSignal.timeout(300000)}));}
        const body=JSON.parse(raw),text=JSON.stringify(body.messages),arm=text.includes('/skillsbench/F/')?'F':activeArm,index=steps.get(arm)??0;steps.set(arm,index+1);const call={...mockCall(index,arm,true)};if(body.tool_choice?.function?.name==='submit'){call.name='submit';call.args={answer:'mock-workbook'};}
        demand((body.tools??[]).some((t:any)=>t.function?.name===call.name),'jpg_local_mock_tool_available');return{httpStatus:200,rawResponse:JSON.stringify({id:'local-jpg-'+arm+'-'+index,model:'local-mock',choices:[{finish_reason:'tool_calls',message:{role:'assistant',content:null,tool_calls:[{id:'local-'+arm+'-'+index,type:'function',function:{name:call.name,arguments:JSON.stringify(call.args)}}]}}],usage:{prompt_tokens:1,completion_tokens:1}})};
      }});
    const equal=(supplied:string)=>{const a=Buffer.from(supplied),b=Buffer.from('Bearer '+proxyToken);return a.length===b.length&&timingSafeEqual(a,b);};
    server=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(r){if(!equal(r.headers.get('authorization')??''))return Response.json({error:'Unauthorized private JPG proxy'},{status:401});const path=new URL(r.url).pathname;if(r.method!=='POST'||!path.endsWith('/v1/chat/completions'))return Response.json({error:'Unsupported proxy route'},{status:404});const route=path.slice(1,-'/v1/chat/completions'.length);if(closedRoutes.has(route))return Response.json({error:'Task delivery closed model route'},{status:409});const value=await proxy!.handle(route,await r.text());return new Response(value.rawResponse,{status:value.httpStatus,headers:{'content-type':'application/json'}});}});demand(server.port!==undefined,'jpg_proxy_port');ports.push(server.port);
    demand(server.port!==undefined,'jpg_proxy_port');const probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')});demand(probe.port!==undefined,'jpg_bridge_port');stand='http://127.0.0.1:'+probe.port;const standPort=probe.port;await probe.stop(true);
    process.env.TGENGIN_GRADER_TOKEN=token;process.env.OBJRUN_JPG_JOURNAL_PROXY_KEY=proxyToken;
    gateway=tbToolGateway({stand,token,store:join(activeDescriptor!.directories.raw!,'tool-receipts'),ledger:receipts=>save('tool-ledger.json',{family:JPG_FAMILY,runId,receipts},existsSync(join(output,'tool-ledger.json')))});ports.push(new URL(gateway.origin).port?Number(new URL(gateway.origin).port):0);
    process.env.TGENGIN_GRADER_ORIGINS=stand+','+gateway.origin;
    bridge=launchNativeJpgService({script:actualPin(join(import.meta.dir,'jpg-D-stand-v1.py')),argv:['--mode','live','--port',String(standPort),'--recipe',join(output,'recipe.json')],descriptorPin:recipe.DStorage.descriptorPin,storageSourcePin:recipe.DStorage.storageSourcePin,port:standPort,env:{...process.env}});
    bridge.child.stdout?.resume();bridge.child.stderr?.resume();
    register(bridge.child.pid!,'bridge');const health=await bridge.waitReady();demand(health.authenticated===true&&health.denominator===87&&health.backend==='live'&&health.unsupportedTaskCount===86,'jpg_bridge_identity');save('bridge-health.json',health);ports.push(standPort);
    for(const arm of ['U','F']){
      activeArm=arm;sourceGuard(recipe);verifyPin(recipe.hostRuntime.bun);resourceGuard(false,store);const id=runId+'/skillsbench/'+arm+'/0/'+TASK_ID,place='skb:'+id,route=id,directory=join(activeDescriptor!.directories.sqlite!,'worker-'+arm);currentPlace=place;
      const engine=await tbEngine({maxTokens:8192,retryTimes:0,continueTimes:0,reasoningEffort:'none',temperature:0,seed:42},directory);engines.push(engine);currentEngine=engine;register(engine.pid,'engine-'+arm);ports.push(Number(new URL(engine.base).port));
      const configPath=join(directory,'config.yaml'),config=readFileSync(configPath,'utf8'),credentials=/api: \{prefix: \/api, token: ("[^"]+"), publisherToken: ("[^"]+")/.exec(config);demand(credentials,'jpg_engine_credentials');privateConfigs.push(configPath);secrets.push(JSON.parse(credentials[1]),JSON.parse(credentials[2]));
      const auth:any[]=[];for(const path of ['/exec','/tasks','/declare'])for(const forged of [false,true]){const response=await fetch(engine.base+path,{method:'POST',headers:{'content-type':'application/json',...(forged?{authorization:'Bearer forged','X-TGEngin-Publisher':'forged'}:{})},body:'{}'});auth.push({path,forged,status:response.status});demand(response.status===401,'jpg_host_api_protected');}save('host-auth-'+arm+'.json',auth);
      await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_JPG_JOURNAL_PROXY_KEY','deepseek-flash',handle,modes,:base,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{base:'http://127.0.0.1:'+server.port+'/'+route+'/v1'}});
      const databasePath=join(directory,'data/h2h.sqlite');gateway.register(place,()=>{const db=new Database(databasePath,{readonly:true});try{const row=sqlAll(db,'select state,created_at,solve_seconds from task where id=?',[id])[0];if(!row)return undefined;if(Date.now()>=row.created_at+row.solve_seconds*1000)return 'task_deadline';if(['done','failed'].includes(row.state))return 'task_terminal';return sqlAll(db,"select 1 from agent_bot_msg where instance like ? and kind='tool' and json_valid(body) and json_extract(body,'$.name')='submit' limit 1",[id+'#%']).length?'task_delivered':undefined;}finally{db.close();}});
      await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:930000},...['verified','passed'].map(name=>({name:stand+'/'+name,expectMs:650000}))],places:[{place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'jpg_journal',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OBJRUN_JPG_JOURNAL_PROXY_KEY','deepseek-flash']],unit:'fn:unit.tools'}]});await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit'"+(arm==='F'?",'verify'":"")+")"});
      await request('/register',{place,taskId:id,databasePath});const cold=await request('/place',{place,op:'ping'});demand(cold.alive&&cold.environmentAudit?.forbiddenHostKeysPresent===false&&cold.environmentAudit?.standTokenPresent===false,'jpg_candidate_environment');save('cold-candidate-'+arm+'.json',cold);for(const cid of [cold.containerId,cold.ownedContainerID])if(typeof cid==='string'&&/^[a-f0-9]{64}$/.test(cid))containerIds.add(cid);
      const endpointProbes:any[]=[];const forwardBefore=(await fetch(stand+'/health').then(r=>r.json()) as any).rpcForwardCount;
      for(const origin of [stand,gateway.origin])for(const forged of [false,true]){const response=await fetch(origin+'/place',{method:'POST',headers:{'content-type':'application/json',...(forged?{'X-ObjRun-Grader-Token':'forged'}:{})},body:JSON.stringify({place,tool:'bash',args:{command:'true'}})});endpointProbes.push({origin,forged,status:response.status});demand(response.status===401,'jpg_sole_tools_auth');}
      const forwardAfter=(await fetch(stand+'/health').then(r=>r.json()) as any).rpcForwardCount;demand(forwardBefore===forwardAfter,'jpg_unauthorized_tool_forwarded');save('tool-auth-'+arm+'.json',{probes:endpointProbes,forwardBefore,forwardAfter});
      const publicEndpoints=[stand+'/place',gateway.origin+'/place',engine.base+'/exec'].map(url=>url.replace('127.0.0.1','host.docker.internal'));
      const benignProbe="python3 - <<'PY'\nimport urllib.request,urllib.error,json\nrows=[]\nfor url in "+JSON.stringify(publicEndpoints)+":\n for forged in [False,True]:\n  headers={'Content-Type':'application/json'}\n  if forged:headers.update({'X-ObjRun-Grader-Token':'forged','Authorization':'Bearer forged','X-TGEngin-Publisher':'forged'})\n  request=urllib.request.Request(url,data=b'{}',headers=headers,method='POST')\n  try:code=urllib.request.urlopen(request,timeout=3).status\n  except urllib.error.HTTPError as e:code=e.code\n  rows.append({'url':url,'forged':forged,'status':code})\nprint(json.dumps(rows))\nPY";
      const candidateAuth=await request('/place',{place,tool:'bash',args:{command:benignProbe,timeout_ms:20000}});save('candidate-host-auth-'+arm+'.json',candidateAuth);
      const candidateAuthRows=JSON.parse(typeof candidateAuth==='string'?candidateAuth:String(candidateAuth.stdout));
      demand(candidateAuthRows.length===6&&candidateAuthRows.every((r:any)=>r.status===401),'jpg_candidate_host_endpoints_not_protected');
      const prompt=readFileSync(join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',TASK_ID,'task.md'),'utf8');
      await engine.api('POST','/tasks',{id,run:runId,mode:'jpg_journal',agent:'bot',place,source:'user',domain:'software',workdir:'/app/workspace',description:prompt,...(arm==='F'?{objective:jpgObjective(stand),readable:false}:{}),solveSeconds:SECONDS,maxBranches:1,maxDeadSiblings:1,noSearch:['jpg-ocr-stat solution']});
      let terminal:any,stableAt=0;const hard=Date.now()+(SECONDS+1400)*1000;
      while(Date.now()<hard){const v=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/status'),verdict=v.result?JSON.parse(v.result):null;
        const eligible=['done','failed'].includes(v.state)&&!['finalization_pending','finalization_error'].includes(verdict?.outcome);
        if(eligible){terminal=v;stableAt ||=Date.now();gateway.seal(place);closedRoutes.add(route);if(proxy.pending(route)===0&&Date.now()-stableAt>=200)break;}
        else{terminal=undefined;stableAt=0;}await Bun.sleep(100);
      }
      demand(terminal,'jpg_finalization_not_closed');closedRoutes.add(route);gateway.seal(place);await proxy.drain(route);const quiescence=await gateway.drain(place);save('quiescence-'+arm+'.json',quiescence);
      await engine.stop();demand(await localhostPortClosed(Number(new URL(engine.base).port),600),'jpg_engine_port_not_closed');currentEngine=undefined;
      const snapshot=stoppedJpgSnapshot(databasePath,id),capture=await request('/capture',{place,final:true});captures.push(capture);save('capture-'+arm+'.json',capture);containerIds.add(capture.ownedContainerID);
      const removed=await request('/stop',{place});demand(removed.ok===true&&removed.ownedContainersRemaining===0,'jpg_candidate_not_removed');save('candidate-removed-'+arm+'.json',removed);currentPlace=undefined;
      const calls=proxy.takeTaskReceipts(route),runtimeVerdict=terminal.result?JSON.parse(terminal.result):{valid:true,outcome:'unaided_generated'},deadlineUnixMs=Number(terminal.created_at)+SECONDS*1000;
      const generation=jpgGeneration({runtimeVerdict,state:terminal.state,calls,trace:snapshot.trace,candidate:snapshot.candidate?.body,deadline:deadlineUnixMs,receipts:quiescence.receipts,capture});
      if(snapshot.units.some((row:any)=>row.done!==1)){generation.valid=false;generation.kind='infrastructure_error';generation.outcome='unfinished_execution_unit';}
      const explicitVerify=snapshot.trace.filter((r:any)=>{try{return r.kind==='tool'&&JSON.parse(r.body).name==='verify';}catch{return false;}}).length;
      const databasePins=[databasePath,databasePath+'-wal'].filter(existsSync).map(actualPin);
      const record={protocol:'jpg-journal-task-v1',family:JPG_FAMILY,runId,index:records.length,benchmark:'skillsbench',arm,replica:0,officialId:TASK_ID,taskId:id,promptSha256:hash(prompt),state:terminal.state,runtimeVerdict,generationValid:generation.valid,generationClassification:generation,actualCreatedAt:terminal.created_at,deadlineUnixMs,candidate:snapshot.candidate?.body??'',candidateHow:snapshot.candidate?.how??'none',candidateSha256:hash(snapshot.candidate?.body??''),artifactCapture:capture,toolQuiescence:quiescence,trace:snapshot.trace,units:snapshot.units,databasePins,apiCalls:calls,workerPid:engine.pid,engineStoppedBeforeAcceptance:true,explicitVerifyCalls:explicitVerify,acceptance:{valid:false,outcome:'pending_after_all_generation'}};
      records.push(record);save('generation-'+arm+'.json',record);sourceGuard(recipe);
    }
    allGenerationClosedAt=Date.now();proxy.stop('all_generation_closed');await proxy.drain();await server.stop(true);await gateway.stop();const bridgeClosure=await bridge.stop();save('bridge-process-closure.json',bridgeClosure);demand(bridgeClosure.closed&&bridgeClosure.identityVerified,'jpg_native_bridge_unclosed');
    demand(records.length===2&&records.every(r=>r.generationValid)&&!proxy.anomalies.length,'jpg_invalid_generation');sourceGuard(recipe);
    const exported=journal.exportLegacyLedger();save('journal-export.json',exported);cashPin=cash.close();verifyCashClosure(cashPin);journal.close();
    const finals:any[]=[];
    for(const record of records){const capturePin=actualPin(record.artifactCapture.captureReceiptPath),gradeStart=Date.now();let report:any,reportPin:Pin|undefined;
      if(record.generationClassification.kind==='candidate'){
        const folder=join(activeDescriptor!.directories['private-logs']!,'grade-'+randomBytes(16).toString('hex'));const inputPinPath=join(output,'capture-pin-'+record.arm+'.json');durableJpgJson(inputPinPath,capturePin);
        await jpgNativeOperation(['--grade','--recipe',join(output,'recipe.json'),'--capture-pin',inputPinPath,'--output',folder],665000);reportPin=actualPin(join(folder,'report.json'));report=jsonPin(reportPin);
      }
      record.acceptance=artifactVerdict(report,record.artifactCapture,record.candidateSha256,record.generationClassification);demand(record.acceptance.valid===true,'jpg_invalid_final_acceptance');
      finals.push({arm:record.arm,captureReceiptPin:capturePin,reportPin,gradingStartedAtUnixMs:gradeStart});save('task-'+record.index+'.json',record);sourceGuard(recipe);
    }
    // Collect exact daemon IDs from the frozen owned operation receipts only.
    const graderRecords:{ownerPin:Pin;reportPin:Pin;cliPin:Pin}[]=[];let bridgeOwnerPin:Pin|undefined;
    for(const path of flushTree(activeDescriptor!.directories.stand!,store).concat(flushTree(activeDescriptor!.directories['private-logs']!,store))){
      if(basename(path.path)==='operation-owner.json'){
        const raw=jsonPin(path);demand(raw.containers.every((r:any)=>r.state==='removed'),'jpg_owned_operation_not_removed');for(const row of raw.containers)if(typeof row.containerId==='string'&&/^[a-f0-9]{64}$/.test(row.containerId))containerIds.add(row.containerId);
        if(resolve(path.path)===join(activeDescriptor!.directories.stand!,'operation-owner.json')){demand(raw.lease?.released===true,'jpg_bridge_lease_unclosed');bridgeOwnerPin=path;}
        else{const folder=dirname(path.path);graderRecords.push({ownerPin:path,reportPin:actualPin(join(folder,'report.json')),cliPin:actualPin(join(dirname(folder),'cli-'+basename(folder)+'.json'))});}
      }
    }
    demand(bridgeOwnerPin,'jpg_bridge_owned_receipt_missing');
    const ownedScope={protocol:'jpg-journal-owned-scope-v1',family:JPG_FAMILY,runId,store,recipePin:actualPin(join(output,'recipe.json')),enginePids:engines.map(e=>e.pid),bridgePid:bridge.child.pid,ports,containerIds:[...containerIds].sort(),registrationPins,bridgeOwnerPin,graderRecords,candidateRecords:records.map(r=>({arm:r.arm,coldPin:actualPin(join(output,'cold-candidate-'+r.arm+'.json')),capturePin:actualPin(r.artifactCapture.captureReceiptPath),removalPin:actualPin(join(output,'candidate-removed-'+r.arm+'.json'))}))};save('owned-scope.json',ownedScope);
    await jpgNativeOperation(['--owned','--owned-scope',join(output,'owned-scope.json'),'--output',join(output,'owned-close.json')],90000);
    const finalPaths=new Set(finals.filter(r=>r.reportPin).map(r=>resolve(r.reportPin.path)));const physicalFeedback=graderRecords.map(r=>r.reportPin).filter(p=>!finalPaths.has(resolve(p.path)));
    save('grading-close.json',{protocol:'jpg-journal-grading-close-v1',family:JPG_FAMILY,runId,generationClosedBeforeAllFinalGrading:true,allGenerationClosedAtUnixMs:allGenerationClosedAt,finalGrades:finals,physicalFeedbackGradePins:physicalFeedback,explicitVerifyCalls:records.map(r=>({arm:r.arm,count:r.explicitVerifyCalls})),runtimeAutomaticGradeCount:'Physical feedback is aggregated; engine traces retain explicit verify count. The frozen bridge does not label every physical grade origin.',independentFinalGrades:finals.filter(r=>r.reportPin).length,queryBudgetCausalEquivalenceClaimed:false});
    flushTree(store,store);await auditJpgEvidence({script:join(import.meta.dir,'skb-jpg-host-ops.py'),output,store,privateConfigs,secrets});flushExisting(join(output,'evidence-secret-audit.json'),output);demand(secrets.length===6,'jpg_six_credential_values');
    const sourcePin=save('source-close.json',{protocol:'jpg-journal-source-close-v1',family:JPG_FAMILY,runId,pins:recipe.sourcePins,artifactPins:recipe.artifacts,hostRuntime:recipe.hostRuntime,freezePin:actualPin(join(output,'frozen-source.json'))});sourceGuard(recipe);
    const inspection=inspectCampaignJournal(journalDirectory);demand(inspection.valid&&inspection.accountingClosed&&inspection.eligibleForScoreCertification,'jpg_journal_not_certifiable');
    const rawPin=save('raw-close.json',{protocol:'jpg-journal-raw-close-v1',family:JPG_FAMILY,runId,journalPrefix:inspection.prefix,journalFilePin:actualPin(join(journalDirectory,'api-events.jsonl')),journalConfigPin:actualPin(join(journalDirectory,'journal-config.json')),journalExportPin:actualPin(join(output,'journal-export.json')),apiLedgerPin:actualPin(join(output,'api-ledger.json')),databasePins:records.flatMap(r=>r.databasePins),toolLedgerPin:actualPin(join(output,'tool-ledger.json')),failureReceipts:proxy.anomalies});
    const summaryPin=save('summary.json',{protocol:'jpg-journal-operational-summary-v1',family:JPG_FAMILY,runId,providerKind:recipe.mode,operationalComplete:true,completed:false,formalScoreCertified:false,mockWorkflowCompleted:false,plannedTaskRuns:2,taskPins:records.map(r=>actualPin(join(output,'task-'+r.index+'.json'))),cashPin,recordedUsageUpperBoundUsd:inspection.snapshot!.recordedUsageUpperBoundUsd,realProviderRequests:mode==='run'?inspection.snapshot!.acceptedRequestCount:0,localMockRequests:mode==='docker-mock'?inspection.snapshot!.acceptedRequestCount:0,sourceTaskCount:87,supportedTaskCount:1,unsupportedTaskCount:86,readyTaskIds:[]});
    await jpgNativeOperation(['--audit','--output',output,'--bun',process.execPath],180000);sourceGuard(recipe);
    const certificate=save('final-certificate.json',{protocol:'jpg-journal-final-certificate-v1',storageVariant:'jpg-D-journal-v1',purpose:'one-task-engineering-cold-foundation',minimumTrialDistinctTasks:10,benchmarkTrialRequirementMet:false,family:JPG_FAMILY,runId,providerKind:recipe.mode,createdAtUtc:new Date().toISOString(),completed:mode==='run',mockWorkflowCompleted:mode==='docker-mock',formalScoreCertified:mode==='run',auditor:actualPin(join(output,'jpg-independent-audit.json')),cash:cashPin,source:sourcePin,owned:actualPin(join(output,'owned-close.json')),summary:summaryPin,journal:actualPin(join(journalDirectory,'journal-config.json')),grading:actualPin(join(output,'grading-close.json')),secrets:actualPin(join(output,'evidence-secret-audit.json')),raw:rawPin});
    verifyJpgCertificate(certificate,runId,recipe.mode);
    if(admission)await admission.release({sourceClosed:sourcePin,ownedClosed:actualPin(join(output,'owned-close.json')),rawClosed:rawPin,cashClosed:cashPin,certification:certificate});
    else{save('jpg-paid-resource-run.json',{protocol:JPG_REGISTRY,family:JPG_FAMILY,runId,providerKind:'local-mock',productionLockAcquired:false,released:true,certificationPin:certificate},true);saveJpgDDiscovery(recipe,actualPin(join(output,'jpg-paid-resource-run.json')));}
    return{runId,output,certificate,completed:mode==='run',mockWorkflowCompleted:mode==='docker-mock',formalScoreCertified:mode==='run'};
  }catch(e){faults.push({stage:'workflow',error:safeError(e)});throw e;}
  finally{
    proxy?.stop('shutdown');if(currentPlace&&gateway){gateway.seal(currentPlace,'shutdown');closedRoutes.add(currentPlace.slice(4));}
    await attempt('provider_drained',()=>proxy?.drain());
    await attempt('active_engine_stopped',()=>currentEngine?.stop());
    if(currentPlace&&gateway){await attempt('tools_drained',()=>gateway!.drain(currentPlace!));await attempt('owned_candidate_removed',()=>request('/stop',{place:currentPlace}));}
    await attempt('gateway_stopped',()=>gateway?.stop());await attempt('proxy_listener_stopped',()=>server?.stop(true));await attempt('native_bridge_stopped',()=>bridge?.stop());
    if(faults.length&&cash&&!cashPin)await attempt('cash_failure_prefix_retained',()=>cash!.close());
    journal?.close();
    try{if(faults.length)save('failure-closure.json',{protocol:'jpg-journal-failed-close-v1',family:JPG_FAMILY,runId,faults,providerState:proxy?.state(),cashSnapshot:cash?.snapshot(),originalUnknownSettled:false,completed:false,lockPreserved:!!admission,confirmedNoProviderForward:(journal?.snapshot().acceptedRequestCount??0)===0});}catch{}
    if(envRestore.token===undefined)delete process.env.TGENGIN_GRADER_TOKEN;else process.env.TGENGIN_GRADER_TOKEN=envRestore.token;
    if(envRestore.origins===undefined)delete process.env.TGENGIN_GRADER_ORIGINS;else process.env.TGENGIN_GRADER_ORIGINS=envRestore.origins;
    if(envRestore.key===undefined)delete process.env.OBJRUN_JPG_JOURNAL_PROXY_KEY;else process.env.OBJRUN_JPG_JOURNAL_PROXY_KEY=envRestore.key;
    ownedFlushRoots.delete(resolve(store));ownedFlushRoots.delete(resolve(output));
    nativeDEnvironment=undefined;activeDescriptor=undefined;
  }
}
let activeArm='U';
if(import.meta.main){
  const [mode='prepare',...args]=process.argv.slice(2),option=(name:string)=>{const n=args.indexOf(name);return n<0?undefined:args[n+1];};
  if(mode==='prepare'){
    const price=option('--prices');demand(price,'jpg_price_pin_file_required');const kind=option('--provider')??'local-mock';demand(['local-mock','real-provider'].includes(kind),'jpg_provider_kind');
    const storage=option('--storage');demand(storage,'jpg_D_explicit_storage_pin_bundle_required');
    const v=prepareJpgJournal({providerKind:kind as any,DStorage:jsonPin(actualPin(resolve(storage))),capUsd:Number(option('--cap-usd')),priorUsd:Number(option('--prior-usd')),prices:actualPin(resolve(price)),balance:option('--balance')?actualPin(resolve(option('--balance')!)):undefined,envelopeCny:option('--envelope-cny'),coldMockCertificate:option('--cold-mock-certificate')?actualPin(resolve(option('--cold-mock-certificate')!)):undefined});console.log(JSON.stringify(v));
  }else{demand(mode==='docker-mock'||mode==='run','jpg_explicit_mode');const path=option('--recipe');demand(path,'jpg_recipe_path_required');console.log(JSON.stringify(await runJpgJournal(actualPin(resolve(path)),mode)));}
}
