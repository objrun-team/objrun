/** A signed, bounded non-Bench probe; ordinary lanes retain their original route. */
import{readFileSync}from'node:fs';import{resolve}from'node:path';import{verify,createHash}from'node:crypto';
const digest=(b:Buffer|string)=>createHash('sha256').update(b).digest('hex');
function need(v:unknown,w:string):asserts v{if(!v)throw Error(w)}
function pinned(p:any){need(p&&typeof p.path==='string'&&Number.isSafeInteger(p.bytes),'provider_probe_pin');const b=readFileSync(p.path);need(b.length===p.bytes&&digest(b)===p.sha256,'provider_probe_pin_changed');return b}
export function verifyProviderProbeScope(scopePin:any,lane:any){
 const envelope=JSON.parse(pinned(scopePin).toString()),p=envelope.scope,key=pinned(envelope.authorityPublicPin);
 need(envelope.protocol==='bench-signed-original-provider-probe-scope-v1'&&envelope.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(p)),key,Buffer.from(envelope.signature,'base64')),'provider_probe_exact_signature');
 const authority=pinned(p.humanAuthorityPin);need(digest(authority)==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e','provider_probe_current_human_authority');
 const zero=p.probeStage==='zero-request-acceptance';
 need(p.protocol==='bench-original-provider-probe-scope-v1'&&p.noBenchContent===true&&p.formal===false&&p.referenceCalls===0&&p.gradeCalls===0&&(zero?p.maximumModelRequests===0:p.maximumModelRequests>=1&&p.maximumModelRequests<=2)&&p.providerSlug==='fireworks'&&p.providerName==='Fireworks'&&p.model==='deepseek/deepseek-v4.1-flash'&&p.canonicalModel==='deepseek/deepseek-v4.1-flash-20260910'&&p.reasoningEffort==='high'&&p.providerSeconds===600&&p.allowFallbacks===false,'provider_probe_exact_scope');
 need(Date.now()>=Date.parse(p.validFromUtc)&&Date.now()<Date.parse(p.expiresAtUtc)&&Date.parse(p.expiresAtUtc)<=Date.parse('2026-10-15T16:00:00Z'),'provider_probe_scope_time');
 need(/^repair-[0-9TZ-]+$/.test(p.runId)&&lane.providerSlug==='fireworks'&&lane.slug==='terminal-bench'&&lane.runId===p.runId&&resolve(lane.output)===resolve(p.output)&&lane.sourcePins.some((x:any)=>x.sha256===scopePin.sha256&&resolve(x.path)===resolve(scopePin.path)),'provider_probe_exact_lane_binding');
 need(Array.isArray(p.requestPins)&&p.requestPins.length===p.maximumModelRequests&&new Set(p.requestPins.map((x:any)=>x.sha256)).size===p.requestPins.length,'provider_probe_frozen_request_count');
 for(const r of p.requestPins){const raw=pinned(r),body=JSON.parse(raw.toString());need(body.model===p.model&&body.reasoning?.enabled===true&&body.reasoning?.effort==='high'&&body.provider?.only?.length===1&&body.provider.only[0]==='fireworks'&&body.provider.allow_fallbacks===false&&body.stream===false&&Number.isInteger(body.max_tokens)&&body.max_tokens>0&&body.max_tokens<=1024,'provider_probe_frozen_request_parameters')}
 const prices=JSON.parse(pinned(p.pricesPin).toString());pinned(prices.originalResponsePin);need(prices.providerSlug==='fireworks'&&prices.model===p.model&&prices.actualOfficialGET===true&&prices.modelCalls===0,'provider_probe_actual_price_identity');return p;
}
export function verifyProviderProbeForward(lane:any,raw:string){const p=verifyProviderProbeScope(lane.providerProbeScopePin,lane);need(lane.forwarded.size<p.maximumModelRequests&&p.requestPins.some((x:any)=>x.sha256===digest(raw)),'provider_probe_exact_request_or_count');return p}
export function markProviderProbeDispatch(lane:any,raw:string){verifyProviderProbeForward(lane,raw);const hash=digest(raw);need(!(lane.providerProbeDispatchedHashes??[]).includes(hash),'provider_probe_frozen_request_already_dispatched');(lane.providerProbeDispatchedHashes??=[]).push(hash)}
