/** Immutable continuation-only neutral probe scope. No ordinary task authority. */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {verify,createHash} from 'node:crypto';
const sha=(b:Buffer|string)=>createHash('sha256').update(b).digest('hex');
function need(v:unknown,w:string):asserts v {if(!v)throw Error(w)}
function pin(p:any){need(p&&typeof p.path==='string'&&Number.isSafeInteger(p.bytes),'probe_pin');const b=readFileSync(p.path);need(b.length===p.bytes&&sha(b)===p.sha256,'probe_pin_changed');return b}
const providers:Record<string,string>={fireworks:'Fireworks',relace:'Relace',wafer:'Wafer'};
export function verifyProviderProbeScope(scopePin:any,lane:any){
 const e=JSON.parse(pin(scopePin).toString()),p=e.scope,key=pin(e.authorityPublicPin);
 need(e.protocol==='bench-signed-original-provider-probe-scope-v1'&&e.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(p)),key,Buffer.from(e.signature,'base64')),'probe_signature');
 need(sha(pin(p.humanAuthorityPin))==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e','probe_human_authority');
 need(sha(pin(p.continuationAuthorityPin))==='94d68f9799b657b886c7887bb7b2f2230130e84fab5e535d784f25273e9d31a5','probe_continuation_authority');
 const zero=p.probeStage==='zero-request-acceptance';
 need(p.protocol==='bench-original-provider-probe-scope-v1'&&p.noBenchContent===true&&p.formal===false&&p.referenceCalls===0&&p.gradeCalls===0&&(zero?p.maximumModelRequests===0:Number.isInteger(p.maximumModelRequests)&&p.maximumModelRequests>=1&&p.maximumModelRequests<=2)&&providers[p.providerSlug]===p.providerName&&p.model==='deepseek/deepseek-v4.1-flash'&&p.canonicalModel==='deepseek/deepseek-v4.1-flash-20260910'&&p.reasoningEffort==='high'&&p.providerSeconds===600&&p.allowFallbacks===false,'probe_exact_scope');
 const start=Date.parse(p.validFromUtc),end=Date.parse(p.expiresAtUtc),now=Date.now();
 need(Number.isFinite(start)&&Number.isFinite(end)&&start<=now&&now<end&&end-start<=1900000&&now-start<=1900000,'probe_fresh_independent_window');
 need(/^repair-[0-9TZ-]+$/.test(p.runId)&&lane.providerSlug===p.providerSlug&&lane.slug==='terminal-bench'&&lane.runId===p.runId&&resolve(lane.output)===resolve(p.output)&&lane.sourcePins.some((x:any)=>x.sha256===scopePin.sha256&&resolve(x.path)===resolve(scopePin.path)),'probe_lane_binding');
 need(Array.isArray(p.requestPins)&&p.requestPins.length===p.maximumModelRequests&&new Set(p.requestPins.map((x:any)=>x.sha256)).size===p.requestPins.length,'probe_request_count');
 for(const r of p.requestPins){const b=JSON.parse(pin(r).toString());need(b.model===p.model&&b.reasoning?.enabled===true&&b.reasoning?.effort==='high'&&b.provider?.only?.length===1&&b.provider.only[0]===p.providerSlug&&b.provider.allow_fallbacks===false&&b.stream===false&&Number.isInteger(b.max_tokens)&&b.max_tokens>0&&b.max_tokens<=1024,'probe_frozen_wire')}
 const prices=JSON.parse(pin(p.pricesPin).toString());pin(prices.originalResponsePin);need(prices.providerSlug===p.providerSlug&&prices.model===p.model&&prices.actualOfficialGET===true&&prices.modelCalls===0,'probe_actual_price_identity');return p;
}
export function verifyProviderProbeForward(lane:any,raw:string){const p=verifyProviderProbeScope(lane.providerProbeScopePin,lane);need(lane.forwarded.size<p.maximumModelRequests&&p.requestPins.some((x:any)=>x.sha256===sha(raw)),'probe_request_or_limit');return p}
export function markProviderProbeDispatch(lane:any,raw:string){verifyProviderProbeForward(lane,raw);const h=sha(raw);need(!(lane.providerProbeDispatchedHashes??[]).includes(h),'probe_duplicate_dispatch');(lane.providerProbeDispatchedHashes??=[]).push(h)}
