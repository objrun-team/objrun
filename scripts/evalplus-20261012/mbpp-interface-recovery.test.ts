import {expect,test} from 'bun:test';
import {withRecoveryInterfaceRetry as recover,transientRecoveryReceipt} from './mbpp-interface-recovery.ts';

test('authorized recovery continues after a durably recorded closed socket',async()=>{
 const receipts=new Map<string,any>();const paths:string[]=[];
 const result=await recover('fresh-authorized-pass',async path=>{
   paths.push(path);
   if(paths.length===1){receipts.set(path,{dispatched:true,httpStatus:0,unknownCost:true,fault:'Error: The socket connection was closed unexpectedly.',seconds:5.003});throw Error('ProviderTransportUnknown:'+path);}
   receipts.set(path,{dispatched:true,httpStatus:200,unknownCost:false,fault:null});return 'genuine provider response';
 },{receipt:path=>receipts.get(path),event:()=>{},wait:async()=>{}});
 expect(result).toBe('genuine provider response');expect(paths).toHaveLength(2);
 expect(receipts.get(paths[0]).unknownCost).toBe(true);
});

test('HTTP 200 provider timeout retries finitely and preserves every receipt',async()=>{
 const receipts=new Map<string,any>();const paths:string[]=[];const waits:number[]=[];
 await expect(recover('call',async path=>{paths.push(path);receipts.set(path,{httpStatus:200,fault:'Provider timed out after 301215ms',unknownCost:true});return 'error response';},{receipt:p=>receipts.get(p),event:()=>{},wait:async n=>{waits.push(n);}})).rejects.toThrow('ProviderFault');
 expect(paths).toEqual(['call','call/authorized-interface-retry-1','call/authorized-interface-retry-2']);
 expect(waits).toEqual([5000,10000]);expect(receipts.size).toBe(3);
});

test('missing receipt, permanent faults, rate limits and solving failures are not transport retries',async()=>{
 for(const receipt of [undefined,{httpStatus:401,fault:'unauthorized'},{httpStatus:429,fault:'ExplicitRateLimit'},{httpStatus:200,fault:'UnexpectedOpenRouterProvider'},{httpStatus:0,dispatched:true,unknownCost:true,fault:'SyntaxError: Unexpected token'}]){
  let count=0;await expect(recover('call',async()=>{count++;throw Error('original');},{receipt:()=>receipt,event:()=>{throw Error('unexpected retry');},wait:async()=>{}})).rejects.toThrow('original');expect(count).toBe(1);
 }
 expect(transientRecoveryReceipt({httpStatus:200,fault:null})).toBe(false);
 expect(transientRecoveryReceipt({httpStatus:0,dispatched:true,unknownCost:true,fault:'ECONNRESET'})).toBe(true);
});
