/** Additive isolated source candidate. It never edits a running or signed module. */
import {join} from 'node:path';
import {providerTaskRouteSource} from './provider-task-route-source-v3.ts';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('async_adoption_exact_anchor:'+a);return s.replace(a,b);}
export function asyncAdoptionSource(path:string,raw:string){
 let s=providerTaskRouteSource(path,raw);const name=path.replaceAll('\\','/').split('/').pop();
 if(name==='unlimited-adopted-parent.ts'){
  s='import{runPinnedSourceRequest,verifyPinInCurrentSourceRequest}from '+JSON.stringify(join(import.meta.dir,'request-scoped-source-proof-v3.ts'))+';\n'+s;
  const start=s.indexOf(' const guard=()=>{'),end=s.indexOf('\n const immutable=',start);
  if(start<0||end<start)throw Error('async_adoption_original_guard_scope');
  const old=s.slice(start,end);s=s.slice(0,start)+old.replaceAll('verifyPin(','verifyPinInCurrentSourceRequest(')+s.slice(end);
  const pins='[plan.financialAuthorityPin,plan.currentPricesPin,jsonPin(plan.currentPricesPin).originalResponsePin,signedPin,plan.sourceLoaderPin,ownerGuardPin,plan.oldOwnerGuardPin,plan.oldHealthPin,plan.oldAllocationPin,plan.oldPoolPin,plan.originalParentPin,plan.canonicalOwnerPin,...plan.sourcePins,...parent.sourcePins,parent.pricesPin,parent.balancePin]';
  const key="actualPin(join(root,'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/review-authority.public.pem'))";
  s=one(s," const lease:any={root,currency:'USD',",` const lease:any={withVerifiedSourceRequest:(extra:any[],deadlineMs:number,fn:any,assertCurrent=true)=>runPinnedSourceRequest({pins:[...${pins},...extra],signatures:[{envelopePin:signedPin,publicKeyPin:${key},protocol:'bench-signed-unlimited-financial-adoption-v1',payloadField:'plan'},{envelopePin:plan.sourceLoaderPin,publicKeyPin:${key},protocol:'bench-signed-financial-source-config-v1',payloadField:'config'}]},deadlineMs,()=>{if(assertCurrent)guard();return fn()}),verifyRequestSourcePin:verifyPinInCurrentSourceRequest,root,currency:'USD',`);
 }
 if(name==='broker-adoption-v76.ts'){
  s='import{runOutsidePinnedSourceRequest}from '+JSON.stringify(join(import.meta.dir,'request-scoped-source-proof-v3.ts'))+';\n'+s;
  s=one(s,'  async function execute(job:Job) {','  async function executeOriginal(job:Job) {');
  s=one(s,'  function pump() {','  const execute=(job:Job)=>runOutsidePinnedSourceRequest(()=>executeOriginal(job));\n  function pump() {');
  s=one(s,'for(const pin of lane.sourcePins)verifyPin(pin);register(lane);syncCash(lane);','for(const pin of lane.sourcePins)(parent?.verifyRequestSourcePin??verifyPin)(pin);register(lane);syncCash(lane);');
  s=one(s,'      assertLane(lane);for(const other of lanes.values())',"      if(parent?.withVerifiedSourceRequest)await parent.withVerifiedSourceRequest(lane.sourcePins,Date.now()+600000,()=>assertLane(lane));else assertLane(lane);for(const other of lanes.values())");
  s=one(s,'  const fetchHandler=async(request:Request)=>{','  const originalFetchHandler=async(request:Request)=>{');
  s=one(s,"        for(const pin of data.sourcePins){check(within(root,pin.path),'lane_source_outside_code_root');verifyPin(pin);}","        for(const pin of data.sourcePins)check(within(root,pin.path),'lane_source_outside_code_root');if(parent?.withVerifiedSourceRequest)await parent.withVerifiedSourceRequest(data.sourcePins,Date.now()+15000,()=>{for(const pin of data.sourcePins){check(within(root,pin.path),'lane_source_outside_code_root');parent.verifyRequestSourcePin(pin);}});else for(const pin of data.sourcePins){check(within(root,pin.path),'lane_source_outside_code_root');verifyPin(pin);}");
  s=one(s,"  const server=Bun.serve({hostname:'127.0.0.1',", "  const fetchHandler=(request:Request)=>parent?.withVerifiedSourceRequest?parent.withVerifiedSourceRequest([],Date.now()+(new URL(request.url).pathname==='/health'?5000:new URL(request.url).pathname==='/forward'?600000:15000),()=>originalFetchHandler(request),false):originalFetchHandler(request);\n  const server=Bun.serve({hostname:'127.0.0.1',");
 }
 if(name==='start-unlimited-broker.ts')s=one(s,"from'./provider-task-route-loader-v3.ts'","from'./provider-task-route-async-loader-v3.ts'");
 return s;
}
