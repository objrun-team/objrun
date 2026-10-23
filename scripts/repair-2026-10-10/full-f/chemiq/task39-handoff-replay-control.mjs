// One-variable captured-request projection controls; zero external calls.
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {gunzipSync} from 'node:zlib';import {Database} from 'bun:sqlite';
import {projectContinuationHandoff} from './task39-continuation-handoff-staged.mjs';import {actualPin,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const root=path.resolve(import.meta.dirname,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq'),read=p=>JSON.parse(fs.readFileSync(p,'utf8')),diag=read(path.join(base,'task39-reasoning-diagnosis.json')),broker=path.dirname(read(path.join(base,'status.json')).brokerHealthPath),results=[];
let representative;const exclusions=[];
for(const row of diag.rows){const db=new Database(path.join(base,'runs',row.run,'task-39/engine/data/h2h.sqlite'),{readonly:true}),task=db.query('select created_at from task').get();db.close();
 for(let seq=1;seq<row.requests.length;seq++){
  const dir=path.join(broker,'stream-evidence',row.run+'-'+seq),previous=path.join(broker,'stream-evidence',row.run+'-'+(seq-1),'capture.aggregate.json');if(!fs.existsSync(previous))continue;
  const ev=read(path.join(dir,'capture.evidence.json'));verifyPin(ev.originalRequest);const request=JSON.parse(gunzipSync(fs.readFileSync(ev.originalRequest.path)).toString()),context={previousAggregatePin:actualPin(previous),createdAtMs:task.created_at,nowMs:Date.parse(ev.atUtc)};
  let projected;try{projected=projectContinuationHandoff(request,context);}catch(e){if(row.supplier==='wafer'&&seq===2&&String(e).includes('previous actual reasoning must already be preserved')){exclusions.push({supplier:row.supplier,seq,rejected:true,reason:'Immediate previous durable response was not carried by original SDK; not safe for this prompt-only candidate',previousAggregatePin:context.previousAggregatePin,originalRequestPin:ev.originalRequest});continue;}throw new Error(`${row.supplier} seq${seq}: ${e}`);}results.push({supplier:row.supplier,seq,passed:true,evidence:projected.evidence});representative={request,context};
 }
}
assert.equal(results.length,17);assert.equal(exclusions.length,1);const {request,context}=representative,negative=[];
for(const [name,edit,ctx] of [['expired deadline',r=>r,{...context,nowMs:context.createdAtMs+900000}],['changed token cap',r=>({...r,max_tokens:32768}),context],['lowered effort',r=>({...r,reasoning:{...r.reasoning,effort:'low'}}),context],['missing real reasoning',r=>({...r,messages:r.messages.filter(m=>m.role!=='assistant')}),context],['missing submit tool',r=>({...r,tools:r.tools.filter(t=>t.function.name!=='submit')}),context]]){
 assert.throws(()=>projectContinuationHandoff(edit(structuredClone(request)),ctx));negative.push({name,rejected:true});
}
const proof={atUtc:new Date().toISOString(),passed:true,modelCalls:0,ownerAcquired:false,projectionControls:results,negativeControls:negative,exclusions,paidOutcomeProven:false,sourcePins:[actualPin(import.meta.filename),actualPin(path.join(root,'scripts/repair-2026-10-10/full-f/chemiq/task39-continuation-handoff-staged.mjs'))]};
fs.writeFileSync(path.join(base,'task39-handoff-replay-control.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify({projectionControls:results.length,negativeControls:negative.length,passed:true,modelCalls:0}));
