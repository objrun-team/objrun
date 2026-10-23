// Regression harness: actual unmodified common.model/accounting, local HTTP only.
import {join} from 'node:path';
import {writeFileSync} from 'node:fs';
const home=process.argv[2],count=Number(process.argv[3]??14);
const {accounting,model,cfg}=await import(join(home,'package/common.ts'));
const originalFetch=globalThis.fetch;let chatRequests=0,balanceRequests=0;
const local=Bun.serve({hostname:'127.0.0.1',port:0,fetch(req){
 const p=new URL(req.url).pathname;
 if(p.endsWith('/credits')){balanceRequests++;return Response.json({data:{total_credits:1000,total_usage:0}});}
 if(p.endsWith('/key')){balanceRequests++;return Response.json({data:{limit:1000,limit_remaining:1000}});}
 if(p.endsWith('/chat/completions')){chatRequests++;return Response.json({id:'fixture-'+chatRequests,provider:'DigitalOcean',model:cfg.model,usage:{cost:0},choices:[{message:{content:'\\boxed{1}'},finish_reason:'stop'}]});}
 return new Response('',{status:404});
}});
globalThis.fetch=((url:any,options:any)=>{
 const u=new URL(String(url));
 if(u.hostname!=='openrouter.ai')throw Error('UnexpectedExternalFixtureURL');
 return originalFetch('http://127.0.0.1:'+local.port+u.pathname,options);
}) as any;
process.env.OPENROUTER_API_KEY='fixture-local-only';
const started=performance.now(),measure=performance.now();accounting();const accountingMs=performance.now()-measure;
const work=[];
for(let i=0;i<count;i++){
 accounting(); // Same synchronous outer status call before execute reaches model.
 const dir=join(home,'fixture-requests',String(i));
 work.push(model(join(dir,'sample-0'),{messages:[{role:'user',content:'fixture'}]},dir,Date.now()+600000).then(()=>({ok:true})).catch(e=>({ok:false,error:String(e)})));
}
const results=await Promise.all(work);
const output={allPassed:results.every(x=>x.ok),count,accountingMs,elapsedMs:performance.now()-started,chatRequests,balanceRequests,realModelCalls:0,actualUsd:0,results};
writeFileSync(join(home,'STORAGE_AUDIT.json'),JSON.stringify(output,null,2)+'\n');
console.log(JSON.stringify(output));
await local.stop(true);
if(!output.allPassed)process.exitCode=1;
