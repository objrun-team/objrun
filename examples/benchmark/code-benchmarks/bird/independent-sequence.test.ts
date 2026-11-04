import {test,expect} from 'bun:test';
import {independentSequence,IndependentRecoveryError} from './independent-sequence.ts';
test('fresh samples are generated then scored one by one and stop on the first correct',async()=>{
 const events:string[]=[],samples:any[]=[];
 const r=await independentSequence(samples,{generate:async i=>{events.push('generate'+i);return {index:i,answer:'candidate'+i};},grade:async s=>{events.push('grade'+s.index);return {valid:true,passed:s.index===1};},save:()=>{}});
 expect(events).toEqual(['generate0','grade0','generate1','grade1']);expect(r.selected.index).toBe(1);expect(samples.length).toBe(2);
});
test('all five historical samples are retained, earliest valid success selected, no generation or grading',async()=>{
 const samples=Array.from({length:5},(_,index)=>({index,answer:'q'+index,grade:{valid:true,passed:index===1||index===4}}));
 const r=await independentSequence(samples,{generate:async()=>{throw Error('must not regenerate')},grade:async()=>{throw Error('must reuse valid EX')},save:()=>{}});
 expect(r.selected.index).toBe(1);expect(samples.length).toBe(5);
});
test('resume grades a saved ungraded candidate before any missing generation; all-wrong selects fifth',async()=>{
 const samples:any[]=[{index:0,answer:'old',grade:{valid:true,passed:false}},{index:1,answer:'ungraded'}],events:string[]=[];
 const r=await independentSequence(samples,{generate:async i=>{events.push('generate'+i);return {index:i,answer:'new'+i}},grade:async s=>{events.push('grade'+s.index);return {valid:true,passed:false}},save:()=>{}});
 expect(events).toEqual(['grade1','generate2','grade2','generate3','grade3','generate4','grade4']);expect(r.selected.index).toBe(4);expect(r.firstSuccessIndex).toBeNull();
});
test('environment failure and duplicate indices stop the independent sequence without advancing',async()=>{
 let generated=0;
 await expect(independentSequence([{index:0,answer:'saved'}],{generate:async()=>{generated++;return {}},grade:async()=>({valid:false,errorType:'GraderEnvironment'}),save:()=>{}})).rejects.toBeInstanceOf(IndependentRecoveryError);
 await expect(independentSequence([{index:0},{index:0}],{generate:async()=>({}),grade:async()=>({}),save:()=>{}})).rejects.toBeInstanceOf(IndependentRecoveryError);expect(generated).toBe(0);
});
