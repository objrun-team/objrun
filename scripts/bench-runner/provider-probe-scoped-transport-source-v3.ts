/** Preserves every ordinary route unless its original signed task opts in. */
import{scopedProbeTransportSource}from'./provider-probe-scoped-transport-source-v2.ts';import{join}from'node:path';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('task_scoped_transport_exact_anchor:'+a);return s.replace(a,b)}
export function scopedTaskTransportSource(path:string,raw:string){let s=scopedProbeTransportSource(path,raw),n=path.replaceAll('\\','/').split('/').pop();
 if(n==='broker-adoption-v76.ts'){
  s=one(s,JSON.stringify(join(import.meta.dir,'provider-task-route-scoped-transport-policy-v2.ts')),JSON.stringify(join(import.meta.dir,'provider-task-route-scoped-transport-policy-v3.ts')));
  s=one(s,'lane.providerProbeScopePin?verifyProviderRoute(lane).transportProxyURL:undefined','(lane.providerProbeScopePin||lane.providerTaskRouteEntryPin)?verifyProviderRoute(lane).transportProxyURL:undefined');
 }
 if(n==='start-unlimited-broker.ts')s=one(s,"from'./provider-probe-scoped-transport-loader-v2.ts'","from'./provider-probe-scoped-transport-loader-v3.ts'");
 return s;
}
