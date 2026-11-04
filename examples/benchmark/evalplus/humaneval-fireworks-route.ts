import {BENCHMARK_PROVIDER,officialOpenRouterFault} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
import {BENCHMARK_INFERENCE,benchmarkProviderRequest} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts';

// HumanEval-only supplier change authorized by the user on 2026-10-12.
// The original shared request builder and native core remain unchanged.
export const FIREWORKS_ROUTE=Object.freeze({only:['fireworks'],allow_fallbacks:false,require_parameters:true,max_price:{prompt:0.3,completion:1.2}});
export function fireworksRequest(body:Record<string,any>){
  const wire=benchmarkProviderRequest(body,BENCHMARK_INFERENCE,BENCHMARK_PROVIDER);
  return {...wire,provider:{...FIREWORKS_ROUTE}};
}
export function fireworksFault(response:any){return officialOpenRouterFault(response,'Fireworks');}
