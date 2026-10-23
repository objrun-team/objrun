import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {HERE,OUT,read,save,walk,receipts,extractSQL,hash} from './common.ts';
import {runIndependent,IndependentPrefixIncomplete,IndependentRecoveryError,independentProtocol} from './independent-ex-stop.ts';
const base=join(OUT,'full'),migration=join(OUT,'protocol-change-independent-ex-stop');
const correctedRoot=process.env.BIRD_CORRECTED_STAGING??join(base,'results/independent-ex-stop');
const tasks=read(join(HERE,'public-tasks.json')),report:any={atUtc:new Date().toISOString(),protocol:independentProtocol,label:'独立采样，EX早停，最多5次',reconstructionLabel:'事后按早停规则重建',completedReconstructed:0,reusedSamples:0,pendingPrefixes:[],recoveryObstacles:[],results:[]};
for(const task of tasks){
 const dir=join(base,'tasks/independent',task.officialId),calls=join(base,'calls/independent',task.officialId),original=join(base,'results/independent',task.officialId+'.json');
 if(!existsSync(dir)&&!existsSync(calls))continue;
 try{
  const old=existsSync(original)?read(original):undefined;
  const x=await runIndependent(task,dir,calls,{allowGeneration:false,originalResult:old});
  const rr=receipts(calls),unresolved=walk(calls).filter(p=>p.endsWith('unresolved-dispatch.json')).map(read);
  const r:any={...old,officialId:task.officialId,question_id:task.question_id,db_id:task.db_id,difficulty:task.difficulty,arm:'independent',promptSha256:hash(task.prompt),benchmarkVersion:'dev_20251106',mode:'full',...x,protocolVersion:independentProtocol,finalSQL:extractSQL(x.answer),completedAtUtc:old?.completedAtUtc??new Date().toISOString(),correctedAtUtc:new Date().toISOString(),originalResultPath:existsSync(original)?original:null,modelCalls:rr.length+unresolved.length,unknownCostCount:rr.filter(r=>r.unknownCost).length+unresolved.length,unknownCostUpperBoundUsd:rr.filter(r=>r.unknownCost).reduce((n,r)=>n+(r.upperBoundUsd??0),0)+unresolved.reduce((n,r)=>n+(r.upperBoundUsd??0),0),unresolvedDispatchCount:unresolved.length};
  for(const key of ['error','retryExhausted','terminalException','offlineAnySuccess','offlineAnySuccessLabel','fixedCandidatePolicy','feedbackChecks'])delete r[key];
  save(join(correctedRoot,task.officialId+'.json'),r);
  report.completedReconstructed++;report.reusedSamples+=x.reusedSampleCount;
  report.results.push({taskId:task.officialId,selectedAttempt:x.selectedCandidateAttempt,passed:x.grade.passed,executionMode:x.executionMode,reusedSamples:x.reusedSampleCount,postSuccessExtraSamples:x.postSuccessExtraSampleCount,actualCostUsd:x.actualCostUsd,postSuccessExtraActualCostUsd:x.postSuccessExtraActualCostUsd,prefixActualCostUsdForAnalysisOnly:x.prefixActualCostUsdForAnalysisOnly});
 }catch(e){
  if(e instanceof IndependentPrefixIncomplete){report.pendingPrefixes.push({taskId:task.officialId,reason:String(e)});continue;}
  report.recoveryObstacles.push({taskId:task.officialId,error:String(e)});
  save(join(base,'independent-pause.json'),{atUtc:new Date().toISOString(),taskId:task.officialId,error:String(e),policy:'Independent recovery could not be verified. Preserve all checkpoints; only this arm paused. Other arms continue.'});
 }
}
report.postSuccessExtraSamples=report.results.reduce((n:any,r:any)=>n+r.postSuccessExtraSamples,0);report.actualCostUsd=report.results.reduce((n:any,r:any)=>n+r.actualCostUsd,0);report.postSuccessExtraActualCostUsd=report.results.reduce((n:any,r:any)=>n+r.postSuccessExtraActualCostUsd,0);report.prefixActualCostUsdForAnalysisOnly=report.actualCostUsd-report.postSuccessExtraActualCostUsd;
report.costDisclosure='Actual cost includes every request. Prefix costs are retrospective analysis only; no claim of actual historical early stopping.';
save(join(migration,'migration-summary.json'),report);console.log(JSON.stringify(report));
