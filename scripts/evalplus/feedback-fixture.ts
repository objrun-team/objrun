import {mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {machine} from '../../test/_lib.ts';
const root=resolve(import.meta.dir,'../..'),out=join(root,'docs/evalplus-20261012/feedback-fixture-'+Date.now());mkdirSync(out,{recursive:true});
let calls=0,checks=0;const inputs:any[]=[];
const server=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(req){const body:any=await req.json();inputs.push(body);
 if(new URL(req.url).pathname==='/parsed')return Response.json(true);
 if(new URL(req.url).pathname==='/correct'){checks++;const q=body.input;const said=typeof q.result==='object'?q.result.body:q.result??q.task.result??'';return Response.json({value:String(said).includes('return a + b'),note:'Public addition test failed'});}
 calls++;const forced=body.tool_choice&&body.tool_choice!=='auto';const name=calls===1&&!forced?'verify':'submit';const answer=name==='verify'?'def add(a, b):\n    return a':'def add(a, b):\n    return a + b';
 return Response.json({id:'synthetic-'+calls,object:'chat.completion',created:1,model:body.model,choices:[{index:0,message:{role:'assistant',content:null,tool_calls:[{id:'call-'+calls,type:'function',function:{name,arguments:JSON.stringify({answer})}}]},finish_reason:'tool_calls'}],usage:{prompt_tokens:0,completion_tokens:0,total_tokens:0}});
}});
const m=await machine({maxTokens:2048,retryTimes:0,reasoningEffort:'none'},{directory:out,keep:true});
try{
const handle=`http://127.0.0.1:${server.port}/correct`,parsed=`http://127.0.0.1:${server.port}/parsed`;await m.api('POST','/declare',{handles:[{name:handle,expectMs:10000},{name:parsed,expectMs:10000}],places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:4,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:4,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY','deepseek/deepseek-v4.1-flash']],unit:'fn:unit.tools'}]});
await m.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('verify','submit')"});
await m.api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model='deepseek/deepseek-v4.1-flash'",params:{url:`http://127.0.0.1:${server.port}/v1`}});
await m.api('POST','/tasks',{id:'synthetic/add',run:'synthetic-fixture',mode:'repair',agent:'bot',place:'local',source:'user',description:'Write def add(a,b) returning a+b. Use public test feedback to repair a wrong candidate, then submit.',objective:{nodes:[{name:'parsed',domain:'bool',moment:'done',handle:parsed},{name:'correct',domain:'bool',moment:'done',handle}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'},readable:false,solveSeconds:60,maxBranches:4,maxDeadSiblings:10,noSearch:['all']});
let task:any;for(let i=0;i<100;i++){task=await m.api('GET','/tasks/synthetic%2Fadd/status');if(task.result&&['done','failed'].includes(task.state))break;await Bun.sleep(200);}
const trace=await m.api<any>('POST','/query',{sql:'select * from agent_bot_msg order by unit,seq'});
const summary={modelCalls:0,syntheticReplies:calls,checks,passed:task.state==='done'&&JSON.parse(task.result??'{}').pass===1,feedbackAndRevisionObserved:inputs.some(q=>JSON.stringify(q.messages??[]).includes('Public addition test failed')),dockerForbidden:true,benchmarkScores:false,task};
writeFileSync(join(out,'trace.json'),JSON.stringify(trace.rows,null,2));writeFileSync(join(out,'summary.json'),JSON.stringify(summary,null,2));writeFileSync(join(root,'docs/evalplus-20261012/feedback-fixture-latest.json'),JSON.stringify({output:out,...summary},null,2));console.log(JSON.stringify(summary));if(!summary.passed||!summary.feedbackAndRevisionObserved)process.exitCode=1;
}finally{await m.stop();await server.stop(true);}
