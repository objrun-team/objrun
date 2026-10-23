import {test,expect} from 'bun:test';
import {mkdtempSync,readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {save} from './common.ts';
import {runIndependent,IndependentRecoveryError} from './independent-ex-stop.ts';
function fixture(contextViolation=false){
 const d=mkdtempSync(join(tmpdir(),'bird-independent-v4-')),dir=join(d,'task'),calls=join(d,'calls'),task={officialId:'CONTROL',prompt:'public task prompt',question_id:-1};
 const samples=Array.from({length:5},(_,index)=>({index,answer:'SELECT '+index,generationId:'g'+index,grade:{valid:true,passed:index===1||index===4}}));
 for(const s of samples){const a=join(calls,'sample-'+s.index,'attempt-0');save(join(a,'request.json'),{model:'deepseek/deepseek-v4.1-flash',max_tokens:16384,temperature:0,provider:{only:['digitalocean'],allow_fallbacks:false},reasoning:{effort:'high'},messages:[{role:'user',content:task.prompt},...(contextViolation&&s.index===1?[{role:'assistant',content:'previous candidate'}]:[])]});save(join(a,'response.json'),{choices:[{message:{content:s.answer}}]});save(join(a,'receipt.json'),{httpStatus:200,fault:null,generationId:s.generationId,actualCostUsd:s.index+1,unknownCost:false});}
 save(join(dir,'samples.json'),samples);return {dir,calls,task};
}
test('rebuild keeps originals, selects earliest correct, and reports full actual costs and extras separately',async()=>{
 const f=fixture(),before=readFileSync(join(f.dir,'samples.json'),'utf8');
 const r=await runIndependent(f.task,f.dir,f.calls,{allowGeneration:false,originalResult:{grade:{valid:true}}});
 expect(r.selectedCandidateIndex).toBe(1);expect(r.executionMode).toBe('post_hoc_early_stop_reconstruction');expect(r.actualEarlyStopExecuted).toBe(false);expect(r.reusedSampleCount).toBe(5);expect(r.actualCostUsd).toBe(15);expect(r.postSuccessExtraSampleCount).toBe(3);expect(r.postSuccessExtraActualCostUsd).toBe(12);expect(r.prefixActualCostUsdForAnalysisOnly).toBe(3);expect(readFileSync(join(f.dir,'samples.json'),'utf8')).toBe(before);
 const again=await runIndependent(f.task,f.dir,f.calls,{allowGeneration:false});expect(again.reusedSampleCount).toBe(5);expect(again.actualCostUsd).toBe(15);
});
test('recovery rejects a historical context containing a previous candidate',async()=>{
 const f=fixture(true);await expect(runIndependent(f.task,f.dir,f.calls,{allowGeneration:false})).rejects.toBeInstanceOf(IndependentRecoveryError);
});
