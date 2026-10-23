// Bench-only routing. Precision-unknown endpoints are explicitly user-authorized.
export const ALLOWED_PRECISIONS=['fp32','fp16','bf16','unknown'];
export function endpointAllowed(endpoint:any):boolean {
 return typeof endpoint?.tag==='string' && endpoint.tag.length>0 && ALLOWED_PRECISIONS.includes(endpoint.quantization) && endpoint.status===0;
}
export function providerRoute(endpoint:any){
 if(!endpointAllowed(endpoint))throw Error('QuantizedOrUnavailableEndpoint:'+endpoint?.tag);
 const rows=[endpoint.pricing,...(endpoint.pricing?.overrides??[])];
 const peak=(field:string)=>Math.max(...rows.map((p:any)=>Number(p[field]??endpoint.pricing[field])))*1e6;
 const input=peak('prompt'),output=peak('completion');
 if(!Number.isFinite(input)||!Number.isFinite(output)||input<0||output<0)throw Error('UnknownProviderPricing');
 return {only:[endpoint.tag],allow_fallbacks:false,quantizations:ALLOWED_PRECISIONS,require_parameters:false,max_price:{prompt:input,completion:output}};
}
export function retryOnAnotherProvider(receipt:any):boolean {
 if(!receipt)return false;
 return receipt.fault==='ExplicitRateLimit'||[408,500,502,503,504].includes(receipt.httpStatus)||
  (receipt.httpStatus===404&&/endpoint|provider|route/i.test(String(receipt.fault)))||
  ([0,200].includes(receipt.httpStatus)&&/timed? out|timeout|socket.*closed|connection.*closed|connection reset|network connection lost|ECONNRESET|ECONNREFUSED|ETIMEDOUT|fetch failed/i.test(String(receipt.fault)));
}
export async function withDifferentProviders<T>(dir:string,endpoints:any[],invoke:(path:string,endpoint:any)=>Promise<T>,options:{receipt:(path:string)=>any;event:(value:any)=>void;wait:()=>Promise<unknown>}):Promise<T>{
 if(!endpoints.length||new Set(endpoints.map(e=>e.tag)).size!==endpoints.length||endpoints.some(e=>!endpointAllowed(e)))throw Error('InvalidProviderRecoveryAllowlist');
 for(let n=0;n<endpoints.length;n++){
  const endpoint=endpoints[n],path=dir+'/provider-'+endpoint.tag.replace(/[^a-zA-Z0-9_-]/g,'-');
  try{
   const result=await invoke(path,endpoint),r=options.receipt(path);
   if(retryOnAnotherProvider(r))throw Error('ProviderFault:'+r.fault);
   return result;
  }catch(error){
   const receipt=options.receipt(path);
   if(n===endpoints.length-1||!retryOnAnotherProvider(receipt))throw error;
   options.event({failedProvider:endpoint.tag,nextProvider:endpoints[n+1].tag,failedCall:path,reason:String(error),unknownCostRetained:receipt.unknownCost===true});
   await options.wait();
  }
 }
 throw Error('FiniteProviderRecoveryExhausted');
}
