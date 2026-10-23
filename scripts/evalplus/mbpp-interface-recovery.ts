// Applies only to the explicitly authorized 22-task recovery scope.
export function transientRecoveryReceipt(r:any):boolean {
 if(!r || r.fault==='ExplicitRateLimit')return false;
 if([408,500,502,503,504].includes(r.httpStatus))return true;
 const connection=/socket.*closed|connection.*closed|connection reset|network connection lost|ECONNRESET|ECONNREFUSED|ETIMEDOUT|fetch failed|timed? out|timeout/i;
 return (r.httpStatus===200 || (r.httpStatus===0 && r.dispatched===true && r.unknownCost===true)) && connection.test(String(r.fault??''));
}

export async function withRecoveryInterfaceRetry<T>(dir:string,invoke:(path:string)=>Promise<T>,options:{
 receipt:(path:string)=>any;event:(value:any)=>void;wait:(milliseconds:number)=>Promise<unknown>;
}):Promise<T>{
 for(let attempt=0;attempt<3;attempt++){
  const path=attempt===0?dir:dir+'/authorized-interface-retry-'+attempt;
  try{
   const result=await invoke(path);const receipt=options.receipt(path);
   if(transientRecoveryReceipt(receipt))throw Error('ProviderFault:'+receipt.fault);
   return result;
  }catch(error){
   // A missing receipt is never retried within a live run. Old unanswered
   // requests require an exited owner and a separately recorded recovery pass.
   const receipt=options.receipt(path);
   if(attempt===2 || !transientRecoveryReceipt(receipt))throw error;
   const delayMs=receipt.httpStatus===0?2000*(attempt+1):5000*(attempt+1);
   options.event({originalCall:path,retryCall:dir+'/authorized-interface-retry-'+(attempt+1),retryLimit:2,reason:String(error),delayMs,unknownCostRetained:receipt.unknownCost===true});
   await options.wait(delayMs);
  }
 }
 throw Error('FiniteInterfaceRecoveryExhausted');
}
