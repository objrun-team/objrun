/** Captured real-response differential controls, zero model/grader/owner/Docker actions. */
import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import {gunzipSync} from 'node:zlib';
import {reasoningDetailBank} from './task39-reasoning-details-staged.mjs';import {actualPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const root=path.resolve(import.meta.dirname,'../../../..'),out=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq'),broker=path.join(root,'docs/repair-2026-10-10/full-f-rerun/broker/repair-2026-10-11T05-06-00-577Z/stream-evidence');
const tests=[];
for(const [slug,run]of [['relace','repair-2026-10-11T05-06-00-577Z-12-2026-10-11T05-07-04-653Z'],['dekallm','repair-2026-10-11T05-06-00-577Z-12-2026-10-11T05-28-25-388Z']]){
 const bank=reasoningDetailBank();
 for(let seq=0;seq<4;seq++){
  const dir=path.join(broker,run+'-'+seq),request=JSON.parse(gunzipSync(fs.readFileSync(path.join(dir,'capture.original-request.json.gz'))).toString()),before=structuredClone(request),projected=bank.project(request);
  assert.deepEqual(request,before,'original captured request mutated');
  const restored=structuredClone(projected.request);
  for(const binding of projected.bindings){const m=restored.messages[binding.messageIndex];m.reasoning_content=m.reasoning_details.map(d=>d.text).join('');delete m.reasoning_details;}
  assert.deepEqual(restored,before,'nonreasoning message or inference/tool parameter changed');
  assert.equal(projected.bindings.length,seq===0?0:1);
  if(seq){assert(request.messages.at(-1).reasoning_content&&!request.messages.at(-1).reasoning_details);assert(projected.request.messages.at(-1).reasoning_details.length===seq);}
  bank.record(actualPin(path.join(dir,'capture.aggregate.json')));
  tests.push({slug,seq,passed:true,legacyMissingCanonicalDetails:seq>0,bindings:projected.bindings,originalPin:actualPin(path.join(dir,'capture.original-request.json.gz'))});
 }
 assert.throws(()=>bank.project({messages:[{role:'assistant',reasoning_content:'unproven synthetic thought'}]}));
 assert.throws(()=>bank.record(actualPin(path.join(broker,run+'-0/capture.aggregate.json'))));
 tests.push({slug,rejectUnprovenThought:true,rejectRepeatedGeneration:true,passed:true});
}
const report={atUtc:new Date().toISOString(),passed:true,tests:tests.length,modelCalls:0,graderCalls:0,ownerAcquired:false,dockerActions:0,paidOutcomeProven:false,candidateInactive:true,sourcePin:actualPin(path.join(import.meta.dirname,'task39-reasoning-details-staged.mjs')),results:tests};fs.writeFileSync(path.join(out,'task39-reasoning-details-control.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:true,tests:tests.length,modelCalls:0,paidOutcomeProven:false}));
