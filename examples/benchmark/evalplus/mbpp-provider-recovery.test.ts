import {expect,test} from 'bun:test';
import {endpointAllowed,providerRoute,withDifferentProviders} from './mbpp-provider-recovery.ts';
const endpoint=(tag:string,quantization:string)=>({tag,quantization,status:0,pricing:{prompt:'0.0000006',completion:'0.0000024'}});
test('all known low-precision formats are excluded while authorized unknown is admitted',()=>{
 for(const q of ['fp4','fp8','mxfp8','int4','int8','fp6','nvfp4','mxfp4',undefined])expect(endpointAllowed(endpoint('route',q as any))).toBe(false);
 for(const q of ['fp32','fp16','bf16','unknown'])expect(endpointAllowed(endpoint('route',q))).toBe(true);
 expect(()=>providerRoute(endpoint('baseten/fp8','fp8'))).toThrow('Quantized');
 const route=providerRoute(endpoint('baseten/fast','fp32'));expect(route.only).toEqual(['baseten/fast']);expect(route.allow_fallbacks).toBe(false);expect(route.quantizations).not.toContain('fp8');expect(route.max_price).toEqual({prompt:0.6,completion:2.4});
});
test('a 504 switches endpoint in a separate durable directory; genuine success is used once',async()=>{
 const providers=[endpoint('one','unknown'),endpoint('baseten/fast','fp32')],receipts=new Map<string,any>(),paths:string[]=[],events:any[]=[];
 const result=await withDifferentProviders('call',providers,async(path,provider)=>{paths.push(path);receipts.set(path,provider.tag==='one'?{httpStatus:200,fault:'Provider timed out after 301213ms',unknownCost:true}:{httpStatus:200,fault:null,unknownCost:false});return provider.tag;},{receipt:p=>receipts.get(p),event:e=>events.push(e),wait:async()=>{}});
 expect(result).toBe('baseten/fast');expect(paths).toEqual(['call/provider-one','call/provider-baseten-fast']);expect(events).toHaveLength(1);expect(receipts.get(paths[0]).unknownCost).toBe(true);
});
test('missing receipts and authentication failures never dispatch another provider',async()=>{
 for(const r of [undefined,{httpStatus:401,fault:'Unauthorized'}]){
  let calls=0;await expect(withDifferentProviders('call',[endpoint('one','unknown'),endpoint('two','fp32')],async()=>{calls++;throw Error('stop');},{receipt:()=>r,event:()=>{},wait:async()=>{}})).rejects.toThrow('stop');expect(calls).toBe(1);
 }
});
