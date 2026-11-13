import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {cfg,read,save,walk,model,grade,cost,budgetSpent,receipts,hash,extractSQL} from './common.ts';
import {IndependentRecoveryError,independentSequence} from './independent-sequence.ts';
export {IndependentRecoveryError};
export const independentProtocol='independent-fresh-context-ex-early-stop-max5-v4';
export class IndependentPrefixIncomplete extends Error {}
function validWire(w:any,task:any){return w.model===cfg.model&&w.max_tokens===16384&&w.temperature===0&&w.provider?.allow_fallbacks===false&&JSON.stringify(w.provider?.only)===JSON.stringify(['digitalocean'])&&w.reasoning?.effort==='high'&&w.messages?.length===1&&w.messages[0].role==='user'&&w.messages[0].content===task.prompt;}
function successful(r:any){return r.httpStatus===200&&(!r.fault||r.fault==='MissingOrInvalidOpenRouterUsdCost');}
export function recoverIndependent(task:any,dir:string,calls:string){
 const map=new Map<number,any>();
 function add(s:any,source:string){
  if(!Number.isInteger(s.index)||s.index<0||s.index>=5||typeof s.answer!=='string')throw new IndependentRecoveryError('InvalidSavedSample:'+source);
  const old=map.get(s.index);
  if(old&&(old.answer!==s.answer||(old.generationId&&s.generationId&&old.generationId!==s.generationId)))throw new IndependentRecoveryError('SavedCandidateConflict:'+s.index);
  if(old?.grade?.valid&&s.grade?.valid&&old.grade.passed!==s.grade.passed)throw new IndependentRecoveryError('SavedEXConflict:'+s.index);
  map.set(s.index,{...old,...s,grade:s.grade?.valid?s.grade:old?.grade??s.grade});
 }
 for(const name of ['samples-ungraded.json','samples.json','samples-ex-stop.json']){
  const p=join(dir,name);if(!existsSync(p))continue;
  const v=read(p);for(const s of Array.isArray(v)?v:v.samples??[])add(s,name);
 }
 for(let index=0;index<5;index++){
  const sd=join(calls,'sample-'+index),rr=walk(sd).filter(p=>p.endsWith('receipt.json'));
  if(walk(sd).some(p=>p.endsWith('dispatch.json')&&!existsSync(join(p.slice(0,-'dispatch.json'.length),'receipt.json'))))throw new IndependentRecoveryError('UnsettledDispatchCannotBeRepeated:'+index);
  const good=rr.filter(p=>successful(read(p)));
  if(good.length>1)throw new IndependentRecoveryError('MultipleSuccessfulRequestsForSample:'+index);
  if(good.length){
   const p=good[0],r=read(p),d=p.slice(0,-'receipt.json'.length);
   if(!existsSync(join(d,'response.json'))||!existsSync(join(d,'request.json')))throw new IndependentRecoveryError('MissingDurableSuccessfulResponse:'+index);
   const wire=read(join(d,'request.json'));
   if(!validWire(wire,task))throw new IndependentRecoveryError('IndependentContextOrProfileViolation:'+index);
   if(r.requestSha256&&hash(JSON.stringify(wire))!==r.requestSha256)throw new IndependentRecoveryError('SavedRequestHashMismatch:'+index);
   const v=read(join(d,'response.json'));if(!v.choices?.[0]?.message)throw new IndependentRecoveryError('MissingResponseMessage:'+index);
   add({index,answer:v.choices[0].message.content??'',finishReason:r.finishReason,maxTokens:16384,generationId:r.generationId,receiptPath:p,receiptAtUtc:r.atUtc},p);
  }else if(map.has(index))throw new IndependentRecoveryError('SavedSampleWithoutSuccessfulReceipt:'+index);
 }
 for(const s of map.values())if(s.grade?.valid&&s.grade.candidateSha256&&s.grade.candidateSha256!==hash(extractSQL(s.answer)))throw new IndependentRecoveryError('SavedEXCandidateHashMismatch:'+s.index);
 return [...map.values()].sort((a,b)=>a.index-b.index);
}
export async function runIndependent(task:any,dir:string,calls:string,options:{allowGeneration?:boolean,originalResult?:any,groupPaused?:()=>boolean}={}){
 const samples=recoverIndependent(task,dir,calls),statePath=join(dir,'ex-stop-state.json');
 const meta=existsSync(statePath)?read(statePath):{protocol:independentProtocol,createdAtUtc:new Date().toISOString(),legacySampleIndices:samples.map(s=>s.index),legacyCompletedResult:!!options.originalResult,legacyOriginalValid:options.originalResult?.grade?.valid??false};
 save(statePath,meta);
 const persist=(ss:any[])=>save(join(dir,'samples-ex-stop.json'),{protocol:independentProtocol,samples:ss,modelContextPolicy:'One fresh user prompt per sample; EX is scheduler-only',perQuestionDollarCap:null});
 persist(samples);
 const selected=await independentSequence(samples,{
  paused:options.groupPaused,
  save:persist,
  generate:async(index)=>{
   if(options.allowGeneration===false)throw new IndependentPrefixIncomplete('MissingSample:'+index);
   // model() reuses durable successful requests and never expands its three-attempt chain on restart.
   const x=await model(join(calls,'sample-'+index),{messages:[{role:'user',content:task.prompt}]},16384);
   return {index,answer:x.answer,finishReason:x.receipt.finishReason,maxTokens:16384,generationId:x.receipt.generationId,receiptAtUtc:x.receipt.atUtc,generatedUnderProtocol:independentProtocol,cumulativeActualCostUsd:cost(calls),cumulativeUnknownCostUpperBoundUsd:budgetSpent(calls)-cost(calls)};
  },
  grade:async(s)=>grade(task,s.answer,dir)
 });
 const chosen=selected.selected,legacyIndices=meta.legacySampleIndices as number[],newCount=samples.filter(s=>!legacyIndices.includes(s.index)).length;
 const executionMode=legacyIndices.length?(newCount?'resumed_legacy_prefix_with_online_ex_early_stop':'post_hoc_early_stop_reconstruction'):'online_ex_early_stop';
 const all=receipts(calls),extra=samples.filter(s=>selected.firstSuccessIndex!==null&&s.index>chosen.index);
 const extraReceipts=walk(calls).filter(p=>p.endsWith('receipt.json')&&selected.firstSuccessIndex!==null&&Number(p.match(/[\\/]sample-(\d+)[\\/]/)?.[1])>chosen.index).map(read);
 const actual=all.reduce((n,r)=>n+(r.actualCostUsd??0),0),extraCost=extraReceipts.reduce((n,r)=>n+(r.actualCostUsd??0),0);
 const result={answer:chosen.answer,grade:chosen.grade,sampleCount:samples.length,generatedSampleCount:samples.length,selectedCandidateIndex:chosen.index,selectedCandidateAttempt:chosen.index+1,firstSuccessIndex:selected.firstSuccessIndex,effectiveAttempts:chosen.index+1,stoppingReason:selected.stoppingReason,finalCandidatePolicy:'first_correct_else_fifth',independentProtocol,independentProtocolLabel:'Independent sampling, EX early stopping, at most 5 attempts',executionMode,reconstructionLabel:executionMode==='post_hoc_early_stop_reconstruction'?'Post-hoc reconstruction under the early-stopping rule':executionMode==='online_ex_early_stop'?'Actual sequential EX early-stopping execution':'Actual sequential EX early stopping after reusing the legacy sample prefix',actualEarlyStopExecuted:executionMode!=='post_hoc_early_stop_reconstruction'&&chosen.grade.passed&&chosen.index<4&&extra.length===0,reusedSampleCount:legacyIndices.length,newSampleCount:newCount,postSuccessExtraSampleCount:extra.length,postSuccessExtraSampleIndices:extra.map(s=>s.index),postSuccessExtraActualCostUsd:extraCost,postSuccessExtraUnknownCostCount:extraReceipts.filter(r=>r.unknownCost).length,postSuccessExtraUnknownCostUpperBoundUsd:extraReceipts.filter(r=>r.unknownCost).reduce((n,r)=>n+(r.upperBoundUsd??0),0),actualCostUsd:actual,prefixActualCostUsdForAnalysisOnly:actual-extraCost,costDisclosure:'actualCostUsd includes ALL historical and new requests, including extra samples after first success. Prefix cost is analysis only, not actual total spending.',schedulerOnlyEX:true,externalEXFeedbackToModel:false,modelContextPolicy:'Every generation uses only the unchanged task prompt in a fresh context; no previous candidates, EX, or feedback.',perQuestionDollarCap:null,truncatedSamples:samples.filter(s=>s.finishReason==='length').length,sampleLedger:samples.map(s=>({index:s.index,generationId:s.generationId,answerSha256:hash(s.answer),validEX:s.grade?.valid??false,passed:s.grade?.valid?s.grade.passed:null,receiptAtUtc:s.receiptAtUtc,origin:legacyIndices.includes(s.index)?'legacy_reused':'v4_online'}))};
 save(join(dir,'ex-stop-selection.json'),result);return result;
}
