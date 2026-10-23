/** Probe-only transport opt-in. Ordinary requests retain their exact 10809 path. */
import {continuationProbeSource} from './provider-probe-continuation-source-v1.ts';import{join}from'node:path';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('scoped_probe_transport_exact_anchor:'+a);return s.replace(a,b)}
export function scopedProbeTransportSource(path:string,raw:string){let s=continuationProbeSource(path,raw),n=path.replaceAll('\\','/').split('/').pop();
 if(n==='broker-adoption-v76.ts'){
  s=one(s,JSON.stringify(join(import.meta.dir,'provider-task-route-continuation-policy-v1.ts')),JSON.stringify(join(import.meta.dir,'provider-task-route-scoped-transport-policy-v2.ts')));
  s=one(s,'benchmarkFetch(raw,benchmarkProviderKey(root))','benchmarkFetch(raw,benchmarkProviderKey(root),lane.providerProbeScopePin?verifyProviderRoute(lane).transportProxyURL:undefined)');
 }
 if(n==='digitalocean-provider-600-proxy10809.next.ts'){
  s=one(s,'benchmarkFetch(raw: string, key: string)','benchmarkFetch(raw: string, key: string, probeProxy?: string)');
  s=one(s,'  const body = JSON.parse(raw);',"  if(probeProxy!==undefined&&probeProxy!=='http://127.0.0.1:18092')throw Error('exact_task_scoped_probe_proxy_required');\n  const body = JSON.parse(raw);");
  s=one(s,"proxy: 'http://127.0.0.1:10809'","proxy: probeProxy??'http://127.0.0.1:10809'");
 }
 if(n==='start-unlimited-broker.ts')s=one(s,"from'./provider-probe-continuation-loader-v1.ts'","from'./provider-probe-scoped-transport-loader-v2.ts'");
 return s;
}
