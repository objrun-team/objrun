import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {Database} from 'bun:sqlite';
import {finalCandidate} from '../../../app/src/objective/candidate.ts';

const spec=JSON.parse(readFileSync(process.argv[2],'utf8'));
const root=resolve(import.meta.dir,'../../..'), dir=spec.directory;
mkdirSync(join(dir,'engine'),{recursive:true});
const save=(name:string,x:any)=>writeFileSync(join(dir,name),JSON.stringify(x,null,2)+'\n');
let ready=false, failure:string|null=null, n=0, deadline=Date.now()+630000;
const transcript:any[]=[], feedback:any[]=[];
async function broker(path:string,body:any){
 const r=await fetch(spec.broker+path,{method:'POST',headers:{'content-type':'application/json','x-token':process.env.CLIMAQA_BROKER_TOKEN!},body:JSON.stringify(body),signal:AbortSignal.timeout(Math.max(1,deadline-Date.now()))});
 const data:any=await r.json(); if(!r.ok)throw Error(data.error??'BrokerError');return data;
}
const service=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:0,async fetch(req){
 try{
  const path=new URL(req.url).pathname,body:any=await req.json();
  if(path==='/parsed'||path==='/correct'){
   const raw=body.input?.result??body.input?.task?.result??'';const answer=String(typeof raw==='object'?raw?.body??'':raw);
   const g=await broker('/grade',{id:spec.task.id,arm:'objrun',candidate:answer,mode:path.slice(1)});
   const result={value:path==='/parsed'?g.parsed:g.passed,note:''};
   feedback.push({node:path,candidate:answer,exposed:result});save('feedback.json',feedback);return Response.json(result);
  }
  if(path!=='/v1/chat/completions')return Response.json({error:'not found'},{status:404});
  while(!ready&&Date.now()<deadline)await Bun.sleep(20);
  const allowed=['verify','submit','task_tree','node_load'];
  if((body.tools??[]).some((x:any)=>!allowed.includes(x.function?.name)))throw Error('UnexpectedTool');
  n++;transcript.push(body);save('engine-requests.json',transcript);
  const response=await broker('/model',{id:spec.task.id,arm:'objrun',index:n,body,deadline:deadline/1000});
  return Response.json(response);
 }catch(e){failure=String(e);return Response.json({error:{message:'LocalBrokerError'}},{status:503});}
}});
const base=`http://127.0.0.1:${service.port}`;
const probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')});const port=probe.port;await probe.stop(true);
const engineDir=join(dir,'engine');
writeFileSync(join(engineDir,'config.yaml'),`server: { host: 127.0.0.1, port: ${port}, bodyLimit: 1048576, shutdownTimeout: 2000 }\nlog: { level: warn }\ndb: { file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite, pragmas: { journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000 } }\napi: { prefix: /api, token: , allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100 }\nllm: { maxTokens: 16384, retryTimes: 0, continueTimes: 0, reasoningEffort: high, temperature: 0, seed: 42 }\ncors: { enabled: false, origin: "*" }\n`);
const child=spawn(process.execPath,[join(root,'app/src/main.ts')],{cwd:engineDir,env:{...process.env,TGENGIN_CONFIG:join(engineDir,'config.yaml'),DEEPSEEK_API_KEY:'local-broker-placeholder'},stdio:['ignore','pipe','pipe'],windowsHide:true});
let logs='';child.stdout?.on('data',x=>logs+=x);child.stderr?.on('data',x=>logs+=x);
const api=async(method:string,path:string,body?:any)=>{const r=await fetch(`http://127.0.0.1:${port}/api`+path,{method,headers:{'content-type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const x:any=await r.json();if(!r.ok)throw Error(method+' '+path+' '+JSON.stringify(x));return x;};
const id='climaqa/'+spec.task.id;let state:any=null,result:any={answer:'',candidateHow:'none'};
try{
 let healthy=false;for(let i=0;i<150;i++){try{await api('GET','/health');healthy=true;break;}catch{if(child.exitCode!==null)break;await Bun.sleep(100);}}
 if(!healthy)throw Error('EngineStartupFailed: '+logs.slice(-1000));
 await api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'DEEPSEEK_API_KEY','deepseek-flash',handle,modes,:url,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{url:base+'/v1'}});
 await api('POST','/declare',{handles:['parsed','correct'].map(p=>({name:base+'/'+p,expectMs:600000})),places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['DEEPSEEK_API_KEY','deepseek-flash']],unit:'fn:unit.tools'}]});
 await api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
 await api('POST','/exec',{sql:"update api set base_url=:url,retry_on='[]' where key_env='DEEPSEEK_API_KEY' and model='deepseek-flash'",params:{url:base+'/v1'}});
 save('tools.json',(await api('POST','/query',{sql:'select name from tool where usable=1 order by name'})).rows);
 await api('POST','/tasks',{id,run:'climaqa-pilot-20261028-v1',mode:'repair',agent:'bot',place:'local',source:'user',description:spec.task.prompt+'\nUse submit to hand in your final answer text. verify checks a proposed answer. Only submit, verify, task_tree and node_load are available.',objective:{nodes:[{name:'parsed',domain:'bool',moment:'done',handle:base+'/parsed'},{name:'correct',domain:'bool',moment:'done',handle:base+'/correct'}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:1,reuse:'text'},readable:false,solveSeconds:600,maxBranches:4,maxDeadSiblings:0,noSearch:['all'],maxSearches:0});
 const task=(await api('POST','/query',{sql:'select created_at,solve_seconds from task where id=:id',params:{id}})).rows[0];deadline=Number(task.created_at)+Number(task.solve_seconds)*1000;ready=true;
 while(Date.now()<deadline){state=await api('GET','/tasks/'+encodeURIComponent(id)+'/status');if(failure)break;if(['done','failed'].includes(state.state)&&state.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(state.result).outcome))break;await Bun.sleep(200);}
 result.engineState=state?.state;result.engineVerdict=state?.result?JSON.parse(state.result):null;
}catch(e){failure=String(e);}
finally{
 if(child.exitCode===null){child.kill();await new Promise<void>(r=>{child.once('exit',()=>r());setTimeout(r,4000);});}
 writeFileSync(join(dir,'engine.log'),logs);
 try{const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});try{
  const c=finalCandidate({all:(sql:string,params:any[]=[])=>{const p=[...params];if(sql.includes('at <= ?'))p[p.length-1]=Math.min(Number(p[p.length-1]),deadline);return db.query(sql).all(...p);},run(){throw Error('readonly');},exec(){throw Error('readonly');},close(){}} as any,id);
  result.answer=c?.how==='submitted'?c.body:'';result.candidateHow=c?.how??'none';
  for(const [name,sql] of [['trace.json','select * from agent_bot_msg order by instance,unit,seq'],['tree.json','select * from task_repair order by unit'],['task.json','select * from task']])try{save(name,db.query(sql).all());}catch{}
 }finally{db.close();}}catch(e){failure=failure??String(e);}
 await service.stop(true);save('native-result.json',{...result,error:failure,modelRequests:n,deadlineEpoch:deadline/1000});
}
