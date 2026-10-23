import {existsSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {cfg,ROOT,OUT,save,read,hash,model,observe,accounting,walk,requestConcurrency} from './common.ts';
import {bridge,toolSpecs,submission,protocol} from './tools.ts';
import {native} from './native.ts';

const catalog=read(join(ROOT,'data/catalog.json'));
const selected=(cfg.taskIds??[]).map((id:string)=>catalog.find((t:any)=>t.id===id)).filter(Boolean);
const prompt=(unit:any)=>readFileSync(join(ROOT,'data',unit.instruction),'utf8');
let stage='starting';const active:any[]=[];
function status(){const rows=walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);save(join(OUT,'status.json'),{stage,pid:process.pid,atUtc:new Date().toISOString(),active,taskConcurrencyCap:cfg.concurrency,modelConcurrency:requestConcurrency(),parents:selected.length,units:selected.reduce((s:number,t:any)=>s+t.units.length,0),arms:Object.fromEntries(cfg.arms.map((a:string)=>{const r=rows.filter(x=>x.arm===a);return[a,{completed:r.length,valid:r.filter(x=>x.valid).length,passedUnits:r.reduce((s:number,x:any)=>s+x.units.filter((g:any)=>g.grade?.valid&&g.grade?.passed).length,0),exceptions:r.filter(x=>!x.valid).length}];})),...accounting()});}

async function episode(unit:any,session:string,messages:any[],dir:string,calls:string){
 mkdirSync(dir,{recursive:true});let candidate='';const deadline=Date.now()+600000;
 messages.push({role:'user',content:prompt(unit)+protocol});
 for(let i=0;i<cfg.toolTurns&&Date.now()<deadline;i++){
  let response:any;
  try{response=await model(join(calls,'turn-'+String(i).padStart(3,'0')),{messages,tools:[...toolSpecs,submission].map(t=>({type:'function',function:t})),tool_choice:'auto'},calls,deadline);}
  catch(e){if(Date.now()>=deadline){save(join(dir,'budget-stop.json'),{reason:'SolveTimeBudget'});break;}throw e;}
  const body=JSON.parse(response.raw),message=body.choices?.[0]?.message;
  if(!message)throw Error('MissingModelMessage');messages.push(message);
  save(join(dir,'messages.json'),messages);
  const callsNow=message.tool_calls??[];
  if(!callsNow.length){candidate=(await bridge('snapshot',{session})).candidate;break;}
  for(const call of callsNow){
   const name=call.function?.name;let args:any,result:any;
   try{args=JSON.parse(call.function?.arguments??'{}');}catch{args={};}
   if(name==='compute')result=Date.now()>=deadline?{stdout:'',stderr:'Stage solve time limit reached.',exitCode:124}:await bridge('compute',{session,command:String(args.command??''),timeout:Math.min(args.timeout??60,Math.max(1,Math.floor((deadline-Date.now())/1000)))});
   else if(name==='snapshot')result=await bridge('snapshot',{session});
   else if(name==='submit'){candidate=String(args.answer??'');result={submitted:true,candidate};}
   else result={error:'UnknownTool'};
   messages.push({role:'tool',tool_call_id:call.id,content:JSON.stringify(result)});
  }
  save(join(dir,'messages.json'),messages);if(candidate)break;
 }
 if(!candidate)candidate=(await bridge('snapshot',{session})).candidate;
 return candidate;
}

async function runTask(task:any,arm:string){
 const resultPath=join(OUT,'results',arm,task.id+'.json');if(existsSync(resultPath))return;
 const dir=join(OUT,'tasks',arm,task.id);mkdirSync(dir,{recursive:true});
 if(existsSync(join(dir,'started.json')))throw Error('UnfinishedTaskRequiresExplicitRecovery:'+arm+'/'+task.id);
 save(join(dir,'started.json'),{atUtc:new Date().toISOString(),pid:process.pid});active.push({arm,task:task.id});status();
 let session='',units:any[]=[],rounds:any[]=[],messages:any[]=[];const start=Date.now();
 try{
  const maximum=arm==='baseline'||arm==='objrun'?1:5;
  for(let round=0;round<maximum;round++){
   if(!session)session=(await bridge('create',{task:task.id,arm})).session;
   units=[];
   for(const unit of task.units){
    await bridge('stage',{session,unit:unit.id});const stageDir=join(dir,'round-'+round,unit.id),calls=join(OUT,'calls',arm,task.id,'round-'+round,unit.id);
    let nativeRecord:any;
    const candidate=arm==='objrun'?(nativeRecord=await native(task,{...unit,prompt:prompt(unit)},session,stageDir,calls)).candidate:await episode(unit,session,messages,stageDir,calls);
    units.push({id:unit.id,session,candidate,...(nativeRecord?{native:nativeRecord}:{})});
   }
   // No whole-task correctness or success-based control is available before all stages finish.
   for(const unit of units){unit.grade=await bridge('grade',{session,candidate:unit.candidate,unit:unit.id});if(!unit.grade.valid)throw Error('InvalidPrivateGrade');}
   const passed=units.every(u=>u.grade.passed);rounds.push({round,session,units,passed});save(join(dir,'rounds.json'),rounds);
   if(passed||round+1===maximum)break;
   if(arm==='independent'){await bridge('dispose',{session});session='';messages=[];}
   if(arm==='binary')messages.push({role:'user',content:passed?'passed':'failed'});
  }
  save(resultPath,{arm,id:task.id,valid:true,units,passed:units.every(u=>u.grade.passed),rounds:rounds.length,seconds:(Date.now()-start)/1000,...accounting(join(OUT,'calls',arm,task.id))});
 }catch(e){save(resultPath,{arm,id:task.id,valid:false,units,rounds:rounds.length,errorType:String(e),seconds:(Date.now()-start)/1000,...accounting(join(OUT,'calls',arm,task.id))});}
 finally{if(session)try{await bridge('dispose',{session});}catch{}active.splice(active.findIndex(x=>x.arm===arm&&x.task===task.id),1);status();}
}

async function main(){
 mkdirSync(OUT,{recursive:true});
 if(cfg.formalExperimentAuthorized){const acceptance=read(join(ROOT,'control/pilot-acceptance.json'));const remote=read(join(ROOT,'control/remote-acceptance.json'));if(!acceptance.passed||!remote.passed||selected.length!==46||process.platform!=='linux'||process.env.TPE_REMOTE_DOCKER!=='1'||cfg.executionHost!=='novaeve')throw Error('FormalReadinessGateNotSatisfied');}
 if(!selected.length||selected.some((t:any)=>t.id==='autonomous-de'))throw Error('ScopeMismatch');
 const lock=join(OUT,'controller.lock');if(existsSync(lock))throw Error('ExistingControllerLock');writeFileSync(lock,JSON.stringify({pid:process.pid}),{flag:'wx'});
 save(join(OUT,'frozen-config.json'),cfg);save(join(OUT,'source-pins.json'),{files:walk(join(ROOT,'package')).filter(p=>!p.includes('/engine/')&&!p.includes('__pycache__')).map(p=>({path:p,sha256:hash(readFileSync(p))}))});
 await observe();stage='running';status();const timer=setInterval(status,10000);
 try{
  const jobs=selected.flatMap((t:any)=>cfg.arms.map((a:string)=>({task:t,arm:a})));let index=0;
  if(cfg.concurrency>32||cfg.modelConcurrency>32)throw Error('ConcurrencyAuthorizationExceeded');
  await Promise.all(Array.from({length:cfg.concurrency},async()=>{while(index<jobs.length){const job=jobs[index++],lease=job.arm+'/'+job.task.id;
   if(cfg.executionHost==='novaeve'){while(!(await bridge('admit',{lease})).admitted)await Bun.sleep(2000);}
   try{await runTask(job.task,job.arm);}finally{if(cfg.executionHost==='novaeve')await bridge('release',{lease});}
  }}));
  const records=walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);stage=records.every(r=>r.valid)?'complete':'complete_with_exceptions';
 }finally{clearInterval(timer);status();}
}
await main().catch(e=>{stage='needs_attention';save(join(OUT,'controller-error.json'),{error:String(e)});status();console.error(String(e));process.exitCode=1;});
