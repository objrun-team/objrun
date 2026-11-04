import {test,expect} from 'bun:test';
import {withOneInterfaceRetry,transientInterfaceReceipt,interfaceFailure} from './humaneval-interface-policy-v2.ts';

test('successful requests are not retried',async()=>{
  let calls=0;
  const value=await withOneInterfaceRetry('task',async()=>{calls++;return 'ok';},{receipt:()=>({httpStatus:200}),event:()=>{throw Error('unexpected retry')},wait:async()=>{}});
  expect(value).toBe('ok');expect(calls).toBe(1);
});
test('an unknown socket failure retries once and retains the original receipt',async()=>{
  const paths:string[]=[],events:any[]=[];
  const receipts:any={'task':{httpStatus:0,unknownCost:true,fault:'socket closed'}};
  const value=await withOneInterfaceRetry('task',async path=>{paths.push(path);if(path==='task')throw Error('ProviderTransportUnknown');receipts[path]={httpStatus:200};return 'recovered';},{receipt:path=>receipts[path],event:e=>events.push(e),wait:async()=>{}});
  expect(value).toBe('recovered');expect(paths).toEqual(['task','task/authorized-interface-retry-1']);expect(events.length).toBe(1);expect(receipts.task.unknownCost).toBe(true);
});
test('exhausted retries affect one task while another task completes',async()=>{
  let failedCalls=0,successfulCalls=0;
  const failed=withOneInterfaceRetry('failed',async()=>{failedCalls++;throw Error('ProviderTransportUnknown');},{receipt:()=>({httpStatus:0,unknownCost:true}),event:()=>{},wait:async()=>{}});
  const successful=withOneInterfaceRetry('good',async()=>{successfulCalls++;return 'ok';},{receipt:()=>({httpStatus:200}),event:()=>{},wait:async()=>{}});
  const outcomes=await Promise.allSettled([failed,successful]);
  expect(outcomes[0].status).toBe('rejected');expect(outcomes[1].status).toBe('fulfilled');expect(failedCalls).toBe(2);expect(successfulCalls).toBe(1);
});
test('explicit rate limits keep their existing three-attempt policy; missing receipts do not retry',async()=>{
  expect(transientInterfaceReceipt({httpStatus:429,fault:'ExplicitRateLimit'})).toBe(false);
  expect(transientInterfaceReceipt(undefined)).toBe(false);
  expect(transientInterfaceReceipt({httpStatus:400,fault:'bad schema'})).toBe(false);
  let calls=0;
  await expect(withOneInterfaceRetry('unknown',async()=>{calls++;throw Error('UncertainPriorDispatch');},{receipt:()=>undefined,event:()=>{},wait:async()=>{}})).rejects.toThrow('UncertainPriorDispatch');
  expect(calls).toBe(1);expect(interfaceFailure('UncertainPriorDispatch')).toBe(true);expect(interfaceFailure('wrong answer')).toBe(false);
});

test('HTTP 200 provider timeouts retry once; successful HTTP 200 responses do not',async()=>{
  expect(transientInterfaceReceipt({httpStatus:200,fault:'Provider timed out after 301480ms'})).toBe(true);
  expect(transientInterfaceReceipt({httpStatus:200,fault:undefined})).toBe(false);
  const paths:string[]=[],receipts:any={first:{httpStatus:200,fault:'Provider timed out after 301480ms'}};
  const value=await withOneInterfaceRetry('first',async path=>{paths.push(path);if(path!=='first')receipts[path]={httpStatus:200};return path;},{receipt:path=>receipts[path],event:()=>{},wait:async()=>{}});
  expect(value).toBe('first/authorized-interface-retry-1');expect(paths.length).toBe(2);
});
