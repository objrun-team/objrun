/** Adds independently signed neutral continuation probes to the accepted async source. */
import {asyncAdoptionSource} from './async-adoption-source-v3.ts';
import {join} from 'node:path';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('continuation_probe_exact_anchor:'+a);return s.replace(a,b)}
export function continuationProbeSource(path:string,raw:string){
 let s=asyncAdoptionSource(path,raw),n=path.replaceAll('\\','/').split('/').pop();
 if(n==='broker-adoption-v76.ts'){
  s=one(s,JSON.stringify(join(import.meta.dir,'provider-task-route-policy-v2.ts')),JSON.stringify(join(import.meta.dir,'provider-task-route-continuation-policy-v1.ts')));
  s=one(s,"if(data.providerSlug==='fireworks'){check(options.providerProbeEnabled!==false,'provider_probe_disabled');verifyProviderRoute(data);}","if(data.providerProbeScopePin||data.providerSlug==='fireworks'){check(options.providerProbeEnabled!==false,'provider_probe_disabled');verifyProviderRoute(data);}");
  s=one(s,"const providerSlug=data.providerSlug==='fireworks'?'fireworks':","const providerSlug=data.providerProbeScopePin?verifyProviderRoute(data).providerSlug:data.providerSlug==='fireworks'?'fireworks':");
  s=one(s,"prices:lane.providerSlug==='fireworks'?verifyProviderRoute(lane).pricesPin:","prices:lane.providerProbeScopePin?verifyProviderRoute(lane).pricesPin:lane.providerSlug==='fireworks'?verifyProviderRoute(lane).pricesPin:");
  s=one(s,"if(lane.providerSlug==='fireworks')verifyProviderRouteForward(lane,raw);","if(lane.providerProbeScopePin||lane.providerSlug==='fireworks')verifyProviderRouteForward(lane,raw);");
  s=one(s,"if(lane.providerSlug==='fireworks')markProviderRouteDispatch(lane,raw);","if(lane.providerProbeScopePin||lane.providerSlug==='fireworks')markProviderRouteDispatch(lane,raw);");
  s=one(s,"if(lane.providerSlug==='fireworks'){verifyProviderRoute(lane);check(journal.providerSlug==='fireworks'&&journal.providerName==='Fireworks','provider_probe_actual_cash_provider_identity');}","if(lane.providerProbeScopePin){const scope=verifyProviderRoute(lane);check(journal.providerSlug===scope.providerSlug&&journal.providerName===scope.providerName,'provider_probe_actual_cash_provider_identity');}else if(lane.providerSlug==='fireworks'){verifyProviderRoute(lane);check(journal.providerSlug==='fireworks'&&journal.providerName==='Fireworks','provider_probe_actual_cash_provider_identity');}");
 }
 if(n==='digitalocean-provider-600-proxy10809.next.ts')s=one(s,'JSON.stringify(["fireworks"])','JSON.stringify(["fireworks"]),JSON.stringify(["relace"]),JSON.stringify(["wafer"])');
 if(n==='start-unlimited-broker.ts')s=one(s,"from'./provider-task-route-async-loader-v3.ts'","from'./provider-probe-continuation-loader-v1.ts'");
 return s;
}
