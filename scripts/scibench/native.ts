import {mkdirSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from './engine/test/_lib.ts';
import {finalCandidate} from './engine/app/src/objective/candidate.ts';
import {cfg,save,hash,model,BudgetStop} from './common.ts';
import {restoreNative} from './recovery.ts';

export async function native(task:any,dir:string,calls:string,grade:(answer:string)=>Promise<any>,fixture=false){
 mkdirSync(dir,{recursive:true});const engineDir=join(dir,'engine');
 let engine:Machine|undefined,requestCount=0,pending=0,interfaceError:any,budgetReason:string|undefined;
 let recovery:ReturnType<typeof restoreNative>|undefined;
 let deadline=Date.now()+(fixture?60:cfg.solveSeconds)*1000;
 const feedback:any[]=[],requests:any[]=[];
 const service=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:0,async fetch(req){
  const body:any=await req.json(),path=new URL(req.url).pathname;
  if(['/parsed','/correct'].includes(path)){
   try{
    const value=body.input?.result??body.input?.task?.result??'';
    const answer=typeof value==='object'?value.body??'':value;
    const g=await grade(String(answer));if(!g.valid)throw Error('GraderUnavailable');
    const out=path==='/parsed'?{value:g.parsed,note:g.parsed?'':'End with a boxed finite numeric answer in the requested unit.'}:{value:g.passed,note:''};
    feedback.push({node:path.slice(1),candidateSha256:hash(String(answer)),exposed:out});save(join(dir,'feedback.json'),feedback);return Response.json(out);
   }catch(e){interfaceError=e;return Response.json({valid:false,outcome:'grader_error',errorType:'PrivateGraderUnavailable'},{status:503});}
  }
  if(path!=='/v1/chat/completions')return Response.json({error:'NotFound'},{status:404});
  const allowed=new Set(['verify','submit','task_tree','node_load']);
  if((body.tools??[]).some((t:any)=>!allowed.has(t.function?.name))){interfaceError=Error('UnexpectedToolExposure');return Response.json({error:'UnexpectedToolExposure'},{status:503});}
  pending++;
  try{
   requestCount++;requests.push(body);
   if(fixture){
    const name=requestCount===1?'read':requestCount===2?'verify':'submit',answer=name==='verify'?'BAD':'GOOD';
    const args=name==='read'?{path:'data/private-tasks.json'}:{answer};
    return Response.json({id:'synthetic-'+requestCount,object:'chat.completion',created:1,model:cfg.model,choices:[{index:0,message:{role:'assistant',content:null,tool_calls:[{id:'fixture-'+requestCount,type:'function',function:{name,arguments:JSON.stringify(args)}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0}});
   }
   if(recovery&&requestCount===1)save(join(dir,'resumed-engine-request.json'),body);
   const response=await model(join(calls,'native-'+String(requestCount).padStart(3,'0')),recovery&&requestCount===1?recovery.wire:body,calls,deadline);
   return new Response(response.raw,{headers:{'content-type':'application/json'}});
  }catch(e){if(e instanceof BudgetStop)budgetReason=e.message;else interfaceError=e;return Response.json({error:{message:e instanceof BudgetStop?'SolveBudgetExhausted':'ProviderUnavailable'}},{status:502});}
  finally{pending--;}
 }});
 const base=`http://127.0.0.1:${service.port}`;
 let id=cfg.run+'/'+task.id;
 let status:any;
 try{
  if(cfg.recoveryFrom&&(!fixture||cfg.recoveryFixture)){recovery=restoreNative(task,dir,base);deadline=recovery.deadline;id=recovery.id;}
  mkdirSync(engineDir,{recursive:true});
  engine=await machine({maxTokens:16384,reasoningEffort:'high',temperature:0,retryTimes:0,continueTimes:3},{directory:engineDir,keep:true});
  save(join(dir,'engine-process.json'),{pid:engine.pid,base:engine.base,runnerPid:process.pid,atUtc:new Date().toISOString()});
  if(!recovery){
  await engine.api('POST','/declare',{handles:[{name:base+'/parsed',expectMs:5000},{name:base+'/correct',expectMs:5000}],places:[{place:'local'}],
   modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:cfg.cyclesMaxUnits,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:cfg.cyclesMaxUnits,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],
   agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',cfg.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
  await engine.api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model",params:{url:base+'/v1',model:cfg.model}});
  const allowed:any=await engine.api('POST','/query',{sql:'select name from tool where usable=1 order by name'});
  save(join(dir,'tool-permissions.json'),allowed.rows);
  await engine.api('POST','/tasks',{id,run:cfg.run,mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt+'\nUse submit to hand in the final answer text. verify checks a proposed answer; no filesystem, search, execution or external calculation tools are available.',
   objective:{nodes:[{name:'parsed',domain:'bool',moment:'done',handle:base+'/parsed'},{name:'correct',domain:'bool',moment:'done',handle:base+'/correct'}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'},
   readable:false,solveSeconds:fixture?60:cfg.solveSeconds,maxBranches:4,maxDeadSiblings:100000,noSearch:['all'],maxSearches:0});
  }else{
   const allowed:any=await engine.api('POST','/query',{sql:'select name from tool where usable=1 order by name'});
   save(join(dir,'tool-permissions.json'),allowed.rows);
  }
  const taskRow:any=await engine.api('POST','/query',{sql:'select * from task where id=:id',params:{id}});
  deadline=Number(taskRow.rows[0].created_at)+Number(taskRow.rows[0].solve_seconds)*1000;
  while(Date.now()<deadline+15000){
   status=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/status');
   if(interfaceError)throw interfaceError;
   if(['done','failed'].includes(status.state)&&status.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(status.result).outcome))break;
   if(budgetReason&&pending===0)break;
   if(Date.now()>deadline+2000&&pending===0)break;
   await Bun.sleep(fixture?100:500);
  }
  const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});let candidate:any;
  try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>db.query(sql).all(...params),run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);}finally{db.close();}
  return {answer:candidate?.body??'',candidateHow:candidate?.how??'none',engineState:status?.state,engineVerdict:status?.result?JSON.parse(status.result):null,
   feedbackNodeCalls:feedback.length,nativeModelRequests:requestCount,budgetReason:budgetReason??null,
   ...(fixture?{fixtureFeedbackObserved:requests.some(q=>JSON.stringify(q.messages).includes('End with a boxed finite numeric answer')),
    fixtureUnauthorizedReadBlocked:requests.some(q=>JSON.stringify(q.messages).includes('read is registered but usable = 0'))}:{})};
 }finally{
  if(engine){
   for(const [file,sql] of [['trace.json','select * from agent_bot_msg order by instance,unit,seq'],['tree.json','select * from task_repair order by unit'],['native-task.json','select * from task']]){
    try{const rows:any=await engine.api('POST','/query',{sql});save(join(dir,file),rows.rows);}catch{}
   }
   await engine.stop();
  }
  await service.stop(true);
 }
}
