import {expect,test} from 'bun:test';
import {readFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {registerVendors,type Unit} from '../../../app/src/llm/index.ts';
import {BENCHMARK_PROVIDER} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts';
import {submitResponse} from './mbpp-submit-response.ts';
const ROOT=resolve(import.meta.dir,'../../..');
const fixture=JSON.parse(readFileSync(join(ROOT,'docs/evalplus-20261012/mbpp/diagnosis/submit-response-shapes.json'),'utf8'));
const {rejected,submitted}=fixture;
test('MBPP text-only hand-in must recover as a genuine submit accepted by unchanged native registerVendors',async()=>{
 let calls=0;const sent:any[]=[];
 const server=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(req){
  const body=await req.json();const result=await submitResponse(body,async request=>{calls++;sent.push(request);return {raw:JSON.stringify(JSON.stringify(request.messages).includes('not handed in')?submitted:rejected),status:200,receipt:{localFixture:true}};});
  return new Response(result.raw,{status:result.status,headers:{'content-type':'application/json'}});
 }});
 const key='TGENGIN_MBPP_SUBMIT_REPLAY_KEY',before=process.env[key];process.env[key]='local-fixture-only';
 try{
  const handles=new Map<string,any>();registerVendors({run(){}} as any,{register(_db:any,name:string,_timeout:any,handler:any){handles.set(name,handler);}} as any,{warn(){}} as any,[],{...BENCHMARK_INFERENCE,retryTimes:0,continueTimes:0});
  const unit:Unit={agent:{},task:{},cycle:{},chain:'MBPP-synthetic-replay',place:'local',instance:'fixture',unit:0,api:{key_env:key,model:BENCHMARK_PROVIDER.model,base_url:`http://127.0.0.1:${server.port}/v1`,retry_on:'[]'},context:[{seq:0,role:'user',kind:'prompt',body:'Submit the complete public Python fixture code.'}],sentAs:{user:'messages',assistant:'messages'},mustCall:'submit',rules:[],tools:[{name:'submit',does:'Hand in Python code',params:'{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}'}]};
  const native=await handles.get('fn:api.openrouter')(unit),value=JSON.parse(native.body);
  expect(value.calls).toHaveLength(1);expect(value.calls[0].name).toBe('submit');expect(calls).toBe(2);
  expect(sent[1].max_tokens).toBe(16384);expect(sent[1].temperature).toBe(0);expect(sent[1].reasoning).toEqual({enabled:true,effort:'high',exclude:false});
 }finally{if(before===undefined)delete process.env[key];else process.env[key]=before;await server.stop(true);}
});
test('valid submit is passed through once with the request unchanged',async()=>{
 const body={tools:[{type:'function',function:{name:'submit'}}],messages:[],max_tokens:16384};let calls=0;
 await submitResponse(body,async request=>{calls++;expect(request).toBe(body);return {raw:JSON.stringify(submitted),status:200};});expect(calls).toBe(1);expect(body.messages).toHaveLength(0);
});
test('ordinary solving, truncation, and provider faults do not trigger protocol repair',async()=>{
 for(const mode of ['ordinary','truncated','fault']){
  const body={tools:mode==='ordinary'?[{type:'function',function:{name:'verify'}},{type:'function',function:{name:'submit'}}]:[{type:'function',function:{name:'submit'}}]};let calls=0;const response=structuredClone(rejected);if(mode==='truncated')response.choices[0].finish_reason='length';
  await submitResponse(body,async()=>{calls++;return {raw:JSON.stringify(response),status:mode==='fault'?504:200};});expect(calls).toBe(1);
 }
});
test('a second malformed response remains malformed and is never converted to submit',async()=>{
 let calls=0;const body={tools:[{type:'function',function:{name:'submit'}}],messages:[]};const r=await submitResponse(body,async()=>{calls++;return {raw:JSON.stringify(rejected),status:200};});expect(calls).toBe(2);expect(JSON.parse(r.raw).choices[0].message.tool_calls).toBeUndefined();expect(body.messages).toHaveLength(0);
});
