/** A bounded neutral prompt through the original shared admission/journal/cash. */
import{readFileSync,mkdirSync,writeFileSync}from'node:fs';import{join}from'node:path';import{createHash}from'node:crypto';
import{installUnlimitedFinancialLoader}from'./provider-probe-loader.ts';
const [loaderPath,scopePath]=process.argv.slice(2),config=installUnlimitedFinancialLoader(loaderPath);
const {actualPin,jsonPin,demand,verifyPin}=await import('../benchmark-repair/paid-resource-proof-v2.ts');
const {verifyProviderProbeScope}=await import('./provider-probe-policy.ts');
const {verifyAdoptedActivation}=await import('./unlimited-readonly-guard-retry.ts');
const {acquireOwnedFullFAdmissionV76}=await import('../benchmark-campaign/full-f/novaeve_formal_v1/broker/shared-admission-owned-price-renewal.ts');
const {createCampaignJournal,inspectCampaignJournal}=await import('../benchmark-campaign/full-f/shared/supplier-journal.ts');
const {createBenchmarkCash}=await import('../benchmark-campaign/full-f/shared/supplier-usd-cash.ts');
const {ScientificJournalProxy}=await import('../benchmark-campaign/full-f/shared/supplier-proxy.ts');
const {supplierProfile}=await import('../benchmark-campaign/full-f/shared/chembench-supplier-profiles.ts');
const {benchmarkProviderRequest}=await import('../benchmark-campaign/full-f/shared/supplier-inference.ts');
const scopePin=actualPin(scopePath),envelope=jsonPin(scopePin),scope=envelope.scope,sourcePins=[...config.sourcePins,scopePin],lane={slug:'terminal-bench',providerSlug:'fireworks',providerProbeScopePin:scopePin,runId:scope.runId,output:scope.output,sourcePins};verifyProviderProbeScope(scopePin,lane);
verifyPin(scope.activationPin);const current=await verifyAdoptedActivation(scope.activationPin.path);demand(current.health.providerProbeCapability==='signed-fireworks-two-request-only-v1','current_single_shared_broker_does_not_support_probe_route');
const owner=Number(process.env.NOVAEVE_RESOURCE_LEASE_PID),token=process.env.NOVAEVE_RESOURCE_TOKEN;
demand(Number.isInteger(owner)&&owner>0&&token,'original_shared_parent_resource_capability_required');
const admission=await acquireOwnedFullFAdmissionV76({...lane,root:scope.root,connection:current.connection,ownedResource:{pid:owner,token}});
const out=scope.output,jdir=join(out,'journal'),cdir=join(out,'cash'),failure=join(out,'failure-receipts');for(const p of [jdir,cdir,failure])mkdirSync(p,{recursive:true});
const provider=supplierProfile('fireworks'),inference={maxTokens:1024,reasoningEffort:'high',temperature:0,seed:42,retryTimes:0,continueTimes:0};
const journal=createCampaignJournal({directory:jdir,campaign:scope.runId,capUsd:null,priorCampaignCostUpperBoundUsd:0,outputDirectory:out,provider}),cash=createBenchmarkCash({directory:cdir,runId:scope.runId,providerKind:'real-provider',admission,prices:scope.pricesPin,journal:{directory:jdir,configPin:actualPin(join(jdir,'journal-config.json')),sourcePin:actualPin(join(import.meta.dir,'../benchmark-campaign/full-f/shared/supplier-journal.ts'))}},provider),tickets=new Map();
const route='neutral/provider-auth-route-format',proxy=new ScientificJournalProxy(journal,{provider,inference,routes:new Set([route]),failureDirectory:failure,beforeAdmission:()=>admission.validateForwardSource(),beforeForward:(start,prefix,raw,r)=>{const fund=cash.beforeForward({id:scope.runId+'/'+start.requestSeq,route:r,rawRequest:Buffer.from(raw),capturedRequest:actualPin(start.requestFile),journal:{admitted:start,startPrefix:prefix}});tickets.set(start.requestSeq,fund.ticket);demand(fund.admitted,'probe_cash_not_admitted')},afterDurableFinish:r=>{cash.finish(tickets.get(r.requestSeq),{kind:'journal-finish',journalRef:{...r.journalRef,callId:String(r.requestSeq)}})},afterFailedJournalCapture:(start,_finish,e:any)=>{if(!start)return;const ticket=tickets.get(start.requestSeq);if(!ticket)return;if(e.journalRef)cash.finish(ticket,{kind:'journal-finish',journalRef:{...e.journalRef,callId:String(start.requestSeq)}});else cash.finish(ticket,{kind:'failed-capture',requestSeq:start.requestSeq,evidence:{files:e.files,responsePin:e.files.find((p:any)=>p.path.endsWith('response.json.gz')),rawResponseSha256:e.rawResponseSha256,usage:e.usage,httpStatus:e.httpStatus,providerAttempted:e.providerAttempted,originalPrefix:e.journalSnapshot.durablePrefix,reason:e.error}})},transport:raw=>admission.transport(raw)});
let probeError:unknown,closed:any;const results=[];
try{
 demand(scope.inputPins?.length===scope.maximumModelRequests,'probe_frozen_input_count');
 for(let i=0;i<scope.inputPins.length;i++){
  const input=jsonPin(scope.inputPins[i]),wire=JSON.stringify(benchmarkProviderRequest(input,inference,provider)),digest=createHash('sha256').update(wire).digest('hex');demand(digest===scope.requestPins[i].sha256,'probe_original_inference_exact_frozen_wire');
  const response=await proxy.handle(route,JSON.stringify(input));const path=join(out,'probe-response-'+i+'.json');writeFileSync(path,response.rawResponse,{flag:'wx'});const body=JSON.parse(response.rawResponse);demand(response.httpStatus===200&&body.provider==='Fireworks'&&[provider.model,provider.canonicalModel].includes(body.model)&&Number.isFinite(body.usage?.cost),'probe_actual_provider_model_cost');
  if(i===0){const calls=body.choices?.[0]?.message?.tool_calls;demand(calls?.length===1&&calls[0].function?.name==='report','probe_actual_named_tool_response');const value=JSON.parse(calls[0].function.arguments);demand(value?.ok===true&&Object.keys(value).length===1,'probe_actual_tool_response_format')}
  else{const value=JSON.parse(body.choices?.[0]?.message?.content);demand(value?.ok===true&&Object.keys(value).length===1,'probe_actual_json_response_format')}
  results.push({responsePin:actualPin(path),httpStatus:response.httpStatus,providerName:body.provider,servedModel:body.model,costUsd:body.usage.cost,actualFormatValidated:true});
 }
}catch(error){probeError=error;cash.poison('actual_probe_failed');}
finally{
 proxy.stop('probe_scope_finished');await proxy.drain();const inspection=inspectCampaignJournal(jdir);journal.exportLegacyLedger();const cashPin=cash.close();journal.close();closed=await admission.finishLightweight({cashPin});writeFileSync(join(out,'provider-probe-result.json'),JSON.stringify({protocol:'bench-original-accounted-provider-probe-result-v1',accepted:!probeError,probeStage:scope.probeStage,supplierLivenessProven:!probeError&&scope.maximumModelRequests>0,results,inspection,cashPin,laneClosure:closed,modelRequestLimit:scope.maximumModelRequests,actualBenchTasks:0,referenceCalls:0,gradeCalls:0,resourceReleasedByOriginalCaller:false,knownUnknownFeesRetained:true,error:probeError instanceof Error?{name:probeError.name,message:probeError.message}:probeError?String(probeError):null},null,2)+'\n',{flag:'wx'});
}
if(probeError)throw probeError;console.log(JSON.stringify({accepted:true,actualFormatValidated:results.length,originalSharedLaneClosed:closed.closed,modelRequests:journal.snapshot().acceptedRequestCount,noBenchTasks:true}));
