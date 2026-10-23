/** Exact root-authorized same-model routing; does not start, stop, adopt or forward. */
import {readFileSync} from 'node:fs';import {verify} from 'node:crypto';
import {verifyPin,demand} from './manifest.ts';
import {officialOpenRouterFault,openRouterRateLimitRejection} from '../repair-2026-10-10/full-f/shared/digitalocean-provider.ts';
const ROOT='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98';
const MODEL='deepseek/deepseek-v4.1-flash',CANONICAL=MODEL+'-20260910';
export const ORIGINAL_PROVIDER_CEILINGS=Object.freeze({input:.3,cachedInput:.006,output:1.2});
const NAMES:Record<string,string>={digitalocean:'DigitalOcean',fireworks:'Fireworks','deepinfra/fp8':'DeepInfra'};
const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
export function validateProviderTransitionData(c:any,now=Date.now()){
 demand(c.protocol==='bench-exact-provider-transition-v1'&&c.model===MODEL&&c.canonicalModel===CANONICAL,'exact_original_transition_model');
 demand(c.providerSeconds===600&&c.reasoning==='high'&&c.maxTokens===16384&&c.temperature===0&&c.parentCapUsd===418.777826378,'original_transition_budget_and_inference');
 demand(NAMES[c.providerSlug]===c.providerName&&['fireworks','deepinfra/fp8'].includes(c.providerSlug),'explicit_approved_same_model_supplier');
 demand(same(c.reservationRates,ORIGINAL_PROVIDER_CEILINGS),'unchanged_transition_reservation_ceilings');
 demand(c.noUnknownRelease===true&&c.noCostReset===true&&c.noHistoricalLockEdits===true&&c.singleBroker===true&&c.originalSharedPool===16,'transition_keeps_all_original_custody');
 verifyPin(c.metadata.responsePin);verifyPin(c.metadata.actualGETCapturePin);verifyPin(c.humanAuthorizationPin);
 demand(c.metadata.url==='https://openrouter.ai/api/v1/models/'+MODEL+'/endpoints'&&c.metadata.method==='GET'&&c.metadata.httpStatus===200,'actual_official_provider_metadata');
 const age=now-Date.parse(c.metadata.observedAtUtc);demand(age>=0&&age<86400000,'fresh_provider_metadata');
 const raw=JSON.parse(readFileSync(c.metadata.responsePin.path,'utf8')),matches=raw.data?.endpoints?.filter((r:any)=>r.tag===c.providerSlug&&r.provider_name===c.providerName&&r.model_id===MODEL);
 demand(raw.data?.id===MODEL&&matches?.length===1,'exact_official_provider_endpoint');
 const endpoint=matches[0];demand(endpoint.name.endsWith(CANONICAL)&&['tools','tool_choice','reasoning','max_tokens'].every(x=>endpoint.supported_parameters.includes(x))&&endpoint.supports_tool_choice?.auto===true&&endpoint.supports_tool_choice?.function===true&&endpoint.supports_tool_choice?.required===true,'original_tools_and_high_reasoning_supported');
 if(c.providerSlug==='deepinfra/fp8')demand(endpoint.quantization==='fp8','exact_deepinfra_quantization');
 const prices=[endpoint.pricing,...(endpoint.pricing.overrides??[])],observed:any={};
 for(const [key,field] of Object.entries({input:'prompt',cachedInput:'input_cache_read',output:'completion'})){const value=Math.max(...prices.map((r:any)=>Number(r[field]??endpoint.pricing[field])))*1e6;demand(Number.isFinite(value)&&value>=0&&value<=ORIGINAL_PROVIDER_CEILINGS[key as keyof typeof ORIGINAL_PROVIDER_CEILINGS]+1e-12,'supplier_price_exceeds_original_ceiling:'+key);observed[key]=value}
 demand(Object.keys(observed).every(k=>Math.abs(observed[k]-c.observedPeakRates[k])<1e-12),'exact_official_transition_rates');
 return Object.freeze({kind:'openrouter-deepseek',model:MODEL,canonicalModel:CANONICAL,baseURL:'https://openrouter.ai/api/v1',endpoint:'https://openrouter.ai/api/v1/chat/completions',keyEnv:'OPENROUTER_API_KEY',currency:'USD',providerName:c.providerName,providerSlug:c.providerSlug,peakRates:ORIGINAL_PROVIDER_CEILINGS,routing:Object.freeze({only:[c.providerSlug],allow_fallbacks:false,max_price:{prompt:.3,completion:1.2}}),forcedToolMode:'constrained-auto',observedPeakRates:observed,metadataStatus: endpoint.status,providerHealthEstablished:false});
}
export function loadRootProviderTransition(planPin:any){
 verifyPin(planPin);const e=JSON.parse(readFileSync(planPin.path,'utf8'));verifyPin(e.authorityPin);
 demand(e.protocol==='bench-root-signed-provider-transition-v1'&&e.authorityPin.sha256===ROOT&&verify(null,Buffer.from(JSON.stringify(e.transition)),readFileSync(e.authorityPin.path),Buffer.from(e.signature,'base64')),'root_signed_provider_transition_required');
 return{transition:e.transition,provider:validateProviderTransitionData(e.transition)};
}
export function requireExactTransitionWire(body:any,provider:any){
 demand(body.model===MODEL&&same(body.provider,provider.routing)&&body.reasoning?.enabled===true&&body.reasoning.effort==='high'&&body.reasoning.exclude===false&&body.temperature===0&&body.max_tokens===16384&&body.stream!==true&&body.seed===undefined,'exact_transition_provider_wire');
}
export function transitionReceiptFault(body:any,httpStatus:number,provider:any){
 if(openRouterRateLimitRejection(body,httpStatus,provider.providerName))return undefined;
 if(httpStatus!==200)return 'ProviderHttpFailure';
 return officialOpenRouterFault(body,provider.providerName);
}
