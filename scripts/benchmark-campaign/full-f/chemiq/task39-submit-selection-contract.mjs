// All SDK HTTP traffic is intercepted in-process. No external model/grader calls.
import fs from 'node:fs'; import path from 'node:path'; import assert from 'node:assert/strict';
import {gunzipSync} from 'node:zlib';
import {generateText,dynamicTool,jsonSchema} from '../../../../app/node_modules/ai/dist/index.js';
import {createOpenAICompatible} from '../../../../app/node_modules/@ai-sdk/openai-compatible/dist/index.js';
import {actualPin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import {submitNextTurn} from './submit-next-turn-inactive.mjs';
const root=path.resolve(import.meta.dirname,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq');
const active=JSON.parse(fs.readFileSync(path.join(base,'active-run.json'),'utf8'));
const run=active.runId, journal=path.join(active.output,'journal');
const responsePath=path.join(journal,'provider-4-response.json.gz');
const captured=JSON.parse(gunzipSync(fs.readFileSync(responsePath)).toString());
const evidenceDir=path.join(root,'docs/repair-2026-10-10/full-f-rerun/broker/repair-2026-10-11T08-45-00-530Z/stream-evidence',run+'-4');
const wirePath=path.join(evidenceDir,'capture.wire-request.json.gz');
const wire=JSON.parse(gunzipSync(fs.readFileSync(wirePath)).toString());
assert.equal(wire.tools.length,1); assert.equal(wire.tools[0].function.name,'submit');
const schema=wire.tools[0].function.parameters,tools={submit:dynamicTool({description:wire.tools[0].function.description,inputSchema:jsonSchema(schema)})};
const instructions=wire.messages.filter(m=>m.role==='system').map(m=>m.content).join('\n');
assert(instructions.includes('requires calling the submit tool exactly once'));
const rows=[];let scenario='replay',choice='auto';
const provider=createOpenAICompatible({name:'openrouter',baseURL:'http://127.0.0.1:1/v1',apiKey:'local-fixture',fetch:async(url,init)=>{
  assert.equal(new URL(url).hostname,'127.0.0.1');const request=JSON.parse(init.body);
  request.reasoning={enabled:true,effort:'high',exclude:false};request.reasoning_effort='high';
  assert.equal(request.max_tokens,16384);assert.deepEqual(request.tools[0].function.parameters,schema);
  rows.push({scenario,choice,request});
  if(scenario==='unsupported') return Response.json({error:{message:'Thinking mode does not support this tool_choice',type:'invalid_request_error'}},{status:400});
  if(scenario==='synthetic-tool') return Response.json({...captured,choices:[{index:0,finish_reason:'tool_calls',message:{role:'assistant',content:'',tool_calls:[{id:'local-control',type:'function',function:{name:'submit',arguments:JSON.stringify({answer:'LOCAL-SYNTHETIC-NOT-CAMPAIGN'})}}]}}]});
  if(scenario==='synthetic-text') return Response.json({...captured,choices:[{index:0,finish_reason:'stop',message:{role:'assistant',content:'LOCAL-SYNTHETIC-NOT-CAMPAIGN'}}]});
  return Response.json(captured);
}});
const call=messages=>generateText({model:provider('deepseek/deepseek-v4.1-flash'),messages,instructions,tools,toolChoice:choice,maxOutputTokens:16384,temperature:0,maxRetries:0});
const initial=[{role:'user',content:'Local SDK contract replay; do not grade.'}];
const first=await call(initial);assert.equal(first.finishReason,'length');assert.equal(first.text,'');assert.equal(first.toolCalls.length,0);assert(first.reasoningText.length>0);
const continuation=[...initial,{role:'assistant',content:[{type:'reasoning',text:first.reasoningText}]}];
const before=structuredClone(continuation),next=submitNextTurn(continuation,first,'submit');
assert.deepEqual(continuation,before);assert.deepEqual(next.slice(0,-1),before);assert.equal(next.at(-1).role,'user');
const replayNext=await call(next);assert.equal(replayNext.toolCalls.length,0);assert.equal(replayNext.finishReason,'length');
assert(rows[1].request.messages.some(m=>m.role==='assistant'&&m.reasoning_content===first.reasoningText));
assert.equal(rows[1].request.messages.at(-1).role,'user');
scenario='synthetic-tool';const positive=await call(next);assert.equal(positive.toolCalls.length,1);assert.equal(positive.toolCalls[0].toolName,'submit');
scenario='synthetic-text';const text=await call(next);assert.equal(text.toolCalls.length,0);
const fakeComplete={...first,finishReason:'stop'},fakeTool={...first,toolCalls:positive.toolCalls},fakeText={...first,text:'visible'};
for(const [p,m] of [[fakeComplete,'submit'],[fakeTool,'submit'],[fakeText,'submit'],[first,null]])assert.strictEqual(submitNextTurn(continuation,p,m),continuation);
scenario='unsupported';for(const toolChoice of ['required',{type:'tool',toolName:'submit'}]){choice=toolChoice;await assert.rejects(()=>call(next),/Thinking mode does not support/);}
assert.equal(rows.length,6,'400 must not trigger retry or fallback');
const report={protocol:'chemiq39-submit-selection-sdk-contract-v1',atUtc:new Date().toISOString(),passed:true,inactive:true,installed:false,modelCalls:0,graderCalls:0,ownerAcquired:false,paidOutcomeProven:false,originalPaidRun:run,
  conclusions:{rawReplayNoToolPreserved:true,newUserTurnPreservesReasoning:true,newUserTurnReplayStillFails:true,syntheticToolMapsCorrectly:true,textNeverSubmit:true,mock400NoRetryFallback:true,upstreamRequiredSupportProven:false},
  sourcePins:[import.meta.filename,path.join(import.meta.dirname,'submit-next-turn-inactive.mjs'),responsePath,wirePath,path.join(root,'app/src/llm/index.ts'),path.join(root,'app/node_modules/ai/dist/index.js'),path.join(root,'app/node_modules/@ai-sdk/openai-compatible/dist/index.js')].map(actualPin),rows};
fs.writeFileSync(path.join(base,'task39-submit-selection-contract.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({passed:true,tests:10,modelCalls:0,rawReplayStillFails:true,paidOutcomeProven:false,inactive:true}));
