import {providerProbeSource} from './provider-probe-source.ts';import {join} from 'node:path';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('provider_task_exact_anchor:'+a);return s.replace(a,b)}
export function providerTaskRouteSource(path:string,raw:string){let s=providerProbeSource(path,raw);const n=path.replaceAll('\\','/').split('/').pop();
if(n==='broker-adoption-v76.ts'){
 s=one(s,"import{verifyProviderProbeScope,verifyProviderProbeForward,markProviderProbeDispatch}from "+JSON.stringify(join(import.meta.dir,'provider-probe-policy.ts'))+';',"import{verifyProviderRoute,verifyProviderRouteForward,markProviderRouteDispatch}from "+JSON.stringify(join(import.meta.dir,'provider-task-route-policy-v2.ts'))+';');
 s=one(s,"const data=await request.json() as any;if(data.providerSlug==='fireworks')","const data=await request.json() as any;if(data.providerTaskRouteEntryPin){check(data.providerSlug===undefined||data.providerSlug==='fireworks','task_route_supplier_conflict');verifyProviderRoute({...data,providerSlug:'fireworks'});data.providerSlug='fireworks';}if(data.providerSlug==='fireworks')");
 s=s.replaceAll('verifyProviderProbeScope(data.providerProbeScopePin,data)','verifyProviderRoute(data)').replaceAll('verifyProviderProbeScope(lane.providerProbeScopePin,lane)','verifyProviderRoute(lane)').replaceAll('verifyProviderProbeForward(lane,raw)','verifyProviderRouteForward(lane,raw)').replaceAll('markProviderProbeDispatch(lane,raw)','markProviderRouteDispatch(lane,raw)');
 s=one(s,'lane={providerProbeScopePin:data.providerProbeScopePin,','lane={providerTaskRouteEntryPin:data.providerTaskRouteEntryPin,providerProbeScopePin:data.providerProbeScopePin,');
 s=one(s,"providerProbeCapability:options.providerProbeEnabled===false?null:'signed-fireworks-two-request-only-v1'","providerTaskRouteCapability:'signed-original-task-route-v1',providerProbeCapability:options.providerProbeEnabled===false?null:'signed-fireworks-two-request-only-v1'");
}
if(n==='unlimited-adopted-parent.ts'){
 s=one(s,'const p=envelope.plan;',`const p=envelope.plan;if(p.continuationOfAdoptionPin){verifyPin(p.continuationOfAdoptionPin);const prior=jsonPin(p.continuationOfAdoptionPin),oldHealth=jsonPin(p.oldHealthPin);demand(prior.protocol==='bench-signed-unlimited-financial-adoption-v1'&&verify(null,Buffer.from(JSON.stringify(prior.plan)),readFileSync(publicKeyPath),Buffer.from(prior.signature,'base64'))&&prior.plan.preparationOnly===false&&same(oldHealth.adoption.signedAdoptionPlanPin,p.continuationOfAdoptionPin)&&oldHealth.pid===p.previousExecutorPid&&oldHealth.adoption.liveExecutorPid===p.previousExecutorPid&&p.providerProbeEnabled===true&&p.directory!==prior.plan.directory,'exact_signed_task_route_continuation');}`);
 s=one(s,'p.previousExecutorPid===30344||!!p.rollbackOfAdoptionPin','p.previousExecutorPid===30344||!!p.rollbackOfAdoptionPin||!!p.continuationOfAdoptionPin');
}
if(['start-unlimited-broker.ts','unlimited-python-bridge-readonly-retry.ts','signed-owned-operation.ts','signed-owned-asset.ts','terminal-driver.ts'].includes(n!))s=s.replaceAll('provider-probe-loader.ts','provider-task-route-loader-v3.ts');
return s;}
