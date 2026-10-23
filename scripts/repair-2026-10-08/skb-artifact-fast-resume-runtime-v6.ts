/** Fast first delivery: real shared engine, two isolated slots, unchanged task budgets. */
import {randomBytes,timingSafeEqual} from 'node:crypto';
import { BENCHMARK_INFERENCE } from './benchmark-inference.ts';
import { BENCHMARK_PROVIDER, benchmarkProviderKey, benchmarkFetch } from './benchmark-provider.ts';
import { acquireOpenRouterAdmission } from './openrouter-paid-admission.ts';
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,readFileSync,statfsSync,unlinkSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {Database} from 'bun:sqlite';
import {actualPin,demand,hash,jsonPin,verifyPin,type Pin} from './paid-resource-proof-v2.ts';
import {durableJpgJson} from './jpg-paid-resource-admission-v1.ts';
import {captureProviderResponse} from './scientific-journal-proxy.ts';
import {createSkbArtifactFeeQueue} from './skb-artifact-journal-core-v6.ts';
import {SKB_ARTIFACT_FAMILY,skbArtifactObjective,skbArtifactGeneration,rawFrontmatterBody,artifactCollectionAcceptance,SKB_ARTIFACT_MODEL,loadSkbArtifactSelection,assertSkbArtifactSchedule} from './skb-artifact-journal-contract-v2.ts';
import {loadSkbStorageDescriptor} from './skb-artifact-storage-v2.ts';
import {launchSkbArtifactNativeService} from './skb-artifact-native-service-v2.ts';
import {tbEngine} from './tb-engine.ts';
import {skbToolGateway} from './skb-artifact-tool-gateway-v2.ts';
import {SIX_TOOLS} from './tb-nginx-contract.ts';
import {loadNativePython,localhostPortClosed} from './skb-jpg-native-python.ts';
import {skbStoppedSnapshot} from './skb-artifact-runtime-v2.ts';
import {acquireSkbFastAdmission} from './skb-fast-admission-v6.ts';
import {createFastDelivery} from './skb-fast-delivery-v3.ts';
import {checkFastPayload} from './skb-fast-payload-guard-v3.ts';
const ROOT=resolve(import.meta.dir,'../..');
function sql(db:Database,text:string,params:any[]=[]):any[]{const s=db.query(text);try{return s.all(...params);}finally{s.finalize();}}
export async function runFastPilot(recipePin:Pin){
 const r=jsonPin(recipePin),mode='run',selection=loadSkbArtifactSelection();
 demand(r.draftFastFirst===true&&r.concurrency===2&&r.providerKind==='real-provider'&&r.taskDescriptorPins.length===10,'skb_fast_fixed_scope');
 assertSkbArtifactSchedule(r.runId,r.taskSchedule,selection.tasks,r.taskScheduleSha256);
 demand(JSON.stringify(r.model)===JSON.stringify(SKB_ARTIFACT_MODEL),'skb_fast_fixed_model');
 const storage=loadSkbStorageDescriptor(r.storageDescriptorPin,actualPin(join(import.meta.dir,'skb_artifact_storage_v2.py')));
 demand(Object.entries(storage.nativeEnvironment).every(([k,v])=>process.env[k]===v),'skb_fast_parent_D_environment');
 const sourceGuard=()=>{for(const p of r.forwardSourcePins)verifyPin(p);};
 let memoryObserved=0; const memoryProbe=()=>{if(Date.now()-memoryObserved<10000)return;const m=JSON.parse(readFileSync(join(r.output,'commit-headroom.json'),'utf8'));const launch=jsonPin(actualPin(join(r.output,'hidden-launch.json')));demand(m.runtimePid===process.pid&&m.launcherPid===launch.launcherPid&&Date.now()-m.observedAtUnixMs<30000&&m.observedAtUnixMs<=Date.now()+1000,'skb_commit_telemetry_identity');save('commit-observation-'+Date.now()+'.json',{...m,modelCalls:0});demand(m.availableCommitBytes>=512*1024**2,'skb_host_commit_headroom');memoryObserved=Date.now();};
 const resource=()=>{memoryProbe();for(const [volume,path] of [['C','C:/'],['D','D:/'],['F','F:/']] as const){const a=statfsSync(path);demand(a.bavail*a.bsize>=(volume==='C'?1024**3:volume==='D'?3*1024**3:22*1024**3),'skb_fast_actual_disk_'+volume);}};
 const save=(name:string,value:any,replace=false)=>durableJpgJson(join(r.output,name),value,replace);
 sourceGuard();resource();const providerKey=benchmarkProviderKey(ROOT);
 const admission=await acquireOpenRouterAdmission({root:ROOT,output:r.output,runId:r.runId,family:SKB_ARTIFACT_FAMILY,entry:import.meta.path,sourcePins:r.forwardSourcePins});r.prices=admission.prices;const delivery=createFastDelivery(r);
 const engines:any[]=[],rowEngines=new Map<number,any>(),records:any[]=[],registrations:Pin[]=[],privateConfigs:string[]=[],faults:any[]=[],ports:number[]=[],slots:any[]=[],activePlaces=new Map<string,any>();
 const resume=new Set<number>(r.resumeIndices);demand(JSON.stringify([...resume])===JSON.stringify([16,17,18,19]),'skb_resume_only_unstarted_four');
 const prior=jsonPin(r.priorRecipePin);demand(JSON.stringify(prior.model)===JSON.stringify(r.model),'skb_resume_original_model');
 demand(r.reuseGenerationPins.length===16,'skb_resume_prior_sixteen');
 for(const p of r.reuseGenerationPins){const old=jsonPin(p),row=r.taskSchedule[old.index];
   demand(old.index<16&&!resume.has(old.index)&&old.officialId===row.officialId&&old.arm===row.arm,'skb_resume_source_case');
   for(const key of ['taskSeconds','verifierSeconds','cpus','memoryMb','promptBodySha256'])demand(old[key]===row[key],'skb_resume_original_'+key);
   demand(old.apiCalls.some((c:any)=>c.providerAttempted&&c.httpStatus===200&&c.completionValid&&c.usage),'skb_resume_prior_real_call');
   const record={...old,reusedGenerationPin:p};
   const recovered=r.recoveredCapturePins?.[String(old.index)];
   if(recovered){const cap=jsonPin(recovered),closure=r.recoveredSolverClosurePins[String(old.index)];
     demand(cap.containerStopped&&cap.taskDescriptorPin.sha256===old.taskDescriptorPin.sha256,'skb_resume_real_stopped_capture');
     demand(jsonPin(closure).capturePins.some((x:Pin)=>x.sha256===recovered.sha256),'skb_resume_capture_in_owned_closure');
     record.artifactCapture={capturePin:recovered,recoveredFromOwnedClosurePin:closure};record.solverClosurePin=closure;record.captureRecoveredFromOriginalStoppedSolver=true;
     const db=r.recoveredDatabasePaths[String(old.index)],snap=skbStoppedSnapshot(db,old.id);record.trace=snap.trace;record.units=snap.units;record.candidate=snap.candidate?.body??'';
     record.candidateSha256=hash(record.candidate);record.databasePins=[db,db+'-wal'].filter(existsSync).map(actualPin);
   }
   records.push(record);const saved=save('generation-'+old.index+'.json',record);
   delivery.update(old.index,{status:'已运行，评分待补',rawGenerationPath:saved.path,providerRequests:old.apiCalls.filter((c:any)=>c.providerAttempted).length,
     promptTokens:old.apiCalls.reduce((n:number,c:any)=>n+(c.usage?.prompt_tokens??0),0),completionTokens:old.apiCalls.reduce((n:number,c:any)=>n+(c.usage?.completion_tokens??0),0),fault:old.fault??null});
 }
 const token=randomBytes(32).toString('hex'),proxyToken=randomBytes(32).toString('hex');
 const secrets=new Set([token,proxyToken,...Object.entries(process.env).filter(([k,v])=>/(KEY|TOKEN|SECRET|PASSWORD)/i.test(k)&&typeof v==='string'&&v.length>=6).map(([,v])=>v!)]);
 const register=(pid:number,role:string)=>{const p=save('process-'+role+'.json',{protocol:'paid-owned-process-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,ownerNonce:admission.owned.ownerNonce,pid,role,registeredAtUnixMs:Date.now()});registrations.push(p);admission.registerOwnedProcess(p);};
 const cleanup=async(stage:string,fn:()=>any)=>{try{return await fn();}catch(e){faults.push({stage,type:e instanceof Error?e.name:'OwnedFailure',code:(e as any)?.code??null});return undefined;}};
 const request=async(origin:string,path:string,body:any,timeout=2000000)=>{const res=await fetch(origin+path,{method:'POST',headers:{'content-type':'application/json','X-ObjRun-Grader-Token':token},body:JSON.stringify(body),signal:AbortSignal.timeout(timeout)});const v=await res.json();demand(res.ok,'skb_fast_bridge_request_'+path);return v as any;};
 const queue=createSkbArtifactFeeQueue({inference:BENCHMARK_INFERENCE,provider:BENCHMARK_PROVIDER,runId:r.runId,providerKind:'real-provider',capUsd:admission.capUsd,priorCostUpperBoundUsd:0,prices:r.prices,admission,storage,sourcePins:r.forwardSourcePins,schedule:r.taskSchedule,
   beforeProducerAdmission:()=>{sourceGuard();resource();},transport:async(raw,route)=>{
     const guard=checkFastPayload(raw,[...secrets]);save('payload-guard-'+randomBytes(12).toString('hex')+'.json',{...guard,route});
     return captureProviderResponse(await benchmarkFetch(raw,providerKey));}});
 const equal=(s:string)=>{const a=Buffer.from(s),b=Buffer.from('Bearer '+proxyToken);return a.length===b.length&&timingSafeEqual(a,b);};
 const server=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(req){if(!equal(req.headers.get('authorization')??''))return Response.json({error:'Unauthorized proxy'},{status:401});const p=new URL(req.url).pathname;demand(req.method==='POST'&&p.endsWith('/v1/chat/completions'),'skb_fast_proxy_path');const result=await queue.handle(p.slice(1,-'/v1/chat/completions'.length),await req.text());return new Response(result.rawResponse,{status:result.httpStatus,headers:{'content-type':'application/json'}});}});ports.push(server.port!);
 const previous={token:process.env.TGENGIN_GRADER_TOKEN,origins:process.env.TGENGIN_GRADER_ORIGINS,key:process.env.OBJRUN_SKB_JOURNAL_PROXY_KEY};
 process.env.TGENGIN_GRADER_TOKEN=token;process.env.OBJRUN_SKB_JOURNAL_PROXY_KEY=proxyToken;
 let accounting:any;
 const native=async(script:string,args:string[],seconds:number)=>{const n=loadNativePython(),started=Date.now(),argv=['-B','-X','utf8',join(import.meta.dir,script),...args];
   const child=spawn(n.executable,argv,{windowsHide:true,env:process.env,stdio:['ignore','pipe','pipe']});let out=Buffer.alloc(0),err=Buffer.alloc(0),code:number|null=null,timed=false;
   child.stdout.on('data',b=>{out=Buffer.concat([out,b]);if(out.length>4*1024**2)child.kill();});child.stderr.on('data',b=>{err=Buffer.concat([err,b]);if(err.length>1024**2)child.kill();});
   await new Promise<void>((ok,bad)=>{const t=setTimeout(()=>{timed=true;child.kill();},seconds*1000);child.once('error',e=>{clearTimeout(t);bad(e);});child.once('exit',c=>{code=c;});child.once('close',()=>{clearTimeout(t);ok();});});
   const caller=save('native-'+randomBytes(8).toString('hex')+'.json',{argv,childPid:child.pid,parentPid:process.pid,startedAtUnixMs:started,finishedAtUnixMs:Date.now(),exitCode:code,timedOut:timed,directChildClosed:true,stdout:out.toString(),stderr:err.toString(),modelCalls:0});
   const lines=out.toString().split(/\r?\n/).filter(x=>x.startsWith('{')).map(x=>JSON.parse(x));return{caller,lines,code,timed};};
 try{
   save('recipe.json',r);save('manifest.json',{family:SKB_ARTIFACT_FAMILY,runId:r.runId,taskSchedule:r.taskSchedule,concurrency:2,plannedTaskRuns:20,model:r.model,draftFastFirst:true,fullEnvironmentCertificationPending:true,apiUsageLimitRemoved:true,full87Authorized:false});
   for(let i=0;i<2;i++){
     const lp=r.slotStorageDescriptorPins[i],s=loadSkbStorageDescriptor(lp,actualPin(join(import.meta.dir,'skb_artifact_storage_v2.py'))),probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')}),port=probe.port!;await probe.stop(true);const stand='http://127.0.0.1:'+port;
     const slotRecipe=durableJpgJson(join(s.directories.taskmeta!,'fast-slot-recipe.json'),{...r,storageDescriptorPin:lp});
     const gateway=skbToolGateway({stand,token,store:join(storage.directories.raw!,'tools-slot-'+i),beforeCapture:resource,ledger:rows=>save('tool-ledger-slot-'+i+'.json',{receipts:rows},existsSync(join(r.output,'tool-ledger-slot-'+i+'.json')))});
     const bridge=launchSkbArtifactNativeService({script:actualPin(join(import.meta.dir,'skb-artifact-stand-v2.py')),argv:['--port',String(port),'--recipe',slotRecipe.path],descriptorPin:lp,storageSourcePin:actualPin(join(import.meta.dir,'skb_artifact_storage_v2.py')),port,env:{...process.env},startupMs:120000});
     bridge.child.stdout?.resume();bridge.child.stderr?.resume();register(bridge.child.pid!,'bridge-'+i);ports.push(port,Number(new URL(gateway.origin).port));
     const slot={index:i,lp,storage:s,stand,gateway,bridge};slots.push(slot);const health=await bridge.waitReady();save('bridge-health-'+i+'.json',health);
   }
   process.env.TGENGIN_GRADER_ORIGINS=slots.flatMap(s=>[s.stand,s.gateway.origin]).join(',');
   const runRow=async(row:any,slot:any)=>{

      const {stand,gateway,storage,lp}=slot;sourceGuard();resource();const dp=r.taskDescriptorPins[Math.floor(row.index/2)]!,d=jsonPin(dp),id=row.id,place='skb:'+id,dir=join(storage.directories.sqlite!,'worker-'+row.index);activePlaces.set(place,slot);delivery.update(row.index,{status:"运行中"});
      const engine=await tbEngine(BENCHMARK_INFERENCE,dir);engines.push(engine);rowEngines.set(row.index,engine);register(engine.pid,'engine-'+row.index);ports.push(Number(new URL(engine.base).port));privateConfigs.push(join(dir,'config.yaml'));
      const config=readFileSync(join(dir,'config.yaml'),'utf8'),credentials=/api: \{prefix: \/api, token: ("[^"]+"), publisherToken: ("[^"]+")/.exec(config);demand(credentials,'skb_private_engine_credentials');secrets.add(JSON.parse(credentials[1]!));secrets.add(JSON.parse(credentials[2]!));
      const auth:any[]=[];for(const path of ['/exec','/tasks','/declare'])for(const forged of [false,true]){const a=await fetch(engine.base+path,{method:'POST',headers:{'content-type':'application/json',...(forged?{authorization:'Bearer forged','X-TGEngin-Publisher':'forged'}:{})},body:'{}'});auth.push({path,forged,status:a.status});demand(a.status===401,'skb_engine_host_auth');}save('host-auth-'+row.index+'.json',auth);
      await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_SKB_JOURNAL_PROXY_KEY','deepseek/deepseek-v4.1-flash',handle,modes,:base,'[]' from api where key_env='OPENROUTER_API_KEY' and model='deepseek/deepseek-v4.1-flash'",params:{base:'http://127.0.0.1:'+server.port+'/'+row.route+'/v1'}});
      const dbPath=join(dir,'data/h2h.sqlite');gateway.register(place,()=>{const db=new Database(dbPath,{readonly:true});try{const t=sql(db,'select state,created_at,solve_seconds from task where id=?',[id])[0];if(!t)return 'task_not_created';if(Date.now()>=t.created_at+t.solve_seconds*1000)return 'task_deadline';return ['done','failed'].includes(t.state)?'task_terminal':undefined;}finally{db.close();}},()=>{const db=new Database(dbPath,{readonly:true});try{const t=sql(db,'select created_at,solve_seconds from task where id=?',[id])[0];return t?t.created_at+t.solve_seconds*1000:Date.now();}finally{db.close();}});
      await engine.api('POST','/declare',{handles:[{name:gateway.origin+'/place',expectMs:(row.taskSeconds+60)*1000},...['verified','passed'].map(name=>({name:stand+'/'+row.officialId+'/'+name,expectMs:(row.verifierSeconds+240)*1000}))],places:[{place,identity:gateway.origin+'/place',forward:true,tools:SIX_TOOLS.map(tool=>({tool,policy:'always'}))}],modes:[{mode:'skb_artifact',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:32,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:32,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OBJRUN_SKB_JOURNAL_PROXY_KEY','deepseek/deepseek-v4.1-flash']],unit:'fn:unit.tools'}]});
      await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit'"+(row.arm==='F'?",'verify'":"")+")"});
      await request(stand,'/register',{place,taskId:id,databasePath:dbPath});const cold=await request(stand,'/place',{place,op:'ping'});demand(cold.alive&&cold.environmentAudit.forbiddenHostKeysPresent===false&&cold.environmentAudit.standTokenPresent===false,'skb_solver_credentials');save('candidate-'+row.index+'.json',cold);
      const prompt=rawFrontmatterBody(readFileSync(join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',row.officialId,'task.md')));demand(hash(prompt)===row.promptBodySha256,'skb_untrimmed_prompt');
      await engine.api('POST','/tasks',{id,run:r.runId,mode:'skb_artifact',agent:'bot',place,source:'user',domain:'software',workdir:d.taskId==='jpg-ocr-stat'?'/app/workspace':'/root',description:prompt,...(row.arm==='F'?{objective:skbArtifactObjective(stand,row.officialId),readable:false}:{}),solveSeconds:row.taskSeconds,maxBranches:mode==='runtime-control'?1:row.arm==='F'?4:1,maxDeadSiblings:mode==='runtime-control'?1:row.arm==='F'?100000:1,noSearch:['all']});
      let terminal:any;const limit=Date.now()+(row.taskSeconds+row.verifierSeconds+300)*1000;
      while(Date.now()<limit){demand(!queue.state().provider.stopReason,'skb_provider_admission_stopped');const s=await engine.api<any>('GET','/tasks/'+encodeURIComponent(id)+'/status'),v=s.result?JSON.parse(s.result):null;if(['done','failed'].includes(s.state)&&!['finalization_pending','finalization_error'].includes(v?.outcome)){terminal=s;break;}await Bun.sleep(200);}
      demand(terminal,'skb_terminal_finalization_missing');queue.sealRoute(row.route);gateway.seal(place);const quiet=await gateway.drain(place);await queue.proxy.drain(row.route);await engine.stop();demand(await localhostPortClosed(Number(new URL(engine.base).port),600),'skb_engine_port_remaining');
      const snapshot=skbStoppedSnapshot(dbPath,id),captured=await request(stand,'/capture',{place,final:true}),removed=await request(stand,'/stop',{place});demand(removed.ownedContainersRemaining===0,'skb_solver_remains');activePlaces.delete(place);
      const calls=queue.taskReceipts(row.route),verdict=terminal.result?JSON.parse(terminal.result):{valid:true,outcome:'unaided_generated'},deadline=terminal.created_at+row.taskSeconds*1000;
      const generation=skbArtifactGeneration({runtimeVerdict:verdict,state:terminal.state,calls,trace:snapshot.trace,candidate:snapshot.candidate?.body,deadline,receipts:quiet.receipts,capture:captured});
      const record={protocol:'skillsbench-ten-task-generation-v2',family:SKB_ARTIFACT_FAMILY,runId:r.runId,...row,taskDescriptorPin:dp,storageDescriptorPin:lp,actualCreatedAt:terminal.created_at,deadlineUnixMs:deadline,state:terminal.state,runtimeVerdict:verdict,generationValid:generation.valid,generationClassification:generation,candidate:snapshot.candidate?.body??'',candidateSha256:hash(snapshot.candidate?.body??''),trace:snapshot.trace,units:snapshot.units,apiCalls:calls,toolQuiescence:quiet,artifactCapture:captured,solverClosurePin:removed.closurePin,workerPid:engine.pid,databasePins:[dbPath,dbPath+'-wal'].filter(existsSync).map(actualPin),explicitVerifyCalls:snapshot.trace.filter((x:any)=>{try{return x.kind==='tool'&&JSON.parse(x.body).name==='verify';}catch{return false;}}).length};
      records.push(record);const genPin=save('generation-'+row.index+'.json',record);delivery.update(row.index,{status:'已运行，评分待补',rawGenerationPath:genPin.path,providerRequests:calls.filter((x:any)=>x.providerAttempted).length,promptTokens:calls.reduce((n:number,x:any)=>n+(x.usage?.prompt_tokens??0),0),completionTokens:calls.reduce((n:number,x:any)=>n+(x.usage?.completion_tokens??0),0)});console.log(JSON.stringify({phase:'real-generation-closed',taskId:row.officialId,arm:row.arm,providerKind:r.providerKind,modelRequests:calls.length,generationValid:generation.valid}));
   };
   let cursor=0;
   await Promise.all(slots.map(async(slot)=>{while(cursor<r.taskSchedule.length){const row=r.taskSchedule[cursor++];if(!resume.has(row.index))continue;try{await runRow(row,slot);}catch(e){
     const fault={stage:'generation_'+row.index,type:e instanceof Error?e.name:'GenerationFailure',code:(e as any)?.code??null};faults.push(fault);
     const place='skb:'+row.id;queue.sealRoute(row.route);slot.gateway.seal(place);await cleanup('row_tool_drain_'+row.index,()=>slot.gateway.drain(place));await cleanup('row_engine_close_'+row.index,()=>rowEngines.get(row.index)?.stop());
     await cleanup('row_provider_drain_'+row.index,()=>queue.proxy.drain(row.route));
     let captured:any,removed:any;if(activePlaces.has(place)){captured=await cleanup('row_capture_'+row.index,()=>request(slot.stand,'/capture',{place,final:true}));removed=await cleanup('row_solver_close_'+row.index,()=>request(slot.stand,'/stop',{place}));activePlaces.delete(place);}
     const calls=queue.taskReceipts(row.route),rec={...row,storageDescriptorPin:slot.lp,taskDescriptorPin:r.taskDescriptorPins[Math.floor(row.index/2)],apiCalls:calls,artifactCapture:captured??null,solverClosurePin:removed?.closurePin??null,fault,state:'error'};
     records.push(rec);const p=save('generation-'+row.index+'.json',rec);delivery.update(row.index,{status:'真实运行失败；评分待补',fault,providerRequests:calls.filter(x=>x.providerAttempted).length,rawGenerationPath:p.path});
   }}}));
 }catch(e){faults.push({stage:'startup',type:e instanceof Error?e.name:'StartupFailure',code:(e as any)?.code??null});}
 finally{
   await cleanup('queue_stop',()=>queue.stop('generation_closed'));for(const [place,s]of activePlaces)await cleanup('active_tools_'+place,()=>s.gateway.drain(place));
   for(const e of engines)await cleanup('engine_close',()=>e.stop());await cleanup('provider_drain',()=>queue.drain());
   for(const s of slots){s.bridgeClosure=await cleanup('bridge_close_'+s.index,()=>s.bridge.stop());await cleanup('gateway_close_'+s.index,()=>s.gateway.stop());}
   await cleanup('proxy_close',()=>server.stop(true));for(const p of privateConfigs)await cleanup('private_config_remove',()=>{if(existsSync(p))unlinkSync(p);});
   for(const [k,v]of [['TGENGIN_GRADER_TOKEN',previous.token],['TGENGIN_GRADER_ORIGINS',previous.origins],['OBJRUN_SKB_JOURNAL_PROXY_KEY',previous.key]]){if(v===undefined)delete process.env[k!];else process.env[k!]=v;}
 }
 records.sort((a,b)=>a.index-b.index);const generationClosedAt=Date.now();save('generation-close.json',{records:records.length,generationClosedAtUnixMs:generationClosedAt,faults,bridgeClosures:slots.map(s=>s.bridgeClosure)});
 accounting=await cleanup('accounting_close',()=>queue.exportClosedAccounting());if(!accounting)accounting=await cleanup('accounting_retention',()=>queue.retainFailure('fast_runtime_failure'));
 const accountingPin=save('accounting-close.json',accounting??{fault:'accounting closure unavailable'}),taskPins:Pin[]=[];
 for(const record of records){
   const offlineGrade=join(r.output,'recovered-stage-grade-'+record.index+'.json');
   const offlinePin=existsSync(offlineGrade)?actualPin(offlineGrade):undefined;
   const priorTask=join(prior.output,'task-'+record.index+'.json');
   let priorGrade:any;
   if(existsSync(priorTask)){const priorPin=actualPin(priorTask),old=jsonPin(priorPin);if(old.finalEvaluation?.valid&&old.artifactCapture?.capturePin?.sha256===record.artifactCapture?.capturePin?.sha256)priorGrade=save('reused-prior-stage-grade-'+record.index+'.json',{taskDescriptorPin:old.taskDescriptorPin,capturePin:old.artifactCapture.capturePin,gradeOwnerPin:old.finalGradeOwnerPin,callerPin:old.finalGradeCallerPin,evaluation:old.finalEvaluation,priorTaskPin:priorPin,modelCalls:0});}
   const reused=r.reuseStageGradePins?.[String(record.index)]??priorGrade??(offlinePin&&jsonPin(offlinePin).evaluation.valid?offlinePin:undefined);
   if(reused){const old=jsonPin(reused);demand(old.capturePin.sha256===record.artifactCapture.capturePin.sha256&&old.taskDescriptorPin.sha256===record.taskDescriptorPin.sha256&&old.evaluation.valid,'skb_resume_exact_grade_reuse');
     record.finalGradeOwnerPin=old.gradeOwnerPin;record.finalGradeCallerPin=old.callerPin;record.finalEvaluation=old.evaluation;record.reusedStageGradePin=reused;
     record.finalGradeStartedAfterGenerationClosed=false;record.finalGradeReusedFromSealedArtifact=true;
     taskPins.push(save('task-'+record.index+'.json',record));delivery.update(record.index,{status:'已评分',graded:true,officialReward:old.evaluation.officialReward,strictAllPassed:old.evaluation.allTestsPassed,fullCollectionValid:old.evaluation.valid,rawGradePath:old.gradeOwnerPin.path});continue;
   }

   if(!record.artifactCapture?.capturePin){taskPins.push(save('task-'+record.index+'.json',record));continue;}
   const dp=record.taskDescriptorPin,cp=record.artifactCapture.capturePin,lp=r.storageDescriptorPin;
   try{const q=await native('skb_artifact_ram_executor_v2.py',['--task-descriptor',dp.path,'--task-descriptor-sha256',dp.sha256,'--storage-descriptor',lp.path,'--storage-descriptor-sha256',lp.sha256,'--mode','grade','--capture',cp.path,'--capture-sha256',cp.sha256],record.verifierSeconds+120);
     record.finalGradeCallerPin=q.caller;const op=q.lines[0]?.gradeOwnerPin;record.finalGradeOwnerPin=op??null;
     const owner=op?jsonPin(op):null,result=owner?.resultPins?jsonPin(owner.resultPins['private-result.json']):null,e=result?.evaluation;
     record.finalEvaluation=e??null;record.finalGradeStartedAfterGenerationClosed=true;
     if(e){delivery.update(record.index,{status:'已评分',graded:true,officialReward:e.officialReward,strictAllPassed:e.allTestsPassed,fullCollectionValid:e.valid,rawGradePath:op.path});}
     else{record.finalGradeFault={exitCode:q.code,timedOut:q.timed,ownerFault:owner?.fault??null};delivery.update(record.index,{status:'已运行，评分未验证',fault:record.finalGradeFault,rawGradePath:op?.path??q.caller.path});}
   }catch(e){record.finalGradeFault={type:e instanceof Error?e.name:'GradeFailure'};delivery.update(record.index,{status:'已运行，评分未验证',fault:record.finalGradeFault});}
   taskPins.push(save('task-'+record.index+'.json',record));console.log(JSON.stringify({phase:'fast-final-grade',taskId:record.officialId,arm:record.arm,officialReward:record.finalEvaluation?.officialReward??null,fullCollectionValid:record.finalEvaluation?.valid??false}));
 }
 const provider=queue.state(),real=records.filter(x=>x.apiCalls.some((c:any)=>c.providerAttempted&&c.httpStatus===200&&c.completionValid&&c.usage));
 const paired=selection.tasks.filter(t=>new Set(real.filter(x=>x.officialId===t.taskId).map(x=>x.arm)).size===2);
 const ownedClosed=slots.length===2&&slots.every(s=>s.bridgeClosure?.closed&&jsonPin(actualPin(join(s.storage.directories.stand,'bridge-owned-close.json'))).ownedSolversClosed);
 const summary=save('summary.json',{protocol:'skillsbench-fast-resumed-summary-v6',family:SKB_ARTIFACT_FAMILY,runId:r.runId,plannedTaskRuns:20,actualTaskRecords:records.length,
   realInferenceTaskRuns:real.length,completedPairedRealTrials:paired.length,gradedTaskRuns:records.filter(x=>x.finalEvaluation).length,taskPins,accountingPin,faults,
   model:r.model,concurrency:2,originalTaskBudgetsPreserved:true,formalScoreCertified:false,fullEnvironmentCertificationPending:true,apiUsageLimitRemoved:true,originalUnknownSettled:false,full87Authorized:false});
 save('owned-close.json',{registrationPins:registrations,ports,bridgeClosurePins:slots.map(s=>actualPin(s.bridge.closurePath)),ownedGenerationClosed:ownedClosed,generationClosedAtUnixMs:generationClosedAt});
 for(const [i,s]of [{storage},...slots].entries()){
   const n=loadNativePython(),script=join(import.meta.dir,'skb-artifact-secret-audit-v2.py'),lp=i===0?r.storageDescriptorPin:slots[i-1].lp,out=join(s.storage.directories.audit!,'fast-secret-audit.json');
   const c=spawn(n.executable,['-B','-X','utf8',script,'--storage',lp.path,'--sha256',lp.sha256,'--output',out],{windowsHide:true,env:process.env,stdio:['pipe','pipe','pipe']});
   let auditOut='',auditErr='',auditCode:number|null=null,auditFault:string|null=null;
   c.stdout.on('data',b=>{auditOut+=b.toString();if(auditOut.length>1024**2)c.kill();});c.stderr.on('data',b=>{auditErr+=b.toString();if(auditErr.length>1024**2)c.kill();});
   await new Promise<void>(done=>{const timer=setTimeout(()=>{auditFault='timeout';c.kill();},180000);c.once('error',e=>{auditFault=e.name;clearTimeout(timer);done();});c.once('close',code=>{auditCode=code;clearTimeout(timer);done();});c.stdin.end(JSON.stringify([...secrets]));});
   save('secret-audit-caller-'+i+'.json',{childPid:c.pid,exitCode:auditCode,directWaitReturned:true,stdout:auditOut,stderr:auditErr,fault:auditFault,actualSecretValuesSerialized:false});demand(auditCode===0&&!auditFault,'skb_fast_secret_scan_failed');
 }
 const pending=provider.provider?.inflight??provider.provider?.pending??0;
 admission.finishLightweight({ownedGenerationClosed:ownedClosed,pendingRequests:pending,summaryPin:summary,accountingPin,originalUnknownSettled:false,newFinancialUnknownPreserved:accounting?.cashPin?jsonPin(accounting.cashPin).snapshot.newUnknownCount:null});
 delivery.save();return {summaryPin:summary,realInferenceTaskRuns:real.length,completedPairedRealTrials:paired.length,gradedTaskRuns:records.filter(x=>x.finalEvaluation).length,formalScoreCertified:false};
}
if(import.meta.main){demand(process.argv[2],'skb_fast_recipe_argument');try{console.log(JSON.stringify(await runFastPilot(actualPin(resolve(process.argv[2])))));}catch(e){const r=jsonPin(actualPin(resolve(process.argv[2])));durableJpgJson(join(r.output,'top-level-failure.json'),{type:e instanceof Error?e.name:'Failure',message:e instanceof Error?e.message:'unknown',atUtc:new Date().toISOString(),modelCallsNotRetried:true});throw e;}}
