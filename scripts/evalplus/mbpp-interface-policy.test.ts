import {test,expect} from 'bun:test';
import {withOneInterfaceRetry,transientInterfaceReceipt} from './mbpp-interface-policy-v2.ts';
test('provider504 wrapped in HTTP200 receives one separately logged retry',async()=>{
 let calls=0;const receipts=new Map<string,any>(),events:any[]=[];
 const result=await withOneInterfaceRetry('fixture',async path=>{calls++;receipts.set(path,calls===1?{httpStatus:200,fault:'Provider timed out after 301ms',unknownCost:true,actualCostUsd:null}:{httpStatus:200,fault:null,actualCostUsd:0.001});return calls;},{receipt:p=>receipts.get(p),event:e=>events.push(e),wait:async()=>{}});
 expect(result).toBe(2);expect(calls).toBe(2);expect(events).toHaveLength(1);expect(receipts.get('fixture').actualCostUsd).toBeNull();
});
test('a repeated confirmed interface failure stops after exactly two calls',async()=>{
 let calls=0;const r={httpStatus:200,fault:'Provider timeout',unknownCost:true};
 await expect(withOneInterfaceRetry('fixture',async()=>{calls++;return {};},{receipt:()=>r,event(){},wait:async()=>{}})).rejects.toThrow('ProviderFault');expect(calls).toBe(2);
});
test('missing durable receipt and transport-without-response do not authorize another dispatch',async()=>{
 for(const receipt of [undefined,{httpStatus:0,fault:'socket closed',unknownCost:true}]){
  let calls=0;await expect(withOneInterfaceRetry('fixture',async()=>{calls++;throw Error('UncertainPriorRequest');},{receipt:()=>receipt,event(){},wait:async()=>{}})).rejects.toThrow('UncertainPriorRequest');expect(calls).toBe(1);
 }
});
test('authentication and explicit rate limit are excluded from timeout policy',()=>{
 expect(transientInterfaceReceipt({httpStatus:401,fault:'auth'})).toBe(false);expect(transientInterfaceReceipt({httpStatus:429,fault:'ExplicitRateLimit'})).toBe(false);
});
