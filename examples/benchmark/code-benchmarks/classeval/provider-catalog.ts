// Read-only official provider observation; credentials never enter the saved response.
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {BENCHMARK_PROVIDER,benchmarkProviderKey} from '../runtime-snapshot/scripts/repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
const ROOT=resolve(import.meta.dir,'../../../..'),OUT=join(ROOT,'docs/newbench-20261014/classeval');
const cfg=JSON.parse(readFileSync(join(import.meta.dir,'./experiment.json'),'utf8')),key=benchmarkProviderKey(ROOT);
const dir=join(OUT,'observations','provider-choice-'+Date.now());mkdirSync(dir,{recursive:true});
async function get(path:string){const response=await fetch(BENCHMARK_PROVIDER.baseURL+path,{headers:{authorization:'Bearer '+key},proxy:cfg.localProxy,signal:AbortSignal.timeout(30000)} as any);if(!response.ok)throw Error('ProviderObservationHttp:'+response.status);return await response.json() as any;}
const catalog=await get('/models/'+cfg.model+'/endpoints');
writeFileSync(join(dir,'endpoints.json'),JSON.stringify(catalog,null,2)+'\n');
const credits=await get('/credits'),limit=await get('/key');
const balance={atUtc:new Date().toISOString(),accountRemainingUsd:credits.data.total_credits-credits.data.total_usage,keyRemainingUsd:limit.data.limit_remaining??null,readOnly:true};
writeFileSync(join(dir,'balance.json'),JSON.stringify(balance,null,2)+'\n');
const rows=(catalog.data?.endpoints??[]).map((e:any)=>({name:e.provider_name,tag:e.tag,status:e.status,quantization:e.quantization,pricing:e.pricing,supportedParameters:e.supported_parameters,supportsToolChoice:e.supports_tool_choice,contextLength:e.context_length,maxCompletionTokens:e.max_completion_tokens}));
writeFileSync(join(OUT,'provider-catalog-latest.json'),JSON.stringify({atUtc:new Date().toISOString(),directory:dir,balance,model:cfg.model,rows},null,2)+'\n');console.log(JSON.stringify({directory:dir,balance,rows}));
