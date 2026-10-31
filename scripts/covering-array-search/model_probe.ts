import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
const dir = resolve(import.meta.dir, '../../data/covering-array-search/preparation');
mkdirSync(dir, { recursive: true });
const key = process.env.OPENROUTER_API_KEY;
if (!key) throw new Error('OPENROUTER_API_KEY missing; never substitute another model.');
const model = 'deepseek/deepseek-v4.1-flash';
const listResponse = await fetch('https://openrouter.ai/api/v1/models');
const list: any = await listResponse.json();
const metadata = list.data?.find((x: any) => x.id === model);
writeFileSync(dir+'/openrouter-model.json', JSON.stringify({ checked_utc: new Date().toISOString(), http_status: listResponse.status, metadata }, null, 2));
if (!metadata) throw new Error('The required model is not in the current OpenRouter model catalogue.');
const body = { model, messages: [{role: 'user', content: 'Interface preflight, not the search experiment. Call environment_probe with message READY. No other task.'}],
  tools: [{type:'function',function:{name:'environment_probe',description:'Confirm tool calling is available.',parameters:{type:'object',properties:{message:{type:'string'}},required:['message'],additionalProperties:false}}}],
  tool_choice: 'auto', reasoning: {effort:'high', enabled:true}, stream:false };
writeFileSync(dir+'/model-probe.request.json', JSON.stringify(body, null, 2));
const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {method:'POST',headers:{authorization:`Bearer ${key}`,'content-type':'application/json'},body:JSON.stringify(body)});
const raw = await response.text();
writeFileSync(dir+'/model-probe.response.json', raw);
const result = JSON.parse(raw);
const receipt = {checked_utc:new Date().toISOString(),http_status:response.status, id:result.id,model:result.model,provider:result.provider,usage:result.usage,finish_reason:result.choices?.[0]?.finish_reason,tool_calls:result.choices?.[0]?.message?.tool_calls,error:result.error};
writeFileSync(dir+'/model-probe.receipt.json', JSON.stringify(receipt,null,2));
console.log(JSON.stringify(receipt));
if (!response.ok || result.model !== model || result.choices?.[0]?.message?.tool_calls?.[0]?.function?.name !== 'environment_probe') process.exitCode=1;
