import {expect,test} from 'bun:test';
import {readFileSync,readdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {registerVendors,type Unit} from '../../../app/src/llm/index.ts';
import {BENCHMARK_PROVIDER} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts';
import {submitResponse} from './humaneval-submit-response.ts';
const ROOT=resolve(import.meta.dir,'../../..');
function walk(dir:string):string[]{return readdirSync(dir,{withFileTypes:true}).flatMap(row=>row.isDirectory()?walk(join(dir,row.name)):[join(dir,row.name)]);}
const dirs=walk(join(ROOT,'docs/evalplus-20261012/humaneval/full/calls/objrun/HumanEval-8')).filter(p=>p.endsWith('response.json'));
const responses=dirs.map(p=>({path:p,value:JSON.parse(readFileSync(p,'utf8'))}));
const rejected=responses.find(r=>!r.value.choices?.[0]?.message?.tool_calls?.length)!.value;
const submitted=responses.find(r=>r.value.choices?.[0]?.message?.tool_calls?.some((c:any)=>c.function?.name==='submit'))!.value;

test('captured HumanEval/8 text-only hand-in recovers through a genuine submit call accepted by the unchanged native adapter',async()=>{
 let upstreamCalls=0;const sent:any[]=[];
 const server=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(req){
   const body=await req.json();
   const result=await submitResponse(body,async(request,attempt)=>{
     upstreamCalls++;sent.push(request);
     const corrected=JSON.stringify(request.messages).includes('not handed in');
     return{raw:JSON.stringify(corrected?submitted:rejected),status:200,receipt:{localFixture:true}};
   });
   return new Response(result.raw,{status:result.status,headers:{'content-type':'application/json'}});
 }});
 const key='TGENGIN_HUMANEVAL_SUBMIT_REPLAY_KEY',before=process.env[key];process.env[key]='local-fixture-only';
 try{
   const handles=new Map<string,any>();
   registerVendors({run(){}} as any,{register(_db:any,name:string,_timeout:any,handler:any){handles.set(name,handler);}} as any,{warn(){}} as any,[],{...BENCHMARK_INFERENCE,retryTimes:0,continueTimes:0});
   const unit:Unit={agent:{},task:{},cycle:{},chain:'captured-HumanEval-8',place:'local',instance:'fixture',unit:0,api:{key_env:key,model:BENCHMARK_PROVIDER.model,base_url:`http://127.0.0.1:${server.port}/v1`,retry_on:'[]'},context:[{seq:0,role:'user',kind:'prompt',body:'Hand in completed sum_product code using submit.'}],sentAs:{user:'messages',assistant:'messages'},mustCall:'submit',rules:[],tools:[{name:'submit',does:'Hand in Python code',params:'{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}'}]};
   const native=await handles.get('fn:api.openrouter')(unit);
   const value=JSON.parse(native.body);
   expect(value.calls).toHaveLength(1);expect(value.calls[0].name).toBe('submit');
   expect(upstreamCalls).toBe(2);expect(sent[0].reasoning).toEqual({enabled:true,effort:'high',exclude:false});
   expect(sent[1].max_tokens).toBe(16384);expect(sent[1].temperature).toBe(0);
 }finally{if(before===undefined)delete process.env[key];else process.env[key]=before;await server.stop(true);}
});

test('a valid submit is forwarded once without changing the request',async()=>{
 const body={tools:[{type:'function',function:{name:'submit'}}],messages:[{role:'user',content:'public task'}],max_tokens:16384};let calls=0;
 const result=await submitResponse(body,async request=>{calls++;expect(request).toBe(body);return{raw:JSON.stringify(submitted),status:200};});
 expect(calls).toBe(1);expect(JSON.parse(result.raw).choices[0].message.tool_calls).toHaveLength(1);expect(body.messages).toHaveLength(1);
});
test('ordinary solving responses and truncations retain the native behavior',async()=>{
 for(const body of [{tools:[{type:'function',function:{name:'verify'}},{type:'function',function:{name:'submit'}}]},{tools:[{type:'function',function:{name:'submit'}}]}]){
  let calls=0;const response=structuredClone(rejected);if(body.tools.length===1)response.choices[0].finish_reason='length';
  await submitResponse(body,async()=>{calls++;return{raw:JSON.stringify(response),status:200};});expect(calls).toBe(1);
 }
});
test('a second malformed response is returned unchanged and never fabricated into submit',async()=>{
 let calls=0;const body={tools:[{type:'function',function:{name:'submit'}}],messages:[]};
 const result=await submitResponse(body,async()=>{calls++;return{raw:JSON.stringify(rejected),status:200};});
 expect(calls).toBe(2);expect(JSON.parse(result.raw).choices[0].message.tool_calls).toBeUndefined();expect(body.messages).toHaveLength(0);
});
