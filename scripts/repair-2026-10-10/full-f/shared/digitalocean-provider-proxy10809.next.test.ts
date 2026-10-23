import {test,expect,spyOn,afterEach,mock} from 'bun:test';
import {benchmarkFetch,BENCHMARK_PROVIDER} from './digitalocean-provider-600-proxy10809.next.ts';
afterEach(()=>mock.restore());
const raw=JSON.stringify({model:BENCHMARK_PROVIDER.model,provider:{only:['digitalocean'],allow_fallbacks:false},reasoning:{enabled:true,effort:'high'},max_tokens:16384,messages:[{role:'user',content:'local transport control'}]});
test('same original wire payload and provider through explicitly authorized proxy',async()=>{
 let seen:any;
 spyOn(globalThis,'fetch').mockImplementation(async(url:any,init:any)=>{seen={url,init};return new Response('{}',{status:200});});
 await benchmarkFetch(raw,'synthetic-local-control-key');
 expect(seen.url).toBe(BENCHMARK_PROVIDER.endpoint);
 expect(seen.init.proxy).toBe('http://127.0.0.1:10809');
 expect(seen.init.body).toBe(raw);
 expect(seen.init.method).toBe('POST');
 expect(seen.init.headers.authorization).toBe('Bearer synthetic-local-control-key');
});
test('original 600 second transport timeout is retained',async()=>{
 let observed=0;
 spyOn(AbortSignal,'timeout').mockImplementation((ms:number)=>{observed=ms;return new AbortController().signal;});
 spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));
 await benchmarkFetch(raw,'synthetic-local-control-key');
 expect(observed).toBe(600000);
});
test('route change is rejected before any transport',async()=>{
 const fetcher=spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));
 const changed=JSON.parse(raw);changed.provider.only=['relace'];
 expect(()=>benchmarkFetch(JSON.stringify(changed),'synthetic-local-control-key')).toThrow();
 expect(fetcher).not.toHaveBeenCalled();
});
test('proxy failure never falls back to a direct or duplicate request',async()=>{
 const fetcher=spyOn(globalThis,'fetch').mockRejectedValue(new Error('synthetic_proxy_unavailable'));
 await expect(benchmarkFetch(raw,'synthetic-local-control-key')).rejects.toThrow('synthetic_proxy_unavailable');
 expect(fetcher).toHaveBeenCalledTimes(1);
});
