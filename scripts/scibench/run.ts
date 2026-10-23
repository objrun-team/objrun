import {existsSync,mkdirSync,readFileSync,writeFileSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {randomBytes} from 'node:crypto';
import {cfg,ROOT,HERE,OUT,read,save,durable,walk,hash,accounting,model,observe,BudgetStop} from './common.ts';
import {native} from './native.ts';
import {sequence} from './sequence.ts';
const catalog=read(join(ROOT,'data',cfg.catalog??'public-pilot.json'));
const token=randomBytes(24).toString('hex');
let stage='starting',stopReason:string|null=null,grader:any,graderPort:number,consecutiveProviderFaults=0;
const active:any[]=[];
const suffix='\nSolve the problem. End with one finite numeric answer in the requested unit inside \\boxed{...}. For scientific notation use a\\times 10^{n}.';
const rows=()=>walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);
function status(){const results=rows();save(join(OUT,'status.json'),{stage,pid:process.pid,atUtc:new Date().toISOString(),active,stopReason,
 arms:Object.fromEntries(cfg.arms.map((arm:string)=>{const r=results.filter(x=>x.arm===arm);return [arm,{total:catalog.length,completed:r.length,valid:r.filter(x=>x.grade?.valid).length,passed:r.filter(x=>x.grade?.valid&&x.grade.passed).length,exceptions:r.filter(x=>!x.grade?.valid).length}];})),...accounting()});}
function pins(){return [...walk(HERE).filter(p=>!p.includes('/node_modules/')&&!p.includes('__pycache__')&&!p.includes('/vendor/dataset/')&&/\.(ts|py|json|lock)$/.test(p)),...walk(join(ROOT,'data')).filter(p=>p.endsWith('.json'))].map(path=>({path,sha256:hash(readFileSync(path))}));}
function frozen(){for(const p of read(join(OUT,'source-pins.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('SourceChanged:'+p.path);}
async function grade(task:any,answer:string){
 const r=await fetch(`http://127.0.0.1:${graderPort}/accept`,{method:'POST',headers:{'content-type':'application/json','x-scibench-token':token},body:JSON.stringify({input:{task:{id:task.id},result:answer}}),signal:AbortSignal.timeout(10000)});
 const g:any=await r.json();if(!r.ok||g.valid!==true||typeof g.passed!=='boolean'||g.candidateSha256!==hash(answer))throw Error('InvalidPrivateGraderResult');return g;
}
async function execute(task:any,arm:string){
 const resultPath=join(OUT,'results',arm,task.id+'.json');
 if(existsSync(resultPath)){
  const r=read(resultPath);if(r.arm!==arm||r.id!==task.id||r.promptSha256!==hash(task.prompt+suffix))throw Error('ExistingRecordIdentityMismatch');
  return;
 }
 const dir=join(OUT,'tasks',arm,task.id),calls=join(OUT,'calls',arm,task.id);mkdirSync(dir,{recursive:true});
 if(existsSync(join(dir,'started.json')))throw Error('UnfinishedTaskRequiresRecovery:'+arm+'/'+task.id);
 frozen();durable(join(dir,'started.json'),{atUtc:new Date().toISOString(),pid:process.pid});
 active.push({arm,id:task.id});status();const start=Date.now();
 let record:any={arm,id:task.id,source:task.source,startedAtUtc:new Date().toISOString(),promptSha256:hash(task.prompt+suffix),perQuestionDollarCap:cfg.perQuestionDollarCap};
 const q={...task,prompt:task.prompt+suffix};
 try{
  if(arm==='objrun'){
   record={...record,...await native(q,dir,calls,answer=>grade(q,answer))};
   record.grade=record.candidateHow==='none'?{valid:false,passed:false,outcome:'no_final_submission'}:await grade(q,record.answer);
   record.stoppingReason=record.budgetReason??(record.grade.passed?'passed':'native_terminated');
  }else{
   const deadline=start+cfg.solveSeconds*1000;
   const result=await sequence(arm,q.prompt,(messages,index)=>model(join(calls,'sample-'+index),{messages},calls,deadline),answer=>grade(q,answer),samples=>save(join(dir,'samples.json'),samples));
   record={...record,answer:result.selected.answer,grade:result.selected.grade,sampleCount:result.samples.length,selectedAttempt:result.selected.index+1,
    stoppingReason:result.selected.grade.passed?'first_correct':arm==='baseline'?'single_attempt':'five_attempt_ceiling'};
  }
 }catch(e){
  if(e instanceof BudgetStop){
   const saved=existsSync(join(dir,'samples.json'))?read(join(dir,'samples.json')):[];
   record={...record,answer:saved.at(-1)?.answer??'',grade:saved.at(-1)?.grade??await grade(q,''),sampleCount:saved.length,stoppingReason:e.message};
   if(['PilotDollarBudget','AccountOrKeyBalance'].includes(e.message))stopReason=e.message;
  }else{record={...record,error:String(e),grade:{valid:false,passed:false,outcome:'infrastructure_error'}};
   if(/SourceChanged|Unexpected|PinnedProviderFault|UnresolvedDispatch|NonJSONProviderResponse/.test(String(e))||(!cfg.continueIsolatedTransportFaults&&/IncompleteProviderResponse/.test(String(e))))stopReason=String(e);
  }
 }
 if(String(record.error??'').startsWith('Error: ProviderFault:'))consecutiveProviderFaults++;else if(record.grade?.valid)consecutiveProviderFaults=0;
 if(cfg.continueIsolatedTransportFaults&&consecutiveProviderFaults>=(cfg.maxConsecutiveProviderFaults??3))stopReason='RepeatedProviderFaults';
 record={...record,candidateSha256:hash(record.answer??''),completedAtUtc:new Date().toISOString(),seconds:(Date.now()-start)/1000,...accounting(calls)};
 writeFileSync(join(dir,'final-answer.txt'),record.answer??'');save(resultPath,record);
 active.splice(active.findIndex(x=>x.arm===arm&&x.id===task.id),1);status();
 console.log(JSON.stringify({arm,id:task.id,valid:record.grade.valid,passed:record.grade.passed,actualCostUsd:record.actualCostUsd,seconds:record.seconds,error:record.error}));return record;
}
async function main(){
 mkdirSync(OUT,{recursive:true});const lock=join(OUT,'runner-lock.json');
 if(existsSync(lock))throw Error('ExistingRunLockRequiresInspection');durable(lock,{pid:process.pid});
 let timer:any;
 try{
  if(!read(join(OUT,'controls.json')).allPassed)throw Error('ControlsNotPassed');
  const expected=cfg.taskCount??21;
  if(catalog.length!==expected||new Set(catalog.map((r:any)=>r.id)).size!==expected||catalog.some((r:any)=>Object.keys(r).sort().join(',')!=='id,prompt,source'))throw Error('CatalogScopeMismatch');
  if(cfg.formalExperimentAuthorized===true&&(expected!==416||cfg.catalog!=='public-formal.json'||cfg.perQuestionDollarCap!==null||cfg.pilotBudgetUsd!==null))throw Error('FormalScopeMismatch');
  if(cfg.recoveryFrom&&(![1,2].includes(expected)||cfg.arms.join(',')!=='objrun'||!catalog.every((r:any)=>['scibench-atkins-dev-001','scibench-atkins-dev-002'].includes(r.id))))throw Error('RecoveryScopeMismatch');
  if(!existsSync(join(OUT,'source-pins.json')))durable(join(OUT,'source-pins.json'),{files:pins(),atUtc:new Date().toISOString()});
  frozen();await observe();
  grader=Bun.spawn(['/usr/bin/python3.11',join(HERE,'stand.py'),'--home',join(ROOT,'data'),'--vendor',join(HERE,'vendor'),'--port','0'],{env:{PATH:'/usr/bin:/bin',PYTHONUTF8:'1',SCIBENCH_GRADER_TOKEN:token},stdout:'pipe',stderr:Bun.file(join(OUT,'grader.stderr.log'))});
  const reader=grader.stdout.getReader();const first=await reader.read();const info=JSON.parse(new TextDecoder().decode(first.value).trim());graderPort=info.port;reader.releaseLock();
  save(join(OUT,'grader-process.json'),{pid:grader.pid,port:graderPort});
  timer=setInterval(status,15000);stage='canary';status();
  await Promise.all(cfg.arms.map((arm:string)=>execute(catalog[0],arm)));
  const canary=rows().filter(r=>r.id===catalog[0].id);save(join(OUT,'canary.json'),canary);
  if(!cfg.recoveryFrom&&(canary.length!==cfg.arms.length||canary.some(r=>!r.grade.valid))){stage='needs_attention';stopReason=stopReason??'CanaryInvalid';return;}
  stage='running';status();
  const jobs=catalog.slice(1).flatMap((task:any,index:number)=>cfg.arms.map((_:string,j:number)=>({task,arm:cfg.arms[(index+j)%cfg.arms.length]})));let cursor=0;
  await Promise.all(Array.from({length:cfg.concurrency},async()=>{while(cursor<jobs.length&&!stopReason){const j=jobs[cursor++];await execute(j.task,j.arm);}}));
  stage=stopReason?'needs_attention':rows().length===catalog.length*cfg.arms.length?(rows().every(r=>r.grade.valid)?'complete':'complete_with_exceptions'):'incomplete';
 }catch(e){stage='needs_attention';stopReason=String(e);console.error(String(e));}
 finally{if(timer)clearInterval(timer);if(grader){grader.kill();await grader.exited;}status();if(existsSync(lock))unlinkSync(lock);}
}
await main();
