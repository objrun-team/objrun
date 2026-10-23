// New attempt scheduling only; __EXECUTE_ONE__ is copied byte-for-byte from the formal runner.
import {existsSync,mkdirSync,readFileSync,writeFileSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {randomBytes} from 'node:crypto';
import {Database} from 'bun:sqlite';
import {cfg,ROOT,HERE,OUT,read,save,durable,walk,hash,accounting,model,observe,BudgetStop} from './common.ts';
import {native} from './native.ts';
import {sequence} from './sequence.ts';
const catalog=read(join(ROOT,'data',cfg.catalog)),plan=read(join(HERE,'repair-plan.json'));
const token=randomBytes(24).toString('hex');
let stage='starting',stopReason:string|null=null,grader:any,graderPort:number,consecutiveProviderFaults=0;
const active:any[]=[];
const suffix='\nSolve the problem. End with one finite numeric answer in the requested unit inside \\boxed{...}. For scientific notation use a\\times 10^{n}.';
const rows=()=>walk(join(OUT,'results')).filter(p=>p.endsWith('.json')).map(read);
const registry=new Database(plan.registryPath,{readwrite:true,create:false});registry.exec('PRAGMA busy_timeout=10000');
const drainPath=join(ROOT,'control/drain.json');
function schedulerDrain(reason:string){stopReason=stopReason??reason;}
process.on('SIGTERM',()=>schedulerDrain('OperatorDrain:SIGTERM'));
process.on('SIGINT',()=>schedulerDrain('OperatorDrain:SIGINT'));
function status(){const results=rows();save(join(OUT,'status.json'),{stage,pid:process.pid,atUtc:new Date().toISOString(),active,stopReason,attemptCount:plan.attempts.length,
 arms:Object.fromEntries(cfg.arms.map((arm:string)=>{const r=results.filter(x=>x.arm===arm);return [arm,{total:plan.attempts.filter((x:any)=>x.arm===arm).length,completed:r.length,valid:r.filter(x=>x.grade?.valid).length,passed:r.filter(x=>x.grade?.valid&&x.grade.passed).length,exceptions:r.filter(x=>!x.grade?.valid).length}];})),...accounting()});}
function pins(){return [...walk(HERE).filter(p=>!p.includes('/node_modules/')&&!p.includes('__pycache__')&&!p.includes('/vendor/dataset/')&&/\.(ts|py|json|lock)$/.test(p)),...walk(join(ROOT,'data')).filter(p=>p.endsWith('.json'))].map(path=>({path,sha256:hash(readFileSync(path))}));}
function frozen(){for(const p of read(join(OUT,'source-pins.json')).files)if(hash(readFileSync(p.path))!==p.sha256)throw Error('SourceChanged:'+p.path);}
async function grade(task:any,answer:string){
 const r=await fetch(`http://127.0.0.1:${graderPort}/accept`,{method:'POST',headers:{'content-type':'application/json','x-scibench-token':token},body:JSON.stringify({input:{task:{id:task.id},result:answer}}),signal:AbortSignal.timeout(10000)});
 const g:any=await r.json();if(!r.ok||g.valid!==true||typeof g.passed!=='boolean'||g.candidateSha256!==hash(answer))throw Error('InvalidPrivateGraderResult');return g;
}
__EXECUTE_ONE__
async function execute(attempt:any){
 const task=catalog.find((x:any)=>x.id===attempt.id),arm=attempt.arm;
 if(!task||hash(task.prompt+suffix)!==attempt.originalPromptSha256)throw Error('AttemptPromptMismatch');
 const rp=join(OUT,'results',arm,task.id+'.json');
 if(existsSync(rp))throw Error('ExistingAttemptNeverRegenerate:'+attempt.attemptId);
 const claimed=registry.query("UPDATE attempts SET state='started',ownerPid=?,claimedAtUtc=? WHERE attemptId=? AND state='pending'").run(process.pid,new Date().toISOString(),attempt.attemptId);
 if(claimed.changes!==1)throw Error('AttemptAlreadyClaimed:'+attempt.attemptId);
 durable(join(OUT,'tasks',arm,task.id,'attempt.json'),attempt);
 const result=await executeOne(task,arm);
 if(!existsSync(rp)||!result)throw Error('MissingAttemptTerminalRecord');
 const linked={...result,attemptId:attempt.attemptId,attemptNo:1,originalExperiment:plan.originalExperiment,originalResultSha256:attempt.originalResultSha256};save(rp,linked);
 const done=registry.query("UPDATE attempts SET state='complete',resultSha256=?,completedAtUtc=? WHERE attemptId=? AND state='started' AND ownerPid=?").run(hash(readFileSync(rp)),linked.completedAtUtc,attempt.attemptId,process.pid);
 if(done.changes!==1)throw Error('AttemptCompletionConflict');
}
async function main(){
 mkdirSync(OUT,{recursive:true});const lock=join(OUT,'runner-lock.json');
 if(existsSync(lock))throw Error('ExistingRunLockRequiresInspection');durable(lock,{pid:process.pid});let timer:any;
 try{
  if(!read(join(OUT,'controls.json')).allPassed)throw Error('ControlsNotPassed');
  if(cfg.concurrency!==32||plan.maxNewFullAttemptsPerIdentity!==1||new Set(plan.attempts.map((x:any)=>x.attemptId)).size!==plan.attempts.length)throw Error('RepairScopeMismatch');
  if(!existsSync(join(OUT,'source-pins.json')))durable(join(OUT,'source-pins.json'),{files:pins(),atUtc:new Date().toISOString()});frozen();
  await observe();
  grader=Bun.spawn(['/usr/bin/python3.11',join(HERE,'stand.py'),'--home',join(ROOT,'data'),'--vendor',join(HERE,'vendor'),'--port','0'],{env:{PATH:'/usr/bin:/bin',PYTHONUTF8:'1',SCIBENCH_GRADER_TOKEN:token},stdout:'pipe',stderr:Bun.file(join(OUT,'grader.stderr.log'))});
  const reader=grader.stdout.getReader();const first=await reader.read();graderPort=JSON.parse(new TextDecoder().decode(first.value).trim()).port;reader.releaseLock();save(join(OUT,'grader-process.json'),{pid:grader.pid,port:graderPort});
  stage='running';timer=setInterval(status,15000);status();let cursor=0;
  await Promise.all(Array.from({length:32},async()=>{while(cursor<plan.attempts.length&&!stopReason){
   if(existsSync(drainPath)){schedulerDrain('OperatorDrain:control-file');break;}
   const attempt=plan.attempts[cursor++];try{await execute(attempt);}catch(e){schedulerDrain(String(e));console.error(String(e));status();}
  }}));
  stage=stopReason?'needs_attention':rows().length===plan.attempts.length?(rows().every(r=>r.grade.valid)?'complete':'complete_with_exceptions'):'incomplete';
 }catch(e){stage='needs_attention';stopReason=String(e);console.error(String(e));}
 finally{if(timer)clearInterval(timer);if(grader){grader.kill();await grader.exited;}status();registry.close();if(existsSync(lock))unlinkSync(lock);}
}
await main();
