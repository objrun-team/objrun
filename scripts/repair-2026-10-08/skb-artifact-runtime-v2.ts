/** Shared real engine/factory for the fixed ten paired SkillsBench tasks. */
import { randomBytes,timingSafeEqual } from 'node:crypto';
import { BENCHMARK_INFERENCE } from './benchmark-inference.ts';
import { spawn,spawnSync } from 'node:child_process';
import { existsSync,readFileSync,readdirSync,statfsSync,unlinkSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { Database } from 'bun:sqlite';
import { actualPin,demand,hash,jsonPin,same,verifyPin,type Pin } from './paid-resource-proof-v2.ts';
import { durableJpgJson } from './jpg-paid-resource-admission-v1.ts';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { captureProviderResponse } from './scientific-journal-proxy.ts';
import { createSkbArtifactFeeQueue } from './skb-artifact-journal-core-v2.ts';
import { acquireOpenRouterAdmission } from './openrouter-paid-admission.ts';
import { BENCHMARK_PROVIDER, benchmarkProviderKey, benchmarkFetch } from './benchmark-provider.ts';
import { validateSkbRecipe,type SkbRecipe } from './skb-artifact-recipe-v2.ts';
import { SKB_ARTIFACT_FAMILY,skbArtifactObjective,skbArtifactGeneration,rawFrontmatterBody,artifactCollectionAcceptance,type SkbScheduleRow } from './skb-artifact-journal-contract-v2.ts';
import { skbArtifactResourceRequirements } from './skb-artifact-storage-v2.ts';
import { launchSkbArtifactNativeService } from './skb-artifact-native-service-v2.ts';
import { tbEngine } from './tb-engine.ts';
import { skbToolGateway } from './skb-artifact-tool-gateway-v2.ts';
import { SIX_TOOLS } from './tb-nginx-contract.ts';
import { finalCandidate } from '../../app/src/objective/candidate.ts';
import { localhostPortClosed,loadNativePython } from './skb-jpg-native-python.ts';

const ROOT=resolve(import.meta.dir,'../..');
function sql(db:Database,text:string,params:any[]=[]):any[]{const s=db.query(text);try{return s.all(...params);}finally{s.finalize();}}
export function skbStoppedSnapshot(path:string,id:string){
  const db=new Database(path,{readonly:true});try{const adapter={all:(text:string,params:any[]=[])=>sql(db,text,params),run(){throw Error('readonly');},exec(){throw Error('readonly');},close(){}};
    return {candidate:finalCandidate(adapter as never,id),trace:sql(db,'select * from agent_bot_msg where instance like ? order by unit,seq',[id+'#%']),units:sql(db,'select * from agent_bot_ctx where instance like ? order by unit',[id+'#%'])};
  }finally{db.close();}
}
function mockAction(step:number,arm:string,body:any){
  if(body.tool_choice?.function?.name==='submit')return {name:'submit',args:{answer:'local-mock-artifact'}};
  const path='/tmp/objrun-skb-local-mock.txt';const a=[
    {name:'bash',args:{command:'printf local-mock-initial > '+path,timeout_ms:10000}},
    {name:'read',args:{file_path:path}},{name:'write',args:{file_path:path,content:'local-mock-updated'}},
    {name:'edit',args:{file_path:path,old_string:'updated',new_string:'edited'}},{name:'glob',args:{pattern:'objrun-skb-*',path:'/tmp'}},
    {name:'grep',args:{pattern:'mock',path}},...(arm==='F'?[{name:'verify',args:{answer:'local-mock-artifact'}}]:[]),{name:'submit',args:{answer:'local-mock-artifact'}}];
  return a[Math.min(step,a.length-1)]!;
}

export async function runSkbArtifactRuntime(recipePin:Pin,mode:'run'|'runtime-control'){
  const r=jsonPin(recipePin) as SkbRecipe,{storage}=validateSkbRecipe(r,mode==='run');
  demand(mode==='run'?r.providerKind==='real-provider':r.providerKind==='local-mock','skb_runtime_provider_mode');
  demand(Object.entries(storage.nativeEnvironment).every(([k,v])=>process.env[k]===v),'skb_D_environment_before_parent_start');
  const sourceGuard=()=>{for(const p of r.sourcePins)verifyPin(p,undefined,512*1024**2);verifyPin(r.freezePin);};
  const save=(name:string,v:any,replace=false)=>durableJpgJson(join(r.output,name),v,replace);
  const resource=(reservationBytes=0)=>{const need=skbArtifactResourceRequirements(storage,{initial:false,solverActive:true,solverWritableBytes:0,solverWritableLimitBytes:10*1024**3});
    for(const [k,path] of [['C','C:/'],['D','D:/'],['F','F:/']] as const){const a=statfsSync(path);demand(a.bavail*a.bsize>=need[k],'skb_actual_disk_'+k);}};
  sourceGuard();resource();
  const readinessScript=join(import.meta.dir,'audit-skb-artifact-readiness-v2.py'),nativeProfile=loadNativePython();
  const readinessArgv=['-B','-X','utf8',readinessScript,'--recipe',recipePin.path,'--sha256',recipePin.sha256,...(mode==='run'?['--paid']:[])];
  const ready=spawnSync(nativeProfile.executable,readinessArgv,{windowsHide:true,env:{...process.env,...storage.nativeEnvironment},timeout:180000,maxBuffer:1024**2,encoding:'utf8'});
  durableJpgJson(join(storage.directories.audit!,'pre-provider-readiness-'+randomBytes(16).toString('hex')+'.json'),{protocol:'skillsbench-pre-provider-readiness-direct-child-v2',scriptPin:actualPin(readinessScript),argv:readinessArgv,pid:ready.pid,parentPid:process.pid,directWaitReturned:true,exitCode:ready.status,signal:ready.signal,errorCode:ready.error?.name??null,stdout:ready.stdout,stderr:ready.stderr,modelCalls:0});
  demand(ready.status===0&&!ready.error,'skb_actual_pre_provider_readiness_graph');
  const provider=mode==='run'?BENCHMARK_PROVIDER:undefined,model=provider?.model??'deepseek-flash',providerKey=provider?benchmarkProviderKey(ROOT):undefined;
  const admission=mode==='run'?await acquireOpenRouterAdmission({root:ROOT,output:r.output,runId:r.runId,family:SKB_ARTIFACT_FAMILY,entry:import.meta.path,sourcePins:r.sourcePins,prices:r.prices,balance:r.balance,capUsd:r.capUsd}):undefined;
  const engines:Awaited<ReturnType<typeof tbEngine>>[]=[],registrations:Pin[]=[],records:any[]=[],ports:number[]=[],privateConfigs:string[]=[],faults:any[]=[],steps=new Map<string,number>();
  const ownedResource=(reservationBytes=0)=>{resource(reservationBytes);const n=loadNativePython(),script=join(import.meta.dir,'skb-artifact-resource-observer-v2.py'),argv=['-B','-X','utf8',script,'--storage',r.storageDescriptorPin.path,'--sha256',r.storageDescriptorPin.sha256,'--reserve',String(reservationBytes)];
    const start=Date.now(),child=spawnSync(n.executable,argv,{windowsHide:true,env:{...process.env,...storage.nativeEnvironment},timeout:45000,maxBuffer:1024**2,encoding:'utf8'});
    durableJpgJson(join(storage.directories.audit!,'resource-'+randomBytes(16).toString('hex')+'.json'),{protocol:'skillsbench-resource-direct-child-observation-v2',argv,scriptPin:actualPin(script),pid:child.pid,parentPid:process.pid,startedAtUnixMs:start,finishedAtUnixMs:Date.now(),exitCode:child.status,signal:child.signal,directWaitReturned:true,errorCode:child.error?.name??null,stdout:child.stdout,stderr:child.stderr,modelCalls:0});
    demand(child.status===0&&!child.error&&JSON.parse(child.stdout).admitted===true,'skb_owned_resource_reservation');};
  let queue:ReturnType<typeof createSkbArtifactFeeQueue>|undefined,server:ReturnType<typeof Bun.serve>|undefined,gateway:ReturnType<typeof skbToolGateway>|undefined,
    bridge:ReturnType<typeof launchSkbArtifactNativeService>|undefined,bridgeClosure:any,activePlace:string|undefined,accounting:any;
  const token=randomBytes(32).toString('hex'),proxyToken=randomBytes(32).toString('hex');
  const secrets=new Set<string>([token,proxyToken,...Object.entries(process.env).filter(([k,v])=>/(KEY|TOKEN|SECRET|PASSWORD)/i.test(k)&&typeof v==='string'&&v.length>=6).map(([,v])=>v!)]);
  const register=(pid:number,role:string)=>{const p=save('process-'+role+'.json',{protocol:'paid-owned-process-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,ownerNonce:admission?.owned.ownerNonce??null,pid,role,registeredAtUnixMs:Date.now()});registrations.push(p);admission?.registerOwnedProcess(p);};
  const native=async(script:string,args:string[],timeout:number)=>{
    const n=loadNativePython(),serial=randomBytes(8).toString('hex'),began=Date.now();let out=Buffer.alloc(0),err=Buffer.alloc(0),ended=false,exit:number|null=null,timed=false;
    const argv=['-B','-X','utf8',join(import.meta.dir,script),...args];const child=spawn(n.executable,argv,{windowsHide:true,env:{...process.env,...storage.nativeEnvironment},stdio:['ignore','pipe','pipe']});
    demand(child.pid,'skb_native_operation_pid');child.stdout.on('data',b=>{out=Buffer.concat([out,b]);if(out.length>4*1024**2)child.kill();});child.stderr.on('data',b=>{err=Buffer.concat([err,b]);if(err.length>1024**2)child.kill();});
    await new Promise<void>((ok,bad)=>{const t=setTimeout(()=>{timed=true;child.kill();},timeout);child.once('error',e=>{clearTimeout(t);bad(e);});child.once('exit',c=>{exit=c;});child.once('close',()=>{ended=true;clearTimeout(t);ok();});});
    const caller=save('native-operation-'+serial+'.json',{protocol:'skillsbench-owned-native-operation-v2',scriptPin:actualPin(join(import.meta.dir,script)),argv,childPid:child.pid,parentPid:process.pid,startedAtUnixMs:began,finishedAtUnixMs:Date.now(),directChildClosed:ended,exitCode:exit,timedOut:timed,stdout:out.toString(),stderr:err.toString(),modelCalls:0});
    demand(ended&&exit===0&&!timed,'skb_native_operation_failed');const rows=out.toString().split(/\r?\n/).filter(x=>x.startsWith('{')).map(x=>JSON.parse(x));return {caller,rows};
  };
  const previous={token:process.env.TGENGIN_GRADER_TOKEN,origins:process.env.TGENGIN_GRADER_ORIGINS,key:process.env.OBJRUN_SKB_JOURNAL_PROXY_KEY};
  const cleanup=async(stage:string,fn:()=>any)=>{try{return await fn();}catch(e){faults.push({stage,type:e instanceof Error?e.name:'OwnedFailure'});return undefined;}};
  let stand='';const request=async(path:string,body:any,timeout=2000000)=>{
    const response=await fetch(stand+path,{method:'POST',headers:{'content-type':'application/json','X-ObjRun-Grader-Token':token},body:JSON.stringify(body),signal:AbortSignal.timeout(timeout)});
    const value=await response.json();demand(response.ok,'skb_bridge_request_failed');return value as any;
  };
  try{
    save('recipe.json',r);save('manifest.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,plannedTaskRuns:20,actualRuntimeControlRuns:mode==='runtime-control'?2:0,minimumDistinctRealTasks:10,providerKind:r.providerKind,model:r.model,taskSchedule:r.taskSchedule,full87Authorized:false,historical85_1Certified:false});
    queue=createSkbArtifactFeeQueue({inference:BENCHMARK_INFERENCE,provider,runId:r.runId,providerKind:r.providerKind,capUsd:admission?.capUsd??r.capUsd,priorCostUpperBoundUsd:r.priorCampaignCostUpperBoundUsd,prices:r.prices,admission,storage,sourcePins:r.sourcePins,schedule:r.taskSchedule,
      beforeProducerAdmission:bytes=>{sourceGuard();ownedResource(bytes);},transport:async(raw,route)=>{
        if(mode==='run')return captureProviderResponse(await benchmarkFetch(raw,providerKey!));
        const body=JSON.parse(raw),row=r.taskSchedule.find(x=>x.route===route)!;const step=steps.get(route)??0;steps.set(route,step+1);const call=mockAction(step,row.arm,body);
        demand((body.tools??[]).some((t:any)=>t.function?.name===call.name),'skb_mock_tool_available');return {httpStatus:200,rawResponse:JSON.stringify({id:'skb-local-'+row.index+'-'+step,model:'local-mock',choices:[{finish_reason:'tool_calls',message:{role:'assistant',content:null,tool_calls:[{id:'skb-local-'+row.index+'-'+step,type:'function',function:{name:call.name,arguments:JSON.stringify(call.args)}}]}}],usage:{prompt_tokens:1,completion_tokens:1}})};
      }});
    const equal=(value:string)=>{const a=Buffer.from(value),b=Buffer.from('Bearer '+proxyToken);return a.length===b.length&&timingSafeEqual(a,b);};
    server=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(req){if(!equal(req.headers.get('authorization')??''))return Response.json({error:'Unauthorized proxy'},{status:401});
      const p=new URL(req.url).pathname;demand(req.method==='POST'&&p.endsWith('/v1/chat/completions'),'skb_proxy_path');const route=p.slice(1,-'/v1/chat/completions'.length);const result=await queue!.handle(route,await req.text());return new Response(result.rawResponse,{status:result.httpStatus,headers:{'content-type':'application/json'}});}});
    ports.push(server.port!);const probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')});const standPort=probe.port!;await probe.stop(true);stand='http://127.0.0.1:'+standPort;
    process.env.TGENGIN_GRADER_TOKEN=token;process.env.OBJRUN_SKB_JOURNAL_PROXY_KEY=proxyToken;
    gateway=skbToolGateway({stand,token,store:join(storage.directories.raw!,'tool-receipts'),beforeCapture:()=>ownedResource(16*1024**2),ledger:rows=>save('tool-ledger.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,receipts:rows},existsSync(join(r.output,'tool-ledger.json')))});
    ports.push(Number(new URL(gateway.origin).port),standPort);process.env.TGENGIN_GRADER_ORIGINS=stand+','+gateway.origin;
    bridge=launchSkbArtifactNativeService({script:actualPin(join(import.meta.dir,'skb-artifact-stand-v2.py')),argv:['--port',String(standPort),'--recipe',recipePin.path],descriptorPin:r.storageDescriptorPin,storageSourcePin:actualPin(join(import.meta.dir,'skb_artifact_storage_v2.py')),port:standPort,env:{...process.env}});
    bridge.child.stdout?.resume();bridge.child.stderr?.resume();register(bridge.child.pid!,'bridge');const health=await bridge.waitReady();demand(health.readyTaskIds.length===10&&health.unsupportedTaskCount===77,'skb_bridge_ten_scope');save('bridge-health.json',health);
    const schedule=mode==='runtime-control'?r.taskSchedule.slice(0,2):r.taskSchedule;
    for(const row of schedule){
      sourceGuard();resource();const dp=r.taskDescriptorPins[Math.floor(row.index/2)]!,d=jsonPin(dp),id=row.id,place='skb:'+id,dir=join(storage.directories.sqlite!,'worker-'+row.index);activePlace=place;
      const engine=await tbEngine(BENCHMARK_INFERENCE,dir);engines.push(engine);register(engine.pid,'engine-'+row.index);ports.push(Number(new URL(engine.base).port));privateConfigs.push(join(dir,'config.yaml'));
      const config=readFileSync(join(dir,'config.yaml'),'utf8'),credentials=/api: \{prefix: \/api, token: ("[^"]+"), publisherToken: ("[^"]+")/.exec(config);demand(credentials,'skb_private_engine_credentials');secrets.add(JSON.parse(credentials[1]!));secrets.add(JSON.parse(credentials[2]!));
      const auth:any[]=[];for(const path of ['/exec','/tasks','/declare'])for(const forged of [false,true]){const a=await fetch(engine.base+path,{method:'POST',headers:{'content-type':'application/json',...(forged?{authorization:'Bearer forged','X-TGEngin-Publisher':'forged'}:{})},body:'{}'});auth.push({path,forged,status:a.status});demand(a.status===401,'skb_engine_host_auth');}save('host-auth-'+row.index+'.json',auth);
      await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_SKB_JOURNAL_PROXY_KEY',:model,handle,modes,:base,'[]' from api where key_env=:sourceKey and model=:sourceModel",params:{model,sourceKey:provider?'OPENROUTER_API_KEY':'DEEPSEEK_API_KEY',sourceModel:provider?model:'deepseek-v4-flash',base:'http://127.0.0.1:'+server.port+'/'+row.route+'/v1'}});
      const dbPath=join(dir,'data/h2h.sqlite');gateway.register(place,()=>{const db=new Database(dbPath,{readonly:true});try{const t=sql(db,'select state,created_at,solve_seconds from task where id=?',[id])[0];if(!t)return 'task_not_created';if(Date.now()>=t.created_at+t.solve_seconds*1000)return 'task_deadline';return ['done','failed'].includes(t.state)?'task_terminal':undefined;}finally{db.close();}},()=>{const db=new Database(dbPath,{readonly:true});try{const t=sql(db,'select created_at,solve_seconds from task where id=?',[id])[0];return t?t.created_at+t.solve_seconds*1000:Date.now();}finally{db.close();}});
      await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:(row.taskSeconds+60)*1000},...['verified','passed'].map(name=>({name:stand+'/'+row.officialId+'/'+name,expectMs:(row.verifierSeconds+240)*1000}))],places:[{place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'skb_artifact',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OBJRUN_SKB_JOURNAL_PROXY_KEY',model]],unit:'fn:unit.tools'}]});
      await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit'"+(row.arm==='F'?",'verify'":"")+")"});
      await request('/register',{place,taskId:id,databasePath:dbPath});const cold=await request('/place',{place,op:'ping'});demand(cold.alive&&cold.environmentAudit.forbiddenHostKeysPresent===false&&cold.environmentAudit.standTokenPresent===false,'skb_solver_credentials');save('candidate-'+row.index+'.json',cold);
      const prompt=rawFrontmatterBody(readFileSync(join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',row.officialId,'task.md')));demand(hash(prompt)===row.promptBodySha256,'skb_untrimmed_prompt');
      await engine.api('POST','/tasks',{id,run:r.runId,mode:'skb_artifact',agent:'bot',place,source:'user',domain:'software',workdir:d.taskId==='jpg-ocr-stat'?'/app/workspace':'/root',description:prompt,...(row.arm==='F'?{objective:skbArtifactObjective(stand,row.officialId),readable:false}:{}),solveSeconds:row.taskSeconds,maxBranches:mode==='runtime-control'?1:row.arm==='F'?4:1,maxDeadSiblings:mode==='runtime-control'?1:row.arm==='F'?100000:1,noSearch:['all']});
      let terminal:any;const limit=Date.now()+(row.taskSeconds+row.verifierSeconds+300)*1000;
      while(Date.now()<limit){const s=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/status'),v=s.result?JSON.parse(s.result):null;if(['done','failed'].includes(s.state)&&!['finalization_pending','finalization_error'].includes(v?.outcome)){terminal=s;break;}await Bun.sleep(200);}
      demand(terminal,'skb_terminal_finalization_missing');queue.sealRoute(row.route);gateway.seal(place);const quiet=await gateway.drain(place);await queue.proxy.drain(row.route);await engine.stop();demand(await localhostPortClosed(Number(new URL(engine.base).port),600),'skb_engine_port_remaining');
      const snapshot=skbStoppedSnapshot(dbPath,id),captured=await request('/capture',{place,final:true}),removed=await request('/stop',{place});demand(removed.ownedContainersRemaining===0,'skb_solver_remains');activePlace=undefined;
      const calls=queue.taskReceipts(row.route),verdict=terminal.result?JSON.parse(terminal.result):{valid:true,outcome:'unaided_generated'},deadline=terminal.created_at+row.taskSeconds*1000;
      const generation=skbArtifactGeneration({runtimeVerdict:verdict,state:terminal.state,calls,trace:snapshot.trace,candidate:snapshot.candidate?.body,deadline,receipts:quiet.receipts,capture:captured});
      const record={protocol:'skillsbench-ten-task-generation-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,...row,taskDescriptorPin:dp,actualCreatedAt:terminal.created_at,deadlineUnixMs:deadline,state:terminal.state,runtimeVerdict:verdict,generationValid:generation.valid,generationClassification:generation,candidate:snapshot.candidate?.body??'',candidateSha256:hash(snapshot.candidate?.body??''),trace:snapshot.trace,units:snapshot.units,apiCalls:calls,toolQuiescence:quiet,artifactCapture:captured,solverClosurePin:removed.closurePin,workerPid:engine.pid,databasePins:[dbPath,dbPath+'-wal'].filter(existsSync).map(actualPin),explicitVerifyCalls:snapshot.trace.filter((x:any)=>{try{return x.kind==='tool'&&JSON.parse(x.body).name==='verify';}catch{return false;}}).length};
      records.push(record);save('generation-'+row.index+'.json',record);console.log(JSON.stringify({phase:'real-generation-closed',taskId:row.officialId,arm:row.arm,providerKind:r.providerKind,modelRequests:calls.length,generationValid:generation.valid}));
    }
  }catch(e){faults.push({stage:'generation',type:e instanceof Error?e.name:'RuntimeFailure',code:(e as any)?.code??null});}
  finally{
    queue?.stop('all_generation_closed');if(activePlace&&gateway)await cleanup('active_tools_drain',()=>gateway!.drain(activePlace!));
    for(const engine of engines)await cleanup('engine_close',()=>engine.stop());
    if(queue)await cleanup('provider_drain',()=>queue!.drain());
    if(bridge)bridgeClosure=await cleanup('bridge_close',()=>bridge!.stop());
    if(gateway)await cleanup('gateway_close',()=>gateway!.stop());if(server)await cleanup('proxy_close',()=>server!.stop(true));
    for(const path of privateConfigs)if(existsSync(path))unlinkSync(path);
    for(const [key,value] of [['TGENGIN_GRADER_TOKEN',previous.token],['TGENGIN_GRADER_ORIGINS',previous.origins],['OBJRUN_SKB_JOURNAL_PROXY_KEY',previous.key]]){if(value===undefined)delete process.env[key!];else process.env[key!]=value;}
  }
  const generationClosedAt=Date.now();save('generation-close.json',{records:records.length,generationClosedAtUnixMs:generationClosedAt,faults,bridgeClosure});
  if(queue)accounting=await cleanup('accounting_close',()=>queue!.exportClosedAccounting());
  if(queue&&!accounting)accounting=await cleanup('accounting_failure_retention',()=>queue!.retainFailure('runtime_failure'));
  demand(accounting?.cashPin,'skb_cash_closure_missing');const accountingPin=save('accounting-close.json',accounting);
  const finalPins:Pin[]=[];
  for(const record of records){
    const dp=record.taskDescriptorPin,cp=record.artifactCapture.capturePin,started=Date.now();let result:any,op:Pin|undefined,caller:Pin|undefined;
    try{const q=await native('skb_artifact_ram_executor_v2.py',['--task-descriptor',dp.path,'--task-descriptor-sha256',dp.sha256,'--storage-descriptor',r.storageDescriptorPin.path,'--storage-descriptor-sha256',r.storageDescriptorPin.sha256,'--mode','grade','--capture',cp.path,'--capture-sha256',cp.sha256],(record.verifierSeconds+240)*1000);op=q.rows[0].gradeOwnerPin;caller=q.caller;const o=jsonPin(op!);result=jsonPin(o.resultPins['private-result.json']);}
    catch(e){faults.push({stage:'final_grade_'+record.index,type:e instanceof Error?e.name:'FinalGradeFailure'});}
    const evaluation=result?.evaluation;record.finalGradeOwnerPin=op??null;record.finalGradeCallerPin=caller??null;record.finalGradeStartedAtUnixMs=started;record.finalEvaluation=evaluation??null;
    const v=evaluation?.valid?{valid:true as const,ran:true as const,reward:evaluation.officialReward,allTestsPassed:evaluation.allTestsPassed,completedTests:evaluation.passedTests+evaluation.failedTests,passedTests:evaluation.passedTests,failedTests:evaluation.failedTests,collectionComplete:true as const,collectionPin:jsonPin(dp).expectedCollectionPin,taskDescriptorPin:dp,artifactSha256:record.artifactCapture.state==='regular'?jsonPin(cp).artifactPin.sha256:null,candidateExecutablesUsed:false as const,candidateSnapshotUsed:false as const,hostBinds:false as const,graderNetwork:'none' as const}:undefined;
    record.acceptance=artifactCollectionAcceptance({generation:record.generationClassification,candidateSha256:record.candidateSha256,capturePin:cp,taskDescriptorPin:dp,officialVerdict:v,rewardKind:record.officialId==='lab-unit-harmonization'?'fractional':'binary'});
    finalPins.push(save('task-'+record.index+'.json',record));console.log(JSON.stringify({phase:'independent-final-grade-recorded',taskId:record.officialId,arm:record.arm,officialReward:evaluation?.officialReward??null,strictG:evaluation?.allTestsPassed??false,acceptanceValid:record.acceptance.valid}));
  }
  const sourcePin=save('source-close.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,pins:r.sourcePins,freezePin:r.freezePin});
  const ownedPin=save('owned-close.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,registrationPins:registrations,ports:[...new Set(ports)],bridgeClosurePin:bridge?actualPin(bridge.closurePath):null,bridgeOwnedClosePin:bridge&&existsSync(join(storage.directories.stand!,'bridge-owned-close.json'))?actualPin(join(storage.directories.stand!,'bridge-owned-close.json')):null,solverClosurePins:records.map(x=>x.solverClosurePin),sourcePins:r.sourcePins,closedAtUnixMs:Date.now()});
  const rawPin=save('raw-close.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,accountingPin,taskPins:finalPins,toolLedgerPin:existsSync(join(r.output,'tool-ledger.json'))?actualPin(join(r.output,'tool-ledger.json')):null,generationClosePin:actualPin(join(r.output,'generation-close.json')),generationClosedAtUnixMs:generationClosedAt});
  const realRecords=mode==='run'?records.filter(x=>x.apiCalls.some((c:any)=>c.providerAttempted===true&&c.httpStatus===200&&c.completionValid===true&&c.usage)):[];
  const realRequests=mode==='run'?records.reduce((n,x)=>n+x.apiCalls.filter((c:any)=>c.providerAttempted===true).length,0):0;
  const successfulRealCalls=mode==='run'?records.reduce((n,x)=>n+x.apiCalls.filter((c:any)=>c.providerAttempted===true&&c.httpStatus===200&&c.completionValid===true&&c.usage).length,0):0;
  const pairedRealTasks=r.taskDescriptorPins.map(p=>jsonPin(p).taskId).filter(tid=>new Set(realRecords.filter(x=>x.officialId===tid).map(x=>x.arm)).size===2);
  const summaryPin=save('summary.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,providerKind:r.providerKind,plannedTaskRuns:20,actualTaskRuns:records.length,
    attemptedDistinctRealTasks:new Set(realRecords.map(x=>x.officialId)).size,realInferenceTaskRuns:realRecords.length,realProviderRequests:realRequests,successfulRealInferenceCalls:successfulRealCalls,
    completedPairedRealTrials:pairedRealTasks.length,
    localMockTaskRuns:mode==='runtime-control'?records.length:0,taskPins:finalPins,faults,full87Authorized:false,historical85_1Certified:false,formalScoreCertified:false});
  const secretScript=join(import.meta.dir,'skb-artifact-secret-audit-v2.py'),secretOutput=join(storage.directories.audit!,'secret-audit.json'),nativeHost=loadNativePython();
  const secretChild=spawnSync(nativeHost.executable,['-B','-X','utf8',secretScript,'--storage',r.storageDescriptorPin.path,'--sha256',r.storageDescriptorPin.sha256,'--output',secretOutput],
    {windowsHide:true,env:{...process.env,...storage.nativeEnvironment},input:JSON.stringify([...secrets]),timeout:180000,maxBuffer:1024**2,encoding:'utf8'});
  save('secret-audit-caller.json',{protocol:'skillsbench-ten-secret-audit-caller-v2',sourcePin:actualPin(secretScript),childPid:secretChild.pid,parentPid:process.pid,exitCode:secretChild.status,directWaitReturned:true,stdout:secretChild.stdout,stderr:secretChild.stderr,actualSecretValuesProvidedOverPrivateStdin:true,actualSecretValuesSerialized:false,modelCalls:0});
  demand(secretChild.status===0&&!secretChild.error,'skb_actual_secret_audit_failed');save('secret-audit-reference.json',{secretAuditPin:actualPin(secretOutput)});
  const {auditSkbCampaign}=await import('./audit-skb-artifact-journal-v2.ts');const kind=mode==='runtime-control'?'local-mock':records.length===20&&realRecords.length===20&&pairedRealTasks.length===10
    &&records.every(x=>x.finalGradeOwnerPin&&x.finalEvaluation?.valid&&x.generationValid&&x.acceptance.valid)&&!faults.length?'score':'financial-abort';
  const audit=await auditSkbCampaign(recipePin,kind);const auditorPin=save('independent-audit.json',audit);
  const certificate=save('final-certificate.json',{protocol:'skillsbench-ten-close-certificate-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,kind,createdAtUtc:new Date().toISOString(),recipePin,auditorPin,sourcePin,ownedPin,rawPin,summaryPin,cashPin:accounting.cashPin,completedRealDistinctTasks:kind==='score'&&realRecords.length===20?10:0,attemptedDistinctRealTasks:new Set(realRecords.map(x=>x.officialId)).size,full87Authorized:false,historical85_1Certified:false});
  if(admission)await admission.release({ownedGenerationClosed:audit.financialClosed&&audit.integrityValid,pendingRequests:0,sourceClosed:sourcePin,ownedClosed:ownedPin,rawClosed:rawPin,cashClosed:accounting.cashPin,certification:certificate});
  return {certificatePin:certificate,completedRealDistinctTasks:kind==='score'&&realRecords.length===20?10:0,completedPairedRealTrials:pairedRealTasks.length,
    realInferenceTaskRuns:realRecords.length,attemptedDistinctRealTasks:new Set(realRecords.map(x=>x.officialId)).size,providerKind:r.providerKind,full87Authorized:false};
}
