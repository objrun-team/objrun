import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {BENCHMARK_PROVIDER,benchmarkProviderKey} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
const root=resolve(import.meta.dir,'../../..'),out=join(root,'docs/evalplus-20261012/tool-control-'+Date.now());mkdirSync(out,{recursive:true});
const body={model:BENCHMARK_PROVIDER.model,max_tokens:16384,temperature:0,stream:false,reasoning:{enabled:true,effort:'high',exclude:false},provider:{...BENCHMARK_PROVIDER.routing},messages:[{role:'user',content:'Use submit to give the Python code def add(a,b): return a+b.'}],tools:[{type:'function',function:{name:'submit',description:'Submit the Python code.',parameters:{type:'object',properties:{answer:{type:'string'}},required:['answer']}}}],tool_choice:'auto'};
if(process.argv[2]){const captured=JSON.parse(readFileSync(process.argv[2],'utf8'));body.tools=captured.tools;}
if(process.argv[3]==='normalize'){
 const clean=(v:any):any=>{if(!v||typeof v!=='object')return v;if(Array.isArray(v))return v.map(clean);const x=Object.fromEntries(Object.entries(v).map(([k,t])=>[k,clean(t)]));if(x.type==='object')x.additionalProperties=false;return x;};
 body.tools=body.tools.map((t:any)=>({...t,function:{...t.function,parameters:clean(t.function.parameters)}}));
}
writeFileSync(join(out,'request.json'),JSON.stringify(body,null,2));const begin=Date.now();
try{const r=await fetch(BENCHMARK_PROVIDER.endpoint,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+benchmarkProviderKey(root)},body:JSON.stringify(body),signal:AbortSignal.timeout(360000),proxy:'http://127.0.0.1:10809'} as any);const v=await r.json();writeFileSync(join(out,'response.json'),JSON.stringify(v,null,2));console.log(JSON.stringify({out,status:r.status,seconds:(Date.now()-begin)/1000,provider:v.provider,usage:v.usage,error:v.error,toolCalls:v.choices?.[0]?.message?.tool_calls}));}catch(e){writeFileSync(join(out,'unknown.json'),JSON.stringify({error:String(e),atUtc:new Date().toISOString()}));console.log(JSON.stringify({out,error:String(e)}));}
