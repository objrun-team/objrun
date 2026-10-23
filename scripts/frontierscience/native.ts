import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from './engine/test/_lib.ts';
import {finalCandidate} from './engine/app/src/objective/candidate.ts';

const root=join(import.meta.dir,'..'),input=JSON.parse(readFileSync(process.argv[2],'utf8'));
const dir=input.directory;mkdirSync(dir,{recursive:true});
const hash=(x:string)=>createHash('sha256').update(x).digest('hex');
const save=(p:string,x:any)=>writeFileSync(join(dir,p),JSON.stringify(x,null,2)+'\n');
const deadline=input.deadlineEpoch*1000,fixture=!!input.fixture;
let engine:Machine|undefined,requestCount=0,pending=0,failure:any=null,judgeWaitMs=0;
const feedback:any[]=[],engineRequests:any[]=[],wireResponses:any[]=[];
async function broker(path:string,body?:any){
 const r=await fetch(process.env.FRONTIER_BROKER_URL+path,{method:body?'POST':'GET',headers:{'content-type':'application/json','X-Frontier-Token':process.env.FRONTIER_BROKER_TOKEN!},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(Math.max(1,deadline-Date.now()))});
 const data:any=await r.json();if(!r.ok)throw Error(data.errorType+':'+data.error);return data;
}
const service=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:0,async fetch(req){
 const path=new URL(req.url).pathname,body:any=await req.json();
 try{
  if(path==='/present'||path==='/equivalent'){
   const value=body.input?.result??body.input?.task?.result??'';
   const answer=typeof value==='object'?value.body??'':value;
   let out:any;
   if(path==='/present')out={value:!!String(answer).trim(),note:String(answer).trim()?'':'Provide an answer to the question.'};
   else{
    if(Date.now()>=deadline)throw Error('OriginalSolveDeadlineExhausted');
    const start=Date.now();let decision:any;
    if(fixture)decision={valid:true,passed:answer==='FINAL ANSWER: 4'};
    else{
     const job=await broker('/jobs',{id:input.task.id,candidate:String(answer)});
     while(Date.now()<deadline){const p=await broker('/jobs/'+job.key);if(p.state==='complete'){decision=p.result;break;}await Bun.sleep(150);}
    }
    judgeWaitMs+=Date.now()-start;
    if(!decision?.valid)throw Error('PrivateGraderUnavailable');
    out={value:decision.passed,note:''};
   }
   feedback.push({node:path.slice(1),candidate:String(answer),candidateSha256:hash(String(answer)),exposed:out,atUtc:new Date().toISOString()});save('feedback.json',feedback);return Response.json(out);
  }
  if(path!=='/v1/chat/completions')return Response.json({error:'NotFound'},{status:404});
  if(Date.now()>=deadline)throw Error('OriginalSolveDeadlineExhausted');
  const allowed=new Set(['verify','submit','task_tree','node_load']);
  if((body.tools??[]).some((t:any)=>!allowed.has(t.function?.name)))throw Error('UnexpectedToolExposure');
  pending++;requestCount++;engineRequests.push(body);save('engine-requests.json',engineRequests);
  let response:any;
  if(fixture){
   const name=requestCount===1?'verify':'submit',answer=requestCount===1?'FINAL ANSWER: 5':'FINAL ANSWER: 4';
   response={id:'fixture-'+requestCount,object:'chat.completion',created:1,model:'deepseek-flash',choices:[{index:0,message:{role:'assistant',content:'',reasoning_content:'fixture reasoning '+requestCount,tool_calls:[{id:'fixture-call-'+requestCount,type:'function',function:{name,arguments:JSON.stringify({answer})}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}};
  }else response=await broker('/model',{logical:input.task.id+'/objrun/native-'+String(requestCount).padStart(3,'0'),deadline:deadline/1000,body});
  wireResponses.push(response);save('bridge-responses.json',wireResponses);
  pending--;return Response.json(response);
 }catch(e){failure=Date.now()>=deadline?'OriginalSolveDeadlineExhausted':String(e);pending=Math.max(0,pending-1);return Response.json({valid:false,outcome:'grader_error',error:{message:'FrontierInterfaceUnavailable'}},{status:503});}
}});
const base=`http://127.0.0.1:${service.port}`,id='frontierscience/'+input.task.id;
let result:any={answer:'',candidateHow:'none'};
try{
 mkdirSync(join(dir,'engine'),{recursive:true});
 engine=await machine({maxTokens:16384,reasoningEffort:'high',temperature:0,retryTimes:0,continueTimes:0},{directory:join(dir,'engine'),keep:true});
 save('engine-process.json',{pid:engine.pid,base:engine.base,runnerPid:process.pid,bridgePort:service.port,atUtc:new Date().toISOString()});
 await engine.api('POST','/declare',{handles:[{name:base+'/present',expectMs:600000},{name:base+'/equivalent',expectMs:600000}],places:[{place:'local'}],
 modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],
 agents:[{name:'bot',apis:[['DEEPSEEK_API_KEY','deepseek-flash']],unit:'fn:unit.tools'}]});
 await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
 await engine.api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='DEEPSEEK_API_KEY' and model='deepseek-flash'",params:{url:base+'/v1'}});
 const allowed:any=await engine.api('POST','/query',{sql:'select name from tool where usable=1 order by name'});save('tool-permissions.json',allowed.rows);
 await engine.api('POST','/tasks',{id,run:input.run,mode:'repair',agent:'bot',place:'local',source:'user',description:input.task.problem+'\nUse submit to hand in your final answer text. verify checks a proposed answer. Only submit, verify, task_tree and node_load are available; solve as text.',
 objective:{nodes:[{name:'present',domain:'bool',moment:'done',handle:base+'/present'},{name:'equivalent',domain:'bool',moment:'done',handle:base+'/equivalent'}],edges:[{src:'present',out:0,dst:'equivalent'}],sink:'equivalent',checks:5,reuse:'text'},
 readable:false,solveSeconds:600,maxBranches:4,maxDeadSiblings:100000,noSearch:['all'],maxSearches:0});
 let status:any;
 while(Date.now()<deadline){
  status=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/status');
  if(failure)break;
  if(['done','failed'].includes(status.state)&&status.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(status.result).outcome))break;
  await Bun.sleep(fixture?25:200);
 }
 result.engineState=status?.state;result.engineVerdict=status?.result?JSON.parse(status.result):null;
}catch(e){failure=String(e);}
finally{
 if(engine){
  // Stop at the original wall-clock boundary, then read the frozen SQLite stores.
  await engine.stop();
  const db=new Database(join(dir,'engine/data/h2h.sqlite'),{readonly:true});
  try{
   const candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const p=[...params];if(sql.includes('at <= ?'))p[p.length-1]=Math.min(Number(p[p.length-1]),deadline);return db.query(sql).all(...p);},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);
   result.answer=candidate?.how==='submitted'?candidate.body:'';result.candidateHow=candidate?.how??'none';
   for(const [file,sql] of [['trace.json','select * from agent_bot_msg order by instance,unit,seq'],['tree.json','select * from task_repair order by unit'],['native-task.json','select * from task']]){
    try{save(file,db.query(sql).all());}catch{}
   }
  }finally{db.close();}
 }
 await service.stop(true);
 result={...result,candidateSha256:hash(result.answer),nativeModelRequests:requestCount,feedbackNodeCalls:feedback.length,judgeWaitSeconds:judgeWaitMs/1000,error:failure,deadlineEpoch:deadline/1000,frozenAtUtc:new Date().toISOString()};
 save('native-result.json',result);writeFileSync(join(dir,'final-answer.txt'),result.answer);
 if(fixture){
  const second=engineRequests[1];const history=second?.messages??[];
  save('fixture-assertions.json',{submitted:result.answer==='FINAL ANSWER: 4',thinkingHistoryReturned:history.some((m:any)=>m.role==='assistant'&&m.reasoning_content==='fixture reasoning 1'),toolHistoryReturned:history.some((m:any)=>m.role==='tool'),feedbackSafe:feedback.every(x=>Object.keys(x.exposed).sort().join(',')==='note,value')});
 }
}
