import {expect,test} from 'bun:test';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {BENCHMARK_PROVIDER} from '../benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../benchmark-campaign/full-f/shared/digitalocean-inference.ts';
import {fireworksRequest,fireworksFault} from './humaneval-fireworks-route.ts';

const captured=JSON.parse(readFileSync(join(import.meta.dir,'../../docs/evalplus-20261012/humaneval/objrun-adapter-v1/full/calls/objrun/HumanEval-41/schema-v3/7911271023a79dc7b9797156e95954be24966b6643d8f7d5328217d3b33eabe5/attempt-0/request.json'),'utf8'));
const body={...captured,seed:42,reasoning_effort:'high'};
test('captured timed-out request changes only its supplier routing',()=>{
  const old=benchmarkProviderRequest(body,BENCHMARK_INFERENCE,BENCHMARK_PROVIDER);
  const next=fireworksRequest(body);
  expect(old.provider.only).toEqual(['digitalocean']);
  expect(next.provider.only).toEqual(['fireworks']);
  const {provider:oldRoute,...oldOptions}=old,{provider:newRoute,...newOptions}=next;
  expect(newOptions).toEqual(oldOptions);
  expect(newRoute.allow_fallbacks).toBe(false);
  expect(newRoute.require_parameters).toBe(true);
  expect(next.max_tokens).toBe(16384);
  expect(next.reasoning).toEqual({enabled:true,effort:'high',exclude:false});
  expect(next.temperature).toBe(0);
  expect(next.seed).toBeUndefined();
});
test('native forced submit remains a submit-only auto station with high thinking',()=>{
  const next=fireworksRequest({...body,tool_choice:{type:'function',function:{name:'submit'}}});
  expect(next.tools.map((x:any)=>x.function.name)).toEqual(['submit']);
  expect(next.tool_choice).toBe('auto');
  expect(next.reasoning.effort).toBe('high');
});
test('actual responses must come from the pinned model and Fireworks',()=>{
  const good={provider:'Fireworks',model:BENCHMARK_PROVIDER.canonicalModel,id:'test-generation',usage:{cost:0.001}};
  expect(fireworksFault(good)).toBeUndefined();
  expect(fireworksFault({...good,provider:'DigitalOcean'})).toBe('UnexpectedOpenRouterProvider');
  expect(fireworksFault({...good,model:'different-model'})).toBe('UnexpectedOpenRouterModel');
  expect(fireworksFault({...good,usage:{}})).toBe('MissingOrInvalidOpenRouterUsdCost');
});
test('supplier switch cannot change the original generation limits',()=>{
  expect(()=>fireworksRequest({...body,max_tokens:4096})).toThrow('Wire parameters differ');
  expect(()=>fireworksRequest({...body,reasoning_effort:'low'})).toThrow('Wire parameters differ');
});
