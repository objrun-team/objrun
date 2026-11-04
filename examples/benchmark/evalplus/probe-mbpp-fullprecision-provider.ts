// A separate provider/tool-transport probe; no benchmark answers or scoring.
import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {BENCHMARK_PROVIDER,benchmarkProviderKey} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts';
const root=resolve(import.meta.dir,'../../..');
const evidence=join(root,'docs/evalplus-20261012/mbpp/diagnosis/provider-routing-20261012T153831Z');
const catalog=JSON.parse(readFileSync(join(evidence,'endpoints.json'),'utf8')).data.endpoints;
const endpoint=catalog.find((e:any)=>e.tag==='baseten/fast'&&e.quantization==='fp32');
if(!endpoint)throw Error('NoVerifiedFullPrecisionEndpoint');
const dir=join(evidence,'baseten-fast-probe');mkdirSync(dir,{recursive:true});
if(existsSync(join(dir,'dispatch.json')))throw Error('ProbeAlreadyDispatchedDoNotRepeat');
const key=benchmarkProviderKey(root),hash=(s:string)=>createHash('sha256').update(s).digest('hex');
const wire=benchmarkProviderRequest({model:BENCHMARK_PROVIDER.model,stream:false,temperature:0,max_tokens:16384,reasoning_effort:'high',messages:[{role:'user',content:'Tool transport probe only. Call submit exactly once with body equal to the literal transport-tool-probe. Do not answer in ordinary text.'}],tools:[{type:'function',function:{name:'submit',description:'Submit the transport probe sentinel.',parameters:{type:'object',properties:{body:{type:'string'}},required:['body'],additionalProperties:false}}}],tool_choice:{type:'function',function:{name:'submit'}}},BENCHMARK_INFERENCE,BENCHMARK_PROVIDER);
wire.provider={only:['baseten/fast'],allow_fallbacks:false,quantizations:['fp32'],require_parameters:false,max_price:{prompt:0.6,completion:2.4}};
const rawReq=JSON.stringify(wire);const begin=Date.now();
const save=(name:string,value:any)=>writeFileSync(join(dir,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
save('request.json',wire);save('dispatch.json',{atUtc:new Date().toISOString(),pid:process.pid,requestSha256:hash(rawReq),purpose:'Separate provider tool probe excluded from formal benchmark scores',providerTag:endpoint.tag,quantization:endpoint.quantization});
let raw='',httpStatus=0,v:any;
try{const r=await fetch(BENCHMARK_PROVIDER.endpoint,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+key},body:rawReq,proxy:'http://127.0.0.1:10809',keepalive:false,signal:AbortSignal.timeout(600000)} as any);httpStatus=r.status;raw=await r.text();v=JSON.parse(raw);save('response.json',v);}catch(error){v={transportError:String(error)};}
const actualCostUsd=typeof v.usage?.cost==='number'?v.usage.cost:null;
const receipt={atUtc:new Date().toISOString(),httpStatus,dispatched:true,generationId:v.id??null,model:v.model??null,provider:v.provider??null,requestedProviderTag:endpoint.tag,observedPrecision:endpoint.quantization,usage:v.usage??null,actualCostUsd,unknownCost:actualCostUsd===null,upperBoundUsd:actualCostUsd??((v.usage?.prompt_tokens??Buffer.byteLength(rawReq))*0.6+(v.usage?.completion_tokens??16384)*2.4)/1e6,seconds:(Date.now()-begin)/1000,requestSha256:hash(rawReq),responseSha256:raw?hash(raw):null,fault:v.error?.message??v.transportError??null,excludedFromFormalResults:true};
save('receipt.json',receipt);
const tools=v.choices?.[0]?.message?.tool_calls??[];
const good=httpStatus===200&&!receipt.fault&&v.provider===endpoint.provider_name&&tools.length===1&&tools[0].function?.name==='submit'&&JSON.parse(tools[0].function.arguments).body==='transport-tool-probe';
save('validation.json',{atUtc:new Date().toISOString(),genuineModelToolResponse:good,requestedProviderTag:endpoint.tag,precisionFromOfficialCatalog:endpoint.quantization,providerFromResponse:v.provider??null,modelFromResponse:v.model??null,toolNames:tools.map((t:any)=>t.function?.name),finishReason:v.choices?.[0]?.finish_reason??null,benchmarkModelChanged:false,formalBenchmarkScoresIncluded:false});
console.log(JSON.stringify({genuineModelToolResponse:good,receipt,toolNames:tools.map((t:any)=>t.function?.name)}));
if(!good)process.exitCode=1;
