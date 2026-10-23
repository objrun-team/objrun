/** One original SkillsBench task, on the caller's shared session and explicit stand. */
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';import{pathToFileURL}from'node:url';import{randomBytes,timingSafeEqual,createHash}from'node:crypto';
import {Database} from 'bun:sqlite';import{pin,verifyPin,demand}from'./manifest.ts';
import {openSkillsBenchSingleTaskSession}from'./skillsbench-single-task-session.ts';
import{BENCHMARK_INFERENCE}from'../repair-2026-10-10/full-f/shared/digitalocean-inference.ts';
import{BENCHMARK_PROVIDER}from'../repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
import{SIX_TOOLS}from'../repair-2026-10-08/tb-nginx-contract.ts';
import{skbToolGateway}from'../repair-2026-10-08/skb-artifact-tool-gateway-v2.ts';
import{skbStoppedSnapshot}from'../repair-2026-10-08/skb-artifact-runtime-v2.ts';
import{classifyGeneration}from'../repair-2026-10-08/campaign-contract.ts';
import{taskSegmentBoundary}from'../repair-2026-10-10/full-f/skillsbench/segment_boundary.ts';
const read=(p:any)=>{verifyPin(p);return JSON.parse(readFileSync(p.path,'utf8'))};
const save=(path:string,x:any)=>{writeFileSync(path,JSON.stringify(x,null,2)+'\n',{flag:'wx'});return pin(path)};
/** Invoke the task's real original validator; no replacement adapter or synthetic full-F schedule. */
export async function validateOriginalSingleTask(input:any){
 const q=input.qualification;demand(q&&q.taskId===input.taskId&&q.export==='validateRuntimeReadiness','single_task_original_readiness_binding');
 const original=read(q.originalManifestPin),ready=read(q.originalReadinessPin);
 demand(original.taskSchedule.filter((r:any)=>r.taskId===input.taskId).length===1&&ready.taskReadiness[input.taskId],'single_task_original_schedule_membership');
 verifyPin(q.validatorPin);demand(input.sourcePins.some((p:any)=>p.path===q.validatorPin.path&&p.sha256===q.validatorPin.sha256),'single_task_actual_validator_source');
 const validator=await import(pathToFileURL(q.validatorPin.path).href);demand(typeof validator[q.export]==='function','single_task_original_validator_callable');validator[q.export](original,ready);
 const row=original.taskSchedule.find((r:any)=>r.taskId===input.taskId);
 demand(JSON.stringify(row.originalResources)===JSON.stringify(input.originalRow.originalResources)&&row.taskSeconds===input.originalRow.taskSeconds&&row.verifierSeconds===input.originalRow.verifierSeconds,'single_task_original_resource_clock_binding');
 return{original,ready,row};
}
/** Prepare genuine engine, private stand and six-tool gateway without creating a model task. */
export async function prepareSkillsBenchSingleTask(input:any){
 demand(input.schedule.length===1&&input.schedule[0].taskId===input.taskId,'single_task_schedule');
 demand(input.deadline>Date.now()&&input.neutralOnly===true||input.deadline>Date.now()&&input.qualification,'single_task_qualified_or_explicit_neutral');
 for(const p of input.sourcePins)verifyPin(p);
  // Apply the already used observer to the real original tbEngine spawn, retaining its original module location/argv.
  verifyPin(input.enginePin);const text=readFileSync(input.enginePin.path,'utf8'),anchor='import { spawn } from "node:child_process";';demand(text.split(anchor).length===2,'single_task_original_engine_spawn_anchor');
  const observed=text.replace(anchor,'import { observedSpawn as spawn } from '+JSON.stringify(join(import.meta.dir,'observed-spawn.ts').replaceAll('\\','/'))+';');
  const exact=new RegExp('^'+input.enginePin.path.replaceAll('\\','/').split('/').map((x:string)=>x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('[/\\\\]')+'$');
  Bun.plugin({name:'single-task-real-engine-observed',setup(build){build.onLoad({filter:exact},()=>({contents:observed,loader:'ts',resolveDir:dirname(input.enginePin.path)}))}});
 if(!input.neutralOnly)await validateOriginalSingleTask(input);
 const row=input.schedule[0],out=input.output;mkdirSync(out,{recursive:true});
 const session=await openSkillsBenchSingleTaskSession(input);let engine:any,gateway:any,proxy:any,closed=false;const proxyToken=randomBytes(32).toString('hex');
 const previous={origins:process.env.TGENGIN_GRADER_ORIGINS,key:process.env.OBJRUN_SKB_FULL_F_PROXY_KEY};
 try{
  proxy=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(request){
   const supplied=Buffer.from(request.headers.get('authorization')??''),expected=Buffer.from('Bearer '+proxyToken);
   if(supplied.length!==expected.length||!timingSafeEqual(supplied,expected))return Response.json({error:'Unauthorized'},{status:401});
   const path=new URL(request.url).pathname;demand(request.method==='POST'&&path==='/'+row.route+'/v1/chat/completions','single_task_exact_proxy_route');
   demand(!input.neutralOnly,'neutral_provider_request_forbidden');
   const response=await session.fees.handle(row.route,await request.text());return new Response(response.rawResponse,{status:response.httpStatus,headers:{'content-type':'application/json'}});
  }});
  const originalEngine=await import(pathToFileURL(input.enginePin.path).href);engine=await originalEngine.tbEngine(BENCHMARK_INFERENCE,join(out,'engine'));
  await session.registerProcess(engine.pid,'skillsbench-single-task-engine');
  gateway=skbToolGateway({stand:session.stand.origin,token:session.stand.token,store:join(out,'tool-receipts'),beforeCapture:()=>{for(const p of input.sourcePins)verifyPin(p)},ledger:(rows:any)=>{const path=join(out,'tool-ledger.json');writeFileSync(path,JSON.stringify(rows,null,2)+'\n')}});
  process.env.TGENGIN_GRADER_ORIGINS=session.stand.origin+','+gateway.origin;process.env.OBJRUN_SKB_FULL_F_PROXY_KEY=proxyToken;
  await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_SKB_FULL_F_PROXY_KEY',:model,handle,modes,:base,'[]' from api where key_env='OPENROUTER_API_KEY' and model=:model",params:{model:BENCHMARK_PROVIDER.model,base:'http://127.0.0.1:'+proxy.port+'/'+row.route+'/v1'}});
  await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:(row.taskSeconds+60)*1000},...['verified','passed'].map(name=>({name:session.stand.origin+'/'+row.taskId+'/'+name,expectMs:(row.verifierSeconds+240)*1000}))],places:[{place:input.place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'skb_full_f',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OBJRUN_SKB_FULL_F_PROXY_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','verify','submit')"});
  const dbPath=join(out,'engine/data/h2h.sqlite');let state:any;
  const current=()=>{const db=new Database(dbPath,{readonly:true});try{return db.query('select state,created_at,solve_seconds from task where id=?').get(input.mainTaskId) as any}finally{db.close()}};
  gateway.register(input.place,()=>{state=current();return !state?'task_not_created':Date.now()>=state.created_at+state.solve_seconds*1000?'task_deadline':['done','failed'].includes(state.state)?'task_terminal':undefined},()=>{state=current();return state?state.created_at+state.solve_seconds*1000:Date.now()});
  const prepared=save(join(out,'engine-prepared.json'),{protocol:'skillsbench-single-task-engine-prepared-v1',taskId:input.taskId,enginePid:engine.pid,engineDirectory:engine.directory,engineBase:engine.base,place:input.place,standPid:session.stand.pid,originalRowPin:input.originalRowPin??null,modelTaskCreated:false,actualRequests:session.fees.state().provider.journal.acceptedRequestCount,neutralOnly:!!input.neutralOnly});
  return{session,engine,gateway,proxy,dbPath,prepared,
   async executeOriginal(){
    demand(!input.neutralOnly,'neutral_cannot_create_model_task');const original=input.originalRow;
    const ping=await session.stand.call('/register',{place:input.place,taskId:input.mainTaskId,databasePath:dbPath},60000);const deployed=await session.stand.call('/place',{place:input.place,op:'ping'},original.originalResources.environment.build_timeout_sec*1000);
    const deployment=read(deployed.skillsDeploymentPin);demand(deployment.taskId===input.taskId&&deployment.verified&&deployment.sourceBeforeAfterEqual&&deployment.privateVerifierCopied===false&&deployment.privateOracleCopied===false,'single_task_original_skills_deployment');
    verifyPin(input.skillCatalogPin);const catalog=read(input.skillCatalogPin);demand(catalog.sourceTreeSha256===deployment.originalSourceTreeSha256,'single_task_original_skills_catalog_join');
    await engine.api('POST','/declare',{skills:[{identity:'original-task-skills',does:'Read original task skill instructions and bundled public helpers',params:{},role:'skill',usable:true,body:catalog.body,when:[[{dim:'task',key:'id',op:'eq',value:input.mainTaskId},{dim:'chain',key:'',op:'not_contains',value:'>'}]]}]});
    verifyPin(original.taskSourcePin);const prompt=input.promptBody;demand(createHash('sha256').update(prompt).digest('hex')===original.promptBodySha256,'single_task_original_prompt_sha');
    const objective={nodes:[{name:'verified',domain:'bool',moment:'done',handle:session.stand.origin+'/'+input.taskId+'/verified'},{name:'passed',domain:'bool',moment:'done',handle:session.stand.origin+'/'+input.taskId+'/passed'}],edges:[{src:'verified',out:0,dst:'passed'}],sink:'passed',checks:6,reuse:'never'};
    await engine.api('POST','/tasks',{id:input.mainTaskId,run:input.runId,mode:'skb_full_f',agent:'bot',place:input.place,source:'user',domain:'software',workdir:original.workdir,description:prompt,objective,readable:false,solveSeconds:original.taskSeconds,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
    let terminal:any;while(Date.now()<input.deadline){const status:any=await engine.api('GET','/tasks/'+encodeURIComponent(input.mainTaskId)+'/status');const verdict=status.result?JSON.parse(status.result):null;if(['done','failed'].includes(status.state)&&!['finalization_pending','finalization_error'].includes(verdict?.outcome)){terminal=status;break}const paid=session.fees.state();demand(!taskSegmentBoundary(paid).closeSegment||paid.provider.activeHandlers!==0||paid.cash.pendingCount!==0,'single_task_provider_segment_closed');await Bun.sleep(300)}
    demand(terminal,'single_task_terminal_finalization_missing');session.fees.sealRoute(row.route);gateway.seal(input.place);const quiet=await gateway.drain(input.place);await session.fees.proxy.drain(row.route);await engine.stop();
    const snapshot=skbStoppedSnapshot(dbPath,input.mainTaskId),calls=session.fees.taskReceipts(row.route),verdict=terminal.result?JSON.parse(terminal.result):null,generation=classifyGeneration({runtimeVerdict:verdict,state:terminal.state,calls,trace:snapshot.trace,candidate:snapshot.candidate?.body});
    const officialGrade=await session.stand.call('/'+input.taskId+'/verified',{place:input.place,said:snapshot.candidate?.body??''},original.verifierSeconds*1000);
    const officialAcceptance={valid:generation.valid&&officialGrade.verified===true,passed:officialGrade.passed===true,gradeOwnerPin:officialGrade.gradeOwnerPin,note:officialGrade.note};
    const closure=await session.stand.call('/stop',{},60000),record={...row,runId:input.runId,protocolValid:true,skillsDeploymentPin:deployed.skillsDeploymentPin,state:terminal.state,verdict,generation,officialAcceptance,trace:snapshot.trace,units:snapshot.units,candidate:snapshot.candidate?.body??'',apiCalls:calls,toolQuiescence:quiet,solverClosure:closure};
    return save(join(out,'task-'+row.index+'.json'),record);
   },
   async close(){demand(!closed,'single_task_runtime_close_once');session.fees.sealRoute(row.route);gateway.seal(input.place);const quiescence=await gateway.drain(input.place);await session.fees.proxy.drain(row.route);await engine.stop();await gateway.stop();await proxy.stop(true);const closure=await session.close();closed=true;if(previous.origins===undefined)delete process.env.TGENGIN_GRADER_ORIGINS;else process.env.TGENGIN_GRADER_ORIGINS=previous.origins;if(previous.key===undefined)delete process.env.OBJRUN_SKB_FULL_F_PROXY_KEY;else process.env.OBJRUN_SKB_FULL_F_PROXY_KEY=previous.key;return{...closure,quiescence,enginePid:engine.pid,modelTaskCreated:!input.neutralOnly};}
  };
 }catch(error){
  const evidence:any={error:String(error),closureProven:false,resourceReleasePermitted:false};
  if(engine)try{await engine.stop();evidence.engineStopReturned=true}catch(e){evidence.engineError=String(e)}
  if(gateway)try{await gateway.stop()}catch(e){evidence.gatewayError=String(e)}
  if(proxy)try{await proxy.stop(true)}catch(e){evidence.proxyError=String(e)}
  try{evidence.sessionClosure=await session.close();evidence.closureProven=true;evidence.resourceReleasePermitted=true}catch(e){evidence.sessionError=String(e)}
  save(join(out,'prepare-failure.json'),evidence);throw error;
 }
}
