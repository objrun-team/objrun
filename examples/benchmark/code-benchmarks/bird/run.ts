import {existsSync,mkdirSync,readFileSync,writeFileSync,unlinkSync,renameSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {HERE,ROOT,OUT,cfg,read,save,walk,hash,model,grade,cost,budgetSpent,receipts,balance,BudgetStop,binaryFeedback,extractSQL} from './common.ts';
import {native} from './native.ts';
import {runIndependent,IndependentRecoveryError,independentProtocol} from './independent-ex-stop.ts';
const mode=process.argv[2]??'full';if(!['canary','full','status'].includes(mode))throw Error('run.ts canary|full|status');
const base=join(OUT,mode==='status'?'full':mode),arms=['baseline','objrun','independent','binary'];mkdirSync(base,{recursive:true});
// Latest user instruction: a real pool of 32 task workers, without per-task dollar caps.
const concurrency=mode==='canary'?1:cfg.initialConcurrency;
if(mode==='full'&&concurrency!==32)throw Error('AuthorizedConcurrencyMustBe32');
const all=read(join(HERE,'public-tasks.json')),tasks=mode==='canary'?all.filter((t:any)=>t.question_id===1):all;
if(all.length!==1534||new Set(all.map((t:any)=>t.question_id)).size!==1534)throw Error('TaskCatalogIntegrity');
if(all.some((t:any)=>t.SQL!==undefined||t.gold!==undefined||!t.prompt))throw Error('GoldInPublicCatalog');
const resultFolder=(arm:string)=>arm==='independent'&&mode!=='canary'?'independent-ex-stop':arm;
const resultPath=(arm:string,t:any)=>join(base,'results',resultFolder(arm),t.officialId+'.json');
const independentPause=join(base,'independent-pause.json');
const taskDir=(arm:string,t:any)=>join(base,'tasks',arm,t.officialId);
const callDir=(arm:string,t:any)=>join(base,'calls',arm,t.officialId);
function records(){return arms.flatMap(arm=>walk(join(base,'results',resultFolder(arm))).filter(p=>p.endsWith('.json')).map(read));}
function unresolved(p:string){return walk(p).filter(p=>p.endsWith('unresolved-dispatch.json')).map(read);}
if(mode==='status'){console.log(JSON.stringify({...read(join(base,'status.json')),verifiedRecords:records().length}));process.exit(0);}
const lock=join(base,'runner-lock.json');
if(existsSync(lock)){const prior=read(lock);let live=false;try{process.kill(prior.pid,0);live=true;}catch{}if(live)throw Error('RunnerAlreadyLive:'+prior.pid);renameSync(lock,lock+'.closed-'+Date.now());}
save(lock,{pid:process.pid,startedAtUtc:new Date().toISOString(),entry:process.argv});
const start=Date.now(),active:any[]=[];let stopReason:string|undefined,stage='starting';
const sourceFiles=[...walk(HERE).filter(p=>/\.(ts|py|json)$/.test(p)),...walk(join(HERE,'../runtime-snapshot/app/src')).filter(p=>p.endsWith('.ts')),join(HERE,'../runtime-snapshot/test/_lib.ts')].sort();
const pins=sourceFiles.map(p=>({path:resolve(p),sha256:hash(readFileSync(p))})),pinFile=join(base,'source-pins.json');
if(existsSync(pinFile)){const old=read(pinFile);if(JSON.stringify(old.files)!==JSON.stringify(pins))throw Error('FrozenSourceChanged');}else save(pinFile,{atUtc:new Date().toISOString(),files:pins});
const safe=(n:number)=>Math.round(n*1e9)/1e9;
function status(){
 const rr=records(),own=active.flatMap(a=>receipts(callDir(a.arm,a.task))),held=active.flatMap(a=>unresolved(callDir(a.arm,a.task)));
 const state={benchmark:'bird',dataset:'dev_20251106',total:tasks.length,mode,pid:process.pid,entry:join(HERE,'run.ts'),stage,atUtc:new Date().toISOString(),startedAtUtc:new Date(start).toISOString(),concurrency,model:cfg.model,provider:cfg.provider,reasoning:'high',active:active.map(({task,...a})=>({...a,taskId:task.officialId})),arms:Object.fromEntries(arms.map(arm=>{const a=rr.filter(r=>r.arm===arm),valid=a.filter(r=>r.grade?.valid);return [arm,{completed:a.length,total:tasks.length,valid:valid.length,passed:valid.filter(r=>r.grade.passed).length,exceptions:a.filter(r=>!r.grade?.valid).length,noCandidate:a.filter(r=>r.sampleCount===0||r.candidateHow==='none').length,actualCostUsd:safe(a.reduce((n,r)=>n+(r.actualCostUsd??0),0))}];})),modelCalls:rr.reduce((n,r)=>n+(r.modelCalls??0),0)+own.length,actualCostUsd:safe(rr.reduce((n,r)=>n+(r.actualCostUsd??0),0)+own.reduce((n,r)=>n+(r.actualCostUsd??0),0)),unknownCostCount:rr.reduce((n,r)=>n+(r.unknownCostCount??0),0)+own.filter(r=>r.unknownCost).length,stopReason,protocol:'Independent fresh samples use scheduler-only EX early stopping; ObjRun and binary retain oracle feedback.',remoteMirror:join(OUT,'mirror-status.json')};
 Object.assign(state,{protocolVersion:cfg.protocolVersion,perQuestionDollarCap:null,independentSamples:cfg.independentSamples,binaryMaxChecks:cfg.binaryMaxChecks,actualActiveWorkers:active.length,workerPoolSize:concurrency});
 state.protocol='Independent sampling, EX early stop, at most five fresh-context attempts; choose first correct else fifth. EX is scheduler-only. Historical samples are explicitly reconstructed with every actual cost retained. Other arms unchanged; no per-question dollar ceiling.';
 Object.assign(state,{independentProtocol,independentPaused:existsSync(independentPause),independentResultDirectory:join(base,'results','independent-ex-stop')});
 state.unknownCostCount+=held.length;
 Object.assign(state,{unresolvedDispatchCount:rr.reduce((n,r)=>n+(r.unresolvedDispatchCount??0),0)+held.length,unknownCostUpperBoundUsd:rr.reduce((n,r)=>n+(r.unknownCostUpperBoundUsd??0),0)+own.filter(r=>r.unknownCost).reduce((n,r)=>n+(r.upperBoundUsd??0),0)+held.reduce((n,r)=>n+(r.upperBoundUsd??0),0)});
 save(join(base,'status.json'),state);save(join(OUT,'status.json'),{...state,requestedTasksPerArm:1534,...(mode==='canary'?{stage:'canary_'+stage}:{})});
}
function stopped(){if(existsSync(join(base,'stop-after-current-tasks.json'))){stopReason='StopFile';return true;}return !!stopReason;}
function pinCheck(){for(const p of pins)if(hash(readFileSync(p.path))!==p.sha256)throw Error('FrozenSourceChanged:'+p.path);}
async function candidate(task:any,arm:string,index:number,messages:any[]){
 const d=join(callDir(arm,task),'sample-'+index),body={messages};
 return model(d,body,cfg.maxTokens);
}
async function execute(task:any,arm:string){
 if(arm==='independent'&&mode==='full'&&existsSync(independentPause))return;
 const path=resultPath(arm,task),dir=taskDir(arm,task);mkdirSync(dir,{recursive:true});
 if(existsSync(path)){
  const old=read(path);if(old.grade?.valid||old.terminalException)return;
  // Regrade durable candidates without another model request.
  if(old.answer!==undefined&&!old.error){const g=await grade(task,old.answer,dir);save(path,{...old,grade:g,regradedAtUtc:new Date().toISOString()});return;}
  // Exhausted API retries stay visible; restarting cannot silently extend retry chains.
  if(old.retryExhausted)return;
 }
 const began=Date.now();active.push({arm,task,startedAtUtc:new Date().toISOString()});status();
 let r:any={officialId:task.officialId,question_id:task.question_id,db_id:task.db_id,difficulty:task.difficulty,arm,promptSha256:hash(task.prompt),benchmarkVersion:'dev_20251106',mode,protocolVersion:cfg.protocolVersion,perQuestionDollarCap:null};
 try{
  if(arm==='baseline'){
   const x=await candidate(task,arm,0,[{role:'user',content:task.prompt}]);r={...r,answer:x.answer,finishReason:x.receipt.finishReason,sampleCount:1,grade:await grade(task,x.answer,dir)};
  }else if(arm==='objrun'){
   const x=await native(task,dir,join(callDir(arm,task),'protocol-v3'));save(join(dir,'candidate.json'),x);r={...r,...x,grade:x.modelProtocolFailure||x.candidateHow!=='submitted'?{valid:true,passed:false,errorType:'ModelSubmissionProtocolFailure'}:await grade(task,x.answer,dir)};
  }else if(arm==='independent'&&mode==='full'){
   const original=join(base,'results','independent',task.officialId+'.json');
   const x=await runIndependent(task,dir,callDir(arm,task),{originalResult:existsSync(original)?read(original):undefined,groupPaused:()=>existsSync(independentPause)});
   r={...r,...x,protocolVersion:independentProtocol};
  }else{
   const nativeFile=resultPath('objrun',task),source=existsSync(nativeFile)?read(nativeFile):{};
   r.analysisReferenceObjrunCostUsd=source.unknownCostCount?null:source.actualCostUsd??null;r.objrunGradeValid=source.grade?.valid;
   const checks=cfg.binaryMaxChecks;r.feedbackCheckCeiling=arm==='binary'?checks:0;
   const samplesFile=join(dir,'samples-ungraded.json'),saved=existsSync(samplesFile)?read(samplesFile):{samples:[]};
   const samples:any[]=saved.samples,messages:any[]=[{role:'user',content:task.prompt}];
   if(arm==='binary')for(const s of samples){messages.push({role:'assistant',content:s.answer},{role:'user',content:binaryFeedback(s.grade)});}
   let reason='fixed_count';
   // Canary is an integration check, excluded from benchmark scores and bounded to two samples.
   const sampleLimit=mode==='canary'?2:arm==='independent'?cfg.independentSamples:cfg.binaryMaxChecks;
   for(let index=samples.length;index<sampleLimit;index++){
    if(arm==='binary'&&(samples.at(-1)?.grade?.passed||samples.length>=Math.max(1,checks))){reason=samples.at(-1)?.grade?.passed?'passed':'check_ceiling';break;}
    const x=await candidate(task,arm,index,messages);
    const s:any={index,answer:x.answer,finishReason:x.receipt.finishReason,maxTokens:cfg.maxTokens,generationId:x.receipt.generationId,cumulativeActualCostUsd:cost(callDir(arm,task)),cumulativeUnknownCostUpperBoundUsd:budgetSpent(callDir(arm,task))-cost(callDir(arm,task))};
    if(arm==='binary'){
     s.grade=await grade(task,s.answer,dir);if(!s.grade.valid)throw Error('BinaryFeedbackEnvironment:'+s.grade.errorType);
     if(checks>0){s.feedback=binaryFeedback(s.grade);messages.push({role:'assistant',content:s.answer},{role:'user',content:s.feedback});}
    }
    samples.push(s);save(samplesFile,{samples,perQuestionDollarCap:null,spentUsd:cost(callDir(arm,task)),generationComplete:false,protocolVersion:cfg.protocolVersion});
   }
   if(mode==='canary'&&samples.length===sampleLimit)reason='canary_sample_ceiling';
   // This durable barrier precedes the first independent score request, including after resume.
   save(samplesFile,{samples,perQuestionDollarCap:null,spentUsd:cost(callDir(arm,task)),generationComplete:true,stoppingReason:reason,protocolVersion:cfg.protocolVersion});
   if(arm==='independent')for(const s of samples){s.grade=await grade(task,s.answer,dir);save(join(dir,'samples.json'),samples);}
   save(join(dir,'samples.json'),samples);
   const last=samples.at(-1);r={...r,sampleCount:samples.length,answer:last?.answer??'',fixedCandidatePolicy:'last_generated_sample',grade:last?.grade??{valid:false,passed:false,errorType:'NoGeneratedSample'},offlineAnySuccess:arm==='independent'?samples.some(s=>s.grade.valid&&s.grade.passed):undefined,offlineAnySuccessLabel:arm==='independent'?'Offline any-success over five fresh samples; not single-pass pass@1':undefined,spentUsd:cost(callDir(arm,task)),reservedUnknownCostUsd:budgetSpent(callDir(arm,task))-cost(callDir(arm,task)),stoppingReason:reason,truncatedSamples:samples.filter(s=>s.finishReason==='length').length,feedbackChecks:arm==='binary'?samples.length:0,protocol:arm==='independent'?'Five fresh-context samples, all generated before any EX scoring. Final score uses last sample. No task dollar cap or budget-driven output reduction.':'History of own SQL retained; external feedback content is exactly passed or failed. Stop after first pass or five checks. No task dollar cap or budget-driven output reduction.'};
  }
 }catch(e){
  r.error=String(e);r.grade={valid:false,passed:false,errorType:'GenerationOrEnvironmentException'};
  r.retryExhausted=/ProviderFault|UnresolvedDispatch/.test(r.error);
  if(e instanceof BudgetStop)stopReason=String(e);
  if(arm==='independent'&&e instanceof IndependentRecoveryError){save(independentPause,{atUtc:new Date().toISOString(),taskId:task.officialId,error:String(e),checkpointDirectory:dir,policy:'Only independent sampling is paused. Other three arms continue; no valid sample regenerated.'});r.independentRecoveryPaused=true;}
 }
 const rr=receipts(callDir(arm,task)),held=unresolved(callDir(arm,task));r={...r,finalSQL:extractSQL(r.answer??''),completedAtUtc:new Date().toISOString(),seconds:(Date.now()-began)/1000,modelCalls:rr.length+held.length,actualCostUsd:safe(rr.reduce((n,a)=>n+(a.actualCostUsd??0),0)),unresolvedDispatchCount:held.length,unknownCostCount:rr.filter(a=>a.unknownCost).length+held.length,unknownCostUpperBoundUsd:rr.filter(a=>a.unknownCost).reduce((n,a)=>n+(a.upperBoundUsd??0),0)+held.reduce((n,a)=>n+(a.upperBoundUsd??0),0)};
 const migration=join(dir,'administrative-checkpoint.json');if(existsSync(migration)){r.administrativeCheckpoint=read(migration);r.administrativeAbortedAttemptCostUsd=r.administrativeCheckpoint.administrativeAbortedAttemptCostUsd;r.validAttemptCostUsd=Math.max(0,r.actualCostUsd-r.administrativeAbortedAttemptCostUsd);}
 save(path,r);active.splice(active.findIndex(a=>a.arm===arm&&a.task.officialId===task.officialId),1);status();
 console.log(JSON.stringify({atUtc:r.completedAtUtc,task:task.officialId,arm,valid:r.grade.valid,passed:r.grade.passed,cost:r.actualCostUsd,sampleCount:r.sampleCount,error:r.error}));
}
async function main(){
 const daemon:any=await (await fetch(cfg.dockerEndpoint+'/info',{signal:AbortSignal.timeout(10000)})).json();
 if(daemon.ID!=='dc87b6a7-ed03-4ccf-8d26-89709287b80a'||daemon.DockerRootDir!==cfg.dockerRoot)throw Error('UnexpectedDockerDaemon');
 save(join(base,'daemon-observation.json'),{atUtc:new Date().toISOString(),id:daemon.ID,dockerRootDir:daemon.DockerRootDir});
 if(!read(join(OUT,'controls/summary.json')).allPassed)throw Error('ControlsNotPassed');
 if(mode==='full'){
  const canary=read(join(OUT,'canary/status.json'));if(canary.stage!=='complete'||Object.values(canary.arms).some((x:any)=>x.valid!==1)||arms.some(arm=>read(join(OUT,'canary/results',arm,'BIRD_1.json')).modelCalls<1)||read(join(OUT,'canary/results/objrun/BIRD_1.json')).candidateHow!=='submitted')throw Error('CanaryNotPassed');
 }
 await balance(true);pinCheck();stage='running';status();
 const timer=setInterval(()=>status(),30000);
 let cursor=0;
 try{await Promise.all(Array.from({length:concurrency},async()=>{
  while(cursor<tasks.length&&!stopped()){
   const task=tasks[cursor++];await balance(true);pinCheck();
   for(const arm of arms){if(stopped())break;await execute(task,arm);}
  }
 }));}finally{clearInterval(timer);stage=stopReason?'needs_attention':existsSync(independentPause)?'independent_paused':records().length!==tasks.length*arms.length?'incomplete':records().some(r=>!r.grade?.valid)?'complete_with_exceptions':'complete';status();unlinkSync(lock);}
}
main().catch(e=>{stopReason=String(e);stage='needs_attention';status();console.error(String(e));if(existsSync(lock))unlinkSync(lock);process.exitCode=1;});
