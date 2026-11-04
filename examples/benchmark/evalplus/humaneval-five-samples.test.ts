import {expect,test} from 'bun:test';
import {sampleUpToFive} from './humaneval-five-samples.ts';
test('stops after the first officially valid correct solution',async()=>{
 const indices:number[]=[],saved:any[][]=[];
 const samples=await sampleUpToFive({prior:[],generate:async index=>{indices.push(index);return{answer:String(index)}},grade:async answer=>({valid:true,passed:answer==='1'}),persist:rows=>saved.push([...rows])});
 expect(indices).toEqual([0,1]);expect(samples.length).toBe(2);expect(saved.length).toBe(2);
});
test('five incorrect solutions receive five independent generation calls',async()=>{
 const indices:number[]=[];
 const samples=await sampleUpToFive({prior:[],generate:async index=>{indices.push(index);return{answer:'same public prompt, fresh call'}},grade:async()=>({valid:true,passed:false}),persist:()=>{}});
 expect(indices).toEqual([0,1,2,3,4]);expect(samples.length).toBe(5);
});
test('invalid grading never triggers early stopping',async()=>{
 let calls=0;
 const samples=await sampleUpToFive({prior:[],generate:async()=>{calls++;return{answer:'candidate'}},grade:async()=>({valid:false,passed:true}),persist:()=>{}});
 expect(calls).toBe(5);expect(samples.length).toBe(5);
});
test('resume skips saved successful samples and continues incomplete attempts without re-generation',async()=>{
 let calls=0;
 const prior=[{index:0,answer:'wrong',grade:{valid:true,passed:false}}];
 const samples=await sampleUpToFive({prior,generate:async index=>{calls++;return{answer:String(index)}},grade:async()=>({valid:true,passed:true}),persist:()=>{}});
 expect(calls).toBe(1);expect(samples[1].index).toBe(1);
 await sampleUpToFive({prior:samples,generate:async()=>{throw Error('must not call')},grade:async()=>{throw Error('must not grade')},persist:()=>{}});
});
test('one failed interface attempt does not stop later attempts or another task',async()=>{
 let calls=0;
 const samples=await sampleUpToFive({prior:[],generate:async index=>{calls++;if(index===0)throw Error('socket closed');return{answer:'ok'}},grade:async()=>({valid:true,passed:true}),persist:()=>{}});
 expect(calls).toBe(2);expect(samples[0].grade.valid).toBe(false);expect(samples[1].grade.passed).toBe(true);
});
