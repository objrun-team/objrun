/** Synthetic planning controls only: no provider, cash creation or grader. */
import { strict as assert } from 'node:assert';
import { mkdirSync,writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { actualPin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { planContinuation,taskFitsPriceWindow } from './resume.ts';
const schedule=Array.from({length:87},(_,index)=>({taskId:'synthetic-'+index,arm:'F',taskSeconds:300,verifierSeconds:60,promptBodySha256:'synthetic',workdir:'/root'}));
const record=(index:number,state='done')=>({...schedule[index],runId:'synthetic-segment',state,solverClosure:{ok:true,ownedContainersRemaining:0},officialAcceptance:{valid:state==='done',passed:state==='done'},apiCalls:[{requestSeq:index}]});
const segment={runId:'synthetic-segment',records:[record(0),record(1,'failed')],requestCount:2,billedUsd:0.125,closurePin:{path:'synthetic-only',bytes:0,sha256:'synthetic'}};
const cases:string[]=[];
const planned=planContinuation(schedule,[segment]);
assert.equal(planned.pending.length,85);assert.equal(planned.records.length,2);assert.equal(planned.billedUsd,0.125);assert.equal(planned.requestCount,2);assert(!planned.pending.some(r=>r.taskId==='synthetic-1'));cases.push('retain_success_and_failure_without_repeat');
for(const [name,mutate] of [
  ['duplicate_result',(s:any)=>s.records.push({...s.records[0],apiCalls:[]})],
  ['unrecorded_charge',(s:any)=>s.requestCount=3],
  ['duplicate_request',(s:any)=>s.records[1].apiCalls[0].requestSeq=0],
  ['changed_budget',(s:any)=>s.records[0].taskSeconds++],
  ['live_solver',(s:any)=>s.records[0].solverClosure.ownedContainersRemaining=1],
  ['nonterminal_result',(s:any)=>s.records[0].state='running'],
  ['foreign_run',(s:any)=>s.records[0].runId='different'],
  ['nonfinite_cost',(s:any)=>s.billedUsd=NaN],
] as const){const altered=structuredClone(segment);mutate(altered);assert.throws(()=>planContinuation(schedule,[altered]));cases.push(name);}
assert.throws(()=>planContinuation(schedule.slice(0,86),[]));cases.push('full87_denominator_required');
const now=Date.parse('2026-10-10T12:00:00Z');
assert(taskFitsPriceWindow({taskSeconds:900,verifierSeconds:240},'2026-10-10T11:00:00Z',now).canStart);cases.push('fresh_price_allows_original_budget');
assert(!taskFitsPriceWindow({taskSeconds:900,verifierSeconds:240},'2026-10-09T12:30:00Z',now).canStart);cases.push('close_segment_before_f6_and_final_grade_exceed_price_window');
assert.throws(()=>taskFitsPriceWindow({taskSeconds:900,verifierSeconds:240},'2026-10-10T13:00:00Z',now));cases.push('future_price_evidence_rejected');
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench/resume-controls',crypto.randomUUID());mkdirSync(home,{recursive:true});
const result={protocol:'skillsbench-full-f-resume-planning-controls-v1',verified:true,scope:'synthetic planning; financial closure reader and full runtime lifecycle remain unvalidated',cases,sourcePins:['resume.ts','verify_resume.ts'].map(n=>actualPin(join(import.meta.dir,n))),modelRequests:0,costUsd:0,realGraderExecuted:false,scoreCertificate:false};
const path=join(home,'result.json');writeFileSync(path,JSON.stringify(result,null,2)+'\n');const pin=actualPin(path);writeFileSync(join(home,'../latest.json'),JSON.stringify({resultPin:pin})+'\n');console.log(JSON.stringify({resultPin:pin,verified:true,cases:cases.length,modelRequests:0}));
