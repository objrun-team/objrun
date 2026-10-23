/** Original FW task authority plus an explicitly signed transport-only opt-in. */
import{readFileSync}from'node:fs';import{resolve}from'node:path';import{createHash,verify}from'node:crypto';
import{verifyProviderRoute as originalRoute,verifyProviderRouteForward as originalForward,markProviderRouteDispatch as originalMark}from'./provider-task-route-continuation-policy-v1.ts';
import{verifyScopedTransportBinding,verifyProviderProbeScope,verifyProviderProbeForward,markProviderProbeDispatch}from'./provider-probe-scoped-transport-policy-v3.ts';
function need(v:unknown,w:string):asserts v{if(!v)throw Error('task_scoped_transport:'+w)}
function same(a:any,b:any){return a&&b&&resolve(a.path)===resolve(b.path)&&a.bytes===b.bytes&&a.sha256===b.sha256}
function pin(p:any){need(p&&typeof p.path==='string'&&Number.isSafeInteger(p.bytes),'pin_schema');const b=readFileSync(p.path);need(b.length===p.bytes&&createHash('sha256').update(b).digest('hex')===p.sha256,'pin_changed');return b}
export function verifyTaskTransportAuthorization(a:any,lane:any){if(!a.transportProfilePin)return verifyScopedTransportBinding(a);
 need(a.supplier==='fireworks'&&['formal-task','formal-consumer-acceptance'].includes(a.scopePhase),'original_fw_scope');
 const required=[a.transportProfilePin,a.proxyStartReceiptPin,a.transportAcceptancePin];need(required.every(Boolean),'explicit_transport_proof_required');
 const manifest=JSON.parse(pin(a.manifestPin).toString());
 for(const p of required)need(manifest.provenance?.sourcePins?.some((x:any)=>same(x,p))&&manifest.provenance?.contractPins?.some((x:any)=>same(x,p))&&lane.sourcePins.some((x:any)=>same(x,p)),'actual_manifest_source_contract_membership');
 const envelope=JSON.parse(pin(a.transportAcceptancePin).toString()),proof=envelope.proof,key=pin(envelope.authorityPublicPin);
 need(envelope.protocol==='bench-signed-scoped-openrouter-transport-actual-proof-v1'&&envelope.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(proof)),key,Buffer.from(envelope.signature,'base64')),'actual_transport_proof_signature');
 need(proof.accepted===true&&proof.actualModelRequests>=1&&proof.actualModelRequests<=2&&proof.allProbeRequestsClosed===true&&proof.parentLeaseReleased===true&&proof.knownUnknownFullyRecorded===true&&proof.supplier==='fireworks'&&same(proof.transportProfilePin,a.transportProfilePin),'actual_transport_probe_scope');
 need(proof.model===a.model&&proof.canonicalModel===a.canonicalModel&&proof.reasoning==='high'&&proof.providerSeconds===600,'actual_transport_original_model');
 const result=JSON.parse(pin(proof.actualResultPin).toString());need(result.protocol==='bench-original-accounted-provider-probe-result-v1'&&result.accepted===true&&result.probeStage==='real-model-probe'&&result.actualBenchTasks===0&&result.referenceCalls===0&&result.gradeCalls===0&&result.laneClosure?.closed===true&&result.knownUnknownFeesRetained===true&&result.results.length===proof.actualModelRequests,'actual_original_accounted_probe_result');
 for(const row of result.results){const response=JSON.parse(pin(row.responsePin).toString());need(row.httpStatus===200&&row.actualFormatValidated===true&&response.provider==='Fireworks'&&[a.model,a.canonicalModel].includes(response.model)&&Number.isFinite(response.usage?.cost)&&response.usage.cost>=0,'actual_provider_response_identity_cost_format')}
 return verifyScopedTransportBinding(a);
}
export function verifyProviderRoute(lane:any){if(!lane.providerTaskRouteEntryPin)return verifyProviderProbeScope(lane.providerProbeScopePin,lane);return verifyTaskTransportAuthorization(originalRoute(lane),lane)}
export function verifyProviderRouteForward(lane:any,raw:string){if(!lane.providerTaskRouteEntryPin)return verifyProviderProbeForward(lane,raw);const a=verifyProviderRoute(lane);originalForward(lane,raw);return a}
export function markProviderRouteDispatch(lane:any,raw:string){if(!lane.providerTaskRouteEntryPin)return markProviderProbeDispatch(lane,raw);verifyProviderRoute(lane);return originalMark(lane,raw)}
