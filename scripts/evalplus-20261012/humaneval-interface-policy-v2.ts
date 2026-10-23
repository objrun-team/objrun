// HumanEval-only policy, authorized by the user on 2026-10-12.
export function transientInterfaceReceipt(r:any):boolean {
  if (!r || r.fault==='ExplicitRateLimit') return false;
  return (r.httpStatus===0 && r.unknownCost===true) || [408,500,502,503,504].includes(r.httpStatus) || (r.httpStatus===200 && /timed? out|timeout|socket.*closed|connection.*closed/i.test(String(r.fault??'')));
}

export function interfaceFailure(error:unknown):boolean {
  return /ProviderFault|ProviderTransportUnknown|UncertainPrior|FiniteRateRetriesExhausted/.test(String(error));
}

export async function withOneInterfaceRetry<T>(dir:string, invoke:(path:string)=>Promise<T>, options:{
  receipt:(path:string)=>any;
  event:(value:any)=>void;
  wait:()=>Promise<unknown>;
}):Promise<T> {
  let lastError:unknown;
  for (let attempt=0;attempt<2;attempt++) {
    const path=attempt===0?dir:dir+'/authorized-interface-retry-1';
    try {
      const result=await invoke(path);
      const receipt=options.receipt(path);
      if (transientInterfaceReceipt(receipt)) throw Error('ProviderFault:'+receipt.fault);
      return result;
    } catch (error) {
      lastError=error;
      // Requests without a durable receipt are isolated to their task; do not guess their status.
      if (attempt===1 || !transientInterfaceReceipt(options.receipt(path))) throw error;
      options.event({originalCall:path,retryCall:dir+'/authorized-interface-retry-1',retryLimit:1,reason:String(error)});
      await options.wait();
    }
  }
  throw lastError;
}
