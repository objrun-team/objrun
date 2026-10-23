/** Native localhost fetch controls only. Never invokes paid captureChemiqStream. */
import { strict as assert } from 'node:assert';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { captureChemiqSSE, makeChemiqStreamingWireRequest, verifyChemiqStreamEvidence } from './upstream-stream-length-staged.ts';
import { createHash } from 'node:crypto';
import { actualPin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
const out=resolve('docs/repair-2026-10-10/full-f-rerun/chemiq/stream-control',new Date().toISOString().replace(/[:.]/g,'-'));
mkdirSync(out,{recursive:true});
const original=JSON.stringify({model:'deepseek/deepseek-v4.1-flash',provider:{only:['digitalocean'],allow_fallbacks:false},reasoning:{enabled:true,effort:'high'},temperature:0,max_tokens:16384,messages:[{role:'user',content:'fixture only'}],tools:[{type:'function',function:{name:'submit',parameters:{type:'object'}}}],tool_choice:'auto'});
const wire=makeChemiqStreamingWireRequest(original);
assert.deepEqual(JSON.parse(wire),{...JSON.parse(original),stream:true,stream_options:{include_usage:true}});
const meta={id:'gen-local-fixture',model:'deepseek/deepseek-v4.1-flash',provider:'DigitalOcean',created:100};
const frame=(v:any)=>'data: '+JSON.stringify(v)+'\n\n';
const base=[{...meta,choices:[{index:0,delta:{role:'assistant',reasoning:'思考🧪',reasoning_details:[{index:0,type:'reasoning.text',id:'r0',format:'fixture',text:'思考'}]}}]},
  {...meta,choices:[{index:0,delta:{content:'答复',reasoning_details:[{index:0,type:'reasoning.text',id:'r0',format:'fixture',text:'🧪'}],tool_calls:[{index:0,id:'call_fixture',type:'function',function:{name:'sub',arguments:'{"answer":'}}]}}]},
  {...meta,choices:[{index:0,delta:{tool_calls:[{index:0,function:{name:'mit',arguments:'"A🧪"}'}}]},finish_reason:'tool_calls'}]},
  {...meta,choices:[],usage:{cost:0.0123,prompt_tokens:7,completion_tokens:3,total_tokens:10,completion_tokens_details:{reasoning_tokens:2}}}];
const valid=': keepalive\n\n'+base.map(frame).join('')+'data: [DONE]\n\n';
const cases:Array<{name:string;body:string;fail?:boolean;error?:boolean;status?:number;chunk?:number;interrupt?:boolean}>=[
 {name:'byte-split-UTF8-reasoning-tool-arguments',body:valid,chunk:1},
 {name:'multiline-data-comments-crlf',body:': comment\r\n\r\n'+base.map(v=>'event: message\r\ndata: '+JSON.stringify(v,null,2).split('\n').join('\r\ndata: ')+'\r\n\r\n').join('')+'data: [DONE]\r\n\r\n',chunk:3},
 {name:'complete-json-http200-error',body:JSON.stringify({id:'gen-timeout',error:{code:504,message:'Provider timed out after301543ms'}}),error:true},
 {name:'sse-error-original-retained',body:frame({id:'gen-error',error:{code:504,message:'timeout'}}),error:true},
 {name:'missing-DONE',body:base.map(frame).join(''),fail:true},
 {name:'missing-usage',body:base.slice(0,3).map(frame).join('')+'data: [DONE]\n\n',fail:true},
 {name:'missing-provider',body:base.map(v=>{const x={...v};delete x.provider;return frame(x)}).join('')+'data: [DONE]\n\n',fail:true},
 {name:'missing-generation',body:base.map(v=>{const x={...v};delete x.id;return frame(x)}).join('')+'data: [DONE]\n\n',fail:true},
 {name:'wrong-model',body:base.map(v=>frame({...v,model:'wrong'})).join('')+'data: [DONE]\n\n',fail:true},
 {name:'generation-changed',body:base.map((v,i)=>frame({...v,id:i?'gen-other':v.id})).join('')+'data: [DONE]\n\n',fail:true},
 {name:'invalid-tool-JSON',body:valid.replace('\\"A🧪\\"}', '\\"A🧪\\"'),fail:true},
 {name:'data-after-DONE',body:valid+frame(base[0]),fail:true},
 {name:'unclosed-event',body:valid.slice(0,-2),fail:true},
 {name:'missing-finish',body:base.map(v=>frame({...v,choices:v.choices.map((c:any)=>({...c,finish_reason:null}))})).join('')+'data: [DONE]\n\n',fail:true},
 {name:'negative-cost',body:valid.replace('"cost":0.0123','"cost":-1'),fail:true},
 {name:'finish-reason-error',body:valid.replace('"finish_reason":"tool_calls"','"finish_reason":"error"'),fail:true},
 {name:'finish-reason-length-preserved',body:valid.replace('"finish_reason":"tool_calls"','"finish_reason":"length"')},
 {name:'tool-finish-without-tools',body:base.map(v=>frame({...v,choices:v.choices.map((c:any)=>({...c,delta:{...c.delta,tool_calls:undefined}}))})).join('')+'data: [DONE]\n\n',fail:true},
 {name:'invalid-UTF8',body:'invalidbytes',fail:true},
 {name:'native-response-body-interruption',body:valid,fail:true,interrupt:true},
];
const server=Bun.serve({hostname:'127.0.0.1',port:0,fetch:async request=>{const n=Number(new URL(request.url).pathname.slice(1)),c=cases[n];const bytes=c.name==='invalid-UTF8'?new Uint8Array([0xc3,0x28]):new TextEncoder().encode(c.body);return new Response(new ReadableStream({async start(controller){try{const size=c.chunk??17;for(let i=0;i<bytes.length;i+=size){controller.enqueue(bytes.slice(i,i+size));if(c.interrupt&&i>50){controller.error(Error('fixture body interruption'));return;}if(i%97===0)await Bun.sleep(1);}controller.close();}catch{}}}),{status:c.status??200,headers:{'content-type':c.error&&c.name.includes('json')?'application/json':'text/event-stream'}});}});
const results=[];
try{
 for(let i=0;i<cases.length;i++){const c=cases[i],prefix=join(out,c.name,'capture');let result:any,error:any;
  try{result=await captureChemiqSSE(await fetch(`http://127.0.0.1:${server.port}/${i}`),{originalRequest:original,wireRequest:wire,evidencePrefix:prefix});}catch(e){error=e;}
  if(c.fail){assert.ok(error,`${c.name} must reject`);assert.throws(()=>verifyChemiqStreamEvidence(join(out,c.name)));}else{assert.ok(!error,`${c.name}: ${error}`);const replay=verifyChemiqStreamEvidence(join(out,c.name));assert.equal(replay.valid,true);assert.equal(replay.providerError,!!c.error);const a=JSON.parse(result.rawResponse);if(c.error)assert.ok(a.error);else{assert.equal(a.id,meta.id);assert.equal(a.provider,'DigitalOcean');assert.equal(a.model,meta.model);assert.equal(a.usage.cost,0.0123);assert.equal(a.choices[0].message.reasoning,'思考🧪');assert.deepEqual(a.choices[0].message.reasoning_details,[{index:0,type:'reasoning.text',id:'r0',format:'fixture',text:'思考🧪'}]);assert.equal(a.choices[0].message.tool_calls[0].function.name,'submit');assert.deepEqual(JSON.parse(a.choices[0].message.tool_calls[0].function.arguments),{answer:'A🧪'});assert.ok(result.evidence.firstDataAtUtc&&result.evidence.firstReasoningAtUtc&&result.evidence.lastDataFrameAtUtc);}}
  const evidence=JSON.parse(readFileSync(prefix+'.evidence.json','utf8'));assert.equal(evidence.wireRequestSha256.length,64);assert.ok(evidence.rawSSE.sha256);assert.equal(gunzipSync(readFileSync(prefix+'.wire-request.json.gz')).toString(),wire);if(!c.interrupt&&c.name!=='invalid-UTF8')assert.equal(gunzipSync(readFileSync(prefix+'.response.raw.gz')).toString(),c.body);
  results.push({name:c.name,passed:true,rejected:!!error,fault:error?.name,evidencePin:actualPin(prefix+'.evidence.json')});
 }
 for(const [name,patch]of [['route',{provider:{only:['relace'],allow_fallbacks:false}}],['fallback',{provider:{only:['digitalocean'],allow_fallbacks:true}}],['reasoning',{reasoning:{effort:'low'}}],['reasoning-disabled',{reasoning:{enabled:false,effort:'high'}}]] as const){assert.throws(()=>makeChemiqStreamingWireRequest(JSON.stringify({...JSON.parse(original),...patch})));results.push({name:'reject-'+name,passed:true,rejected:true});}
 const fakeDir=join(out,'tampered-aggregate');mkdirSync(fakeDir);const proof=JSON.parse(readFileSync(join(out,cases[0].name,'capture.evidence.json'),'utf8')),fake=JSON.stringify({id:'gen-fake',usage:{cost:0}}),fakePath=join(fakeDir,'fake.json');writeFileSync(fakePath,fake);proof.aggregate=actualPin(fakePath);proof.aggregateSha256=createHash('sha256').update(fake).digest('hex');writeFileSync(join(fakeDir,'capture.evidence.json'),JSON.stringify(proof));assert.throws(()=>verifyChemiqStreamEvidence(fakeDir));results.push({name:'independent-replay-rejects-consistently-repinned-fake-aggregate',passed:true,rejected:true});
 const report={protocol:'chemiq-stream-local-control-v1',atUtc:new Date().toISOString(),passed:true,tests:results.length,externalCalls:0,localHTTP:true,modelRequests:0,sourcePin:actualPin(resolve('scripts/benchmark-campaign/full-f/chemiq/upstream-stream-length-staged.ts')),results};
 writeFileSync(join(out,'report.json'),JSON.stringify(report,null,2)+'\n');writeFileSync(resolve('docs/repair-2026-10-10/full-f-rerun/chemiq/stream-length-control.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:true,tests:results.length,externalCalls:0,report:join(out,'report.json')}));
}finally{server.stop(true);}
