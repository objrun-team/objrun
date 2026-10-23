// Independent, read-only inspection of saved native submissions. No model calls.
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {createHash} from 'node:crypto';
import {Database} from 'bun:sqlite';
import {finalCandidate} from '../../app/src/objective/candidate.ts';
const root=resolve(import.meta.dir,'../..'),he=join(root,'docs/evalplus-20261012/humaneval');
const read=(path:string)=>JSON.parse(readFileSync(path,'utf8').replace(/^\uFEFF/,''));
const combined=read(join(he,'objrun-fireworks-v1/recovery/combined-progress-checkpoint.json'));
if(!combined.allTasksValidAndNoPending||Object.values(combined.processes).some((p:any)=>p.live.length))throw Error('Final native inspection requires all 164 valid and all engines exited');
const rows:any[]=[];
for(const source of combined.provenance){
 const result=read(source.resultPath),out=resolve(dirname(source.resultPath),'../..'),short=source.officialId.replace('/','-');
 const db=new Database(join(out,'tasks/objrun',short,'engine/data/h2h.sqlite'),{readonly:true});
 try{
  const task:any=db.query('select id,state,result from task').get();
  const native=finalCandidate({all:(sql:string,params:any[]=[])=>{const q=db.prepare(sql);try{return q.all(...params)}finally{q.finalize()}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,task.id);
  const calls=db.query("select kind,instance,unit,body from agent_bot_msg where kind in ('call','result') order by unit,seq").all() as any[];
  const submissions=calls.filter(row=>row.kind==='call').flatMap(row=>{try{return (JSON.parse(row.body).calls??[]).filter((c:any)=>c.name==='submit').map((c:any)=>({instance:row.instance,unit:row.unit,answerSha256:createHash('sha256').update(typeof c.input?.answer==='string'?c.input.answer:'').digest('hex')}))}catch{return []}});
  const units=db.query('select * from task_repair').all() as any[];
  const candidateMatches=native?.how==='submitted'&&result.candidateHow==='submitted'&&native.body===result.answer;
  if(!candidateMatches&&!result.modelProtocolFailure)throw Error('NativeFinalCandidateMismatch:'+source.officialId);
  const answerSha256=createHash('sha256').update(result.answer??'').digest('hex');
  const submitUnits=units.filter(u=>u.cycle==='submit');
  const completedMatchingSubmit=submitUnits.some(u=>u.done===1&&submissions.some(s=>s.instance===u.instance&&s.unit===u.unit&&s.answerSha256===answerSha256));
  if(!completedMatchingSubmit&&!result.modelProtocolFailure)throw Error('NativeSubmitWasNotCompleted:'+source.officialId);
  rows.push({officialId:source.officialId,provider:source.provider,resultPath:source.resultPath,nativeTaskId:task.id,nativeState:task.state,nativeOutcome:task.result?JSON.parse(task.result).outcome:null,candidateHow:native?.how,candidateMatches,completedMatchingSubmit,answerSha256,submissions,submitUnits,resultMessageKinds:calls.filter(r=>r.kind==='result').length,protocolRepairCalls:result.protocolRepairCalls,grade:result.grade});
 }finally{db.close()}
}
const report={atUtc:new Date().toISOString(),fixedTasks:164,nativeCandidateMatches:rows.filter(r=>r.candidateMatches).length,nativeSubmitted:rows.filter(r=>r.candidateHow==='submitted').length,readOnly:true,coreModified:false,rows};
writeFileSync(join(he,'diagnosis/final-native-submissions.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({fixedTasks:164,nativeCandidateMatches:report.nativeCandidateMatches,nativeSubmitted:report.nativeSubmitted,firstSubmitUnits:rows[0].submitUnits,firstSubmission:rows[0].submissions,resultPath:join(he,'diagnosis/final-native-submissions.json')},null,2));
