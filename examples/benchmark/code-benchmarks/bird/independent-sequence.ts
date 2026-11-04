export class IndependentRecoveryError extends Error {}
export async function independentSequence(samples:any[], io:{generate:(index:number)=>Promise<any>,grade:(sample:any)=>Promise<any>,save:(samples:any[])=>void,paused?:()=>boolean}) {
 const indexes=samples.map(s=>s.index);
 if(indexes.some(i=>!Number.isInteger(i)||i<0||i>=5)||new Set(indexes).size!==indexes.length)throw new IndependentRecoveryError('InvalidOrDuplicateSampleIndex');
 for(let index=0;index<5;index++){
  if(io.paused?.())throw new IndependentRecoveryError('IndependentGroupPaused');
  let s=samples.find(s=>s.index===index);
  if(!s){s=await io.generate(index);if(s.index!==index)throw new IndependentRecoveryError('GeneratedSampleIndexMismatch');samples.push(s);samples.sort((a,b)=>a.index-b.index);io.save(samples);}
  if(!s.grade?.valid){s.grade=await io.grade(s);io.save(samples);}
  if(!s.grade?.valid)throw new IndependentRecoveryError('IndependentEXEnvironment:'+JSON.stringify(s.grade));
  if(s.grade.passed)return {selected:s,firstSuccessIndex:index,stoppingReason:'first_correct'};
 }
 return {selected:samples.find(s=>s.index===4),firstSuccessIndex:null,stoppingReason:'five_incorrect'};
}
