/** Opt-in only; probe and ordinary Fireworks branches remain the frozen implementation. */
import{currentProbeSource}from'./provider-probe-caffe-current-prices-source-v4.ts';import{join}from'node:path';
function one(s:string,a:string,b:string,count=1){if(s.split(a).length!==count+1)throw Error('wafer_task_source_exact_anchor:'+a);return s.split(a).join(b)}
export function waferTaskSource(path:string,raw:string){let s=currentProbeSource(path,raw),n=path.replaceAll('\\','/').split('/').pop();
 if(n==='broker-adoption-v76.ts'){
  s=one(s,JSON.stringify(join(import.meta.dir,'provider-task-route-scoped-transport-policy-v3.ts')),JSON.stringify(join(import.meta.dir,'wafer-original-task-route-policy-v1.ts')));
  s=one(s,"if(data.providerProbeScopePin||data.providerSlug==='fireworks')","if(data.providerProbeScopePin||data.providerTaskRouteEntryPin||data.providerSlug==='fireworks')");
  s=one(s,"const providerSlug=data.providerProbeScopePin?verifyProviderRoute(data).providerSlug:data.providerSlug==='fireworks'?'fireworks':","const providerSlug=data.providerProbeScopePin?verifyProviderRoute(data).providerSlug:data.providerTaskRouteEntryPin?verifyProviderRoute(data).supplier:data.providerSlug==='fireworks'?'fireworks':");
  s=one(s,"prices:lane.providerProbeScopePin?verifyProviderRoute(lane).pricesPin:lane.providerSlug==='fireworks'?","prices:lane.providerProbeScopePin?verifyProviderRoute(lane).pricesPin:(lane.providerSlug==='fireworks'||lane.providerSlug==='wafer')?");
  s=one(s,"if(lane.providerProbeScopePin||lane.providerSlug==='fireworks')","if(lane.providerProbeScopePin||lane.providerTaskRouteEntryPin||lane.providerSlug==='fireworks')",2);
  s=one(s,"else if(lane.providerSlug==='fireworks'){verifyProviderRoute(lane);check(journal.providerSlug==='fireworks'&&journal.providerName==='Fireworks','provider_probe_actual_cash_provider_identity');}","else if(lane.providerTaskRouteEntryPin){const a=verifyProviderRoute(lane);check(journal.providerSlug===a.supplier&&journal.providerName===(a.supplier==='wafer'?'Wafer':'Fireworks'),'provider_probe_actual_cash_provider_identity');}");
 }
 if(n==='start-unlimited-broker.ts')s=one(s,"from'./provider-probe-caffe-current-prices-loader-v4.ts'","from'./wafer-original-task-loader-v1.ts'");
 return s;
}
