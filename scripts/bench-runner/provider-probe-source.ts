/** Add only the signed Fireworks probe path to the original cash/broker chain. */
import{join}from'node:path';import{unlimitedFinancialSource as financial}from'./financial-policy-source-benchmark.ts';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('provider_probe_exact_anchor:'+a);return s.replace(a,b)}
export function providerProbeSource(path:string,raw:string){
 let s=financial(path,raw);const n=path.replaceAll('\\','/').split('/').pop();
 if(n==='chembench-supplier-profiles.ts')s=one(s,"{relace:make('relace','Relace'),","{fireworks:make('fireworks','Fireworks'),relace:make('relace','Relace'),");
 if(n==='supplier-journal.ts'){s=one(s,'["deepseek", "relace", "digitalocean", "dekallm", "wafer"]','["deepseek", "relace", "digitalocean", "dekallm", "wafer", "fireworks"]');s=one(s,'{relace:"Relace",deepseek:"DeepSeek",','{fireworks:"Fireworks",relace:"Relace",deepseek:"DeepSeek",')}
 if(n==='supplier-usd-cash.ts')s=one(s,"{relace:'Relace',deepseek:'DeepSeek',","{fireworks:'Fireworks',relace:'Relace',deepseek:'DeepSeek',");
 if(n==='start-unlimited-broker.ts'){s=one(s,"from'./financial-policy-loader.ts'","from'./provider-probe-loader.ts'");s=one(s,'recordAndContinue:true,remoteDiskObservationPath:', 'recordAndContinue:true,providerProbeEnabled:p.providerProbeEnabled!==false,remoteDiskObservationPath:')}
 if(n==='unlimited-adopted-parent.ts'){
  s=one(s,'verifyPin(plan.pythonPin);verifyPin(plan.executorPreflightPin);',"demand(plan.preparationOnly===false,'fresh_final_provider_adoption_required');verifyPin(plan.pythonPin);verifyPin(plan.executorPreflightPin);");
  s=one(s,'const p=envelope.plan;',`const p=envelope.plan;if(p.rollbackOfAdoptionPin){verifyPin(p.rollbackOfAdoptionPin);const prior=jsonPin(p.rollbackOfAdoptionPin),oldHealth=jsonPin(p.oldHealthPin);demand(prior.protocol==='bench-signed-unlimited-financial-adoption-v1'&&verify(null,Buffer.from(JSON.stringify(prior.plan)),readFileSync(publicKeyPath),Buffer.from(prior.signature,'base64'))&&prior.plan.previousExecutorPid===30344&&prior.plan.preparationOnly===false&&oldHealth.adoption.liveExecutorPid===oldHealth.pid&&prior.plan.providerProbeHumanAuthorityPin?.sha256==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e'&&same(oldHealth.adoption.signedAdoptionPlanPin,p.rollbackOfAdoptionPin)&&oldHealth.pid===p.previousExecutorPid&&p.providerProbeEnabled===false&&p.directory!==prior.plan.directory,'exact_signed_singleton_probe_rollback');}`);
  s=one(s,'p.previousExecutorPid===22388',"(p.previousExecutorPid===30344||!!p.rollbackOfAdoptionPin)&&p.providerProbeHumanAuthorityPin?.sha256==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e'");
  s=one(s,'[p.sourceLoaderPin,p.oldHealthPin','[p.providerProbeHumanAuthorityPin,p.sourceLoaderPin,p.oldHealthPin');
  s=one(s,'h.pid===22388','h.pid===plan.previousExecutorPid');
  s=one(s,'old=jsonPin(plan.oldAllocationPin),pool=',"rawOld=jsonPin(plan.oldAllocationPin),old={...rawOld,originalCapUsd:rawOld.originalDeclaredCapUsd,additionalRetainedUsd:Object.values(rawOld.newLanes??{}).reduce((n:number,r:any)=>n+(r.retainedUsd??0),0),historyUnknownUpperUsd:rawOld.originalHistoryUnknownUpperUsd},pool=");
  s=s.replaceAll('previousExecutorPid:22388','previousExecutorPid:plan.previousExecutorPid');
  s=one(s,'allOriginalRowsUnmodified:true,inheritedRetainedUsd:', 'allOriginalRowsUnmodified:true,inheritedLaneRows:rawOld.newLanes??{},inheritedUnknownUpperUsd:rawOld.originalHistoryUnknownUpperUsd,inheritedRetainedUsd:');
 }
 if(n==='unlimited-python-bridge-readonly-retry.ts')s=one(s,"from'./financial-policy-loader.ts'","from'./provider-probe-loader.ts'");
 if(['signed-owned-operation.ts','signed-owned-asset.ts','terminal-driver.ts'].includes(n!))s=one(s,JSON.stringify(join(import.meta.dir,'financial-policy-loader-benchmark.ts')),JSON.stringify(join(import.meta.dir,'provider-probe-loader.ts')));
 if(n==='digitalocean-provider-600-proxy10809.next.ts')s=one(s,'JSON.stringify(body.provider?.only) !== JSON.stringify(BENCHMARK_PROVIDER.routing.only)','![JSON.stringify(BENCHMARK_PROVIDER.routing.only),JSON.stringify(["fireworks"])].includes(JSON.stringify(body.provider?.only))');
 if(n==='broker-adoption-v76.ts'){
  s='import{verifyProviderProbeScope,verifyProviderProbeForward,markProviderProbeDispatch}from '+JSON.stringify(join(import.meta.dir,'provider-probe-policy.ts'))+';\n'+s;
  s=one(s,'recordAndContinue?:boolean; remoteDiskObservationPath?:string;', 'recordAndContinue?:boolean;providerProbeEnabled?:boolean; remoteDiskObservationPath?:string;');
  s=one(s,"const data=await request.json() as any;check(!stopReason", "const data=await request.json() as any;if(data.providerSlug==='fireworks'){check(options.providerProbeEnabled!==false,'provider_probe_disabled');verifyProviderProbeScope(data.providerProbeScopePin,data);}check(!stopReason");
  s=one(s,"const providerSlug=['chembench','chemiq'].includes(data.slug)?(data.providerSlug??'digitalocean'):'digitalocean';","const providerSlug=data.providerSlug==='fireworks'?'fireworks':['chembench','chemiq'].includes(data.slug)?(data.providerSlug??'digitalocean'):'digitalocean';");
  s=one(s,'lane={slug:data.slug,providerSlug,runId:', 'lane={providerProbeScopePin:data.providerProbeScopePin,slug:data.slug,providerSlug,runId:');
  s=one(s,"prices:['chembench','chemiq'].includes(lane.slug)&&lane.providerSlug!=='digitalocean'?approvedPrices(lane.providerSlug):parent.prices", "prices:lane.providerSlug==='fireworks'?verifyProviderProbeScope(lane.providerProbeScopePin,lane).pricesPin:['chembench','chemiq'].includes(lane.slug)&&lane.providerSlug!=='digitalocean'?approvedPrices(lane.providerSlug):parent.prices");
  s=one(s,"const expectedRoute=supplierProfile(lane.providerSlug);","if(lane.providerSlug==='fireworks')verifyProviderProbeForward(lane,raw);const expectedRoute=supplierProfile(lane.providerSlug);");
  s=one(s,'lane.forwarded.add(seq);',"if(lane.providerSlug==='fireworks')markProviderProbeDispatch(lane,raw);lane.forwarded.add(seq);");
  s=one(s,'transportPolicy:{chembench:',"providerProbeCapability:options.providerProbeEnabled===false?null:'signed-fireworks-two-request-only-v1',transportPolicy:{chembench:");
  s=one(s,"const journal=jsonPin(config.journal.configPin);check(","const journal=jsonPin(config.journal.configPin);if(lane.providerSlug==='fireworks'){verifyProviderProbeScope(lane.providerProbeScopePin,lane);check(journal.providerSlug==='fireworks'&&journal.providerName==='Fireworks','provider_probe_actual_cash_provider_identity');}check(");
 }
 return s;
}
