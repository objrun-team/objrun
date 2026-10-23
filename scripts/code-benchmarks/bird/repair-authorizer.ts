import {existsSync,mkdirSync,readFileSync,writeFileSync,copyFileSync,renameSync} from 'node:fs';
import {join,resolve,dirname,sep} from 'node:path';
import {HERE,OUT,read,save,walk,hash,grade,extractSQL,cost} from './common.ts';
const full=join(OUT,'full'),diag=join(OUT,'diagnosis-authorizer'),archive=join(diag,'records-before');
const tasks=read(join(HERE,'public-tasks.json')),byId=new Map(tasks.map((t:any)=>[t.officialId,t]));
const changes:any[]=[],warnings:any[]=[],nativeRestarts:any[]=[];
function preserve(p:string){const rel=p.slice(full.length+1),dest=join(archive,rel);mkdirSync(dirname(dest),{recursive:true});if(!existsSync(dest))copyFileSync(p,dest);}
async function corrected(task:any,answer:string,dir:string){
 const g=await grade(task,answer,join(diag,'regrade',task.officialId));
 if(!g.valid)throw Error('AuthorizerRegradeStillInvalid:'+task.officialId+':'+g.errorType);
 const cache=join(dir,'grades',hash(JSON.stringify([task.question_id,extractSQL(answer),null]))+'.json');
 if(existsSync(cache))preserve(cache);save(cache,g);return g;
}
if(!read(join(diag,'controls-after.json')).allPassed)throw Error('RepairControlsFailed');
const resultFiles=walk(join(full,'results')).filter(p=>p.endsWith('.json'));
for(const p of resultFiles){
 const r=read(p),task:any=byId.get(r.officialId),dir=join(full,'tasks',r.arm,r.officialId);
 let changed=false;
 if(r.arm==='independent'&&existsSync(join(dir,'samples.json'))){
  const samplesPath=join(dir,'samples.json'),samples=read(samplesPath);let sampleChanges=0;
  for(const sample of samples)if(sample.grade?.message==='not authorized'){
   sample.gradeBeforeAuthorizerRepair=sample.grade;sample.grade=await corrected(task,sample.answer,dir);sampleChanges++;
  }
  if(sampleChanges){preserve(samplesPath);save(samplesPath,samples);preserve(p);r.gradeBeforeAuthorizerRepair=r.grade;r.grade=samples.at(-1).grade;r.offlineAnySuccess=samples.some((s:any)=>s.grade?.valid&&s.grade?.passed);r.authorizerRegradedSamples=sampleChanges;changed=true;}
 }else if(r.grade?.message==='not authorized'&&r.answer!==undefined){
  preserve(p);r.gradeBeforeAuthorizerRepair=r.grade;r.grade=await corrected(task,r.answer,dir);changed=true;
 }
 if(changed){r.authorizerRepairedAtUtc=new Date().toISOString();r.newModelCallsForGradeRepair=0;save(p,r);changes.push({arm:r.arm,task:r.officialId,before:r.gradeBeforeAuthorizerRepair,after:r.grade});}
}
// Keep actual exposed feedback immutable; save an explicit reassessment instead.
for(const p of walk(join(full,'tasks/objrun')).filter(p=>p.endsWith(sep+'feedback.json'))){
 const dir=dirname(p),id=dir.split(sep).at(-1)!,task:any=byId.get(id),feedback=read(p);
 const affected=feedback.map((x:any,i:number)=>({x,i})).filter(({x}:any)=>x.verdict?.message==='not authorized');
 if(!affected.length)continue;
 const answers=new Map<string,string>();
 if(existsSync(join(dir,'trace.json')))for(const row of read(join(dir,'trace.json'))){
  if(row.kind!=='call')continue;try{for(const call of JSON.parse(row.body).calls??[])if(typeof call.input?.answer==='string')answers.set(hash(call.input.answer),call.input.answer);}catch{}
 }
 const reassessment:any[]=[];
 for(const {x,i} of affected){const answer=answers.get(x.candidateSha256);if(answer===undefined)throw Error('FeedbackCandidateMissing:'+id);const g=await corrected(task,answer,dir);reassessment.push({index:i,originalExposed:x.exposed,originalGrade:x.verdict,correctedGrade:g,correctnessChanged:x.verdict.passed!==g.passed,actualOriginalFeedbackRetained:true});}
 save(join(dir,'feedback-authorizer-reassessment.json'),{atUtc:new Date().toISOString(),reassessment,newModelCalls:0});
 const rp=join(full,'results/objrun',id+'.json');if(existsSync(rp)){preserve(rp);const result=read(rp);result.feedbackIntegrityWarnings={type:'HistoricalReadAuthorizationFalsePositive',count:reassessment.length,correctnessChanged:reassessment.some(x=>x.correctnessChanged),reassessmentPath:join(dir,'feedback-authorizer-reassessment.json'),validFinalCandidateNotRegenerated:true};save(rp,result);}
 warnings.push({task:id,reassessment});
}
// Only incomplete native attempts rejected by the environment are restarted.
for(const p of resultFiles){
 const r=read(p);if(r.arm!=='objrun'||r.grade?.valid||!/FeedbackEnvironment:GoldOrDatabaseError/.test(r.error??''))continue;
 const dir=join(full,'tasks/objrun',r.officialId),marker=join(dir,'authorizer-recovery.json');
 if(existsSync(marker))continue;
 preserve(p);const oldEngine=join(dir,'engine'),retained=join(dir,'engine.before-authorizer-repair');
 const intended=resolve(full,'tasks/objrun')+sep;
 if(!resolve(oldEngine).startsWith(intended)||!resolve(retained).startsWith(intended)||dirname(resolve(oldEngine))!==dirname(resolve(retained)))throw Error('UnsafeEngineArchivePath');
 if(existsSync(oldEngine))renameSync(oldEngine,retained);
 for(const name of ['engine-process.json','addresses.json','feedback.json','trace.json','tree.json','candidate.json']){const old=join(dir,name);if(existsSync(old))renameSync(old,old+'.before-authorizer-repair');}
 const checkpoint={atUtc:new Date().toISOString(),reason:'Incomplete native attempt stopped by COUNT(*) authorization environment error; valid completed tasks are preserved',administrativeAbortedAttemptCostUsd:cost(join(full,'calls/objrun',r.officialId)),completedModelCalls:r.modelCalls,checkpoint:retained,boundedRecoveryAttempt:1,rawCallsReplayedOnlyForIdenticalRequests:true};
 save(marker,checkpoint);save(join(dir,'administrative-checkpoint.json'),checkpoint);nativeRestarts.push(r.officialId);
}
save(join(diag,'repair-summary.json'),{atUtc:new Date().toISOString(),finalCandidateGradeChanges:changes,historicalFeedbackWarnings:warnings,incompleteNativeAttemptsPreparedForOneRecovery:nativeRestarts,newModelCallsForRegrading:0});
console.log(JSON.stringify({regradedResults:changes.length,feedbackWarnings:warnings.length,incompleteNativeRecoveries:nativeRestarts}));
