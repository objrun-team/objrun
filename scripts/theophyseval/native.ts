import {mkdirSync,cpSync} from 'node:fs';
import {join} from 'node:path';
import {Database} from 'bun:sqlite';
import {randomBytes} from 'node:crypto';
import {machine,type Machine} from './engine/test/_lib.ts';
import {finalCandidate} from './engine/app/src/objective/candidate.ts';
import {cfg,save,hash,model} from './common.ts';
import {bridge,toolSpecs,protocol} from './tools.ts';

export async function native(task:any,unit:any,session:string,dir:string,calls:string,fixture=false){
 mkdirSync(dir,{recursive:true});const archivedEngineDir=join(dir,'engine');
 const engineDir=process.env.TPE_ENGINE_RUNTIME?join(process.env.TPE_ENGINE_RUNTIME,hash(dir)):archivedEngineDir;mkdirSync(engineDir,{recursive:true});
 let engine:Machine|undefined,requestCount=0,pending=0,fault:any,budgetReason:string|undefined,deadline=Date.now()+cfg.solveSeconds*1000;
 const feedback:any[]=[],requests:any[]=[];
 const scope='/s/'+randomBytes(24).toString('hex');
 const service=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:0,async fetch(req){
  let path=new URL(req.url).pathname;
  if(!path.startsWith(scope+'/'))return Response.json({error:'Unauthorized'},{status:403});
  path=path.slice(scope.length);
  const body:any=await req.json();
  try{
   if(path==='/tool/compute')return Response.json(Date.now()>=deadline?{stdout:'',stderr:'Stage solve time limit reached.',exitCode:124}:await bridge('compute',{...body.args,session,timeout:Math.min(body.args?.timeout??60,Math.max(1,Math.floor((deadline-Date.now())/1000)))}));
   if(path==='/tool/snapshot')return Response.json(await bridge('snapshot',{session}));
   if(['/output_valid','/correct'].includes(path)){
    const value=body.input?.result??body.input?.task?.result??'';
    const candidate=String(typeof value==='object'?value.body??'':value);
    const g=await bridge('grade',{session,unit:unit.id,candidate});if(!g.valid)throw Error('GraderUnavailable');
    const isFormat=path==='/output_valid';
    const out={value:isFormat?g.parsed:g.parsed&&g.passed,note:isFormat&&!g.parsed?'Write the required answer file in the public numerical/template format, then freeze it with snapshot.':''};
    feedback.push({node:path.slice(1),candidate,exposed:out});save(join(dir,'feedback.json'),feedback);return Response.json(out);
   }
   if(path!=='/v1/chat/completions')return Response.json({error:'NotFound'},{status:404});
   const allowed=new Set(['compute','snapshot','verify','submit','task_tree','node_load']);
   if((body.tools??[]).some((t:any)=>!allowed.has(t.function?.name)))throw Error('UnexpectedToolExposure');
   pending++;requestCount++;requests.push(body);
   if(fixture){
    const content=JSON.stringify(body.messages);const matches=[...content.matchAll(/tpe-[a-f0-9]{16}:[a-f0-9]{64}/g)];
    const name=requestCount===1?'compute':requestCount===2?'snapshot':requestCount===3?'verify':'submit',answer=matches.at(-1)?.[0]??'invalid';
    const args=name==='compute'?{command:'python -c "print(12345)"',timeout:10}:name==='snapshot'?{}:{answer};
    return Response.json({id:'fixture-'+requestCount,object:'chat.completion',created:1,model:cfg.model,choices:[{index:0,message:{role:'assistant',content:null,tool_calls:[{id:'fixture-'+requestCount,type:'function',function:{name,arguments:JSON.stringify(args)}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0}});
   }
   const response=await model(join(calls,'native-'+String(requestCount).padStart(3,'0')),body,calls,deadline);
   return new Response(response.raw,{headers:{'content-type':'application/json'}});
  }catch(e){if(path==='/v1/chat/completions'&&Date.now()>=deadline)budgetReason='SolveTimeBudget';else fault=e;return Response.json({error:{message:budgetReason??'PrivateRuntimeUnavailable'}},{status:503});}
  finally{if(path==='/v1/chat/completions')pending=Math.max(0,pending-1);}
 }});
 const base=`http://127.0.0.1:${service.port}${scope}`;const id=cfg.run+'/'+task.id+'/'+unit.id;
 let status:any;
 try{
  engine=await machine({maxTokens:16384,reasoningEffort:'high',temperature:0,retryTimes:0,continueTimes:3},{directory:engineDir,keep:true});
  save(join(dir,'engine-process.json'),{pid:engine.pid,base:engine.base,controllerPid:process.pid});
  await engine.api('POST','/declare',{handles:['output_valid','correct','tool/compute','tool/snapshot'].map(p=>({name:base+'/'+p,expectMs:120000})),places:[{place:'local'}],
   tools:toolSpecs.map(t=>({name:t.name,identity:base+'/tool/'+t.name,does:t.description,params:t.parameters,output:{type:'object'},concurrent:false,
    when:[[{dim:'task',key:'description',op:'contains',value:'Use compute'}]]})),
   modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:cfg.cyclesMaxUnits,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:cfg.cyclesMaxUnits,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],
   agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',cfg.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('compute','snapshot','submit','verify','task_tree','node_load')"});
  await engine.api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model",params:{url:base+'/v1',model:cfg.model}});
  save(join(dir,'tool-permissions.json'),(await engine.api<any>('POST','/query',{sql:'select name from tool where usable=1 order by name'})).rows);
  await engine.api('POST','/tasks',{id,run:cfg.run,mode:'repair',agent:'bot',place:'local',source:'user',description:unit.prompt+protocol,
   objective:{nodes:[{name:'output_valid',domain:'bool',moment:'done',handle:base+'/output_valid'},{name:'correct',domain:'bool',moment:'done',handle:base+'/correct'}],edges:[{src:'output_valid',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'never'},
   readable:false,solveSeconds:cfg.solveSeconds,maxBranches:4,maxDeadSiblings:100000,noSearch:['all'],maxSearches:0});
  const row=(await engine.api<any>('POST','/query',{sql:'select * from task where id=:id',params:{id}})).rows[0];
  deadline=Number(row.created_at)+Number(row.solve_seconds)*1000;
  while(Date.now()<deadline+15000){
   status=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/status');if(fault)throw fault;
   if(['done','failed'].includes(status.state)&&status.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(status.result).outcome))break;
   if((budgetReason||Date.now()>deadline+2000)&&pending===0)break;await Bun.sleep(400);
  }
  const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});let candidate:any;
  try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>db.query(sql).all(...params),run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);}finally{db.close();}
  return {candidate:candidate?.body??'',candidateHow:candidate?.how??'none',engineState:status?.state,engineVerdict:status?.result?JSON.parse(status.result):null,feedbackNodeCalls:feedback.length,nativeModelRequests:requestCount,budgetReason:budgetReason??null};
 }finally{
  if(engine){for(const [file,sql] of [['trace.json','select * from agent_bot_msg order by instance,unit,seq'],['tree.json','select * from task_repair order by unit'],['native-task.json','select * from task']]){
    try{save(join(dir,file),(await engine.api<any>('POST','/query',{sql})).rows);}catch{}
   }await engine.stop();
   if(engineDir!==archivedEngineDir){cpSync(engineDir,archivedEngineDir,{recursive:true,errorOnExist:true,force:false});save(join(dir,'engine-location.json'),{executionHost:'novaeve',liveDatabase:engineDir,archivedDatabase:archivedEngineDir,copiedAfterProcessExit:true});}}
  await service.stop(true);
 }
}
