import {mkdirSync,readFileSync,existsSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {Database} from 'bun:sqlite';
import {machine,type Machine} from './engine/test/_lib.ts';
import {finalCandidate} from './engine/app/src/objective/candidate.ts';
const q=JSON.parse(await Bun.stdin.text()),ROOT=join(import.meta.dir,'..'),dir=q.directory;
mkdirSync(dir,{recursive:true});mkdirSync(join(dir,'engine'),{recursive:true});const save=(name:string,v:any)=>writeFileSync(join(dir,name),JSON.stringify(v,null,2)+'\n');
process.env.LLM_SRBENCH_BINARY=q.arm==='binary'?'1':'0';
process.env.OPENROUTER_API_KEY='local-proxy-no-provider-credential';
let engine:Machine|undefined,pending=0,stopReason='',fixtureCalls=0;
const deadline=Date.now()+(q.fixture?45:600)*1000;
const history:any[]=[],wireRequests:any[]=[];
const station=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:0,async fetch(req){
 const b:any=await req.json();
 if(new URL(req.url).pathname==='/parsed')return Response.json(true);
 if(new URL(req.url).pathname==='/correct'){
  try{
   const a=b.input?.result??b.input?.task?.result??'',answer=typeof a==='object'?a.body??'':a;
   let v:any;
   if(q.fixture){const passed=String(answer)==='GOOD';v={value:passed,...(q.arm==='objrun'&&!passed?{note:'{"nmse":999,"errorType":"SyntheticCanaryError"}'}:{})};}
   else{
    const r=await fetch(q.gateway+'/feedback',{method:'POST',body:JSON.stringify({key:q.task.key,arm:q.arm,answer:String(answer)}),signal:AbortSignal.timeout(1000)});
    const job:any=await r.json();if(!r.ok)throw Error(job.error);
    while(true){
     const r=await fetch(q.gateway+'/feedback/'+job.job,{signal:AbortSignal.timeout(5000)});const d:any=await r.json();
     if(d.state==='done'){v=d.projected;break;}if(d.state==='fault')throw Error(d.error);
     await Bun.sleep(200);
    }
   }
   history.push({answer,exposed:v});save('feedback-visible.json',history);return Response.json(v);
  }catch(e){stopReason=String(e);return Response.json({valid:false,error:'FeedbackUnavailable'},{status:503});}
 }
 pending++;
 try{
  wireRequests.push(b);
  if(q.fixture){
   fixtureCalls++;const name=fixtureCalls===1?'verify':'submit',answer=fixtureCalls===1?'BAD':'GOOD';
   return Response.json({id:'fixture-'+fixtureCalls,object:'chat.completion',created:1,model:q.model,provider:'DigitalOcean',choices:[{index:0,message:{role:'assistant',content:null,tool_calls:[{id:'call-'+fixtureCalls,type:'function',function:{name,arguments:JSON.stringify({answer})}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0,cost:0}});
  }
  const r=await fetch(q.gateway+'/model',{method:'POST',body:JSON.stringify({body:b,remainingSeconds:Math.max(1,(deadline-Date.now())/1000)}),signal:AbortSignal.timeout(Math.max(1000,deadline-Date.now()+5000))});
  const text=await r.text();if(!r.ok){stopReason=text;return new Response(text,{status:502});}
  return new Response(text,{headers:{'content-type':'application/json'}});
 }catch(e){stopReason=String(e);return Response.json({error:{message:'ModelGatewayStopped'}},{status:502});}finally{pending--;}
}});
let result:any={};
try{
 engine=await machine({maxTokens:16384,reasoningEffort:'high',temperature:0,retryTimes:0,continueTimes:3},{directory:join(dir,'engine'),keep:true});
 save('engine-process.json',{pid:engine.pid,base:engine.base,ownerPid:process.pid});
 const handle=`http://127.0.0.1:${station.port}/correct`,parsed=`http://127.0.0.1:${station.port}/parsed`,id='llm-srbench-240/'+q.task.key;
 await engine.api('POST','/declare',{handles:[{name:handle,expectMs:120000},{name:parsed,expectMs:1000}],places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',q.model]],unit:'fn:unit.tools'}]});
 await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
 await engine.api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model",params:{url:`http://127.0.0.1:${station.port}/v1`,model:q.model}});
 await engine.api('POST','/tasks',{id,run:'llm-srbench-release240-v2',mode:'repair',agent:'bot',place:'local',source:'user',description:q.task.prompt+'\nUse verify to assess a complete JSON candidate and submit to hand in your final complete JSON candidate in the answer string. Maximum five training candidate checks, 600 seconds, and $0.10 including all model calls. Feedback never uses ID or OOD tests. Submit your best candidate before the budget expires. No filesystem or search tools are available.',objective:{nodes:[{name:'parsed',domain:'bool',moment:'done',handle:parsed},{name:'correct',domain:'bool',moment:'done',handle}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'},readable:false,solveSeconds:q.fixture?40:600,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
 let status:any;
 while(Date.now()<deadline+5000){
  status=await engine.api('GET','/tasks/'+encodeURIComponent(id)+'/status');
  if(stopReason&&pending===0)break;
  if(['done','failed'].includes(status.state)&&status.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(status.result).outcome))break;
  await Bun.sleep(200);
 }
 for(const [name,sql] of [['trace','select * from agent_bot_msg order by instance,unit,seq'],['tree','select * from task_repair order by unit'],['task','select * from task where id=:id']]){
  const r:any=await engine.api('POST','/query',{sql,params:name==='task'?{id}:{}});save(name+'.json',r.rows);
 }
 const db=new Database(join(dir,'engine/data/h2h.sqlite'),{readonly:true});
 try{
  const c=finalCandidate({all:(sql:string,params:any[]=[])=>{const s=db.prepare(sql);try{return s.all(...params);}finally{s.finalize();}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,id);
  result={answer:c?.body??'',candidateHow:c?.how??'none',state:status?.state,stopReason,feedbackCount:history.length,fixtureCalls};
 }finally{db.close();}
 if(q.fixture){
  save('fixture-wire-requests.json',wireRequests);
  const raw=JSON.stringify(wireRequests);
  result.feedbackDetailReachedModel=raw.includes('SyntheticCanaryError');
  result.fixturePassed=result.answer==='GOOD'&&(q.arm==='binary'?!result.feedbackDetailReachedModel:result.feedbackDetailReachedModel);
 }
}catch(e){result={...result,error:String(e),stopReason};}
finally{if(engine)await engine.stop();await station.stop(true);save('native-result.json',result);}
console.log(JSON.stringify(result));
