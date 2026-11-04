import {test,expect} from 'bun:test';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {withProviderRoute} from './wire-provider.ts';
test('Fireworks changes only routing on the captured real native request',()=>{
 const request=JSON.parse(readFileSync(join(import.meta.dir,'../../../../docs/newbench-20261014/classeval/calls/objrun/ClassEval_0/task-attempt-0/3611aff329b2af48f8f99afdab0a6648730feed2c2298d1d0afce59c40518e56/attempt-0/request.json'),'utf8'));
 const route={model:request.model,providerName:'Fireworks',providerSlug:'fireworks',routing:{only:['fireworks'],allow_fallbacks:false,max_price:{prompt:0.3,completion:1.2}}};
 const changed=withProviderRoute(request,route);
 const {provider:old,...before}=request,{provider:current,...after}=changed;
 expect(after).toEqual(before);expect(current.only).toEqual(['fireworks']);expect(current.allow_fallbacks).toBe(false);
});
test('fallbacks and a model substitution are rejected before dispatch',()=>{
 const base={providerName:'Fireworks',providerSlug:'fireworks',routing:{only:['fireworks'],allow_fallbacks:false}};
 expect(()=>withProviderRoute({model:'deepseek/deepseek-v4.1-flash'},{...base,model:'different-model'})).toThrow('ProviderModelChanged');
 expect(()=>withProviderRoute({},{...base,routing:{only:['fireworks'],allow_fallbacks:true}})).toThrow('InvalidPinnedProviderRoute');
});
