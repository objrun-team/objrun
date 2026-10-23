import {mkdirSync,existsSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from '../runtime-snapshot/test/_lib.ts';
import {finalCandidate} from '../runtime-snapshot/app/src/objective/candidate.ts';
import {cfg,save,read,hash,model,grade,fullFeedback} from './common.ts';

export async function native(task:any,dir:string,calls:string,fixture=false){
 mkdirSync(dir,{recursive:true});const engineDir=join(dir,'engine');mkdirSync(engineDir,{recursive:true});
 const priorProcessFile=join(dir,'engine-process.json');
 if(existsSync(priorProcessFile)){
  const old=read(priorProcessFile);
  if(Number.isInteger(old.pid)&&old.pid>0){
   const check=spawnSync('powershell.exe',['-NoProfile','-Command',`Get-CimInstance Win32_Process -Filter "ProcessId=${old.pid}" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress`],{encoding:'utf8',windowsHide:true});
   if(check.status!==0)throw Error('PriorEngineOwnershipCheckFailed');
   const info=check.stdout.trim()?JSON.parse(check.stdout):null;
   if(info){
    const command=String(info.CommandLine??'').replace(/\//g,'\\').toLowerCase();
    if(info.ParentProcessId!==old.runnerPid||!command.includes('\\runtime-snapshot\\app\\src\\main.ts'))throw Error('PriorEngineOwnershipMismatch');
    let parentLive=false;try{process.kill(old.runnerPid,0);parentLive=true;}catch{}
    if(parentLive&&old.runnerPid!==process.pid)throw Error('PriorEngineRunnerStillLive');
    process.kill(old.pid);save(join(dir,'orphan-engine-recovery-'+Date.now()+'.json'),{priorEnginePid:old.pid,priorRunnerPid:old.runnerPid,ownershipVerified:true,reason:'Recover only this task engine before reopening its durable database'});
    await Bun.sleep(1000);
   }
  }
 }
 const addressFile=join(dir,'addresses.json'),address=existsSync(addressFile)?read(addressFile):{};
 let interfaceError:any,pending=0,syntheticReplies=0;const feedback:any[]=existsSync(join(dir,'feedback.json'))?read(join(dir,'feedback.json')):[];
 const requests:any[]=[];
 const service=Bun.serve({hostname:'127.0.0.1',port:address.port??0,idleTimeout:255,async fetch(req){
  const body:any=await req.json(),path=new URL(req.url).pathname;
  if(path==='/parsed')return Response.json(true);
  if(path==='/correct'){
   try{
    const q=body.input;const v=q.result??q.task.result??'';const answer=typeof v==='object'?v.body??'':v;
    const g=fixture?{valid:true,passed:String(answer).trim()==='SELECT 1',errorType:'ResultMismatch'}:await grade(task,String(answer),dir);
    if(!g.valid){interfaceError=Error('FeedbackEnvironment:'+g.errorType);return Response.json({error:'Feedback environment unavailable'},{status:503});}
    const output={value:!!g.passed,note:fullFeedback(g)};
    feedback.push({atUtc:new Date().toISOString(),candidateSha256:hash(String(answer)),verdict:g,exposed:output});save(join(dir,'feedback.json'),feedback);return Response.json(output);
   }catch(e){interfaceError=e;return Response.json({error:'Feedback environment exception'},{status:503});}
  }
  pending++;
  try{
   if(fixture){
    requests.push(body);syntheticReplies++;
    const name=syntheticReplies===1?'verify':'submit',answer=name==='verify'?'SELECT 0':'SELECT 1';
    return Response.json({id:'synthetic-'+syntheticReplies,object:'chat.completion',created:1,model:cfg.model,choices:[{index:0,message:{role:'assistant',content:null,tool_calls:[{id:'call-'+syntheticReplies,type:'function',function:{name,arguments:JSON.stringify({answer})}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0}});
   }
   const invoke=(b:any)=>model(join(calls,hash(JSON.stringify(b))),b);
   let response=await invoke(body);
   const handin=body.tools?.length===1&&body.tools[0]?.function?.name==='submit';
   const v=JSON.parse(response.raw),tc=v.choices?.[0]?.message?.tool_calls??[];
   if(handin&&v.choices?.[0]?.finish_reason!=='length'&&!(tc.length===1&&tc[0].function?.name==='submit')){
    const repair={...body,messages:[...(body.messages??[]),{role:'user',content:'Your preceding response did not invoke submit and was not handed in. Invoke the available submit tool exactly once with the complete SQLite query in the answer argument. Plain text is not accepted at this hand-in station.'}]};
    save(join(dir,'submit-format-repair-'+Date.now()+'.json'),{originalRequestSha256:hash(JSON.stringify(body)),repairRequestSha256:hash(JSON.stringify(repair))});response=await invoke(repair);
   }
   return new Response(response.raw,{status:response.status,headers:{'content-type':'application/json'}});
  }catch(e){interfaceError=e;return Response.json({error:{message:String(e)}},{status:502});}finally{pending--;}
 }});
 save(addressFile,{port:service.port});
 let engine:Machine|undefined;const id='bird-20251106/'+task.officialId;
 try{
  engine=await machine({maxTokens:cfg.maxTokens,reasoningEffort:'high',temperature:cfg.temperature,seed:42,retryTimes:0,continueTimes:3},{directory:engineDir,keep:true});
  save(join(dir,'engine-process.json'),{pid:engine.pid,base:engine.base,runnerPid:process.pid,atUtc:new Date().toISOString()});
  const handle=`http://127.0.0.1:${service.port}/correct`;
  const parsed=`http://127.0.0.1:${service.port}/parsed`;
  await engine.api('POST','/declare',{handles:[{name:handle,expectMs:100000},{name:parsed,expectMs:100000}],places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:cfg.cyclesMaxUnits,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:cfg.cyclesMaxUnits,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',cfg.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
  await engine.api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model",params:{url:`http://127.0.0.1:${service.port}/v1`,model:cfg.model}});
  const prior:any=await engine.api('POST','/query',{sql:'select * from task where id=:id',params:{id}});
  if(!prior.rows.length)await engine.api('POST','/tasks',{id,run:'bird-20251106',mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt+'\nUse submit to hand in the complete SQLite query. verify provides oracle execution feedback. No database exploration, filesystem, or search tools are available.',objective:{nodes:[{name:'parsed',domain:'bool',moment:'done',handle:parsed},{name:'correct',domain:'bool',moment:'done',handle}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:cfg.checks,reuse:'text'},readable:false,solveSeconds:fixture?60:cfg.solveSeconds,maxBranches:cfg.maxBranches,maxDeadSiblings:cfg.maxDeadSiblings,noSearch:['all']});
  const start=Date.now();let status:any,why:any;
  while(Date.now()-start<(fixture?60000:1260000)){
   if(interfaceError)throw interfaceError;
   status=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/status');why=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/why');
   if(pending===0&&(why.problems??[]).some((s:string)=>/kernel threw while advancing/i.test(s)&&/timed out|fetch failed|socket.*closed|connection.*closed/i.test(s)))throw Error('NativeInterfaceTimeout');
   if(JSON.stringify(why.problems).includes('The required submit tool was not called exactly once'))return {answer:'',candidateHow:'none',modelProtocolFailure:true,engineState:status.state,engineVerdict:why};
   if(['done','failed'].includes(status.state)&&status.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(status.result).outcome))break;
   await Bun.sleep(fixture?100:1000);
  }
  if(!status?.result)throw Error('EngineTaskDeadline');
  const trace:any=await engine.api('POST','/query',{sql:'select * from agent_bot_msg order by instance,unit,seq'});save(join(dir,'trace.json'),trace.rows);
  const tree:any=await engine.api('POST','/query',{sql:'select * from task_repair order by unit'});save(join(dir,'tree.json'),tree.rows);
  const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});let candidate:any;
  try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const q=db.prepare(sql);try{return q.all(...params);}finally{q.finalize();}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);}finally{db.close();}
  return {answer:candidate?.body??'',candidateHow:candidate?.how??'none',engineState:status.state,engineVerdict:JSON.parse(status.result),feedbackChecks:feedback.length,treeNodes:tree.rows.length,...(fixture?{syntheticReplies,feedbackObserved:requests.some(q=>JSON.stringify(q.messages??[]).includes('failed: result mismatch'))}:{})};
 }finally{
  if(engine){try{const trace:any=await engine.api('POST','/query',{sql:'select * from agent_bot_msg order by instance,unit,seq'});save(join(dir,'trace.json'),trace.rows);}catch{}await engine.stop();}
  const end=Date.now();while(pending&&Date.now()-end<610000)await Bun.sleep(100);await service.stop(true);
 }
}
